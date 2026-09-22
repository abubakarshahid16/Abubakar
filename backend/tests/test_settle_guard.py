"""The settle guard: progress must not be mistaken for churn.

One OCR round costs three passes of the status loop, and ocr.round_size doubles
each round, so a heavily scanned document legitimately needs many more passes
than a document that walks the states once. The guard used to count passes and
allow about ten; a document that was progressing correctly reached `failed`
after three rounds, with a reason that blamed the state machine and never
named OCR.
"""
import pymupdf
from fastapi.testclient import TestClient
from app import db, states, ocr as ocr_mod
from app.config import settings
from app.main import app
from app.db import connect


def make(tmp):
    doc = pymupdf.open()
    doc.new_page()                       # scanned page -> needs_ocr
    p = doc.new_page()
    p.insert_text((72, 100), "Section 2.0 Coating", fontsize=13)
    p.insert_text((72, 130), "The quick brown fox jumps over the lazy dog. " * 5, fontsize=9)
    path = tmp / "s.pdf"; doc.save(str(path)); doc.close(); return path


def test_ocr_rounds_are_progress_not_churn(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "u")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection(); db.init_db()
    pdf = make(tmp_path)
    c = TestClient(app)
    with open(pdf, "rb") as fh:
        doc_id = c.post("/api/documents",
                        files={"file": ("s.pdf", fh, "application/pdf")}
                        ).json()["document"]["id"]

    from app.extract import extract_document
    from app.chunker import chunk_document
    extract_document(doc_id); chunk_document(doc_id)

    calls = {"n": 0}

    def fake(did, max_pages=None, progress=None):
        # Four successive rounds that each read new pages: legitimate progress.
        # Writes to the database exactly as the real recognise_document does,
        # because "progress" means the document's recorded work advanced - a
        # round that reports success while changing nothing IS churn.
        calls["n"] += 1
        remaining = max(0, 4 - calls["n"])
        c = connect()
        with c:
            c.execute(
                """INSERT OR REPLACE INTO page_ocr (document_id, page_no, text,
                       char_count, engine, model, dpi, box_count, seconds,
                       recognised_at, batch_no)
                   VALUES (?,?,?,?,'stub','stub',150,3,0.1,'2026-01-01T00:00:00Z',?)""",
                (did, calls["n"], "recognised text " * 20, 320, calls["n"]))
            c.execute("UPDATE documents SET recognised_pages = ? WHERE id = ?",
                      (calls["n"], did))
        return {"document_id": did, "filename": "s.pdf", "pages_pending": 1,
                "pages_recognised": 1, "pages_remaining": remaining,
                "pages_with_text": 1, "alphabet_violations": 0,
                "seconds": 0.1, "batches": 1, "model": "stub"}

    monkeypatch.setattr(ocr_mod, "recognise_document", fake)
    monkeypatch.setattr(ocr_mod, "pending_pages",
                        lambda d: [1] if calls["n"] < 4 else [])

    from app.ingest import IngestionWorker
    IngestionWorker().process(doc_id)

    row = connect().execute(
        "SELECT status, error_message FROM documents WHERE id=?", (doc_id,)).fetchone()
    print(f"\nOCR rounds driven: {calls['n']}")
    print(f"FINAL STATUS: {row['status']}")
    print(f"ERROR       : {row['error_message']}")
    assert row["status"] != states.FAILED, row["error_message"]



def test_a_genuinely_stuck_loop_is_still_caught_and_says_what_stopped(
        tmp_path, monkeypatch):
    """The guard must still fire. A round that reports success while changing
    nothing is churn, however many times it repeats - and the recorded reason
    has to name the stage that stopped, not the loop that noticed."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "u")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t2.sqlite")
    db.reset_connection(); db.init_db()
    pdf = make(tmp_path)
    c = TestClient(app)
    with open(pdf, "rb") as fh:
        doc_id = c.post("/api/documents",
                        files={"file": ("s2.pdf", fh, "application/pdf")}
                        ).json()["document"]["id"]
    from app.extract import extract_document
    from app.chunker import chunk_document
    extract_document(doc_id); chunk_document(doc_id)

    spins = {"n": 0}

    def never_progresses(did, max_pages=None, progress=None):
        spins["n"] += 1
        return {"document_id": did, "filename": "s2.pdf", "pages_pending": 1,
                "pages_recognised": 1, "pages_remaining": 1,
                "pages_with_text": 1, "alphabet_violations": 0,
                "seconds": 0.1, "batches": 1, "model": "stub"}

    monkeypatch.setattr(ocr_mod, "recognise_document", never_progresses)
    monkeypatch.setattr(ocr_mod, "pending_pages", lambda d: [1])

    from app.ingest import IngestionWorker
    IngestionWorker().process(doc_id)

    row = connect().execute(
        "SELECT status, error_message FROM documents WHERE id=?", (doc_id,)).fetchone()
    assert row["status"] == states.FAILED, "a non-settling loop must still fail"
    msg = row["error_message"]
    # The reason names the STAGE, not the detector.
    assert "did not settle" not in msg, msg
    assert "recognition" in msg and "scanned page" in msg, msg
    assert spins["n"] < 60, f"spun {spins['n']} times before the guard fired"
