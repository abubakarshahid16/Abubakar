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
from html import escape

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


def arabic_chars(text: str) -> int:
    """Arabic block (U+0600-U+06FF) plus the presentation forms (U+FB50-U+FEFF)
    that shaping produces. Counted the same way at every stage below, so the
    numbers are comparable."""
    return sum(1 for c in text
               if "؀" <= c <= "ۿ" or "ﭐ" <= c <= "﻿")


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


def build_shaped(path, blocks):
    """Fixture PDF through Story, the only API here that can carry Arabic.

    `build` draws with `page.insert_text`, which uses base-14 Helvetica. That
    font HAS NO ARABIC GLYPHS: PyMuPDF substitutes a notdef, and every Arabic
    codepoint in the fixture became "·" in the saved PDF - measured, see
    `test_arabic_glyphs_come_from_naskh_and_none_are_notdef`. So an Arabic
    fixture built by `build` was decorative: the Arabic was destroyed at
    FIXTURE BUILD time, before upload, before extraction, before the report.
    Story shapes and embeds Noto Naskh Arabic, which is also the path the
    product renders through, so the fixture and the report agree on the text.
    """
    html = "<html><body>" + "".join(
        "<p>" + "<br/>".join(escape(line) for line in block) + "</p>"
        for block in blocks) + "</body></html>"
    story = fitz.Story(html)
    writer = fitz.DocumentWriter(str(path))
    more = 1
    while more:
        device = writer.begin_page(fitz.paper_rect("letter"))
        more, _ = story.place(fitz.Rect(72, 72, 540, 720))
        story.draw(device)
        writer.end_page()
    writer.close()
    return path


def ingest(name="spec.pdf", blocks=(VIBRATION, MATERIALS), builder=build) -> str:
    client = TestClient(app)
    path = builder(settings.data_dir / name, blocks)
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
    # A zero-page report would satisfy every assertion inside the loop below by
    # never running one. The furniture claim is "on EVERY page", which is only
    # a claim if there is at least one page.
    assert doc.page_count, "the report has no pages: the loop below asserts nothing"
    assert rec["page_count"] == doc.page_count
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


def test_extract_report_warns_when_matched_passages_are_not_merged():
    ingest()
    m = answered_message()
    conn = db.connect()
    payload = json.loads(conn.execute("SELECT payload FROM messages WHERE id = ?",
                                      (m["id"],)).fetchone()["payload"])
    supporting = dict(payload["passage"])
    supporting.update(
        chunk_id="supporting-continuation",
        text="The continuation passage is relevant but was not part of the quoted answer.",
    )
    payload["supporting"] = [supporting]
    with conn:
        conn.execute("UPDATE messages SET payload = ? WHERE id = ?",
                     (json.dumps(payload), m["id"]))

    rec = reports.generate(m["id"], access.unrestricted_scope())
    text = all_text(pdf_of(rec))
    assert "quoted answer is the cited extract only" in text
    assert "Other matched passages are preserved in the Evidence section" in text
    assert "supplied, not cited" in text
    assert "not merged into the quoted answer" in text


def test_generated_report_prints_a_citation_audit():
    ingest()
    m = answered_message("what are the vibration limits for pump P-101A")
    conn = db.connect()
    payload = json.loads(conn.execute("SELECT payload FROM messages WHERE id = ?",
                                      (m["id"],)).fetchone()["payload"])
    second = dict(payload["passage"])
    second.update(
        chunk_id="second-cited",
        text="A second cited passage also supports the generated answer.",
    )
    payload.update(passages=[payload["passage"], second], cited=[1, 2],
                   model="qwen3.5:4b")
    with conn:
        conn.execute("UPDATE messages SET payload = ?, answer_type = 'generated', text = ? "
                     "WHERE id = ?",
                     (json.dumps(payload), "The answer is supported by two sources [S1][S2].",
                      m["id"]))

    rec = reports.generate(m["id"], access.unrestricted_scope())
    text = all_text(pdf_of(rec))
    assert "Citation audit" in text
    assert "Answer markers: S1, S2" in text
    assert "Evidence marked cited: S1, S2" in text
    assert "Supporting passages not cited by the answer: 0" in text
    assert "Citation audit passed" in text
    assert "[S1] spec.pdf, page 1" in text
    assert "cited by answer" in text


def test_generated_report_warns_when_answer_names_missing_evidence():
    ingest()
    m = answered_message("what are the vibration limits for pump P-101A")
    conn = db.connect()
    payload = json.loads(conn.execute("SELECT payload FROM messages WHERE id = ?",
                                      (m["id"],)).fetchone()["payload"])
    payload.update(passages=[payload["passage"]], cited=[1], model="qwen3.5:4b")
    with conn:
        conn.execute("UPDATE messages SET payload = ?, answer_type = 'generated', text = ? "
                     "WHERE id = ?",
                     (json.dumps(payload), "The answer cites evidence that is absent [S9].",
                      m["id"]))

    rec = reports.generate(m["id"], access.unrestricted_scope())
    text = all_text(pdf_of(rec))
    assert "Citation audit failed" in text
    assert "missing evidence marker" in text
    assert "S9" in text


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
    # Same shape as the watermark test: nothing below is asserted about a
    # zero-page document, or about a page that yielded no blocks. Count what was
    # actually measured and require it to be non-zero, so "nothing is clipped"
    # cannot be satisfied by "nothing was looked at".
    assert doc.page_count, "the report has no pages: the geometry loop asserts nothing"
    measured = 0
    for page in doc:
        for b in page.get_text("blocks"):
            r = fitz.Rect(b[:4])
            measured += 1
            assert r.x1 <= page.rect.x1 + 2 and r.y1 <= page.rect.y1 + 2, (
                f"block past the page edge on page {page.number + 1}: {r}")
    assert measured, "no text blocks were measured, so nothing was checked for clipping"


PAYLOAD = "<script>alert(1)</script>"
MARKUP = "<b>bold</b>"


def test_document_text_is_html_escaped():
    """Document text goes through a REAL HTML layer, and must survive it as text.

    THE OLD ASSERTION WAS `"<script>" in text or "&lt;script&gt;" not in text`,
    which is TRUE when the text contains NEITHER form - i.e. when the passage
    never reached the PDF at all. An escaping test that passes on absent content
    is how an escaping bug ships. Entry 4 of docs/status-honesty-audit.md is the
    same shape.

    THE PREMISE WAS CORRECT, and it was worth checking: `reports.to_html` really
    does build an HTML document, `_esc` really is `html.escape`, and
    `fitz.Story` really parses that HTML - measured below at both layers, so the
    escaping is load-bearing rather than decorative.

    WHAT IS ASSERTED, POSITIVELY, at each of the two layers:

      * HTML SOURCE - the entity form `&lt;script&gt;` IS in `to_html` output
        and the raw tag is NOT. This is the escape actually happening.
      * RENDERED PDF - the payload comes back as LITERAL CHARACTERS,
        `<script>alert(1)</script>`, and no entity form (`&lt;`, `&gt;`,
        `&amp;`) is visible to a reader: the reader sees what the document said,
        not entities and not markup.

        MEASURED LIMIT OF THIS SECOND CHECK: Story's HTML parser decodes
        entities RECURSIVELY. Double-escaping `_esc` (`html.escape` applied
        twice) produces a PDF whose extracted text is byte-identical to the
        correct one, so no PDF-text assertion can tell single from double
        escaping. The HTML-source assertion above is the one that catches it -
        it was mutated and does. This check catches the opposite failure: a
        renderer that stops decoding and shows a reader `&lt;script&gt;`.
      * NOT INTERPRETED - the span carrying "bold" still carries the literal
        `<b>` characters. If Story had consumed `<b>` as an element the tag
        characters would be gone and the word alone would remain, styled.

    POSITIVE CONTROL: every assertion here requires the dangerous string to be
    PRESENT. Absence fails, at the HTML layer and again in the PDF.
    """
    ingest("evil.pdf", [[
        "9.9 Evil Clause",
        f"The limit is {MARKUP} and {PAYLOAD} shall not apply",
        "to any centrifugal pump in hydrocarbon service under this specification.",
    ]])
    m = answered_message("what does the evil clause say about the limit")

    # POSITIVE CONTROL 0 - the payload survived the fixture, ingestion and the
    # persisted answer. Without this, everything below could be measuring a
    # passage that lost its markup upstream of the renderer.
    assert PAYLOAD in (m.get("text") or ""), (
        "the payload never reached the persisted answer, so this test would be "
        f"measuring nothing: {m.get('text')!r}")

    # LAYER 1 - the HTML the renderer hands to Story. The escape, asserted
    # positively: the entity form present, the live tag absent.
    snapshot = reports.build_snapshot(m["id"], access.unrestricted_scope())
    html_src = reports.to_html(snapshot)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_src, (
        "document text reached the HTML layer unescaped or not at all")
    assert "<script>" not in html_src, "a live <script> tag is in the report HTML"

    # LAYER 2 - the rendered PDF, read back as text.
    rec = reports.generate(m["id"], access.unrestricted_scope())
    doc = pdf_of(rec)
    assert doc.page_count, "the report has no pages"
    text = all_text(doc)
    assert PAYLOAD in text, (
        "the payload did not reach the rendered PDF as literal text - absence "
        "must not be mistaken for escaping")
    assert MARKUP in text, "the markup passage did not reach the rendered PDF"
    # Escaped once, decoded once. An entity visible to the reader means the
    # text was escaped twice and the report now misquotes the document.
    for entity in ("&lt;", "&gt;", "&amp;", "&lt;script&gt;"):
        assert entity not in text, (
            f"{entity!r} is visible in the PDF: the document text was escaped "
            "twice and the quotation no longer matches the document")

    # NOT INTERPRETED - the tag characters are still in the span that carries
    # the word, so Story rendered them as text rather than consuming them.
    spans = [N(s["text"]) for page in doc
             for b in page.get_text("dict")["blocks"]
             for line in b.get("lines", [])
             for s in line["spans"]
             if "bold" in N(s["text"]).lower()]
    assert spans, "the word 'bold' was not found in any span"
    assert any("<b>" in s for s in spans), (
        f"the <b> tag characters were consumed as markup, not drawn: {spans}")
    assert rec["page_count"] == doc.page_count


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

    # POSITIVE CONTROL: the body does render the filename, so "renamed.pdf is
    # absent" is a statement about the rename and not about a body that never
    # names any file.
    assert "spec.pdf" in before, "the report body does not render the filename at all"
    # Same snapshot in, same body out - the renderer never looked at the table.
    assert reports.to_html(snapshot) == before
    assert "renamed.pdf" not in before
    assert "renamed.pdf" not in reports.to_html(snapshot)


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
    assert f"rag-intelligence-report-{rec['id']}.pdf" in r.headers["content-disposition"]
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

    FURNITURE = "def _draw_furniture"
    RENDER = "def render"

    src = inspect.getsource(reports)

    # Drop the module docstring, which names the forbidden APIs in order to
    # forbid them. POSITIVE CONTROL on the split: the docstring half must be the
    # half that mentions them, or the split did not land where we think.
    parts = src.split('"""', 2)
    assert len(parts) == 3, "the module docstring is not where this test expects it"
    docstring, src = parts[1], parts[2]
    assert "insert_text" in docstring, (
        "the text dropped as 'the module docstring' does not mention insert_text, "
        "so the docstring split landed somewhere else")

    # LOUD ANCHORS. The old version derived `body` by splitting on these two
    # function names with no check that either matched. Rename `_draw_furniture`
    # or `render` and `body` silently shrank to a fragment - or the second split
    # raised IndexError - and `insert_text not in body` became vacuously true.
    # A missing or duplicated anchor must FAIL and name itself.
    for anchor in (FURNITURE, RENDER):
        assert src.count(anchor) == 1, (
            f"{anchor!r} appears {src.count(anchor)} time(s) in app/reports.py; "
            "this test slices the module on that name and cannot slice it "
            "correctly. If the function was renamed, rename it here too - do "
            "not let the search silently narrow")
    assert src.index(FURNITURE) < src.index(RENDER), (
        f"{FURNITURE!r} no longer precedes {RENDER!r}; the slice below would "
        "not separate the furniture from the body")

    head, furniture_and_render = src.split(FURNITURE, 1)
    furniture, render_onward = furniture_and_render.split(RENDER, 1)
    body = head + render_onward

    # POSITIVE CONTROL on the exclusion: the unshaped API must actually BE in
    # the half deliberately cut out. This is what proves the slice landed where
    # the test believes it landed - without it, "not in body" is satisfied by a
    # module that never calls insert_text anywhere, or by a body that is empty.
    assert "insert_text" in furniture, (
        f"insert_text is not in the {FURNITURE!r} half that this test excludes, "
        "so the exclusion proves nothing about the body")
    assert body.strip(), "the body half of the split came out empty"

    assert "insert_text" not in body, (
        "body text goes through an API that performs no Arabic shaping; "
        "insert_text/insert_textbox are confined to ASCII furniture")
    assert "TextWriter" not in src


ARABIC_SPEC = [
    "3.1 Coating",
    "The coating thickness shall be 280 um. المواصفات الفنية للطلاء تشترط "
    "سماكة الفيلم الجاف for every centrifugal pump in "
    "hydrocarbon service at site.",
]
#: The floor every stage below is measured against. The source block carries 40
#: Arabic letters; extraction returns 34 of them, because two lam-alef
#: presentation ligatures come back as Latin caron letters (see the note in the
#: test). 20 is a floor, not the measurement - it fails loudly if a stage keeps
#: a token letter or two, and it does not have to be re-tuned every time the
#: shaper changes its mind about a ligature.
ARABIC_FLOOR = 20


def test_arabic_glyphs_come_from_naskh_and_none_are_notdef():
    """WHAT THIS DOES NOT PROVE: that the joins are the right ones, or that bidi
    order is correct. That needs a reader of Arabic. This proves glyph coverage
    and font identity, so a green tick here must not be read as "Arabic works".

    THIS TEST USED TO SKIP ITSELF when the report contained no Arabic, blaming
    extraction - "the ingested fixture lost its Arabic before the report". That
    was measured and is FALSE, and the skip was hiding a broken fixture rather
    than a broken product. The fixture was built by `build`, i.e. by
    `page.insert_text` in base-14 Helvetica, which has no Arabic glyphs: the
    saved fixture PDF contained 0 Arabic characters and 42 "·" notdefs
    before anything was uploaded. Extraction was never given Arabic to lose.
    Built through Story instead (`build_shaped`), the same block measures 34
    Arabic characters out of the fixture, 34 through extraction into the chunk
    row, 34 in the persisted answer, and 68 in the rendered report - all in
    NotoNaskhArabic-Regular with 0 notdefs.

    The skip is gone and it must not come back: the four stage assertions below
    each carry their own floor, so this test can no longer report success while
    measuring nothing. If Arabic really does vanish at some stage, the
    assertion for THAT stage fails and names it.
    """
    ingest("ar.pdf", [ARABIC_SPEC], builder=build_shaped)

    # STAGE 1 - the fixture. Asserted, not assumed: this is the assertion the
    # skip existed instead of.
    fixture = fitz.open(settings.data_dir / "ar.pdf")
    fixture_arabic = arabic_chars("".join(page.get_text() for page in fixture))
    assert fixture_arabic >= ARABIC_FLOOR, (
        f"the fixture itself carries only {fixture_arabic} Arabic characters - "
        "it is decorative, and nothing downstream can be measured. An Arabic "
        "fixture must go through build_shaped, never build/insert_text")

    # STAGE 2 - extraction. Where the old skip message put the blame.
    chunks = "".join(r["text"] for r in
                     db.connect().execute("SELECT text FROM chunks").fetchall())
    chunk_arabic = arabic_chars(chunks)
    assert chunk_arabic >= ARABIC_FLOOR, (
        f"extraction dropped Arabic: {fixture_arabic} characters in the fixture "
        f"PDF, {chunk_arabic} in the chunk rows. This is a product defect in "
        "the extraction path, not a rendering one")

    # STAGE 3 - the persisted answer the report is built from.
    m = answered_message("what coating thickness is required")
    answer_arabic = arabic_chars(m.get("text") or "")
    assert answer_arabic >= ARABIC_FLOOR, (
        f"the answer persisted only {answer_arabic} Arabic characters from a "
        f"passage that carried {chunk_arabic}")

    # STAGE 4 - the rendered PDF: coverage and font identity.
    rec = reports.generate(m["id"], access.unrestricted_scope())
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
    assert arabic >= ARABIC_FLOOR, (
        f"the report rendered {arabic} Arabic characters from an answer "
        f"carrying {answer_arabic}; the loss is in rendering")
    assert notdef == 0
    assert fonts, "unreachable: arabic >= floor means at least one span"
    assert all("Naskh" in f or "Arabic" in f for f in fonts), fonts


def test_the_passage_label_names_no_clause():
    """Document and page only. The chunker's `section` is not printed.

    It was wrong on 5 of 6 cited passages, and 0 of 11 correct on doc16 - a
    citation pointing an engineer at a different requirement. Chat stopped
    printing it and so did the claim table; this is the frozen PDF, and a
    report naming a clause the screen no longer claims is worse than either
    alone, because the PDF is what outlives the session.

    The fixture PLANTS a distinctive section on the passage, so the assertion
    can actually fail. Asserting the absence of a value the fixture never
    supplied is the vacuous shape recorded as entry 10 of
    docs/status-honesty-audit.md.
    """
    ingest()
    m = answered_message()
    conn = db.connect()
    payload = json.loads(conn.execute("SELECT payload FROM messages WHERE id = ?",
                                      (m["id"],)).fetchone()["payload"])
    PLANTED = "9.9.9 PLANTED CLAUSE LABEL"
    payload["passage"]["section"] = PLANTED
    for ap in (payload.get("answer_passages") or []) + (payload.get("supporting") or []):
        ap["section"] = PLANTED
    with conn:
        conn.execute("UPDATE messages SET payload = ? WHERE id = ?",
                     (json.dumps(payload), m["id"]))

    rec = reports.generate(m["id"], access.unrestricted_scope())
    text = all_text(pdf_of(rec))

    assert PLANTED not in text, (
        "the chunker's clause label reached the frozen PDF, which the screen "
        "no longer prints")
    assert "9.9.9" not in text, "the clause number reached the PDF"
    # And the citation is still usable: the document and page must remain.
    assert "page" in text.lower(), "the passage label lost its page as well"
