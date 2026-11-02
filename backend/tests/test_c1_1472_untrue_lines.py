"""#1472: the two kinds of untrue datasheet line a real 35B run still wrote after #1453/#1455/#1459.

1. A range the sheet prints twice (one reading carries a plain note such as "By Contractor",
   the other does not) is ONE value, not "two different values".
2. A field whose label lists several attributes joined by "/" or "," answers each attribute it
   names, so a rating inside a combined line is never "no label found".
Invented labels and values only (rule 13). Behind `datasheet_one_value_enabled`, off by default.
"""

from __future__ import annotations

import pytest

from app import datasheet_checks as dc
from app.config import settings
from app.same_value import key
from tests.test_746_relief_valve_checklist import PSV, fact

VISC = "viscosity at relieving temper"


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "datasheet_one_value_enabled", True)


def _range(text, lo=4.0, hi=28.0, *, tag="PSV-A"):
    f = fact(VISC, text, None, tag=tag, page=4)
    f.update(raw_value=None, raw_unit="cP", value_min=lo, value_max=hi)
    return f


def _row(facts, rule_id):
    facts = [*facts, fact("fluid phase", "Liquid", tag="PSV-A")]
    rows = dc.evaluate(facts, equipment_type=PSV, page_texts={1: "x"})
    return next(r for r in rows if r.get("checklist") and r["rule_id"] == rule_id)


def test_off_a_noted_range_and_a_bare_range_stay_two_values():
    row = _row([_range("4-28 cP By Contractor"), _range("4-28 cP")], "PSV-23")
    assert "two different values" in row["detail"]


def test_on_a_noted_range_and_a_bare_range_are_one_value(on):
    row = _row([_range("4-28 cP By Contractor"), _range("4-28 cP")], "PSV-23")
    assert row["status"] == "COMPLIANT"
    assert "two different values" not in row["detail"]


@pytest.mark.parametrize(
    "text,lo,hi",
    [
        ("5-30 cP", 5.0, 30.0),  # another range
        ("max 28 cP", 4.0, 28.0),  # a bound
        ("4-28 cP at 20 C", 4.0, 28.0),  # a condition
        ("4-28 cP (shell side)", 4.0, 28.0),  # a side
        ("4-28 cP typical", 4.0, 28.0),  # a provisional marker
    ],
)
def test_on_anything_else_around_a_range_keeps_two_values(on, text, lo, hi):
    other = _range(text, lo, hi)
    assert key(_range("4-28 cP")) != key(other)
    row = _row([_range("4-28 cP"), other], "PSV-23")
    assert row["status"] == "NEEDS_ENGINEER_REVIEW"
    assert "two different values" in row["detail"]


def _combined(value=None, marker=None, label="Valve size / rating / ends"):
    f = fact(
        "valve size rating ends",
        value or "x",
        None,
        label=label,
        page=2,
        blank=marker,
        tag="PSV-A",
    )
    if value is not None:
        f["raw_value"] = value
    if marker:
        f["field_value"] = marker
    return f


def test_off_a_combined_line_is_not_read_for_the_rating():
    row = _row([_combined(marker="By Contractor / Vendor")], "PSV-S02")
    assert "no label for it was found" in row["detail"]


def test_on_a_combined_line_marked_by_contractor_names_that_line(on):
    row = _row([_combined(marker="By Contractor / Vendor")], "PSV-S02")
    assert row["status"] == "MISSING_INFORMATION"
    assert "no label for it was found" not in row["detail"]
    assert "Valve size / rating / ends" in row["detail"]
    assert "By Contractor / Vendor" in row["detail"]


def test_on_a_combined_line_with_a_value_is_an_engineer_question_never_compliant(on):
    row = _row([_combined(value="3 in / 300 / RF")], "PSV-S02")
    assert row["status"] == "NEEDS_ENGINEER_REVIEW"
    assert "Valve size / rating / ends" in row["detail"]


def test_on_a_value_under_the_rating_label_itself_is_decided_as_before(on):
    row = _row(
        [_combined(value="3 in / 300 / RF"), fact("inlet rating", "300", tag="PSV-A")],
        "PSV-S02",
    )
    assert row["status"] == "COMPLIANT"


def test_on_an_ambiguous_part_answers_nothing(on):
    # "material" ends several wanted roles: not one, so no role is answered.
    f = _combined(marker="By Contractor", label="Valve size / material")
    f["field_name"] = "valve size material"
    row = _row([f], "PSV-S02")
    assert "no label for it was found" in row["detail"]


def test_on_a_numeric_role_is_never_answered_by_a_combined_label(on):
    f = fact(
        "design operating pressure",
        "23.5 / 11 barg",
        None,
        label="Design / Operating pressure",
        tag="PSV-A",
    )
    rows = dc.evaluate([f], equipment_type=PSV, page_texts={1: "x"})
    assert all("combined" not in (r.get("detail") or "") for r in rows)


def test_combined_roles_names_only_a_part_that_ends_exactly_one_wanted_text_role():
    from app import datasheet_roles as dr

    rules = dc.load_rules()
    wanted = dr.wanted_roles(PSV, rules)
    assert dr.combined_roles("Valve size / rating / ends", rules, wanted) == [
        "inlet_rating"
    ]
    assert dr.combined_roles("Valve size, rating, facing", rules, wanted) == [
        "inlet_rating"
    ]
    # "type" ends several roles; one part alone is not a combined line
    assert dr.combined_roles("Valve size / material", rules, wanted) == []
    assert dr.combined_roles("rating", rules, wanted) == []


def test_combined_roles_qualifier_must_agree():
    from app import datasheet_roles as dr

    rules = dc.load_rules()
    wanted = dr.wanted_roles(PSV, rules)
    for label in (
        "Outlet size / rating",
        "Connection type / rating",
        "Outlet size / rating / ends",
    ):
        assert dr.combined_roles(label, rules, wanted) == [], label
    assert dr.combined_roles("Valve size / rating", rules, wanted) == ["inlet_rating"]


def test_on_an_outlet_line_never_writes_an_inlet_rating_row(on):
    row = _row(
        [_combined(marker="By Contractor", label="Outlet size / rating")], "PSV-S02"
    )
    assert "no label for it was found" in row["detail"]


@pytest.mark.parametrize("order", [0, 1])
def test_on_a_merged_noted_range_is_a_query_when_deferred_values_are_queries(
    on, monkeypatch, order
):
    monkeypatch.setattr(settings, "deferred_value_is_query_enabled", True)
    facts = [_range("4-28 cP By Contractor"), _range("4-28 cP")]
    facts[0]["value_note"] = "By Contractor"
    row = _row(facts[::-1] if order else facts, "PSV-23")
    assert row["status"] == "NEEDS_ENGINEER_REVIEW"
    assert "By Contractor" in row["detail"]


def test_on_a_merged_noted_range_stays_the_existing_deferred_pass_when_d2_is_off(on):
    facts = [_range("4-28 cP"), _range("4-28 cP By Contractor")]
    facts[1]["value_note"] = "By Contractor"
    row = _row(facts, "PSV-23")
    assert row["status"] == "COMPLIANT"
    assert "By Contractor" in row["detail"]
