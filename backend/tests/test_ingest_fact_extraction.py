"""B19's other half: fact extraction wired into ingestion completion.

`datasheets.extract_facts` had exactly one production caller -
`submittal_review._extract_facts_if_none`, reachable only when a human
manually starts a review run (`POST /api/reviews/run`). A contractor
submittal that arrived through direct upload or the watched folder was fully
searchable and held ZERO facts until somebody pressed "run review".

These tests go through the REAL ingestion path - `POST /api/documents` then
`IngestionWorker.process`, exactly what the upload route and the folder
watcher both funnel into - and never call `datasheets.extract_facts` or
`submittal_review.create_review_run` directly. A test that called the
extractor itself would prove the extractor works, not that ingestion now
wires it in.
"""

from __future__ import annotations

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import classification, db, states
from app import submittal_review
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

#: Real ruled label-value rows, shaped exactly like the fixtures in
#: `test_datasheets.py`, so the rule-based extractor has genuine values to
#: read rather than prose it will correctly refuse.
ROWS = [
    ("Set pressure", "340 psig By Contractor"),
    ("Density at relieving temper.", "23.55 Kg/m3"),
    ("Design pressure", "23.5 barg"),
    ("Compressibility factor", "0.892"),
]


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


def _datasheet_pdf(path, rows) -> str:
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=500)
    y = 60
    for index, (label, value) in enumerate(rows, start=1):
        page.draw_rect(pymupdf.Rect(40, y - 14, 300, y + 6), color=(0, 0, 0), width=0.7)
        page.draw_rect(pymupdf.Rect(300, y - 14, 560, y + 6), color=(0, 0, 0), width=0.7)
        page.insert_text((44, y), f"{index}", fontsize=9)
        page.insert_text((64, y), label, fontsize=9)
        page.insert_text((304, y), value, fontsize=9)
        y += 26
    doc.save(str(path))
    doc.close()
    return str(path)


def _upload(client, tmp_path, name="EF-DAS-TEST.pdf", rows=ROWS) -> str:
    path = _datasheet_pdf(tmp_path / name, rows)
    with open(path, "rb") as fh:
        resp = client.post(
            "/api/documents", files={"file": (name, fh, "application/pdf")}
        )
    return resp.json()["document"]["id"]


def _run_to_settled(doc_id: str, *, max_passes: int = 10) -> str:
    """Drive `IngestionWorker.process` until the document leaves the pipeline.

    One pass is normally enough for a small, real-text PDF (see
    `test_stage_atomicity.test_after_indexing_the_worker_goes_on_to_embed`),
    but this loops rather than assuming, so the test does not become flaky if
    a future change adds a stage boundary.
    """
    worker = IngestionWorker()
    status = None
    for _ in range(max_passes):
        worker.process(doc_id)
        status = db.connect().execute(
            "SELECT status FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()["status"]
        if status in (states.READY, states.FAILED, states.NO_SEARCHABLE_CONTENT):
            break
    return status


def _facts(doc_id: str) -> list:
    return db.connect().execute(
        "SELECT * FROM submittal_facts WHERE submittal_document_id = ?",
        (doc_id,),
    ).fetchall()


def _review_run_count(doc_id: str) -> int:
    return db.connect().execute(
        "SELECT COUNT(*) c FROM review_runs WHERE submittal_document_id = ?",
        (doc_id,),
    ).fetchone()["c"]


# =========================================================== the new wiring


def test_a_contractor_submittal_gets_facts_from_ingestion_alone(tmp_path):
    """THE MUTATION TARGET. Upload + classify + let the worker finish -
    no review run, no direct call to `extract_facts` - and facts exist."""
    client = TestClient(app)
    doc_id = _upload(client, tmp_path)
    changed = classification.set_role(doc_id, "CONTRACTOR_SUBMITTAL")
    assert changed, "the role must actually be set for this test to mean anything"

    status = _run_to_settled(doc_id)
    assert status == states.READY, f"fixture did not reach READY: {status}"

    facts = _facts(doc_id)
    assert facts, (
        "ingestion completed for a CONTRACTOR_SUBMITTAL with real datasheet "
        "content and produced zero submittal_facts rows - the ingestion "
        "path is still not wired to extract_facts"
    )
    assert all(f["review_run_id"] is None for f in facts), (
        "facts written by the ingestion path must not be attributed to a "
        "review run that was never created"
    )
    assert _review_run_count(doc_id) == 0, (
        "the new wiring must not fabricate a review run just to satisfy "
        "extract_facts's review_run_id parameter"
    )


def test_a_company_standard_never_gets_datasheet_facts(tmp_path):
    """The role gate. A standard document must never run the datasheet
    extractor - it gets `standard_requirements` extraction instead."""
    client = TestClient(app)
    doc_id = _upload(client, tmp_path, name="STD-XX-001.pdf")
    classification.set_role(doc_id, "COMPANY_STANDARD")

    status = _run_to_settled(doc_id)
    assert status == states.READY, f"fixture did not reach READY: {status}"

    assert _facts(doc_id) == [], (
        "a COMPANY_STANDARD must never produce submittal_facts rows"
    )


def test_an_unclassified_document_gets_no_facts(tmp_path):
    """No role yet (NULL) means skip, not a guess at what the document is."""
    client = TestClient(app)
    doc_id = _upload(client, tmp_path, name="unclassified.pdf")

    status = _run_to_settled(doc_id)
    assert status == states.READY, f"fixture did not reach READY: {status}"

    assert _facts(doc_id) == [], (
        "a document with no assigned role must not be treated as a "
        "contractor submittal"
    )


def test_reingesting_a_submittal_with_facts_does_not_duplicate_them(tmp_path):
    """The idempotency guard, exercised a second time.

    `_finish_if_embedded` fires this hook every time a document lands on
    READY - which happens more than once for a document that goes back
    through re-chunking (a later OCR round, a re-extraction) and re-embeds.
    `worker.process()` alone cannot simulate that second landing here (the
    fixture has no OCR rounds to force one), so the hook is called a second
    time directly - the same call `_finish_if_embedded` itself would make.
    """
    from app import ingest as ingest_mod

    client = TestClient(app)
    doc_id = _upload(client, tmp_path)
    classification.set_role(doc_id, "CONTRACTOR_SUBMITTAL")
    _run_to_settled(doc_id)
    first_count = len(_facts(doc_id))
    assert first_count > 0

    # A second landing on READY for the same document - the same thing a
    # re-chunk-then-re-embed cycle, or a second watcher scan, produces.
    ingest_mod._extract_facts_if_contractor_submittal(doc_id)

    assert len(_facts(doc_id)) == first_count, (
        "re-running the ingestion-completion hook over a document that "
        "already has facts must not extract them a second time"
    )
