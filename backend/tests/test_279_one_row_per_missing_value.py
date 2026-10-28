"""Order 279.1: one missing value is ONE request on the CRS. A comparison item whose own field is missing folds
into the "is stated" item of that field (PSV-09 "the cold differential test pressure is stated" and PSV-30 "the
cold differential test pressure does not exceed the set pressure" asked the contractor for the same value twice).
Invented values only."""

from __future__ import annotations

from app import datasheet_checks as dc
from app import review as review_mod
from tests.test_746_relief_valve_checklist import PSV, SHEET, fact, results


def _without(name):
    return [f for f in SHEET if f["field_name"] != name]


def test_a_comparison_whose_own_field_is_missing_folds_into_the_is_stated_item():
    r = results(SHEET)  # SHEET states no cold differential test pressure
    assert r["PSV-09"]["status"] == "MISSING_INFORMATION"
    assert r["PSV-30"]["status"] == "NOT_CALCULATED"
    assert "PSV-09" in r["PSV-30"]["detail"]


def test_it_folds_per_tag_and_only_for_the_tag_that_misses_it():
    sheet = [  # the sheet's common section, plus one tagged value for each valve
        *SHEET,
        fact("operating pressure", "8", "barg", tag="PSV-101"),
        fact("operating pressure", "8", "barg", tag="PSV-102"),
        fact("cdtp", "10", "barg", tag="PSV-102"),
    ]
    out = [
        x
        for x in dc.evaluate(sheet, equipment_type=PSV, page_texts={1: "x"})
        if x.get("checklist")
    ]
    by = {(x["rule_id"], x["equipment_tag"]): x["status"] for x in out}
    assert by[("PSV-09", "PSV-101")] == "MISSING_INFORMATION"
    assert by[("PSV-30", "PSV-101")] == "NOT_CALCULATED"
    assert by[("PSV-09", "PSV-102")] == "COMPLIANT"
    assert by[("PSV-30", "PSV-102")] == "COMPLIANT"  # 10 barg <= set pressure 10 barg


def test_a_comparison_whose_other_side_is_missing_is_a_different_question_and_stays():
    no_set = [*_without("set pressure"), fact("cdtp", "10", "barg")]
    r = results(no_set)
    assert (
        r["PSV-01"]["status"] == "MISSING_INFORMATION"
    )  # the set pressure is asked once, by PSV-01
    assert (
        r["PSV-30"]["status"] == "NEEDS_ENGINEER_REVIEW"
    )  # cdtp is stated; its partner is not given


def test_a_stated_cdtp_changes_nothing():
    r = results([*SHEET, fact("cdtp", "11", "barg")])
    assert r["PSV-09"]["status"] == "COMPLIANT"
    assert (
        r["PSV-30"]["status"] == "NON_COMPLIANT"
    )  # 11 barg exceeds the set pressure 10 barg


def test_the_folded_comparison_writes_no_row_so_the_crs_asks_once(monkeypatch):
    written = []
    monkeypatch.setattr(review_mod, "rejected_in_run", lambda *a, **k: [])
    monkeypatch.setattr(
        review_mod,
        "create",
        lambda row, created_by=None: written.append(row) or {"id": "x"},
    )
    out = [
        x
        for x in dc.evaluate(SHEET, equipment_type=PSV, page_texts={1: "x"})
        if x["rule_id"] in ("PSV-09", "PSV-30")
    ]
    assert {x["status"] for x in out} == {"MISSING_INFORMATION", "NOT_CALCULATED"}
    dc.store("run", "sub", out, pages_read={1: "read"})
    assert [
        w["requirement_source_text"]
        for w in written
        if "PSV-" in w["requirement_source_text"]
    ] == [
        next(
            w["requirement_source_text"]
            for w in written
            if "PSV-09" in w["requirement_source_text"]
        )
    ]
    assert len(written) == 1
