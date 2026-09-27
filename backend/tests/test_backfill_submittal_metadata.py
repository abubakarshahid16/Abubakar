"""`scripts/backfill_submittal_metadata.py`: item 4 of Fix 3 (2026-09-27).

The script itself calls the SAME functions the live ingestion hook does
(`classification.classify_equipment_type_for_submittal`), whose "never
overwrite a confirmed value" guard is already proven directly in
`test_equipment_type_classification.py::test_a_confirmed_classification_is_
not_overwritten_by_the_classifier`. These tests are about the SCRIPT's own
two responsibilities on top of that: it must actually reach every
CONTRACTOR_SUBMITTAL in the database (not just prove the guard once,
in isolation), and it must refuse a live-shaped path outright rather than
silently writing it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import classification, db, live_guard, submittal_review
from app.config import settings
from app.main import app

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

PUMP_COVER = """Sheet 1 of 7
CENTRIFUGAL PUMP DATA SHEET
Item No.: 09-G-411 A/B
"""


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


def _pdf(path, text) -> str:
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    y = 60
    for line in text.splitlines():
        page.insert_text((50, y), line, fontsize=11)
        y += 18
    doc.save(str(path))
    doc.close()
    return str(path)


def _submittal(client, tmp_path, name) -> str:
    from app import ingest as ingest_mod
    from app import states

    path = _pdf(tmp_path / name, PUMP_COVER)
    with open(path, "rb") as fh:
        resp = client.post("/api/documents", files={"file": (name, fh, "application/pdf")})
    assert resp.status_code == 200, resp.text
    doc_id = resp.json()["document"]["id"]
    classification.set_role(doc_id, "CONTRACTOR_SUBMITTAL")
    worker = ingest_mod.IngestionWorker()
    status = None
    for _ in range(10):
        worker.process(doc_id)
        status = db.connect().execute(
            "SELECT status FROM documents WHERE id = ?", (doc_id,)).fetchone()["status"]
        if status in (states.READY, states.FAILED, states.NO_SEARCHABLE_CONTENT):
            break
    assert status == states.READY, f"fixture did not reach READY: {status}"
    return doc_id


def _classification(doc_id: str) -> dict:
    row = db.connect().execute(
        "SELECT * FROM document_classification WHERE document_id = ?", (doc_id,)).fetchone()
    return dict(row) if row else {}


def test_the_backfill_classifies_every_unconfirmed_submittal_and_skips_confirmed_ones(
        tmp_path, monkeypatch):
    client = TestClient(app)
    unconfirmed_id = _submittal(client, tmp_path, "pump1.pdf")
    confirmed_id = _submittal(client, tmp_path, "pump2.pdf")

    # The ingestion hook (B9) already classifies a submittal the moment it
    # lands on READY - this fixture's own point is that the hook works. The
    # backfill script exists for exactly the OTHER case: a submittal ingested
    # BEFORE this classifier existed (issue #176's own history - see
    # scripts/backfill_submittal_metadata.py's docstring), whose
    # equipment_type is NULL for a reason that has nothing to do with the
    # classifier ever having failed on it. Simulated here by clearing it back
    # to NULL after ingestion - the state a pre-existing submittal is in.
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET equipment_type = NULL,"
            " equipment_type_evidence = NULL WHERE document_id = ?",
            (unconfirmed_id,))
    assert _classification(unconfirmed_id)["equipment_type"] is None, (
        "fixture must start unclassified for this test to mean anything")

    # An administrator already confirmed a DIFFERENT value - this is the one
    # the backfill must leave alone.
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users (id,email,display_name,password_hash,created_at)"
            " VALUES ('admin1','admin@example.test','Admin','h','2026-09-07T00:00:00Z')")
    classification.confirm(
        confirmed_id, doc_type=None, discipline=None, doc_class=None, subject_ids=[],
        confirmed_by="admin1",
        metadata={"document_role": "CONTRACTOR_SUBMITTAL", "equipment_type": "Reciprocating Pump"})

    db_path = settings.db_path
    db.reset_connection()  # the script under test opens its own connection
    import backfill_submittal_metadata as script
    monkeypatch.setattr(sys, "argv", ["backfill_submittal_metadata.py", "--db", str(db_path)])
    assert script.main() == 0

    settings.db_path = db_path
    db.reset_connection()
    assert _classification(unconfirmed_id)["equipment_type"] == "Centrifugal Pump"
    assert _classification(confirmed_id)["equipment_type"] == "Reciprocating Pump", (
        "an engineer's confirmed equipment_type must never be clobbered by the backfill"
    )


def test_the_backfill_refuses_a_live_shaped_path_without_the_live_flag(tmp_path, monkeypatch):
    """`live_guard.is_live_shaped` is purely a shape check on the path - a
    "backend/data/rag_intelligence.sqlite" path anywhere refuses without
    --live, which is exactly the guard this script must never bypass."""
    live_shaped = tmp_path / "checkout" / "backend" / "data" / "rag_intelligence.sqlite"
    live_shaped.parent.mkdir(parents=True)
    assert live_guard.is_live_shaped(live_shaped)

    db.reset_connection()
    import backfill_submittal_metadata as script
    monkeypatch.setattr(sys, "argv", ["backfill_submittal_metadata.py", "--db", str(live_shaped)])
    with pytest.raises(SystemExit):
        script.main()
