"""Order 211 (audit R1): a submittal's equipment type and title are recorded
BEFORE its facts are read.

The form reader builds its field list from the recorded equipment type
(`form_reader_run.equipment_type_of`: the stored row, else a quick guess from
the text). The two READY hooks used to read the facts first and classify after,
so the first reading of every sheet ran without what the sheet is. Real
ingestion, no model, invented text.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import classification, datasheets, db, states
from app.main import app
from tests.test_equipment_type_classification import (  # noqa: F401 - temp_storage is a fixture
    PUMP_COVER,
    _run_to_settled,
    _upload,
    temp_storage,
)


@pytest.fixture
def seen_at_read(monkeypatch):
    """What the stored classification held at the moment facts were read."""
    seen: list[dict] = []
    real = datasheets.extract_facts

    def spy(document_id, *args, **kwargs):
        row = (
            db.connect()
            .execute(
                "SELECT document_role, equipment_type, title FROM document_classification"
                " WHERE document_id = ?",
                (document_id,),
            )
            .fetchone()
        )
        seen.append(dict(row) if row else {})
        return real(document_id, *args, **kwargs)

    monkeypatch.setattr(datasheets, "extract_facts", spy)
    return seen


def test_the_ready_hook_classifies_before_it_reads_the_facts(tmp_path, seen_at_read):
    client = TestClient(app)
    doc_id = _upload(client, tmp_path, "pump.pdf", [PUMP_COVER])
    assert classification.set_role(doc_id, "CONTRACTOR_SUBMITTAL")
    assert _run_to_settled(doc_id) == states.READY
    assert seen_at_read, "the facts were never read: the test would prove nothing"
    assert seen_at_read[0]["equipment_type"] == "Centrifugal Pump"


def test_a_role_set_after_ready_classifies_before_it_reads_the_facts(
    tmp_path, seen_at_read
):
    client = TestClient(app)
    doc_id = _upload(client, tmp_path, "pump2.pdf", [PUMP_COVER])
    assert _run_to_settled(doc_id) == states.READY  # no role yet: nothing read
    assert not seen_at_read
    assert classification.set_role(doc_id, "CONTRACTOR_SUBMITTAL")  # on_role_changed
    assert seen_at_read, "the facts were never read: the test would prove nothing"
    assert seen_at_read[0]["equipment_type"] == "Centrifugal Pump"


def test_a_confirmed_form_is_not_reclassified_but_still_read(tmp_path, seen_at_read):
    """`classify=False` (the person just filled the form): no classifier runs,
    the facts are still read, and the person's record is what the reader sees."""
    from app import ingest

    client = TestClient(app)
    doc_id = _upload(client, tmp_path, "pump3.pdf", [PUMP_COVER])
    classification.set_role(doc_id, "CONTRACTOR_SUBMITTAL")
    _run_to_settled(doc_id)
    seen_at_read.clear()
    ingest.on_role_changed(doc_id, classify=False)
    assert seen_at_read and seen_at_read[0]["document_role"] == "CONTRACTOR_SUBMITTAL"
