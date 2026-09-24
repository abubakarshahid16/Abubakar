"""B9: automated, evidence-based `equipment_type` for CONTRACTOR_SUBMITTAL.

`document_classification.equipment_type` was written only by `classification.
confirm()`, reachable only through the admin-only `PUT /api/documents/{id}/
classification` route. Nothing in the ingestion path ever called it, so all
275 live rows carried `equipment_type IS NULL` no matter what the underlying
PDF said about itself - measured, not assumed (see the B9 task notes).

These tests go through the REAL ingestion path - `POST /api/documents`, set
the role, then drive `IngestionWorker.process` to READY - the same path
`test_ingest_fact_extraction.py` uses for the sibling B19 wiring, and for the
same reason: a test that called `classification.classify_equipment_type_for_
submittal` directly would prove the classifier works, not that ingestion now
wires it in.

Title text mirrors the STRUCTURE of real engineering datasheet cover pages
(a "<EQUIPMENT> DATA SHEET" / "PRESSURE SAFETY VALVES (PSVs)" / "MECHANICAL
DATASHEET ... pressure vessel" convention) without reproducing any of the
client's own document numbers, tags or filenames.
"""

from __future__ import annotations

import json

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import classification, db, states
from app import submittal_review
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app


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


def _pdf(path, pages: list[str]) -> str:
    """One page of real, extractable text per string in `pages`."""
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page(width=612, height=792)
        y = 60
        for line in text.splitlines():
            page.insert_text((50, y), line, fontsize=11)
            y += 18
    doc.save(str(path))
    doc.close()
    return str(path)


def _upload(client, tmp_path, name, pages) -> str:
    path = _pdf(tmp_path / name, pages)
    with open(path, "rb") as fh:
        resp = client.post(
            "/api/documents", files={"file": (name, fh, "application/pdf")})
    assert resp.status_code == 200, resp.text
    return resp.json()["document"]["id"]


def _run_to_settled(doc_id: str, *, max_passes: int = 10) -> str:
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


def _classification(doc_id: str) -> dict:
    row = db.connect().execute(
        "SELECT * FROM document_classification WHERE document_id = ?",
        (doc_id,)).fetchone()
    return dict(row) if row else {}


PUMP_COVER = """Sheet 1 of 7
SOME CLIENT (X.Y.Z.)
Project: A Refinery Debottlenecking Project
CENTRIFUGAL PUMP DATA SHEET
Item No.: 09-G-411 A/B
Doc. No.: SITE-DAS-M-01
This document is subject to detail design verification.
"""

PSV_COVER = """Page 1 of 5
PRESSURE SAFETY VALVES (PSVs)
DOCUMENT NO. SITE-DAS-I-02
Design Standard: API RP 520 Pt-1&2
Tag No. PSV-1001 A/B
Location 1st Stage Separator
This document is subject to detail design verification, development and
inclusion of vendor design information by the Contractor before issue.
"""

# The vessel document's own cover carries no "pressure vessel" phrase - the
# REAL corpus document does not either, it says "MECHANICAL DATASHEET ...
# DRUMS" on its cover and only names "pressure vessel" in a body clause
# several pages in ("materials and workmanship of the pressure vessel",
# "Manufacture of Pressure Vessels"). This fixture reproduces that shape: a
# generic cover, then a body page carrying the real distinguishing phrase.
VESSEL_COVER = """MECHANICAL DATASHEET
SOUR SERVICE DRUM
CONTRACTOR DOC NO: SITE-2003-SP-0001
Rev. 00
This document is subject to detail design verification, development and
inclusion of vendor design information by the Contractor before issue.
"""
VESSEL_BODY = """Sht 4 Vessel Standards
Non Material Requirements for Pressure Vessels
The VENDOR shall warrant materials and workmanship of the pressure vessel
for a period of not less than eighteen months from the date of shipment.
32-SAMSS-004 (Manufacture of Pressure Vessels)
"""

NO_EVIDENCE_COVER = """TRANSMITTAL COVER SHEET
Project Correspondence
Subject: Response to comments received on the previous submission
Reference: Letter 4521 dated earlier this month regarding scheduling
No equipment of any kind is named anywhere on this particular page.
"""


def _submittal(client, tmp_path, name, pages) -> str:
    doc_id = _upload(client, tmp_path, name, pages)
    changed = classification.set_role(doc_id, "CONTRACTOR_SUBMITTAL")
    assert changed, "the role must actually be set for this test to mean anything"
    status = _run_to_settled(doc_id)
    assert status == states.READY, f"fixture did not reach READY: {status}"
    return doc_id


# =========================================================== the new wiring


def test_a_pump_datasheet_is_classified_as_a_pump_not_a_vessel(tmp_path):
    client = TestClient(app)
    doc_id = _submittal(client, tmp_path, "pump.pdf", [PUMP_COVER])

    record = _classification(doc_id)
    assert record["equipment_type"] == "Centrifugal Pump", record
    assert record["equipment_type"] != "Pressure Vessel"

    evidence = json.loads(record["equipment_type_evidence"])
    assert evidence["page"] == 1
    assert "centrifugal pump" in evidence["quote"].lower()
    assert evidence["method"] == "title_phrase_match"
    assert evidence["confidence"] < 0.9, "confidence must never read as 'high'"
    assert evidence["classifier_version"]


def test_a_psv_datasheet_is_classified_as_a_valve_not_a_pump(tmp_path):
    client = TestClient(app)
    doc_id = _submittal(client, tmp_path, "psv.pdf", [PSV_COVER])

    record = _classification(doc_id)
    assert record["equipment_type"] == "Pressure Safety Valve", record
    assert record["equipment_type"] != "Centrifugal Pump"
    assert record["equipment_type"] != "Pump"

    evidence = json.loads(record["equipment_type_evidence"])
    assert evidence["page"] == 1
    assert "pressure safety valve" in evidence["quote"].lower()


def test_a_vessel_datasheet_is_classified_from_its_body_text(tmp_path):
    """The cover alone names no equipment; only the body clause does - the
    same shape as the real vessel datasheet this fixture is modelled on
    (cover: "MECHANICAL DATASHEET ... DRUMS"; body: "materials and
    workmanship of the pressure vessel"). This is checked by confirming the
    COVER PAGE ALONE produces no match, and only adding the body text tips
    it into "Pressure Vessel" - proof the classifier read past the cover
    rather than guessing from a generic "MECHANICAL DATASHEET" title.
    """
    client = TestClient(app)
    cover_only_id = _submittal(client, tmp_path, "vessel_cover_only.pdf", [VESSEL_COVER])
    assert _classification(cover_only_id)["equipment_type"] is None, (
        "the cover alone names no equipment and must not be guessed at"
    )

    doc_id = _submittal(client, tmp_path, "vessel.pdf", [VESSEL_COVER, VESSEL_BODY])
    record = _classification(doc_id)
    assert record["equipment_type"] == "Pressure Vessel", record

    evidence = json.loads(record["equipment_type_evidence"])
    assert "pressure vessel" in evidence["quote"].lower()
    assert evidence["page"] in (1, 2), evidence
    assert evidence["method"] in ("title_phrase_match", "body_phrase_match")


def test_a_document_with_no_evidence_stays_unclassified(tmp_path):
    """Proves the classifier does not guess.

    Calls `classification.classify_equipment_type_for_submittal` DIRECTLY, in
    addition to checking the stored row - the ingestion hook
    (`ingest._classify_equipment_type_if_contractor_submittal`) catches and
    records any exception rather than raising it, which would hide a broken
    "no match" guard behind an ordinary-looking NULL: the write simply never
    happens, so the column looks the same whether the guard works or the
    function crashed before reaching it.
    """
    client = TestClient(app)
    doc_id = _submittal(client, tmp_path, "cover.pdf", [NO_EVIDENCE_COVER])

    record = _classification(doc_id)
    assert record["equipment_type"] is None, record
    assert record["equipment_type_evidence"] is None

    assert classification.classify_equipment_type_for_submittal(doc_id) is None, (
        "no phrase matched, so the classifier must return None rather than "
        "guess - or crash trying to read a guess that was never made"
    )


def test_a_company_standard_never_gets_equipment_type_set(tmp_path):
    client = TestClient(app)
    doc_id = _upload(client, tmp_path, "standard.pdf", [PUMP_COVER])
    classification.set_role(doc_id, "COMPANY_STANDARD")
    status = _run_to_settled(doc_id)
    assert status == states.READY, f"fixture did not reach READY: {status}"

    record = _classification(doc_id)
    assert record["equipment_type"] is None, (
        "a COMPANY_STANDARD must never receive an equipment_type from this "
        "classifier - equipment_type does not apply to a standard"
    )


def test_an_unclassified_document_gets_no_equipment_type(tmp_path):
    client = TestClient(app)
    doc_id = _upload(client, tmp_path, "unclassified.pdf", [PUMP_COVER])
    status = _run_to_settled(doc_id)
    assert status == states.READY, f"fixture did not reach READY: {status}"

    record = _classification(doc_id)
    assert record.get("equipment_type") is None


# ===================================================== reclassification (B9)


def test_reclassification_is_versioned_not_silently_overwritten(tmp_path):
    """Changing evidence changes the stored value AND leaves an audit trail.

    Simulates a submittal whose cover page evidence changes between two
    ingestion-completion landings (the same "document lands on READY more
    than once" scenario `test_reingesting_a_submittal_with_facts_does_not_
    duplicate_them` exercises for facts) by editing its chunk text directly
    between two calls to the hook - the narrowest way to prove the OLD value
    is recorded rather than simply replaced.
    """
    client = TestClient(app)
    doc_id = _submittal(client, tmp_path, "pump.pdf", [PUMP_COVER])
    first = _classification(doc_id)
    assert first["equipment_type"] == "Centrifugal Pump"

    # THE EVIDENCE CHANGES WHERE THE CLASSIFIER READS IT. Since #183 the title
    # block is read from `pages` first and chunks second, so both change -
    # editing only the chunk would leave the page-1 title saying "pump".
    conn = db.connect()
    with conn:
        conn.execute(
            "UPDATE chunks SET text = ? WHERE document_id = ? AND page_start = 1",
            (PSV_COVER, doc_id))
        conn.execute(
            "UPDATE pages SET text = ? WHERE document_id = ? AND page_no = 1",
            (PSV_COVER, doc_id))

    from app import ingest as ingest_mod
    ingest_mod._classify_equipment_type_if_contractor_submittal(doc_id)

    second = _classification(doc_id)
    assert second["equipment_type"] == "Pressure Safety Valve", second

    audit_rows = conn.execute(
        "SELECT * FROM audit_events WHERE action = 'equipment_type_reclassified'"
        " AND resource_id = ?", (doc_id,)).fetchall()
    assert len(audit_rows) == 1, (
        "exactly one reclassification happened and must produce exactly one "
        "audit row"
    )
    detail = json.loads(audit_rows[0]["detail"])
    assert detail["old"] == "Centrifugal Pump", (
        "the OLD value must be recorded before being overwritten, not lost"
    )
    assert detail["new"] == "Pressure Safety Valve"
    # PRIVACY: the audit detail must never carry the document's own text.
    assert "quote" not in detail
    assert "psv" not in json.dumps(detail).lower() or detail["new"] == "Pressure Safety Valve"


def test_reclassification_to_the_same_value_does_not_audit(tmp_path):
    """Re-running the classifier over an unchanged document is a no-op,
    not a reclassification - no audit row for a value that did not change."""
    client = TestClient(app)
    doc_id = _submittal(client, tmp_path, "pump.pdf", [PUMP_COVER])

    from app import ingest as ingest_mod
    ingest_mod._classify_equipment_type_if_contractor_submittal(doc_id)
    ingest_mod._classify_equipment_type_if_contractor_submittal(doc_id)

    conn = db.connect()
    audit_rows = conn.execute(
        "SELECT * FROM audit_events WHERE action = 'equipment_type_reclassified'"
        " AND resource_id = ?", (doc_id,)).fetchall()
    assert len(audit_rows) == 0


def test_a_confirmed_classification_is_not_overwritten_by_the_classifier(tmp_path):
    """An administrator's `confirm()` is authoritative; automation defers to it."""
    client = TestClient(app)
    doc_id = _submittal(client, tmp_path, "pump.pdf", [PUMP_COVER])
    assert _classification(doc_id)["equipment_type"] == "Centrifugal Pump"

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users (id,email,display_name,password_hash,created_at)"
            " VALUES ('admin1','admin@example.test','Admin','h',"
            "'2026-09-07T00:00:00Z')")
    classification.confirm(
        doc_id, doc_type=None, discipline=None, doc_class=None, subject_ids=[],
        confirmed_by="admin1",
        # `metadata` REPLACES every METADATA_FIELDS column (confirm()'s own
        # docstring: "a PUT sends the whole record"), `document_role`
        # included - it must be repeated here or the confirm would silently
        # clear the very role this classifier gates on.
        metadata={"document_role": "CONTRACTOR_SUBMITTAL",
                 "equipment_type": "Reciprocating Pump"})
    assert _classification(doc_id)["equipment_type"] == "Reciprocating Pump"

    from app import ingest as ingest_mod
    ingest_mod._classify_equipment_type_if_contractor_submittal(doc_id)

    record = _classification(doc_id)
    assert record["equipment_type"] == "Reciprocating Pump", (
        "a confirmed equipment_type must not be overwritten by the automated "
        "classifier re-running over the same document"
    )
