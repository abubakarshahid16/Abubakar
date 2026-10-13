"""#904 (PF2): re-reading a standard gives every stored sentence the reading of
the code that is stamped on it.

Since #640 a re-read keeps a stored row whose (clause, sentence) is met again:
same id, so findings keep resolving. But it also kept the row's OLD operator,
value, unit and condition and stamped it with the NEW `extractor_version` -
the row said it was read by today's code while holding yesterday's reading,
and no fix to the reader ever reached a sentence already stored (found while
measuring #894: 38 reversed limits would have stayed reversed).

Invented standard only; no model, no socket.
"""
from __future__ import annotations

import uuid

import pytest

from app import db, standards
from tests.test_w6_640_requirements_supersede import NOW, _standard, _user, temp_storage  # noqa: F401

LINES = [
    "5.3.3 Noise",
    "The noise level of rotating equipment shall not exceed 90 dB(A) at",
    "one metre from the equipment surface under rated operating conditions.",
    "6.1 Vibration",
    "The vibration velocity of the bearing housing shall be at least 3 mm/s",
    "when measured with the standard probe at the rated operating point.",
]


def _extract(std):
    return standards.extract_requirements(std, allowed_document_ids=frozenset({std}))


def _rows(std):
    return {r["clause"]: dict(r) for r in db.connect().execute(
        "SELECT * FROM standard_requirements WHERE standard_document_id = ? AND superseded_at IS NULL", (std,))}


def _spoil(std, clause, **wrong):
    """Make a stored row hold what an OLDER reader would have stored."""
    assignments = ", ".join(f"{name} = ?" for name in wrong)
    with db.connect() as conn:
        conn.execute(f"UPDATE standard_requirements SET {assignments}, extractor_version = 'old-reader'"
                     " WHERE standard_document_id = ? AND clause = ?", (*wrong.values(), std, clause))


def test_a_reread_gives_a_stored_sentence_todays_reading_and_keeps_its_id():
    """THE CASE: an older reader stored the noise ceiling reversed."""
    std = _standard(lines=LINES)
    _extract(std)
    before = _rows(std)
    assert before["5.3.3"]["operator"] == "<=" and before["5.3.3"]["raw_value"] == "90"
    _spoil(std, "5.3.3", operator=">", requirement_type="statement", subject="noise level shall not")
    result = _extract(std)
    after = _rows(std)
    assert after["5.3.3"]["id"] == before["5.3.3"]["id"]                    # findings keep resolving
    assert after["5.3.3"]["operator"] == "<=" and after["5.3.3"]["requirement_type"] == "numeric_limit"
    assert after["5.3.3"]["subject"] == before["5.3.3"]["subject"]
    assert after["5.3.3"]["extractor_version"] != "old-reader"              # and the stamp is now true
    assert result["readings_changed"] == 1 and result["kept"] == 2
    assert result["reading_fields_changed"] == {"operator": 1, "requirement_type": 1, "subject": 1}


def test_a_number_a_unit_and_a_condition_are_reread_too():
    std = _standard(lines=LINES)
    _extract(std)
    before = _rows(std)["6.1"]
    _spoil(std, "6.1", value=30.0, raw_value="30", unit=None, raw_unit=None, condition="for old pumps")
    result = _extract(std)
    after = _rows(std)["6.1"]
    for name in ("value", "raw_value", "unit", "raw_unit", "condition"):
        assert after[name] == before[name], name
    assert result["readings_changed"] == 1
    assert set(result["reading_fields_changed"]) == {"value", "raw_value", "unit", "raw_unit", "condition"}


def test_a_row_whose_reading_did_not_change_is_not_counted():
    std = _standard(lines=LINES)
    _extract(std)
    result = _extract(std)
    assert result["readings_changed"] == 0 and result["reading_fields_changed"] == {} and result["kept"] == 2
    assert not db.connect().execute(
        "SELECT 1 FROM audit_events WHERE action = 'standard.requirement_readings_changed'").fetchone()


def test_a_row_a_person_confirmed_keeps_what_the_person_confirmed():
    """A human's decision outranks every parse, including a better one."""
    std = _standard(lines=LINES)
    _extract(std)
    user = _user()
    with db.connect() as conn:
        conn.execute("UPDATE standard_requirements SET operator = '>', confirmed_by = ?, confirmed_at = ?"
                     " WHERE standard_document_id = ? AND clause = '5.3.3'", (user, NOW, std))
    result = _extract(std)
    row = _rows(std)["5.3.3"]
    assert row["operator"] == ">" and row["confirmed_by"] == user
    assert result["readings_changed"] == 0


def test_the_change_is_audited_by_id_and_field_never_by_text():
    std = _standard(lines=LINES)
    _extract(std)
    row_id = _rows(std)["5.3.3"]["id"]
    _spoil(std, "5.3.3", operator=">")
    _extract(std)
    event = db.connect().execute(
        "SELECT detail FROM audit_events WHERE action = 'standard.requirement_readings_changed'").fetchone()
    assert event is not None and row_id in event["detail"] and "operator:1" in event["detail"]
    assert "noise" not in event["detail"].lower() and "90" not in event["detail"]
    summary = db.connect().execute(
        "SELECT detail FROM audit_events WHERE action = 'standard.requirements_extracted'"
        " ORDER BY rowid DESC LIMIT 1").fetchone()
    assert "readings_changed=1" in summary["detail"]


@pytest.mark.parametrize("old, new, same", [
    (None, None, True), ("", None, True), (None, "", True), (90.0, "90", True), ("90", 90, True),
    (90.0, 90.0000000001, True), (90, 91, False), (None, 0, False), (0, None, False), ("", "0", False),
    (">", "<=", False), ("dB(A)", "dB(A)", True), ("mm", None, False),
])
def test_what_counts_as_the_same_reading(old, new, same):
    """Nothing and "" are one nothing; ZERO IS A VALUE, never nothing."""
    assert standards._same_reading(old, new) is same


def test_a_finding_written_against_the_old_reading_still_resolves_its_requirement():
    std = _standard(lines=LINES)
    _extract(std)
    row_id = _rows(std)["5.3.3"]["id"]
    _spoil(std, "5.3.3", operator=">")
    _extract(std)
    assert db.connect().execute(
        "SELECT operator FROM standard_requirements WHERE id = ? AND superseded_at IS NULL",
        (row_id,)).fetchone()["operator"] == "<="
    assert str(uuid.UUID(row_id)) == row_id
