"""#725 F3: a datasheet value with a note is a value plus a note, never blank.

On the real PSV datasheet the set pressure reads "340 psig (By Contractor, as
per Code)". Because "By Contractor" appeared anywhere in the cell, the field
was stored as BLANK and the CRS told the contractor the set pressure was "left
to be provided". A field is blank only when no value is present; the marker
is kept as the value's note, and a finding names it. Invented values only.
"""
from __future__ import annotations

import pytest

from app import comparison, datasheets


@pytest.mark.parametrize("text,value,note", [
    ("340 psig (By Contractor, as per Code)", "340", "By Contractor"),
    ("(By Contractor) 340 psig", "340", "By Contractor"),
    ("340 psig - by contractor", "340", "by contractor"),
    ("10 barg (by vendor)", "10", "by vendor"),
])
def test_a_value_beside_a_marker_is_a_value_with_a_note(text, value, note):
    assert datasheets.is_blank_value(text) == (False, None)
    cols = datasheets.value_columns(text, field_label="Set pressure")
    assert cols["is_blank"] is False
    assert cols["raw_value"] == value
    assert cols["value_note"] == note
    assert cols["blank_marker"] is None


def test_a_range_beside_a_marker_is_a_range_with_a_note():
    cols = datasheets.value_columns("5-10 bar (by vendor)", field_label="Pressure range")
    assert cols["is_blank"] is False
    assert (cols["value_min"], cols["value_max"]) == (5.0, 10.0)
    assert cols["value_note"] == "by vendor"


@pytest.mark.parametrize("text", ["By Contractor", "TBD", "Vendor to advise", "", "______",
                                  "By Contractor, as per Code"])
def test_a_marker_with_no_value_is_still_blank(text):
    cols = datasheets.value_columns(text, field_label="Set pressure")
    assert cols["is_blank"] is True
    assert cols["raw_value"] is None and cols["value_note"] is None


def test_a_plain_value_has_no_note():
    cols = datasheets.value_columns("340 psig", field_label="Set pressure")
    assert cols["is_blank"] is False and cols["raw_value"] == "340"
    assert cols["value_note"] is None


def test_the_note_is_stored_with_the_fact(tmp_path, monkeypatch):
    from app import db, submittal_review
    from app.config import settings
    monkeypatch.setattr(settings, "db_path", tmp_path / "f3.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    with db.connect() as conn:
        conn.execute("INSERT INTO documents (id, filename, sha256, size_bytes, stored_path, status,"
                     " uploaded_at) VALUES ('sub','s.pdf','x',1,'s.pdf','ready','2026-10-09T00:00:00Z')")
        conn.execute("INSERT INTO chunks (id, document_id, filename, ordinal, page_start, page_end,"
                     " section, kind, text, token_count, content_hash, retrievable) VALUES"
                     " ('c','sub','s.pdf',0,1,1,NULL,'prose','Set pressure 340 psig',4,'h',1)")
        conn.execute("INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at)"
                     " VALUES ('run','sub','pending','2026-10-09T00:00:00Z','2026-10-09T00:00:00Z')")
    fact = datasheets.create_fact(submittal_document_id="sub", chunk_id="c", review_run_id="run",
                                  field_label="Set pressure",
                                  raw_value="340 psig (By Contractor, as per Code)", page=1)
    row = db.connect().execute("SELECT is_blank, raw_value, value_note FROM submittal_facts"
                               " WHERE id = ?", (fact["id"],)).fetchone()
    assert (row["is_blank"], row["raw_value"], row["value_note"]) == (0, "340", "By Contractor")
    db.reset_connection()


def test_a_finding_on_a_noted_value_names_the_note():
    requirement = {"id": "r", "standard_document_id": None, "requirement_type": "numeric_limit",
                   "requirement_text": "Set pressure shall not exceed 400 psig.",
                   "operator": "<=", "raw_value": "400", "raw_unit": "psig",
                   "field": "set pressure", "exceptions": []}
    fact = {"id": "f", "document_id": None, "field_name": "set pressure",
            "field_label": "Set pressure", "field_value": "340 psig (By Contractor, as per Code)",
            "raw_value": "340", "raw_unit": "psig", "is_blank": 0, "blank_marker": None,
            "value_note": "By Contractor"}
    verdict = comparison.compare(requirement, fact)
    assert verdict["status"] == comparison.COMPLIANT
    assert "By Contractor" in verdict["rationale"]
