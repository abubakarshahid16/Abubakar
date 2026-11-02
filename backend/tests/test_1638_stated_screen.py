"""#1638, what blocks switch-on: an engineer must never read a stated row as checked. On the
screen's data (tiers, sheet counts) and the CRS cell (a safety-tick row's comment and its
reasoning). Invented rows only; with the switch off every home is as it was."""

from __future__ import annotations

import pytest

from app import crs_mapping, presence_check, review_counts, review_tiers
from app import datasheet_checks as dc
from app.config import settings

FACTS = review_tiers.RunFacts()
WORDS = presence_check.WORDS


def _item(kind: str) -> str:
    return next(
        item["id"]
        for name, entry in dc.load_rules()["checklists"].items()
        if not name.startswith("_")
        for item in entry["items"]
        if item["rule"]["kind"] == kind
    )


REQUIRED, COMPARED = _item("required"), _item("compare")


def _row(item: str = REQUIRED, status: str = "COMPLIANT", **extra) -> dict:
    return {
        "id": extra.pop("id", "f1"),
        "origin": "datasheet_check",
        "compliance_status": status,
        "requirement": "The field is stated.",
        "requirement_source_text": f"Datasheet check {item}: words",
        "contractor_section": "Rated flow",
        "contractor_evidence_text": "40 m3/h",
        "contractor_page": 1,
        "standard_clause": "API 610 datasheet annex",
        **extra,
    }


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "presence_not_pass_enabled", True)


# ------------------------------------------------------------------ the screen's data


def test_off_a_presence_row_is_met_as_it_was():
    assert review_tiers.tier_of(_row(), FACTS) == ("A", "Met", None)


def test_on_a_stated_row_is_not_met(on):
    assert review_tiers.tier_of(_row(), FACTS) == ("A", WORDS, None)


def test_the_flag_from_the_api_is_enough(monkeypatch):
    """The screen's tiers read the flag the API sent, whatever this process's switch says."""
    got = review_tiers.tier_of({**_row(), "stated_only": True}, FACTS)
    assert got == ("A", WORDS, None)


def test_on_a_compared_row_stays_met(on):
    assert review_tiers.tier_of(_row(COMPARED), FACTS) == ("A", "Met", None)


def test_a_stated_row_on_an_unread_page_still_needs_you(on):
    facts = review_tiers.RunFacts(pages_not_read=frozenset({1}))
    assert review_tiers.tier_of(_row(), facts)[0] == review_tiers.C


def test_an_unticked_safety_row_still_needs_you_and_a_ticked_one_is_not_met(on):
    tick = _row(
        show_for_engineer_tick=1, trust_label="unproven", approval_status="pending"
    )
    assert review_tiers.tier_of(tick, FACTS)[1] != "Met"
    ticked = {**tick, "engineer_decision": "accepted", "approval_status": "approved"}
    assert review_tiers.tier_of(ticked, FACTS)[1] != "Met"


def test_the_headline_counts_it_apart(on):
    got = review_tiers.summarise(
        [_row(id="a"), _row(id="b"), _row(COMPARED, id="c")], FACTS
    )
    assert got["counts"]["met"] == 1 and got["counts"]["stated"] == 2
    labels = {r["finding_id"]: r["label"] for r in got["rows"]}
    assert labels == {"a": WORDS, "b": WORDS, "c": "Met"}


def test_off_the_counts_have_no_new_key():
    got = review_tiers.summarise([_row(id="a")], FACTS)
    assert "stated" not in got["counts"] and got["counts"]["met"] == 1


def test_the_sheet_counts_it_apart(on):
    rows = [_row(id="a"), _row(COMPARED, id="c")]
    got = review_counts.sheet_counts(rows, FACTS, {})
    assert got["met"] == 1 and got["stated"] == 1


def test_a_row_of_several_is_not_met_if_one_member_is_only_stated(on):
    groups = {"a": {"crs_group": "g"}, "c": {"crs_group": "g"}}
    rows = [_row(COMPARED, id="c"), _row(id="a")]
    got = review_counts.sheet_counts(rows, FACTS, groups)
    assert got["met"] == 0 and got["stated"] == 1


def test_off_the_sheet_counts_have_no_new_key():
    assert "stated" not in review_counts.sheet_counts([_row(id="a")], FACTS, {})


# ------------------------------------------------------------------ the CRS cell


def _tick(**extra) -> dict:
    return _row(show_for_engineer_tick=1, trust_label="unproven", **extra)


def _tick_row() -> dict:
    rows = crs_mapping.build_crs_rows([_tick()], [], "invented.pdf")
    return next(r for r in rows if r["row_kind"] == crs_mapping.ROW_KIND_SAFETY_TICK)


def test_off_the_tick_cell_is_as_it_was():
    row = _tick_row()
    assert "Automatic result: meets the standard" in row["comment"]
    assert "Result: meets" in row["reasoning"]


def test_on_the_tick_comment_and_its_reasoning_never_say_meets(on):
    row = _tick_row()
    assert "stated, not checked" in row["comment"]
    assert "meets" not in row["comment"]
    assert "Result: stated, not checked" in row["reasoning"]
    assert "Result: meets" not in row["reasoning"]


def test_on_a_compared_tick_still_says_meets(on):
    rows = crs_mapping.build_crs_rows(
        [_row(COMPARED, show_for_engineer_tick=1, trust_label="unproven")],
        [],
        "invented.pdf",
    )
    assert "meets the standard" in rows[0]["comment"]
    assert "Result: meets" in rows[0]["reasoning"]


def test_the_reasoning_of_any_group_says_it(on):
    text = crs_mapping.reasoning_text([_row()])
    assert "Result: stated, not checked" in text and "meets" not in text
