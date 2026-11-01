"""Order 261.2: a failed AI reading never makes a verdict more confident. s2's REAL stored reader
summaries (counts only) as fixtures: three clean relief-valve reads, a clean pump-sheet read, the
broken read (every page read only in part, "engine answer unusable", no per-field error reason).
No model, no network."""

from __future__ import annotations

import pytest

from app import (
    absence,
    datasheets,
    db,
    degraded_read,
    submittal_review,
)
from app.config import settings

PARTLY = "read in 2 parts after the answer was cut off; 1 part(s) not read (engine answer unusable)"


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


# a CLEAN relief-valve read: 117 gate refusals against 58 agreed is normal (the AI proposes more
# than it can prove); its 13 per-field refusals are quote and value checks, not engine errors
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
        "set_pressure: blank_marker_not_proven": 11,
        "design_temperature: value_not_in_quote": 1,
        "bearing_type: unit_not_in_quote": 1,
    },
}
# a CLEAN pump-sheet read: only 27 of its 51 facts are agreed (0.53)
CLEAN_PUMP = {**CLEAN, "pages": 7, "pages_read": 7, "facts_written": 51, "agreed": 27}
# the same sheet when the engine failed under it: HTTP 200, no timeout, the SAME per-field
# refusals as the clean run, but every page read only in part
BROKEN = {
    **CLEAN,
    "refused_by_gate": 46,
    "agreed": 24,
    "facts_written": 39,
    "conflicts": 4,
    "partly_read": {str(p): PARTLY for p in range(1, 6)},
}


def passes(*roles, rule_ids=None):
    return [
        {
            "rule_id": (rule_ids or {}).get(role, f"P{i}"),
            "role": role,
            "status": "COMPLIANT",
            "checklist": True,
            "detail": "stated",
        }
        for i, role in enumerate(roles)
    ]


def meets(results):
    return sum(r["status"] == "COMPLIANT" for r in results)


@pytest.fixture
def reader(monkeypatch):
    def set_summary(summary):
        monkeypatch.setattr(datasheets, "latest_reader_summary", lambda _doc: summary)

    return set_summary


@pytest.mark.parametrize("summary", [CLEAN, CLEAN_PUMP])
def test_a_clean_read_is_not_flagged_and_holds_nothing(summary, reader):
    """Many gate refusals (117 > 58) and a low agreed share (0.53) are normal on a clean read."""
    assert summary["refused_by_gate"] > summary["agreed"] or summary is CLEAN_PUMP
    assert degraded_read.assess(summary) is None
    reader(summary)
    results = passes("set_pressure", "design_temperature", "bearing_type")
    assert degraded_read.hold(results, "doc") == results


def test_the_broken_read_is_flagged_and_no_checklist_pass_survives(reader):
    record = degraded_read.assess(BROKEN)
    assert record["why"] == ["partly_read_pages"] and record["partly_read_pages"] == 5
    assert degraded_read.is_part(record)
    assert (
        degraded_read.missing_roles(BROKEN) == {}
    )  # it has no per-field error reason at all
    roles = ["set_pressure", "design_temperature", "bearing_type", "flow", "orifice"]
    reader(CLEAN)
    clean = degraded_read.hold(passes(*roles), "doc")
    reader(BROKEN)
    broken = degraded_read.hold(passes(*roles), "doc")
    assert meets(clean) == 5 and meets(broken) == 0 <= meets(clean)
    assert "AI reading missing" in broken[0]["detail"]
    assert "5 page(s) were read only in part" in broken[0]["detail"]


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ({"cut_off": [2]}, "cut_off_pages"),
        ({"timed_out": [3]}, "timed_out_pages"),
        ({"code_only": {"2": "engine answer unusable (x)"}}, "failed_pages"),
        ({"stopped": "time budget"}, "stopped"),
        ({"unavailable": "no model"}, "unavailable"),
    ],
)
def test_every_other_way_a_page_is_not_fully_read_flags_and_holds(change, why, reader):
    record = degraded_read.assess({**CLEAN, **change})
    assert why in record["why"] and degraded_read.is_part(record)
    reader({**CLEAN, **change})
    held = degraded_read.hold(passes("flow"), "doc")
    assert held[0]["status"] == "NEEDS_ENGINEER_REVIEW"


def test_a_page_with_no_text_and_a_reader_that_was_not_asked_flag_nothing():
    assert (
        degraded_read.assess({**CLEAN, "code_only": {"1": "no text on this page"}})
        is None
    )
    assert degraded_read.assess({"engine": "off", "pages": 3}) is None
    assert degraded_read.assess(None) is None


def test_only_the_fields_whose_ai_reading_did_not_come_back_are_held(reader):
    summary = {
        **CLEAN,
        "rejected_fields": {
            "set_pressure: model_malformed": 2,
            "bearing_type: quote_missing": 1,
        },
    }
    assert degraded_read.missing_roles(summary) == {"set_pressure": ["model_malformed"]}
    record = degraded_read.assess(summary)
    assert record["why"] == ["fields_missing"] and not degraded_read.is_part(record)
    reader(summary)
    held = {
        r["role"]: r["status"]
        for r in degraded_read.hold(passes("set_pressure", "bearing_type"), "doc")
    }
    assert held == {
        "set_pressure": "NEEDS_ENGINEER_REVIEW",
        "bearing_type": "COMPLIANT",
    }


def test_a_pass_that_reads_two_fields_is_held_when_either_reading_failed(reader):
    """PSV-24 reads set_pressure AND mawp; its result carries only the first as `role`."""
    roles = degraded_read.item_roles()
    assert roles["PSV-24"] == {"set_pressure", "mawp"}
    assert {"set_pressure", "mawp", "relief_case"} <= roles["PSV-S04"]
    summary = {**CLEAN, "rejected_fields": {"mawp: model_failed": 1}}
    reader(summary)
    results = passes("set_pressure", rule_ids={"set_pressure": "PSV-24"})
    held = degraded_read.hold(results, "doc")
    assert (
        held[0]["status"] == "NEEDS_ENGINEER_REVIEW"
        and "mawp: model_failed" in held[0]["detail"]
    )
    reader(
        {**CLEAN, "rejected_fields": {"flow: model_failed": 1}}
    )  # a field it does not read
    assert degraded_read.hold(results, "doc") == results


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
    ]
    kept = [r["status"] for r in degraded_read.hold(results, "doc")]
    assert kept == ["NON_COMPLIANT", "MISSING_INFORMATION", "COMPLIANT"]


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
    assert (
        Reason.QUOTE_NOT_ON_PAGE.value not in degraded_read.ERROR_REASONS
    )  # a gate working


def test_the_split_carries_the_record_and_the_reader_summary(reader):
    reader(BROKEN)
    split = degraded_read.with_reader({"checked": 3}, "doc")
    assert (
        split["reader"] == BROKEN
        and "partly_read_pages" in split["degraded_read"]["why"]
    )
    reader(CLEAN)
    clean = degraded_read.with_reader({"checked": 3}, "doc")
    assert "degraded_read" not in clean and clean["reader"] == CLEAN


def test_the_crs_banner_lists_a_partly_read_page_and_not_a_per_field_reason_alone():
    counts = {"not_compared": 0, "not_applied": 0, "checked": 5}

    def parts(record):
        outcome = {
            "requirement_split": {"degraded_read": record},
            "unchecked_counts": counts,
        }
        return absence.unchecked_parts(run_status="completed", outcome=outcome)

    shown = parts(degraded_read.assess(BROKEN))
    assert [p["part"] for p in shown] == ["degraded_read"] and "detail" not in shown[0]
    assert "REVIEW INCOMPLETE" in absence.notice_for(shown)
    only_fields = {**CLEAN, "rejected_fields": {"flow: model_failed": 1}}
    assert parts(degraded_read.assess(only_fields)) == []
    assert absence.unchecked_parts(run_status="completed", outcome={}) == []


def _checklist_findings():
    rows = db.connect().execute(
        "SELECT compliance_status FROM review_findings WHERE origin = 'datasheet_check'"
    )
    return [r["compliance_status"] for r in rows]


def test_a_whole_review_on_the_broken_read_holds_every_checklist_pass(monkeypatch):
    from tests.test_746_checklist_governs import _review, _review_again

    monkeypatch.setattr(datasheets, "latest_reader_summary", lambda _doc: CLEAN)
    _review("Pressure Safety Valve")
    clean = _checklist_findings()
    assert "COMPLIANT" in clean

    monkeypatch.setattr(datasheets, "latest_reader_summary", lambda _doc: BROKEN)
    result, _stored, _ids = _review_again("Pressure Safety Valve")
    after = _checklist_findings()
    assert "COMPLIANT" not in after and "NEEDS_ENGINEER_REVIEW" in after
    assert len(after) == len(clean)
    assert "partly_read_pages" in result["requirement_split"]["degraded_read"]["why"]


def test_a_calculation_is_held_when_any_input_it_reads_in_code_failed(reader):
    """PSV-C01 reads its formula's inputs in code, not in its JSON; cloud's repro."""
    roles = degraded_read.item_roles()["PSV-C01"]
    assert {
        "fluid_phase",
        "orifice_area",
        "molecular_weight",
        "required_capacity",
    } <= roles
    assert "fluid" in roles  # the field that implies the phase
    results = passes("orifice_area", rule_ids={"orifice_area": "PSV-C01"})
    for role in sorted(roles):
        reader({**CLEAN, "rejected_fields": {f"{role}: model_failed": 1}})
        assert (
            degraded_read.hold(results, "doc")[0]["status"] == "NEEDS_ENGINEER_REVIEW"
        ), role
    reader({**CLEAN, "rejected_fields": {"bearing_type: model_failed": 1}})
    assert degraded_read.hold(results, "doc") == results


def test_the_formula_input_table_matches_what_the_formulas_read():
    import inspect
    import re

    from app import datasheet_checks as dc

    called = {
        "api520_gas_area": [dc.api520_gas_area],
        "api520_liquid_area": [dc.api520_liquid_area],
    }
    helpers = [dc._overpressure_kpa, dc._back_pressure_kpa_g, dc._conventional]
    for formula, fns in called.items():
        source = "".join(inspect.getsource(fn) for fn in [*fns, *helpers])
        read = set(re.findall(r'(?:_input\(get, |get\()"([a-z_]+)"', source))
        read |= set(
            re.findall(
                r'"([a-z_]+)"', "".join(re.findall(r"for role in \(([^)]*)\)", source))
            )
        )
        read.discard("is_blank")
        if formula == "api520_gas_area":
            read -= {"density_relieving", "viscosity_relieving"}
        assert read <= degraded_read.FORMULA_INPUTS[formula], (formula, read)


def test_an_unavailable_reader_with_no_engine_name_still_flags_the_read():
    summary = {
        "engine": None,
        "unavailable": "form reader: checklist refused (ValueError)",
    }
    assert degraded_read.assess(summary)["why"] == ["unavailable"]
    assert degraded_read.assess({"engine": "off", "unavailable": "x"}) is None
