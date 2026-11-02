"""#1607: a value that cannot be negative, printed negative, never gives a Pass.

A negative built-up back pressure met its "at most 10% of set pressure" limit, so the
planted-defect scorer read it as a Pass. The gap was not one check's: every check whose
arithmetic is one-sided passes on a negative value. Pass becomes Query; a Fail stays a Fail.
Invented values only.
"""

from __future__ import annotations

import json

import pytest

from app import comparison, impossible_sign
from app import datasheet_checks as dc

PSV = "Pressure Safety Valve"


def fact(name, value, unit=None, *, tag=None):
    return {
        "id": f"f-{name}",
        "field_name": name,
        "field_label": name.capitalize(),
        "field_value": f"{value} {unit}".strip() if unit else value,
        "raw_value": value,
        "raw_unit": unit,
        "normalized_value": None,
        "normalized_unit": None,
        "is_blank": 0,
        "blank_marker": None,
        "value_note": None,
        "page": 2,
        "equipment_tag": tag,
    }


CLEAN = {
    "set pressure": ("10", "barg"),
    "mawp": ("12", "barg"),
    "design pressure": ("12", "barg"),
    "operating pressure": ("8.5", "barg"),
    "over pressure": ("21", "%"),
    "built up back pressure": ("0.5", "barg"),
    "superimposed back pressure": ("0.2", "barg"),
    "cdtp": ("10", "barg"),
    "relief case": ("Fire", None),
    "valve type": ("Conventional", None),
    "fluid phase": ("Gas", None),
    "molecular weight": ("28", None),
    "compressibility": ("0.95", None),
    "specific heat ratio": ("1.3", None),
    "required capacity": ("5400", "kg/h"),
    "rated capacity": ("7100", "kg/h"),
    "relieving temperature": ("180", "degC"),
    "orifice area": ("830", "mm2"),
    "required area": ("630", "mm2"),
}


def results(**changes):
    values = {**CLEAN, **{k.replace("_", " "): v for k, v in changes.items()}}
    facts = [fact(name, *pair) for name, pair in values.items()]
    return {
        r["rule_id"]: r
        for r in dc.evaluate(facts, equipment_type=PSV, page_texts={1: "x"})
        if r.get("checklist")
    }


def test_the_sheet_the_scorer_found_is_a_query_with_the_reason():
    r = results(built_up_back_pressure=("-0.5", "barg"))["PSV-29"]
    assert r["status"] == "NEEDS_ENGINEER_REVIEW"
    assert "cannot be negative" in r["detail"] and "-0.5" in r["detail"]


@pytest.mark.parametrize(
    "field, value, unit, check",
    [
        ("built_up_back_pressure", "-0.5", "barg", "PSV-07"),  # stated
        ("set_pressure", "-10", "barg", "PSV-01"),  # stated
        ("set_pressure", "-10", "barg", "PSV-24"),  # left of a compare
        ("mawp", "-12", "barg", "PSV-02"),
        ("cdtp", "-10", "barg", "PSV-30"),  # left of a compare
        ("overpressure", "-21", "%", "PSV-06"),
        ("rated_capacity", "-7100", "kg/h", "PSV-11"),
        ("required_capacity", "-5400", "kg/h", "PSV-31"),  # the RIGHT of a compare
        ("required_capacity", "-5400", "kg/h", "PSV-10"),
        ("molecular_weight", "-28", None, "PSV-19"),
        ("orifice_area", "-830", "mm2", "PSV-12"),
    ],
)
def test_a_negative_value_gives_no_pass_on_any_check_that_reads_it(
    field, value, unit, check
):
    label = {"overpressure": "over pressure"}.get(field, field.replace("_", " "))
    assert results()[check]["status"] == "COMPLIANT", "a Pass on the clean sheet first"
    assert (
        results(**{label.replace(" ", "_"): (value, unit)})[check]["status"]
        == "NEEDS_ENGINEER_REVIEW"
    )


def test_no_calculation_passes_on_a_negative_input():
    """The area formula takes a gauge pressure: a negative one still gives a number."""
    clean = results()
    assert clean["PSV-C01"]["status"] == "COMPLIANT"
    held = results(superimposed_back_pressure=("-0.2", "barg"))
    assert held["PSV-C01"]["status"] != "COMPLIANT"


def test_a_fail_stays_a_fail():
    """Purely stopping a false Pass: no breach is softened."""
    r = results(set_pressure=("-10", "barg"))
    assert r["PSV-S03"]["status"] == "NON_COMPLIANT"
    assert "cannot be negative" not in r["PSV-S03"]["detail"]


@pytest.mark.parametrize(
    "name, value, unit, check",
    [
        ("design pressure", "-1", "barg", "PSV-03"),
        ("operating pressure", "-0.5", "barg", "PSV-04"),
    ],
)
def test_vacuum_is_a_real_value_so_these_keep_their_pass(name, value, unit, check):
    assert (
        results(**{name.replace(" ", "_"): (value, unit)})[check]["status"]
        == "COMPLIANT"
    )


def test_a_negative_temperature_keeps_its_pass():
    assert (
        results(relieving_temperature=("-40", "degC"))["PSV-05"]["status"]
        == "COMPLIANT"
    )


@pytest.mark.parametrize("value", ["0", "0.0", "10", "10-12", "10 to 12", "A216"])
def test_zero_a_range_and_words_are_not_negative(value):
    assert impossible_sign.is_negative({"raw_value": value}) is False


@pytest.mark.parametrize(
    "value", ["-0.5", "-10", chr(0x2212) + "0.5", chr(0x2013) + "0.5"]
)
def test_a_printed_minus_is_negative(value):
    assert impossible_sign.is_negative({"raw_value": value}) is True


def test_a_blank_or_absent_value_is_not_negative():
    assert impossible_sign.is_negative({"raw_value": None}) is False
    assert impossible_sign.is_negative({"raw_value": "-5", "is_blank": 1}) is False
    assert impossible_sign.is_negative(None) is False


def test_a_negative_value_for_one_tag_holds_that_tag_only():
    facts = [
        *[fact(n, *p) for n, p in CLEAN.items() if n != "cdtp"],
        fact("cdtp", "-10", "barg", tag="PSV-A"),
        fact("cdtp", "10", "barg", tag="PSV-B"),
    ]
    facts[-2]["id"], facts[-1]["id"] = "a", "b"
    rows = dc.evaluate(facts, equipment_type=PSV, page_texts={1: "x"})
    by_tag = {r["equipment_tag"]: r for r in rows if r["rule_id"] == "PSV-30"}
    assert by_tag["PSV-A"]["status"] == "NEEDS_ENGINEER_REVIEW"
    assert by_tag["PSV-B"]["status"] == "COMPLIANT"


def test_the_data_marks_no_field_where_a_negative_is_real():
    roles = dc.load_rules()["roles"]
    marked = {
        name
        for name, role in roles.items()
        if isinstance(role, dict) and role.get("never_negative")
    }
    assert {
        "built_up_back_pressure",
        "set_pressure",
        "rated_capacity",
        "orifice_area",
    } <= marked
    assert not marked & {
        "design_pressure",
        "operating_pressure",
        "npsh_available",
        "heat_duty",
    }
    assert not any(roles[name]["kind"] in ("temperature", "text") for name in marked)


# ------------------------------------------------------------------ the library standards


def verdict(status="COMPLIANT"):
    return {"status": status, "rationale": "within the limit"}


def lib_fact(name, value):
    return {"field_name": name, "raw_value": value, "is_blank": 0}


def test_a_library_rule_gives_no_pass_on_a_negative_value():
    out = comparison._hold_low_trust_breach(
        verdict(), lib_fact("built up back pressure", "-0.5")
    )
    assert out["status"] == "NEEDS_ENGINEER_REVIEW"
    assert (
        "cannot be negative" in out["rationale"]
        and "within the limit" in out["rationale"]
    )


def test_a_library_fail_on_a_negative_value_stays_a_fail():
    out = comparison._hold_low_trust_breach(
        verdict("NON_COMPLIANT"), lib_fact("built up back pressure", "-0.5")
    )
    assert out["status"] == "NON_COMPLIANT"


def test_a_library_pass_on_a_real_negative_stays_a_pass():
    for name in ("design pressure", "relieving temperature"):
        assert (
            impossible_sign.hold_pass(verdict(), lib_fact(name, "-1"))["status"]
            == "COMPLIANT"
        )
    assert impossible_sign.hold_pass(verdict(), None)["status"] == "COMPLIANT"


def test_the_rule_data_stays_valid_json_with_a_reason_written_down():
    data = json.loads(dc.RULES_PATH.read_text(encoding="utf-8"))
    assert data["_never_negative"], "why each kind is in or out is said beside the data"
