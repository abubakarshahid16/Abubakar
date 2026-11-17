"""Order 14 live proof LP1, 17 Nov 2026 (gates G5 and G4 on a live pump review). Invented data only.

1. G5 (honesty rule 4): a FIRM "not met" (proven by code, two AI readers agree, or one AI reader) never stands without a clause code
   checked. When its clause is moved off ("not checked" or "not confirmed", `crs_ai_words.mark_clause_unconfirmed`), or it names
   none, it is a question for the engineer with its reason, in every reader (the run file, the page's rank, `classify`). A firm line
   that keeps its checked clause, and a "met", are unchanged.
2. G4: the AI run's own file treats a "does not apply" the AI could not prove as the team file does: not a comment (its own kind on
   the sheet "Not a comment", one row each), so several such lines under one clause are never several comments on one topic. No line
   is lost: comment rows + other rows = every line."""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

import openpyxl

from app import agent_review_standards as standards
from app import agent_review_wording as W
from app import crs_ai_words as words
from app import crs_ai_workbook as WB
from app import crs_layout, firm_clause
from app import review_points as rp
from app.crs_completeness import _table_rows

_SPEC = importlib.util.spec_from_file_location(
    "crs_gates_lp1", Path(__file__).resolve().parents[2] / "scripts" / "crs_gates.py"
)
gates = importlib.util.module_from_spec(_SPEC)
sys.modules["crs_gates_lp1"] = gates
_SPEC.loader.exec_module(gates)

META = {"paper": "Invented widget datasheet", "run_id": "run-lp1"}
UNSURE = lambda *_a: standards.CLAUSE_UNSURE  # noqa: E731 - code is not sure the clause holds the words
FALSE = lambda *_a: False  # noqa: E731 - code is certain the words are outside the clause
NONE = lambda *_a: None  # noqa: E731 - code cannot tell: nothing changes


def _not_met(item: str = "R-1", clause: str = "6.7.4", **kw) -> dict:
    """One AI reader's "not met" on an invented widget rule, both quotes verified by code."""
    base = {"item_id": item, "source": "rule", "standard": "ZZ-9", "clause": clause, "clause_page": 4,
            "standard_document_id": "doc-zz9", "clause_quote": "The widget seal shall be of grade nine.",
            "requirement": "The widget seal shall be of grade nine.", "verdict": "Query", "ai_verdict": "Fail",
            "decided_by": "engineer", "reason_code": "not_met", "why": "the seal grade differs",
            "paper_quote": "Seal grade: seven", "field_roles": ["seal grade"],
            "quotes_checked": {"paper": True, "clause": True, "both": True}, "clause_book": {"found": True, "page": 4}}  # fmt: skip
    line = {**base, **kw}
    return {**line, **W.classify(line)}  # stored as the exit wrote it


def _rows(lines: list[dict]) -> tuple[list, list]:
    """The built run file read back: (rows of the sheet CRS, rows of the sheet of other lines)."""
    wb = openpyxl.load_workbook(
        io.BytesIO(crs_layout.build_layout_crs(WB.layout_view(lines, META, "internal")))
    )
    other = (
        _table_rows(wb[words.NOT_A_COMMENT_SHEET], "Item No")
        if words.NOT_A_COMMENT_SHEET in wb.sheetnames
        else []
    )
    return _table_rows(wb[crs_layout.LAYOUT_MAIN_SHEET], "Item No"), other


def _status(row) -> str:
    return row[crs_layout.LAYOUT_COLUMNS.index("Status")]


# --- 1. G5: a firm "not met" carries a checked clause, or it is a question


def test_a_firm_not_met_whose_clause_was_not_checked_is_a_question_in_the_built_file():
    (got,) = words.read_now([_not_met()], [], holds=UNSURE)
    assert (
        got["clause"] == "" and rp.rank_of_ai_line(got)[0] == 4
    )  # never firm with no clause
    assert (
        got["verdict_label"] == W.WORD_QUERY and got["verdict_class"] == W.CLASS_QUERY
    )
    assert words.CLAUSE_NOT_CHECKED.format(clause="6.7.4") in got["not_proven_reason"]
    assert (
        "not met in the AI reviewer's view" in got["not_proven_reason"]
    )  # what the line said, kept for the engineer
    (row,), _other = _rows(
        [got]
    )  # the file's builder reads the line again (`read_now`): still a question
    assert _status(row) == words.STATUS_QUERY
    built = gates.g5_firm([gates._line_row("R1", got, row)])
    assert (
        built.status != gates.FAIL and built.checked == 0
    )  # gate G5: no firm row without a clause


def test_a_firm_not_met_that_keeps_its_checked_clause_stays_firm():
    (kept,) = words.read_now([_not_met()], [], holds=NONE)
    assert kept["clause"] == "6.7.4" and rp.rank_of_ai_line(kept)[0] == 3
    assert firm_clause.HELD_KEY not in kept
    (row,), _other = _rows(
        [_not_met()]
    )  # the default reader holds no book text: code cannot tell, the clause stays
    assert _status(row) == words.STATUS_AI


def test_a_clause_code_is_certain_does_not_hold_the_words_makes_a_question_too():
    (got,) = words.read_now([_not_met()], [], holds=FALSE)
    assert rp.rank_of_ai_line(got)[0] == 4
    assert (
        "clause 6.7.4 not confirmed: the rule's words are not in it"
        in got["not_proven_reason"]
    )


def test_a_firm_not_met_that_names_no_clause_is_a_question():
    (got,) = words.read_now([_not_met(clause="")], [], holds=NONE)
    assert (
        rp.rank_of_ai_line(got)[0] == 4
        and firm_clause.NO_CLAUSE in got["not_proven_reason"]
    )


def test_a_proven_fail_whose_clause_was_not_checked_is_a_question_and_not_a_fail():
    line = _not_met(
        verdict="Fail",
        decided_by="decided by code",
        compare={"decided": True, "verdict": "does_not_meet"},
    )
    assert line["verdict_class"] == W.CLASS_PROVEN
    assert (
        rp.rank_of_ai_line(words.read_now([line], [], holds=NONE)[0])[0] == 1
    )  # with its clause: a proven Fail
    (got,) = words.read_now([line], [], holds=UNSURE)
    assert (
        got["verdict"] == "Query"
        and got["decided_by"] == "engineer"
        and rp.rank_of_ai_line(got)[0] == 4
    )
    assert "not met, proven by code" in got["not_proven_reason"]
    assert WB.contractor_rows([got]) == []  # never issued to the contractor


def test_classify_reads_a_held_line_as_a_question_whatever_the_readers_said():
    (got,) = words.read_now([_not_met()], [], holds=UNSURE)
    assert (
        W.classify(got)["verdict_class"] == W.CLASS_QUERY
    )  # a recomputing reader (two readers, opinion) agrees
    assert W.read_time(got)["not_proven_reason"] == got["not_proven_reason"]


def test_a_met_whose_clause_was_not_checked_is_left_as_it_is():
    met = _not_met(ai_verdict="Pass", reason_code="met")
    before = rp.rank_of_ai_line(words.read_now([met], [], holds=NONE)[0])[0]
    (got,) = words.read_now([met], [], holds=UNSURE)
    assert firm_clause.HELD_KEY not in got and rp.rank_of_ai_line(got)[0] == before


def test_the_reading_is_idempotent():
    once = words.read_now([_not_met()], [], holds=UNSURE)
    assert words.read_now(once, [], holds=UNSURE) == once


# --- 2. G4: the AI run's file, one comment per topic


def _does_not_apply(item: str, req: str) -> dict:
    """The AI reader's own "not applicable" with no proof found by code (FTU-17: a question to confirm)."""
    return _not_met(item=item, clause="4.1.1", ai_verdict="Query", reason_code="not_applicable", requirement=req,
                    clause_quote=req, field_roles=[], why="the widget has no such part")  # fmt: skip


def test_does_not_apply_lines_under_one_clause_are_not_several_comments_in_the_run_file():
    lines = [
        _does_not_apply(f"R-{n}", f"Rule {n} of the widget annex shall hold.")
        for n in range(1, 5)
    ]
    lines.append(_not_met(item="R-9", clause="6.1"))
    assert all(
        rp.shown_rank(ln) == 9 for ln in lines[:4]
    )  # the page's own rank of such a line
    crs, other = _rows(lines)
    assert len(crs) == 1 and _status(crs[0]) == words.STATUS_AI  # the one real finding
    kinds = [r[4] for r in other]
    assert (
        kinds.count(rp.RANKS[9][0]) == 4
    )  # one row each, named as the team file names them
    assert len(crs) + len(other) == len(lines)  # completeness: no line lost
    read = words.read_now(lines, [], holds=NONE)
    rows = [
        gates._line_row(f"R{n}", ln)
        for n, (ln, _s, _o) in enumerate(WB.ordered_item_lines(read), start=1)
    ]
    assert gates.g4_one_per_field(rows).failed == []
