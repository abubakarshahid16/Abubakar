"""Order 261.2: a failed AI reading never makes a verdict more confident. s2's real clean vs broken
I-06 reader summaries (counts only) as invented fixtures. No model, no network."""

from __future__ import annotations

import pytest

from app import (
    absence,
    datasheets,
    db,
    degraded_read,
    form_reader_fields,
    submittal_review,
)
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "degraded.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


# s2's REAL clean I-06 read (35B): the AI proposes far more than it can prove, so many gate
# refusals (117 > agreed 58) are normal; they are quote and value checks, not engine failures.
CLEAN = {
    "engine": "local",
    "pages": 5,
    "pages_read": 5,
    "timed_out": [],
    "code_only": {},
    "refused_by_gate": 117,
    "agreed": 58,
    "facts_written": 68,
    "conflicts": 16,
    "rejected_fields": {
        "set_pressure: quote_not_on_page": 4,
        "design_temperature: value_not_in_quote": 9,
        "bearing_type: label_not_in_quote": 2,
    },
}
# the same sheet when the engine failed under it: replies cut off / malformed / not answered for
# some fields, fewer facts, fewer agreements, fewer conflicts
BROKEN = {
    **CLEAN,
    "refused_by_gate": 46,
    "agreed": 24,
    "facts_written": 39,
    "conflicts": 4,
    "rejected_fields": {
        "set_pressure: model_malformed": 2,
        "design_temperature: field_not_answered": 2,
        "bearing_type: label_not_in_quote": 2,
    },
}


def passes(*roles):
    return [
        {
            "rule_id": f"P{i}",
            "role": role,
            "status": "COMPLIANT",
            "checklist": True,
            "detail": "stated",
        }
        for i, role in enumerate(roles)
    ]


@pytest.fixture
def reader(monkeypatch):
    def set_summary(summary):
        monkeypatch.setattr(datasheets, "latest_reader_summary", lambda _doc: summary)

    return set_summary


def test_a_clean_read_with_many_gate_refusals_holds_and_flags_nothing(reader):
    assert CLEAN["refused_by_gate"] > CLEAN["agreed"]
    assert degraded_read.missing_roles(CLEAN) == {}
    assert degraded_read.assess(CLEAN) is None
    reader(CLEAN)
    results = passes("set_pressure", "design_temperature", "bearing_type")
    assert degraded_read.hold(results, "doc") == results


def test_only_the_fields_whose_ai_reading_did_not_come_back_are_held(reader):
    assert degraded_read.missing_roles(BROKEN) == {
        "set_pressure": ["model_malformed"],
        "design_temperature": ["field_not_answered"],
    }
    reader(BROKEN)
    held = {
        r["role"]: r["status"]
        for r in degraded_read.hold(
            passes("set_pressure", "design_temperature", "bearing_type", "flow"), "doc"
        )
    }
    assert held == {
        "set_pressure": "NEEDS_ENGINEER_REVIEW",
        "design_temperature": "NEEDS_ENGINEER_REVIEW",
        "bearing_type": "COMPLIANT",  # refused by a quote check: a gate doing its job
        "flow": "COMPLIANT",
    }


def test_the_broken_read_gives_no_more_meets_than_the_clean_one(reader):
    roles = ["set_pressure", "design_temperature", "bearing_type", "flow", "orifice"]
    reader(CLEAN)
    clean = degraded_read.hold(passes(*roles), "doc")
    reader(BROKEN)
    broken = degraded_read.hold(passes(*roles), "doc")
    meets = lambda rs: sum(r["status"] == "COMPLIANT" for r in rs)  # noqa: E731
    assert meets(broken) < meets(clean) == 5
    held = next(r for r in broken if r["role"] == "set_pressure")
    assert (
        "AI reading missing" in held["detail"] and "model_malformed" in held["detail"]
    )


def test_a_failure_a_missing_value_and_a_non_checklist_pass_keep_their_status(reader):
    reader(BROKEN)
    results = [
        {
            "role": "set_pressure",
            "status": "NON_COMPLIANT",
            "checklist": True,
            "detail": "x",
        },
        {
            "role": "set_pressure",
            "status": "MISSING_INFORMATION",
            "checklist": True,
            "detail": "x",
        },
        {"role": "set_pressure", "status": "COMPLIANT", "detail": "a consistency pair"},
        {"role": None, "status": "COMPLIANT", "checklist": True, "detail": "x"},
    ]
    kept = [r["status"] for r in degraded_read.hold(results, "doc")]
    assert kept == ["NON_COMPLIANT", "MISSING_INFORMATION", "COMPLIANT", "COMPLIANT"]


def test_every_form_reader_error_reason_is_a_missing_reading():
    from app.form_reader import Reason

    errors = {
        Reason.MODEL_FAILED,
        Reason.MODEL_CUT_OFF,
        Reason.MODEL_TIMED_OUT,
        Reason.MODEL_MALFORMED,
        Reason.MODEL_STOPPED,
        Reason.MODEL_UNSTABLE,
        Reason.FIELD_NOT_ANSWERED,
    }
    assert {r.value for r in errors} == set(degraded_read.ERROR_REASONS)
    # a failed quote or value check is not one of them
    assert Reason.QUOTE_NOT_ON_PAGE.value not in degraded_read.ERROR_REASONS


def test_the_banner_names_a_page_the_engine_could_not_read_and_a_low_agreed_share():
    assert degraded_read.assess(BROKEN)["why"] == ["low_agreement", "fields_missing"]
    failed = {
        **CLEAN,
        "code_only": {"2": "engine answer unusable (x)", "3": "no text on this page"},
    }
    record = degraded_read.assess(failed)
    assert record["why"] == ["failed_pages"] and record["failed_pages"] == 1
    assert degraded_read.is_part(record)
    assert not degraded_read.is_part(degraded_read.assess(BROKEN))  # internal note only
    assert degraded_read.assess({**CLEAN, "timed_out": [4]})["why"] == ["timed_out"]
    assert degraded_read.assess({**CLEAN, "stopped": "time budget"})["why"] == [
        "stopped"
    ]
    assert degraded_read.assess({**CLEAN, "unavailable": "no model"})["why"] == [
        "unavailable"
    ]


def test_an_ai_reader_that_was_not_asked_is_not_flagged():
    assert degraded_read.assess({"engine": "off", "pages": 3}) is None
    assert degraded_read.assess(None) is None


def test_the_split_carries_the_record_and_the_reader_summary(reader):
    reader(BROKEN)
    split = degraded_read.with_reader({"checked": 3}, "doc")
    assert (
        split["reader"] == BROKEN and "fields_missing" in split["degraded_read"]["why"]
    )
    reader(CLEAN)
    clean = degraded_read.with_reader({"checked": 3}, "doc")
    assert "degraded_read" not in clean and clean["reader"] == CLEAN


def test_the_crs_banner_lists_a_failed_page_but_a_low_share_is_not_in_the_banner():
    counts = {"not_compared": 0, "not_applied": 0, "checked": 5}

    def parts(record):
        outcome = {
            "requirement_split": {"degraded_read": record},
            "unchecked_counts": counts,
        }
        return absence.unchecked_parts(run_status="completed", outcome=outcome)

    failed = degraded_read.assess(
        {**CLEAN, "code_only": {"2": "engine answer unusable (x)"}}
    )
    shown = parts(failed)
    assert [p["part"] for p in shown] == ["degraded_read"] and "detail" not in shown[0]
    assert "REVIEW INCOMPLETE" in absence.notice_for(shown)
    # a low agreed share or missing fields alone stay in the stored record, never in the banner
    assert parts(degraded_read.assess(BROKEN)) == []
    assert absence.unchecked_parts(run_status="completed", outcome={}) == []


def _checklist_findings():
    rows = db.connect().execute(
        "SELECT compliance_status FROM review_findings WHERE origin = 'datasheet_check'"
    )
    return [r["compliance_status"] for r in rows]


def test_a_whole_review_holds_the_passes_of_fields_the_ai_did_not_read(monkeypatch):
    from tests.test_746_checklist_governs import _review, _review_again

    monkeypatch.setattr(datasheets, "latest_reader_summary", lambda _doc: CLEAN)
    _review("Pressure Safety Valve")
    clean = _checklist_findings()
    assert "COMPLIANT" in clean

    roles = [f.key for f in form_reader_fields.field_list_for("Pressure Safety Valve")]
    broken = {**BROKEN, "rejected_fields": {f"{r}: model_malformed": 1 for r in roles}}
    monkeypatch.setattr(datasheets, "latest_reader_summary", lambda _doc: broken)
    result, _stored, _ids = _review_again("Pressure Safety Valve")
    after = _checklist_findings()
    assert "COMPLIANT" not in after and "NEEDS_ENGINEER_REVIEW" in after
    assert len(after) == len(clean)
    assert "fields_missing" in result["requirement_split"]["degraded_read"]["why"]
