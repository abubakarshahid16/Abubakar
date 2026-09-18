"""Phase 2: the original file - served under scope, and never rewritten.

Two invariants, both from master-plan section 27:

  * "Preview and export endpoints check access." The original-file route is the
    one that serves raw document bytes, so an unscoped version of it would be a
    hole no other boundary could cover (mutation M13).
  * "Original uploaded files remain immutable." Storage is content-addressed,
    which makes that true by construction - but nothing asserted it, so nothing
    would notice if a later change started replacing stored files (M15).

Run the mutations with:  python scripts/mutation_check.py --phase 2
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import access, db
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "original.sqlite")
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    (tmp_path / "uploads").mkdir(parents=True, exist_ok=True)
    db.reset_connection(); db.init_db()
    yield
    db.reset_connection()


def _stored(tmp_path, name: str, body: bytes):
    path = tmp_path / "uploads" / name
    path.write_bytes(body)
    return path


def _doc(doc_id: str, filename: str, digest: str, path) -> str:
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,uploaded_at)
            VALUES (?,?,?,?,?,'ready',?)""",
            (doc_id, filename, digest, len(path.read_bytes()), str(path),
             "2026-09-18T00:00:00Z"))
    return doc_id


@pytest.fixture()
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def _as_user(monkeypatch, *ids: str):
    """Run the next request as an identified user granted exactly `ids`."""
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    monkeypatch.setattr(access, "_resolve_user_id", lambda request: "u1")
    monkeypatch.setattr(access, "scope_for_user", lambda uid: access.AccessScope(
        user_id="u1", allowed_document_ids=frozenset(ids)))


# --------------------------------------------------------------- the route

def test_an_authorised_user_downloads_the_original_bytes(client, tmp_path, monkeypatch):
    body = b"%PDF-1.7 original bytes"
    path = _stored(tmp_path, "abc.pdf", body)
    doc = _doc("doc_ok", "spec.pdf", "abc", path)
    _as_user(monkeypatch, doc)
    r = client.get(f"/api/documents/{doc}/original")
    assert r.status_code == 200
    assert r.content == body                       # byte for byte
    assert r.headers["content-type"].startswith("application/pdf")
    assert 'filename="spec.pdf"' in r.headers["content-disposition"]
    assert r.headers["content-disposition"].startswith("inline")


def test_the_download_flag_switches_to_attachment(client, tmp_path, monkeypatch):
    path = _stored(tmp_path, "abc.pdf", b"%PDF-1.7 x")
    doc = _doc("doc_ok", "spec.pdf", "abc", path)
    _as_user(monkeypatch, doc)
    r = client.get(f"/api/documents/{doc}/original", params={"download": "true"})
    assert r.headers["content-disposition"].startswith("attachment")


def test_an_unauthorised_user_cannot_download_another_documents_original(
        client, tmp_path, monkeypatch):
    """THE MUTATION TARGET (M13). 404, never 403: a 403 confirms it exists."""
    mine = _doc("doc_mine", "mine.pdf", "m",
                _stored(tmp_path, "m.pdf", b"%PDF mine"))
    theirs = _doc("doc_theirs", "theirs.pdf", "t",
                  _stored(tmp_path, "t.pdf", b"%PDF theirs"))
    _as_user(monkeypatch, mine)
    r = client.get(f"/api/documents/{theirs}/original")
    assert r.status_code == 404
    # No document BYTES. The body echoes the id the caller itself supplied,
    # which discloses nothing it did not already know; what must never appear
    # is the file's content.
    assert b"%PDF" not in r.content
    assert r.headers.get("content-type", "").startswith("application/json")


def test_a_caller_with_no_grants_cannot_download_anything(client, tmp_path, monkeypatch):
    doc = _doc("doc_x", "x.pdf", "x", _stored(tmp_path, "x.pdf", b"%PDF x"))
    _as_user(monkeypatch)                          # granted nothing
    assert client.get(f"/api/documents/{doc}/original").status_code == 404


def test_a_missing_stored_file_is_reported_not_served_empty(client, tmp_path, monkeypatch):
    path = _stored(tmp_path, "gone.pdf", b"%PDF gone")
    doc = _doc("doc_gone", "gone.pdf", "g", path)
    path.unlink()
    _as_user(monkeypatch, doc)
    r = client.get(f"/api/documents/{doc}/original")
    assert r.status_code == 404
    # An empty 200 would render as a blank document and look like a real one.
    assert r.content != b""


def test_an_xlsx_original_is_served_with_the_workbook_media_type(
        client, tmp_path, monkeypatch):
    path = _stored(tmp_path, "book.xlsx", b"PK\x03\x04 workbook")
    doc = _doc("doc_xl", "crs-template.xlsx", "xl", path)
    _as_user(monkeypatch, doc)
    r = client.get(f"/api/documents/{doc}/original")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def test_an_unknown_extension_never_becomes_html(client, tmp_path, monkeypatch):
    """A filename is user-supplied. Letting it pick the Content-Type is how a
    document executes in the reader's origin."""
    path = _stored(tmp_path, "odd.bin", b"<html>hi</html>")
    doc = _doc("doc_odd", "payload.html", "odd", path)
    _as_user(monkeypatch, doc)
    r = client.get(f"/api/documents/{doc}/original")
    assert r.headers["content-type"].startswith("application/octet-stream")
    assert "text/html" not in r.headers["content-type"]


def test_a_filename_cannot_inject_a_header(client, tmp_path, monkeypatch):
    path = _stored(tmp_path, "h.pdf", b"%PDF h")
    doc = _doc("doc_h", 'ev"il\r\nX-Injected: yes.pdf', "h", path)
    _as_user(monkeypatch, doc)
    r = client.get(f"/api/documents/{doc}/original")
    assert "x-injected" not in {k.lower() for k in r.headers}
    assert "\r" not in r.headers["content-disposition"]
    assert "\n" not in r.headers["content-disposition"]


def test_the_original_is_not_stored_in_a_shared_cache(client, tmp_path, monkeypatch):
    path = _stored(tmp_path, "c.pdf", b"%PDF c")
    doc = _doc("doc_c", "c.pdf", "c", path)
    _as_user(monkeypatch, doc)
    r = client.get(f"/api/documents/{doc}/original")
    cache = r.headers.get("cache-control", "")
    assert "private" in cache
    assert "public" not in cache


# ------------------------------------------------------------- immutability

def test_an_upload_never_rewrites_an_existing_stored_original():
    """THE MUTATION TARGET (M15). Calls the real `upload.ingest`.

    The scenario is an ORPHANED stored file: bytes on disk at the
    content-addressed path with no `documents` row pointing at them, which is
    what a deleted-then-re-uploaded document leaves behind. `find_by_hash`
    returns nothing, so ingest reaches the store step and meets a file that is
    already there.

    The file is seeded with DIFFERENT content than the upload carries. That
    cannot happen from hashing alone, and that is the point: if the two ever
    disagree - a truncated write, a future change to how the name is derived -
    the existing bytes are the ones every chunk, page image and citation
    already describes, and overwriting them would silently repoint every one of
    those at a different document under the same id.
    """
    import hashlib
    import io

    from app import upload

    payload = b"%PDF-1.7\nreal upload\n"
    digest = hashlib.sha256(payload).hexdigest()
    target = settings.upload_dir / f"{digest}.pdf"
    target.write_bytes(b"%PDF-1.7\nALREADY ON DISK\n")
    before = target.read_bytes()

    row, job_id, duplicate_of = upload.ingest(io.BytesIO(payload), "thing.pdf")

    assert duplicate_of is None, "no documents row existed, so this is not a duplicate"
    assert row["sha256"] == digest
    assert target.read_bytes() == before, "the stored original was rewritten"
    # And no temp file is left behind by the branch that declined to write.
    leftovers = list(settings.upload_dir.glob(".incoming-*.part"))
    assert leftovers == [], f"temp files left behind: {leftovers}"


def test_the_upload_module_guards_the_stored_path(tmp_path):
    """The guard exists in the source, not only in the test above.

    A behavioural test of the real upload path needs a full multipart request
    and a running ingestion worker; this asserts the branch is present so the
    guard cannot be deleted while the behavioural test keeps passing against a
    reimplementation of it.
    """
    from pathlib import Path
    source = Path(__file__).resolve().parent.parent / "app" / "upload.py"
    text = source.read_text(encoding="utf-8")
    assert "if final_path.exists():" in text
    assert "os.replace(temp_path, final_path)" in text
    guard = text.index("if final_path.exists():")
    replace = text.index("os.replace(temp_path, final_path)")
    assert guard < replace, "the overwrite is not guarded by the existence check"
