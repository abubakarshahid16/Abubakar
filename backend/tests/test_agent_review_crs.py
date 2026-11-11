"""The CRS files of the AI reviewer: internal, contractor, comment-only. Invented data only; no model, no network."""

from __future__ import annotations

import openpyxl
import pytest

from app import agent_review_crs as C
from app import agent_review_verdict as V
from app import agent_review_wording as W

META = {
    "paper": "Paper A",
    "run_id": "run-1",
    "date": "2026-11-11",
    "lead_models": ["lead-m"],
    "second_models": ["second-m"],
}
SK = {"S-1"}
OK = {"source": "rule", "rule_label": {"tier": "AI approved"}}
NO = {
    "source": "rule",
    "rule_tier": V.RULE_NOT_APPROVED,
    "rule_unapproved_why": "values",
}


def mk(iid, verdict, ai=None, item=OK, **kw):
    base = {
        "item_id": iid,
        "source": item["source"],
        "standard": "STD-1",
        "clause": "4.1",
        "verdict": verdict,
        "decided_by": "decided by code",
        "ai_verdict": ai,
        "paper_page": 2,
        "paper_quote": "Nameplate: steel",
        "clause_quote": "Nameplates shall be steel and fixed",
        "quotes_checked": {"paper": True, "clause": True},
        "reasoning": "It is steel.",
        "model": "lead-m",
        "field_roles": ["nameplate_material"],
    }
    base.update(kw)
    return W.final_cap(base, item, skill_ids=SK)


def sheet_text(path, title):
    wb = openpyxl.load_workbook(path)
    if title not in wb.sheetnames:
        return None
    return "\n".join(
        " | ".join(str(c) for c in row if c is not None)
        for row in wb[title].iter_rows(values_only=True)
    )


def item_ids(path, title="CRS"):
    wb = openpyxl.load_workbook(path)
    return [
        r[0]
        for r in wb[title].iter_rows(min_row=10, values_only=True)
        if r[0] and str(r[0]).startswith(("R-", "S-"))
    ]


LINES = [
    mk("R-1", "Fail", "Fail"),  # proven Fail
    mk("R-2", "Pass", "Pass"),  # proven Pass
    mk("R-3", "Query", "Fail", why="no second opinion"),  # AI thinks: not met
    mk("R-4", "Query", "Pass", why="no second opinion"),  # AI thinks: met (held)
    mk(
        "R-5", "Fail", "Fail", item=NO
    ),  # proven by the gate but the rule is not approved: capped
    mk("R-6", "Fail", "Fail", rule_kind="advice"),  # a "should" rule
    mk(
        "S-1", "Fail", "Fail", item={"source": "skill", "item_id": "S-1"}
    ),  # a checklist Fail
    mk("R-7", "Query", None, reason_code="not_applicable"),
]


def test_the_contractor_copy_holds_proven_fail_lines_only(tmp_path):
    path = C.write_contractor(LINES, tmp_path / "c.xlsx", META)
    assert sorted(item_ids(path)) == [
        "R-1",
        "S-1",
    ]  # no Pass, no AI thinks, no unapproved, no should, no Query
    text = sheet_text(path, "CRS")
    for word in ("AI thinks", "Recommendation", "lead-m", "second-m", "It is steel"):
        assert word not in text


def test_the_contractor_copy_never_takes_an_ai_thinks_or_unapproved_line_even_if_its_verdict_says_fail(
    tmp_path,
):
    """Defence beside the cap: a line forced to look like a Fail but filed as an opinion is still left out."""
    sneaky = {**mk("R-1", "Fail", "Fail"), "verdict_class": W.CLASS_OPINION}
    unapproved = {**mk("R-1", "Fail", "Fail"), "rule_tier": V.RULE_NOT_APPROVED}
    advice = {**mk("R-1", "Fail", "Fail"), "recommendation": True}
    for bad in (sneaky, unapproved, advice):
        path = C.write_contractor([bad], tmp_path / "c.xlsx", META)
        assert item_ids(path) == []


def test_the_comment_only_copy_excludes_unapproved_lines_and_pass_lines(tmp_path):
    path = C.write_comment_only(LINES, tmp_path / "o.xlsx", META)
    ids = item_ids(path)
    assert (
        "R-5" not in ids and "R-2" not in ids and "R-4" not in ids and "R-7" not in ids
    )
    assert {"R-1", "R-3", "R-6", "S-1"} <= set(ids)
    leaked = {**mk("R-8", "Query", "Fail", item=NO)}
    assert "R-8" not in item_ids(
        C.write_comment_only([leaked], tmp_path / "o2.xlsx", META)
    )


def test_the_internal_copy_keeps_the_classes_on_their_own_sheets(tmp_path):
    path = C.write_internal(LINES, tmp_path / "i.xlsx", META)
    assert sorted(item_ids(path, "CRS")) == ["R-1", "R-3", "R-6", "S-1"]
    assert sorted(item_ids(path, C.PASSED_SHEET)) == [
        "R-2"
    ]  # a Pass is never on the CRS sheet
    assert item_ids(path, C.HELD_PASS_SHEET) == ["R-4"]
    assert item_ids(path, C.NOT_APPLICABLE_SHEET) == ["R-7"]
    assert item_ids(path, C.UNAPPROVED_SHEET) == [
        "R-5"
    ]  # off the CRS and off every Pass list
    assert "Recommendation" in sheet_text(path, "CRS")
    run = sheet_text(path, C.RUN_SHEET)
    assert "unapproved_lines | 1" in run and "proven_fail" in run


def test_the_passed_list_never_holds_a_stored_pass_of_an_unapproved_rule(tmp_path):
    """R7: a stored Pass line whose item is not approved NOW went through final_cap and cannot be on the Passed sheet."""
    stored = {
        "item_id": "R-9",
        "source": "rule",
        "verdict": "Pass",
        "decided_by": "decided by code",
        "ai_verdict": "Pass",
    }
    capped = W.final_cap_all([stored], {"R-9": NO}, skill_ids=SK)
    path = C.write_internal(capped, tmp_path / "i.xlsx", META)
    assert item_ids(path, C.PASSED_SHEET) == []
    contractor = C.write_contractor(capped, tmp_path / "c.xlsx", META)
    assert item_ids(contractor) == []


@pytest.mark.parametrize(
    "writer", ["write_internal", "write_contractor", "write_comment_only"]
)
@pytest.mark.parametrize("tier", [None, "not AI approved", "nobody"])
def test_every_writer_refuses_a_pass_or_fail_without_an_approved_tier(
    writer, tier, tmp_path
):
    bad = {
        "item_id": "R-1",
        "source": "rule",
        "verdict": "Fail",
        "decided_by": "decided by code",
        "tier": tier,
    }
    with pytest.raises(C.UnprovenLineRefused):
        getattr(C, writer)([bad], tmp_path / "x.xlsx", META)
    assert not (tmp_path / "x.xlsx").exists()  # nothing written
    raw = {k: v for k, v in bad.items() if k != "tier"}  # never went through final_cap
    with pytest.raises(C.UnprovenLineRefused):
        getattr(C, writer)([{**raw, "verdict": "Pass"}], tmp_path / "x.xlsx", META)


@pytest.mark.parametrize("tier", ["owner", "engineer", "AI approved"])
def test_the_approved_tiers_are_written(tier, tmp_path):
    ok = {
        "item_id": "R-1",
        "source": "rule",
        "verdict": "Fail",
        "decided_by": "decided by code",
        "tier": tier,
    }
    path = C.write_internal([ok], tmp_path / "x.xlsx", META)
    assert path.exists()


def test_a_should_rule_is_marked_a_recommendation_and_kept_out_of_the_contractor_copy(
    tmp_path,
):
    line = mk("R-6", "Fail", "Fail", rule_kind="advice")
    assert C.company_comment(line).startswith("Recommendation (should, not shall)")
    assert "Recommendation (should)" in C.verdict_cell(line)
    assert item_ids(C.write_contractor([line], tmp_path / "c.xlsx", META)) == []


def test_ai_opinion_lines_are_worded_as_ai_thinks_never_pass_or_fail(tmp_path):
    cell = C.verdict_cell(mk("R-3", "Query", "Fail", why="no second opinion"))
    assert cell.startswith("AI thinks: not met (AI opinion, engineer to confirm)")
    assert "no second opinion" in cell and "Fail," not in cell
    unapproved = C.verdict_cell(mk("R-5", "Fail", "Fail", item=NO))
    assert unapproved.startswith(
        "AI thinks: not met (AI opinion, rule not yet approved)"
    )
    assert C.verdict_cell(mk("R-1", "Fail", "Fail")) == "Fail, decided by code"


def test_the_rule_books_we_do_not_hold_are_listed_and_the_summary_lines_are_there(
    tmp_path,
):
    meta = {
        **META,
        "rule_labels": {
            "summary_lines": ["needs another paper: 3 rules (procedure 3)"],
            "missing_rule_books": [
                {"rule_book": "Book X", "why": "cited by the paper"}
            ],
        },
    }
    text = sheet_text(C.write_internal([LINES[0]], tmp_path / "i.xlsx", meta), "CRS")
    assert "needs another paper: 3 rules (procedure 3)" in text
    assert (
        "Rule books not held by the library" in text
        and "Book X (cited by the paper)" in text
    )
    assert "not counted against the system" in text


def test_the_top_of_every_sheet_says_engineer_to_confirm(tmp_path):
    for path in (
        C.write_internal(LINES, tmp_path / "i.xlsx", META),
        C.write_contractor(LINES, tmp_path / "c.xlsx", META),
    ):
        wb = openpyxl.load_workbook(path)
        assert all(ws["A1"].value == C.TOP_TEXT for ws in wb.worksheets)


def test_run_counts_are_counts_only_with_a_denominator():
    counts = C.run_counts(LINES)
    assert counts["lines"] == 8 and counts["lines_with_a_verdict"].endswith(" of 8")
    assert (
        counts["unapproved_lines"] == 1 and counts["proven_fail"] == 3
    )  # R-1, R-6 (advice), S-1


def test_a_not_reviewed_line_is_off_the_crs_the_comment_only_copy_and_the_contractor_copy(
    tmp_path,
):
    nr = mk("R-N", "Query", None, error="stop_max_tokens", reasoning="")
    assert nr["verdict_class"] == W.CLASS_NOT_REVIEWED
    held = mk(
        "R-H", "Query", "Pass", error="timeout"
    )  # an AI Pass with a failed call is still not reviewed, not a held Pass
    assert held["verdict_class"] == W.CLASS_NOT_REVIEWED
    lines = [nr, held, mk("R-1", "Fail", "Fail")]
    internal = C.write_internal(lines, tmp_path / "i.xlsx", META)
    assert item_ids(internal, "CRS") == ["R-1"]
    assert sorted(item_ids(internal, C.NOT_REVIEWED_SHEET)) == ["R-H", "R-N"]
    assert (
        item_ids(internal, C.HELD_PASS_SHEET) == []
        and item_ids(internal, C.PASSED_SHEET) == []
    )
    assert "not_reviewed | 2" in sheet_text(internal, C.RUN_SHEET)
    assert item_ids(C.write_comment_only(lines, tmp_path / "o.xlsx", META)) == ["R-1"]
    assert item_ids(C.write_contractor(lines, tmp_path / "c.xlsx", META)) == ["R-1"]
    assert (
        C.NOT_REVIEWED_SHEET
        not in openpyxl.load_workbook(
            C.write_internal([lines[2]], tmp_path / "j.xlsx", META)
        ).sheetnames
    )
