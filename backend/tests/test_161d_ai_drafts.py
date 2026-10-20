"""Order 161 D, second part (planner answer on #692, 20 Oct): one row per field
for the AI / web check drafts, and no placeholder text ever takes a CRS row.

Two unconfirmed AI drafts about one field are ONE row; when they differ the row
keeps both and says so (never one picked silently); a confirmed draft is the
engineer's own and is never merged with an unconfirmed one; a draft that says
nothing (empty, "n/a", "-") is no row (it stays in the review data).

Invented findings only - no client document, no real standard text.
"""

from __future__ import annotations

from app import crs_mapping
from app.crs_mapping import build_crs_rows

BASE = {
    "origin": "ai_engineering_check",
    "compliance_status": "NEEDS_ENGINEER_REVIEW",
    "contractor_page": 4,
    "contractor_section": "Minimum operating pressure",
    "approval_status": "pending",
    "severity": "minor",
}


def _ai(fid: str, text: str, relates: str = "STD-A", **over) -> dict:
    return {
        **BASE,
        "id": fid,
        "finding": text,
        "ai_rationale": f"Relates to: {relates}.",
        **over,
    }


def _rows(findings):
    return [
        r
        for r in build_crs_rows(findings, [], "sheet.pdf")
        if r["row_kind"] in ("ai_engineering_check", "web_standard_check")
    ]


def test_two_drafts_about_one_field_are_one_row_that_keeps_both():
    a = _ai("a", "A minimum operating pressure is required.", "STD-A 6.1")
    b = _ai("b", "The minimum operating pressure is blank.", "STD-B 1.4")
    rows = _rows([a, b])
    assert len(rows) == 1
    row = rows[0]
    assert sorted(row["finding_ids"]) == ["a", "b"]
    text = row["ai_review_comment"]
    assert "required" in text and "is blank" in text
    assert "differ" in text
    assert (
        "STD-A 6.1" in row["standard_reference"]
        and "STD-B 1.4" in row["standard_reference"]
    )
    assert row["comment"] == crs_mapping.AI_UNCONFIRMED_COMMENT


def test_two_identical_drafts_are_one_row_without_a_difference_note():
    rows = _rows([_ai("a", "Confirm the guard."), _ai("b", "confirm the guard.")])
    assert len(rows) == 1
    assert "differ" not in rows[0]["ai_review_comment"]


def test_the_screen_groups_the_drafts_exactly_as_the_file_does():
    from app.api import run_summary

    findings = [_ai("a", "One."), _ai("b", "Two.")]
    rows = build_crs_rows(findings, [], "sheet.pdf")
    fields = run_summary.crs_row_fields(rows, findings)
    assert fields["a"]["crs_group"] == fields["b"]["crs_group"]
    assert "crs_note" not in fields["a"] and "crs_note" not in fields["b"]


def test_drafts_about_different_fields_or_pages_stay_apart():
    findings = [
        _ai("a", "One."),
        _ai("b", "Two.", contractor_section="Minimum operating temperature"),
        _ai("c", "Three.", contractor_page=5),
    ]
    assert len(_rows(findings)) == 3


def test_web_and_ai_drafts_are_never_merged_with_each_other():
    findings = [_ai("a", "One."), _ai("b", "Two.", origin="web_standard_check")]
    assert len(_rows(findings)) == 2


def test_a_confirmed_draft_is_never_merged_with_an_unconfirmed_one():
    findings = [
        _ai("a", "One.", confirmed_by="eng-1"),
        _ai("b", "Two."),
    ]
    rows = _rows(findings)
    assert len(rows) == 2
    assert sorted(r["engineer_confirmed"] for r in rows) == [False, True]


def test_a_confirmed_draft_never_joins_an_unconfirmed_one_with_the_same_words():
    words = "Contractor to provide the minimum operating pressure."
    findings = [
        _ai("a", "One.", engineer_comment=words),
        _ai("b", "Two.", engineer_comment=words, confirmed_by="eng-1"),
    ]
    rows = _rows(findings)
    assert len(rows) == 2
    assert sorted(r["engineer_confirmed"] for r in rows) == [False, True]


def test_the_key_of_a_merged_row_does_not_depend_on_the_drafts_or_their_order():
    keys = set()
    for findings in (
        [_ai("a", "One."), _ai("b", "Two.")],
        [_ai("b", "Two."), _ai("a", "One.")],
        [_ai("a", "One."), _ai("b", "Something else."), _ai("c", "More.")],
    ):
        keys.add(_rows(findings)[0]["comment_key"])
    assert len(keys) == 1


def test_a_single_draft_keeps_its_own_key_and_row():
    a = _ai("a", "One.")
    row = _rows([a])[0]
    assert row["comment_key"] == crs_mapping.finding_comment_key(a)


def test_the_merged_row_carries_the_keys_its_drafts_were_numbered_under():
    a, b = _ai("a", "One."), _ai("b", "Two.")
    own = {
        crs_mapping.finding_comment_key(dict(a)),
        crs_mapping.finding_comment_key(dict(b)),
    }
    row = _rows([a, b])[0]
    assert own <= set(row["member_keys"])


def test_a_draft_that_says_nothing_is_no_row():
    for text in ("", "   ", "n/a", "N/A.", "-", "TBD", "none"):
        assert _rows([_ai("a", text)]) == [], text


def test_a_placeholder_does_not_hide_the_real_draft_beside_it():
    rows = _rows([_ai("a", "n/a"), _ai("b", "Confirm the guard.")])
    assert len(rows) == 1
    assert rows[0]["finding_ids"] == ["b"]


def test_an_engineers_own_words_on_a_draft_are_not_a_placeholder():
    rows = _rows(
        [_ai("a", "", engineer_comment="Contractor to confirm.", confirmed_by="e1")]
    )
    assert len(rows) == 1


def test_grouping_twice_gives_the_same_rows():
    findings = [_ai("a", "One."), _ai("b", "Two.")]
    first, second = _rows(findings), _rows(findings)
    assert [r["ai_review_comment"] for r in first] == [
        r["ai_review_comment"] for r in second
    ]


def test_two_different_confirmed_drafts_are_two_rows_and_the_issue_copy_has_no_note():
    findings = [
        _ai("a", "A minimum operating pressure is required.", confirmed_by="eng-1"),
        _ai("b", "The minimum operating pressure is blank.", confirmed_by="eng-1"),
    ]
    rows = _rows(findings)
    assert len(rows) == 2
    assert all("differ; all are kept" not in r["comment"] for r in rows)


def test_two_identical_confirmed_drafts_are_one_row():
    findings = [
        _ai("a", "Confirm the guard.", confirmed_by="eng-1"),
        _ai("b", "confirm the guard.", confirmed_by="eng-1"),
    ]
    rows = _rows(findings)
    assert len(rows) == 1
    assert "differ; all are kept" not in rows[0]["comment"]
