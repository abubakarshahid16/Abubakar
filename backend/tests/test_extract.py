import fitz
import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import settings
from app.extract import _batches, extract_document
from app.main import app


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def make_pdf(path, pages: int, blank_pages: set[int] = frozenset()):
    doc = fitz.open()
    for i in range(1, pages + 1):
        page = doc.new_page()
        if i not in blank_pages:
            page.insert_text((72, 100), f"Section {i}.0 Heading", fontsize=13)
            page.insert_text((72, 130), "The quick brown fox jumps over the lazy dog. " * 4, fontsize=9)
    doc.save(str(path))
    doc.close()


def upload(path):
    c = TestClient(app)
    with open(path, "rb") as fh:
        r = c.post("/api/documents", files={"file": (path.name, fh, "application/pdf")})
    return r.json()["document"]["id"]


def test_batches_are_contiguous_and_resume_from_the_checkpoint():
    # 70 pages, batches of 32 -> (0,1-32) (1,33-64) (2,65-70)
    assert _batches(70, 32, 0) == [(0, 1, 32), (1, 33, 64), (2, 65, 70)]
    # resuming after batch 0 must skip it and start at page 33
    assert _batches(70, 32, 1) == [(1, 33, 64), (2, 65, 70)]
    # nothing left once every batch is done
    assert _batches(70, 32, 3) == []


def test_resume_does_not_duplicate_or_skip_pages(tmp_path):
    p = tmp_path / "doc.pdf"
    make_pdf(p, 70)
    doc_id = upload(p)
    conn = db.connect()

    # simulate a crash after batch 0: extract it, then rewind the job
    extract_document(doc_id)
    with conn:
        conn.execute("DELETE FROM pages WHERE document_id=? AND page_no>32", (doc_id,))
        conn.execute("UPDATE jobs SET last_completed_batch=0, state='running' WHERE document_id=?", (doc_id,))
    assert conn.execute("SELECT COUNT(*) FROM pages WHERE document_id=?", (doc_id,)).fetchone()[0] == 32

    r = extract_document(doc_id)
    assert r["resumed_from_batch"] == 1          # not 0 - it did not start over
    rows = conn.execute(
        "SELECT COUNT(*) n, COUNT(DISTINCT page_no) u, MAX(page_no) hi FROM pages WHERE document_id=?",
        (doc_id,)).fetchone()
    assert rows["n"] == rows["u"] == rows["hi"] == 70   # no duplicates, no gaps


def test_blank_pages_are_flagged_needs_ocr_but_not_ocred(tmp_path):
    p = tmp_path / "scan.pdf"
    make_pdf(p, 5, blank_pages={2, 4})
    doc_id = upload(p)
    extract_document(doc_id)
    conn = db.connect()
    flagged = [r["page_no"] for r in conn.execute(
        "SELECT page_no FROM pages WHERE document_id=? AND needs_ocr=1 ORDER BY page_no", (doc_id,))]
    assert flagged == [2, 4]
    doc = conn.execute("SELECT needs_ocr_pages, status FROM documents WHERE id=?", (doc_id,)).fetchone()
    assert doc["needs_ocr_pages"] == 2
    # extraction finished, but the document is NOT ready - it has no chunks yet
    assert doc["status"] == "chunking"


def test_noop_resume_reports_null_rate_not_a_finite_number(tmp_path):
    """Re-extracting a finished document processes 0 pages this run.

    The old code divided pages_total by a near-zero elapsed time and produced
    1021658887.25 pages/sec.
    """
    p = tmp_path / "done.pdf"
    make_pdf(p, 40)
    doc_id = upload(p)

    first = extract_document(doc_id)
    assert first["pages_extracted_this_run"] == 40

    second = extract_document(doc_id)          # nothing left to do
    assert second["pages_extracted_this_run"] == 0
    assert second["pages_extracted"] == 40     # total is still reported
    assert second["pages_per_sec"] is None     # but the rate is not fabricated
    assert isinstance(second["seconds"], float)
