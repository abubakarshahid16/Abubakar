"""Order 14 LPH (owner, 17 Nov 2026): a line the AI could not settle never shows "Not met", "Met", "Pass" or "Fail" anywhere.

An AI-written rule-check row (clause review, AI engineering check, web standard check, specification kit) is a question whatever its
stored state: NEEDS_ENGINEER_REVIEW (which the clause review always stores), none (the AI engineering check), and even a stored COMPLIANT
or NON_COMPLIANT, which has no code-verified quote behind it (lead's review of PR #1882). On the page's points and tiles, in the paper's
team and contractor files and in the run file. Never from a document or its wording. Invented data only."""

from __future__ import annotations

import io
import re

import pytest
from openpyxl import load_workbook

from app import (
    crs_ai_drafts,
    crs_export,
    crs_normal,
    crs_one,
    main,
    review_points,
    review_points_service,
)
from app.config import settings
from tests.test_crs_endpoint import (  # noqa: F401 - fixture
    _finding,
    _run,
    _submittal,
    temp_db,
)
from tests.test_k4_one_crs import scope_all

AI_KINDS = ("clause_review", "ai_engineering_check", "web_standard_check", "spec_kit")
UNSETTLED = (
    None,
    "NEEDS_ENGINEER_REVIEW",
    "MISSING_INFORMATION",
    "NOT_IN_DOCUMENT_SCOPE",
)
FIRM = re.compile(r"\b(Not met|Met|Pass|Fail)\b")


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    monkeypatch.setattr(settings, "review_code_resubmit_at_kept_mandatory_not_met", 0)


def test_an_ai_row_is_a_query_whatever_its_stored_state():
    for kind in AI_KINDS:
        for state in (*UNSETTLED, "COMPLIANT", "NON_COMPLIANT"):
            assert crs_normal.crs_status(kind, 3, state) == "Query", (kind, state)
            assert not crs_normal.settled({crs_ai_drafts.STORED_STATE: state})


def test_the_draft_row_carries_its_findings_stored_state():
    assert crs_ai_drafts.row_extras(
        {"id": "f1", "compliance_status": "NEEDS_ENGINEER_REVIEW"}
    )[crs_ai_drafts.STORED_STATE] == ("NEEDS_ENGINEER_REVIEW")
    assert crs_ai_drafts.row_extras({"id": "f2"})[crs_ai_drafts.STORED_STATE] is None


def test_the_run_files_view_keeps_the_stored_state_so_its_status_is_the_pages():
    rows = [
        {
            "row_kind": "clause_review",
            "comment": "c1",
            crs_ai_drafts.STORED_STATE: "NEEDS_ENGINEER_REVIEW",
        },
        {
            "row_kind": "clause_review",
            "comment": "c2",
            crs_ai_drafts.STORED_STATE: "NON_COMPLIANT",
        },
    ]
    view = crs_export.build_crs_view(rows, {"review_run_id": "run-x"})
    assert [r[crs_ai_drafts.STORED_STATE] for r in view["rows"]] == [
        "NEEDS_ENGINEER_REVIEW",
        "NON_COMPLIANT",
    ]
    assert [r["status"] for r in view["rows"]] == ["Query", "Query"]


def _rule_point(state):
    row = {
        "row_kind": "clause_review",
        "finding_id": "f-1",
        "comment": "Engineer to check.",
        crs_ai_drafts.STORED_STATE: state,
    }
    ctx = {
        "run_id": "r",
        "paper_document_id": "doc_x",
        "readable": frozenset({"doc_x"}),
    }
    return review_points.rule_point(row, ctx, None, {})


def test_a_rule_check_ai_line_is_a_question_on_the_page_whatever_its_stored_state():
    for state in ("NEEDS_ENGINEER_REVIEW", None, "COMPLIANT", "NON_COMPLIANT"):
        p = _rule_point(state)
        review_points.with_groups([p])
        assert (p["rank"], p["tile"], p["firm"]) == (4, "questions", None), state
        assert not FIRM.search(p["pill"]) and not FIRM.search(
            review_points.TILE_WORDS[p["tile"]]
        )
    assert "AI opinion" not in {
        s for s, r in review_points._RANK_OF_RC_STATUS.items() if r in (2, 3, 5, 6)
    }  # no AI rank by Status


def _paper_with_unsettled_ai_rows():
    doc = _submittal("doc_lph", "invented-procedure.pdf")
    run = _run(doc)
    for i in range(3):
        _finding(doc, run, "NEEDS_ENGINEER_REVIEW", origin="clause_review", category="technical_query", severity="minor",
                 contractor_evidence_text=None, requirement=f"Invented clause {i}: the study shall record each node.",
                 finding=f"Requirement {i}. The AI found no passage; engineer to check.", standard_clause=f"4.{i}")  # fmt: skip
    _finding(doc, run, None, origin="ai_engineering_check", category="technical_query", severity="minor",
             finding="Invented observation for the engineer.")  # fmt: skip
    return doc, run


def test_no_firm_word_anywhere_for_lines_the_ai_could_not_settle(temp_db):  # noqa: F811
    doc, run = _paper_with_unsettled_ai_rows()
    scope = scope_all()
    page = review_points_service.assemble(doc, scope)
    rule = [p for p in page["points"] if p["source"] == review_points.SOURCE_RULE_CHECK]
    assert len(rule) == 4 and {p["tile"] for p in rule} == {"questions"}
    assert (
        page["counts"]["tiles"]["not_met"]["total"] == 0
        and page["counts"]["tiles"]["met"]["total"] == 0
    )
    assert not [p["pill"] for p in rule if FIRM.search(p["pill"] or "")]
    for data in (crs_one.build_team(doc, scope), crs_one.build_contractor(doc, scope)):
        cells = [
            str(v)
            for ws in load_workbook(io.BytesIO(data)).worksheets
            for r in ws.iter_rows(values_only=True)
            for v in r
            if v
        ]
        assert not [c for c in cells if FIRM.search(c)]
    data, _name = main._crs_workbook(
        run, scope, "internal"
    )  # the run file as built (its older route is off beside the one CRS)
    wb = load_workbook(io.BytesIO(data))
    statuses = [
        str(v)
        for r in wb["CRS"].iter_rows(values_only=True)
        for v in r
        if v in ("AI opinion", "Query", "Pass", "Fail")
    ]
    assert statuses.count("Query") == 4 and "AI opinion" not in statuses
