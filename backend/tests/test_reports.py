"""Evidence reports: frozen snapshot, rendered PDF, scoped access.

Every assertion on the PDF is on SEMANTICS read back through PyMuPDF - text,
fonts, page geometry - never on bytes. Byte assertions break on every point
release, and the library is already the parser.

Every text assertion NFKC-normalises first. The spike found `fitz` returns
typographic ligatures - "prefix" came back as "preﬁx" - and the first
version of its `<thead>` check found no header on any page for exactly that
reason.
"""

from __future__ import annotations

import json
import unicodedata

import fitz
import pytest
from fastapi.testclient import TestClient

from app import access, chat, db, keyword, reports
from app.config import config_version, settings
from app.ingest import IngestionWorker
from app.main import app

VIBRATION = [
    "5.3.2 Vibration Limits",
    "Vibration limits per API 610 shall not exceed 3.0 mm/s RMS measured at the",
    "bearing housing of pump P-101A during continuous operation at rated flow,",
    "and any exceedance shall be reported to the area engineer before the pump",
    "is returned to service under the procedure given in this specification.",
]
MATERIALS = [
    "7.1 Materials of Construction",
    "Casing material shall be ASTM A216 WCB with an impeller of CA6NM and a",
    "shaft of AISI 4140 for all centrifugal pumps in hydrocarbon service, and",
    "alternative materials require written approval from the principal engineer.",
]


def N(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


def build(path, blocks):
    doc = fitz.open()
    for block in blocks:
        page = doc.new_page()
        for i, line in enumerate(block):
            page.insert_text((72, 100 + i * 16), line)
    doc.save(str(path))
    doc.close()
    return path


def ingest(name="spec.pdf", blocks=(VIBRATION, MATERIALS)) -> str:
    client = TestClient(app)
    path = build(settings.data_dir / name, blocks)
    with open(path, "rb") as fh:
        doc_id = client.post("/api/documents",
                             files={"file": (name, fh, "application/pdf")}
                             ).json()["document"]["id"]
    IngestionWorker().process(doc_id)
    return doc_id


def answered_message(question="what are the vibration limits for pump P-101A") -> dict:
    """A real Tier 1 answer, persisted the way the product persists it."""
    conv = chat.create_conversation()
    result = chat.ask(conv["id"], question, tier="extract",
                      allowed_document_ids=frozenset(_all_ids()))
    assert result["answer_type"] == "extract", result.get("reason")
    return result["assistant_message"]


def _all_ids():
    return {r["id"] for r in db.connect().execute("SELECT id FROM documents")}


def pdf_of(record) -> fitz.Document:
    row = db.connect().execute("SELECT stored_path FROM reports WHERE id = ?",
                               (record["id"],)).fetchone()
    return fitz.open(row["stored_path"])


def all_text(doc) -> str:
    """Whole-document text, NFKC-normalised and whitespace-collapsed.

    Collapsed because a narrow table cell wraps "not recorded" onto two lines
    and extraction puts a newline between them; asserting on the phrase with a
    single space then fails against a PDF that renders it correctly.
    """
    raw = "\n".join(page.get_text() for page in doc)
    return " ".join(N(raw).split())


# ------------------------------------------------------------- what it says


def test_page_one_says_what_this_report_is_and_is_not():
    """The bordered box. A single-answer evidence report must not be mistaken
    for the plan's analysis report, and the sections it lacks are named rather
    than rendered empty."""
    ingest()
    m = answered_message()
    rec = reports.generate(m["id"], access.unrestricted_scope())
    doc = pdf_of(rec)
    page1 = N(doc[0].get_text())
    assert "single-answer evidence report" in page1
    for section in ("coverage ledger", "gap analysis", "recommendation",
                    "public-market findings"):
        assert section in page1, f"{section!r} not named as not included"
    assert rec["not_implemented_sections"] == reports.NOT_INCLUDED


def test_the_watermark_and_page_number_are_on_every_page():
    ingest()
    rec = reports.generate(answered_message()["id"], access.unrestricted_scope())
    doc = pdf_of(rec)
    for page in doc:
        text = N(page.get_text())
        assert "NOT FOR CONSTRUCTION" in text, f"page {page.number + 1} unwatermarked"
        assert f"Page {page.number + 1} of {doc.page_count}" in text


def test_the_engineer_approval_sentence_appears_twice():
    ingest()
    rec = reports.generate(answered_message()["id"], access.unrestricted_scope())
    text = all_text(pdf_of(rec))
    key = "requires review and approval by a qualified engineer"
    assert text.count(key) >= 2, f"approval sentence appears {text.count(key)} time(s)"


def test_quoted_text_is_serif_and_generated_text_is_sans_on_amber():
    """The two kinds of text must never look alike. Checked by font family
    read back from the spans, not by eye."""
    ingest()
    rec = reports.generate(answered_message()["id"], access.unrestricted_scope())
    doc = pdf_of(rec)
    quoted_fonts = set()
    for page in doc:
        for b in page.get_text("dict")["blocks"]:
            for line in b.get("lines", []):
                for span in line["spans"]:
                    if "3.0 mm/s" in N(span["text"]):
                        quoted_fonts.add(span["font"])
    assert quoted_fonts, "the quoted passage was not found in any span"
    # MuPDF's built-in serif is Charis SIL; its sans is Noto Sans.
    assert all(_is_serif(f) for f in quoted_fonts), f"quoted text is not serif: {quoted_fonts}"

    # The generated half: the same passage, answered as model prose, must NOT
    # come back in the serif face.
    conn = db.connect()
    m = answered_message("what are the vibration limits for pump P-101A")
    payload = json.loads(conn.execute("SELECT payload FROM messages WHERE id = ?",
                                      (m["id"],)).fetchone()["payload"])
    payload.update(passages=[payload["passage"]], cited=[1], model="qwen3.5:4b")
    with conn:
        conn.execute("UPDATE messages SET payload = ?, answer_type = 'generated', text = ? "
                     "WHERE id = ?",
                     (json.dumps(payload), "The limit is 3.0 mm/s RMS at the bearing housing [S1].", m["id"]))
    rec2 = reports.generate(m["id"], access.unrestricted_scope())
    generated_fonts = set()
    for page in pdf_of(rec2):
        for b in page.get_text("dict")["blocks"]:
            for line in b.get("lines", []):
                for span in line["spans"]:
                    if "at the bearing housing [S1]" in N(span["text"]):
                        generated_fonts.add(span["font"])
    assert generated_fonts, "the generated answer was not found in any span"
    assert not any(_is_serif(f) for f in generated_fonts), (
        f"generated prose rendered in the quotation face: {generated_fonts}")


def _is_serif(font: str) -> bool:
    return any(k in font for k in ("Charis", "Serif", "Times", "Roman"))


def test_a_recognised_passage_carries_its_provenance_line():
    """On EVERY recognised passage. A reader may open the report at that page."""
    ingest()
    m = answered_message()
    # Mark the answer's passage as recognised, the way OCR output is stored.
    conn = db.connect()
    payload = json.loads(conn.execute("SELECT payload FROM messages WHERE id = ?",
                                      (m["id"],)).fetchone()["payload"])
    payload["passage"]["text_source"] = "recognised"
    payload["passage"]["ocr_min_conf"] = 0.51
    payload["passage"]["ocr_alphabet_violations"] = 2
    payload["passage"]["ocr_alphabet_sample"] = "≦"
    # EVERY passage from the document, or the document's text_source is
    # correctly "mixed" - which the first version of this test asserted against
    # and lost to, because it had left the supporting passage as extracted.
    for ap in (payload.get("answer_passages") or []) + (payload.get("supporting") or []):
        ap.update(text_source="recognised", ocr_min_conf=0.51,
                  ocr_alphabet_violations=2, ocr_alphabet_sample="≦")
    with conn:
        conn.execute("UPDATE messages SET payload = ? WHERE id = ?",
                     (json.dumps(payload), m["id"]))

    rec = reports.generate(m["id"], access.unrestricted_scope())
    text = all_text(pdf_of(rec))
    assert "Read by OCR from a scanned page" in text
    assert "0.51" in text
    assert "2 character(s) this document cannot contain" in text
    assert rec["documents"][0]["text_source"] == "recognised"


def test_revision_and_approval_are_not_recorded_rather_than_invented():
    ingest()
    rec = reports.generate(answered_message()["id"], access.unrestricted_scope())
    assert rec["documents"][0]["revision"] is None
    assert rec["documents"][0]["approval_status"] is None
    assert "not recorded" in all_text(pdf_of(rec))


def test_nothing_is_clipped_and_the_full_hash_survives():
    ingest()
    rec = reports.generate(answered_message()["id"], access.unrestricted_scope())
    doc = pdf_of(rec)
    sha = db.connect().execute("SELECT sha256 FROM documents").fetchone()["sha256"]
    joined = "".join(all_text(doc).split())
    assert sha in joined, "the 64-character hash did not survive the table cell"
    for page in doc:
        for b in page.get_text("blocks"):
            r = fitz.Rect(b[:4])
            assert r.x1 <= page.rect.x1 + 2 and r.y1 <= page.rect.y1 + 2, (
                f"block past the page edge on page {page.number + 1}: {r}")


def test_document_text_is_html_escaped():
    """A passage containing markup must render as text, not as markup."""
    ingest("evil.pdf", [[
        "9.9 Evil Clause",
        "The limit is <b>bold</b> and <script>alert(1)</script> shall not apply",
        "to any centrifugal pump in hydrocarbon service under this specification.",
    ]])
    rec = reports.generate(answered_message("what does the evil clause say about the limit")["id"],
                           access.unrestricted_scope())
    text = all_text(pdf_of(rec))
    assert "<script>" in text or "&lt;script&gt;" not in text
    assert "alert(1)" in text  # rendered as literal text, not executed or dropped


# ------------------------------------------------------------ the snapshot


def test_the_renderer_reads_only_the_snapshot(monkeypatch):
    """A25. Rename and re-index the document; the report body does not change."""
    ingest()
    m = answered_message()
    snapshot = reports.build_snapshot(m["id"], access.unrestricted_scope())
    before = reports.to_html(snapshot)

    conn = db.connect()
    with conn:
        conn.execute("UPDATE documents SET filename = 'renamed.pdf', indexed_at = '2099-01-01T00:00:00'")

    # Same snapshot in, same body out - the renderer never looked at the table.
    assert reports.to_html(snapshot) == before
    assert "renamed.pdf" not in before


def test_evidence_drift_is_reported_not_silently_used():
    ingest()
    rec = reports.generate(answered_message()["id"], access.unrestricted_scope())
    scope = access.unrestricted_scope()
    assert reports.verify(rec["id"], scope)["evidence_drift"] == []

    conn = db.connect()
    with conn:
        conn.execute("UPDATE documents SET sha256 = ?", ("f" * 64,))
    v = reports.verify(rec["id"], scope)
    assert any("file content changed" in d for d in v["evidence_drift"])
    assert v["snapshot_intact"] is True
    assert v["file_intact"] is True


def test_a_tampered_file_is_detected():
    ingest()
    rec = reports.generate(answered_message()["id"], access.unrestricted_scope())
    row = db.connect().execute("SELECT stored_path FROM reports WHERE id = ?",
                               (rec["id"],)).fetchone()
    with open(row["stored_path"], "ab") as fh:
        fh.write(b"\n%tampered")
    assert reports.verify(rec["id"], access.unrestricted_scope())["file_intact"] is False


def test_config_version_tracks_answer_settings_and_ignores_the_port(monkeypatch):
    base = config_version()
    monkeypatch.setattr(settings, "port", 9999)
    assert config_version() == base, "the port is not part of the answer"
    monkeypatch.setattr(settings, "num_ctx", settings.num_ctx + 1)
    assert config_version() != base


def test_no_remote_fetch_during_render(monkeypatch):
    """The target is air-gapped. A renderer that phones home fails there."""
    import socket

    import httpx

    def boom(*a, **k):
        raise AssertionError("network access during render")

    # Ingest FIRST: TestClient is itself an httpx.Client, so patching request
    # before the upload would fail the fixture, not the renderer.
    ingest()
    m = answered_message()
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(httpx.Client, "request", boom)
    rec = reports.generate(m["id"], access.unrestricted_scope())
    assert rec["page_count"] >= 1


# ------------------------------------------------------------------ storage


def test_the_file_is_content_addressed_and_the_path_is_never_serialised():
    ingest()
    rec = reports.generate(answered_message()["id"], access.unrestricted_scope())
    row = db.connect().execute("SELECT stored_path, report_sha256 FROM reports").fetchone()
    assert row["stored_path"].endswith(f"{row['report_sha256']}.pdf")
    assert "vibration" not in row["stored_path"].lower(), "the filename carries question text"
    assert "stored_path" not in json.dumps(rec)
    assert "stored_path" not in TestClient(app).get("/api/reports").text


def test_the_download_name_is_the_report_id_and_the_response_is_private():
    ingest()
    rec = reports.generate(answered_message()["id"], access.unrestricted_scope())
    r = TestClient(app).get(f"/api/reports/{rec['id']}/download")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert f"nabaa-report-{rec['id']}.pdf" in r.headers["content-disposition"]
    assert r.headers["cache-control"] == "private, no-store"


# ------------------------------------------------------------------- access


def _user(email, role_id, doc_ids):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = db.connect()
    uid = f"user_{email.split('@')[0]}"
    with conn:
        conn.execute("INSERT OR IGNORE INTO roles (id, name, description, created_at) "
                     "VALUES (?, ?, '', ?)", (role_id, role_id, now))
        conn.execute("INSERT INTO users (id, email, display_name, password_hash, is_active, "
                     "created_at) VALUES (?, ?, ?, 'x', 1, ?)", (uid, email, email, now))
        conn.execute("INSERT OR IGNORE INTO user_roles (user_id, role_id, granted_at) "
                     "VALUES (?, ?, ?)", (uid, role_id, now))
        for d in doc_ids:
            conn.execute("INSERT INTO document_role_access (document_id, role_id, granted_at) "
                         "VALUES (?, ?, ?)", (d, role_id, now))
    return uid


def test_a_report_vanishes_when_a_cited_document_leaves_the_readers_scope(monkeypatch):
    """404, not 403, and not partially redacted. The listing shows only THAT
    something is hidden."""
    doc_id = ingest()
    m = answered_message()
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    uid = _user("a@x.test", "role_a", [doc_id])
    scope = access.scope_for_user(uid)
    assert scope.allowed_document_ids == {doc_id}, "fixture: the user cannot see the document"

    rec = reports.generate(m["id"], scope)
    monkeypatch.setattr(access, "_resolve_user_id", lambda request: uid)
    client = TestClient(app)
    assert client.get(f"/api/reports/{rec['id']}/verify").status_code == 200
    assert client.get("/api/reports").json()["suppressed_count"] == 0

    # the grant is revoked
    with db.connect() as conn:
        conn.execute("DELETE FROM document_role_access WHERE document_id = ?", (doc_id,))

    for path in (f"/api/reports/{rec['id']}/verify", f"/api/reports/{rec['id']}/download"):
        r = client.get(path)
        assert r.status_code == 404, f"{path} -> {r.status_code}"
        assert r.json()["detail"]["code"] == "not_found"
    listing = client.get("/api/reports").json()
    assert listing["reports"] == []
    assert listing["suppressed_count"] == 1


def test_another_users_report_is_404(monkeypatch):
    doc_id = ingest()
    m = answered_message()
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    owner = _user("a@x.test", "role_a", [doc_id])
    other = _user("b@x.test", "role_b", [doc_id])
    assert owner != other
    rec = reports.generate(m["id"], access.scope_for_user(owner))

    monkeypatch.setattr(access, "_resolve_user_id", lambda request: other)
    r = TestClient(app).get(f"/api/reports/{rec['id']}/verify")
    assert r.status_code == 404


def test_generating_from_a_message_outside_scope_is_404(monkeypatch):
    ingest()
    m = answered_message()
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    stranger = _user("c@x.test", "role_c", [])
    monkeypatch.setattr(access, "_resolve_user_id", lambda request: stranger)
    r = TestClient(app).post("/api/reports", json={"message_id": m["id"]})
    assert r.status_code == 404
    assert db.connect().execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0


def test_a_refusal_cannot_be_reported_on():
    ingest()
    conv = chat.create_conversation()
    result = chat.ask(conv["id"], "what is the hafnium concentration limit",
                      tier="extract", allowed_document_ids=frozenset(_all_ids()))
    assert result["answer_type"] == "insufficient_evidence"
    r = TestClient(app).post("/api/reports",
                             json={"message_id": result["assistant_message"]["id"]})
    assert r.status_code == 422


def test_owner_is_null_under_disabled_and_never_a_placeholder():
    ingest()
    rec = reports.generate(answered_message()["id"], access.unrestricted_scope())
    assert rec["owner_username"] is None
    text = all_text(pdf_of(rec))
    assert "authentication disabled - no user identity recorded" in text
    assert "Administrator" not in text and "admin" not in text.lower().split("generated by")[1][:60]


# ------------------------------------------------------------ the two rules


def test_body_text_never_goes_through_the_unshaped_text_apis():
    """Story shapes Arabic; insert_text and insert_textbox do not, and produce
    unjoined Arabic that still looks like Arabic to a non-reader. They are
    confined to ASCII furniture."""
    import inspect

    src = inspect.getsource(reports)
    # drop the module docstring, which names the forbidden APIs in order to forbid them
    src = src.split('"""', 2)[2]
    body = src.split("def _draw_furniture", 1)[0] + src.split("def render", 1)[1]
    assert "insert_text" not in body
    assert "TextWriter" not in src


def test_arabic_glyphs_come_from_naskh_and_none_are_notdef():
    """WHAT THIS DOES NOT PROVE: that the joins are the right ones, or that bidi
    order is correct. That needs a reader of Arabic. This proves glyph coverage
    and font identity, so a green tick here must not be read as "Arabic works"."""
    ingest("ar.pdf", [[
        "3.1 Coating",
        "The coating thickness shall be 280 um. المواصفات الفنية للطلاء تشترط سماكة",
        "الفيلم الجاف for every centrifugal pump in hydrocarbon service at site.",
    ]])
    rec = reports.generate(answered_message("what coating thickness is required")["id"],
                           access.unrestricted_scope())
    doc = pdf_of(rec)
    fonts, arabic, notdef = set(), 0, 0
    for page in doc:
        for b in page.get_text("rawdict")["blocks"]:
            for line in b.get("lines", []):
                for span in line["spans"]:
                    for ch in span["chars"]:
                        c = ch["c"]
                        if "؀" <= c <= "ۿ" or "ﭐ" <= c <= "﻿":
                            arabic += 1
                            fonts.add(span["font"])
                        notdef += c == "�"
    if arabic == 0:
        pytest.skip("the ingested fixture lost its Arabic before the report - "
                    "extraction, not rendering; nothing measured here")
    assert notdef == 0
    assert all("Naskh" in f or "Arabic" in f for f in fonts), fonts
