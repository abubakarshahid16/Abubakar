"""Lane 6, part 3: what the INTERNAL CRS shows of the accepted AI review proposals. Invented rows and pages only.

A removed row leaves the main sheet and is listed with its words and the AI's reason; a restore puts it back; an added row
is a question, never confirmed, with the AI's reason; a reword prints beside the template; the issue copy shows none of it.
"""

from __future__ import annotations

import io
import json

import openpyxl
import pytest

from app import ai_review_pass as arpass
from app import crs_ai_review_view as view
from app import crs_export, run_record
from app.config import settings
from tests.test_ai_review_pass import ADD, FAIL, HELD, PAGES, REMOVE, ROW, Stub

REWORD = {
    "id": "p5",
    "type": "reword",
    "row_key": "k-rev",
    "reason": "Clearer wording.",
    "confidence": "low",
    "text": "Engineer to check MAWP: tags P-101A and P-101B state 14 barg and 16 barg; please confirm.",
}
UNDERSTANDING = {
    "id": "p6",
    "type": "understanding",
    "reason": "Summary.",
    "confidence": "low",
    "understanding": {"equipment": "Relief valve", "tags": ["P-101A", "PSV-9901"]},
}


@pytest.fixture
def stored(monkeypatch):
    monkeypatch.setattr(settings, "ai_engineering_review_pass_enabled", True)
    arpass.run(
        "rv1",
        [dict(ROW), dict(FAIL)],
        pages=PAGES,
        held=HELD,
        provider=Stub([REMOVE, ADD, REWORD, UNDERSTANDING]),
    )
    return "rv1"


def rows():
    return [
        dict(ROW, document_name="Doc", priority=3),
        dict(FAIL, document_name="Doc", priority=1),
    ]


def test_a_removed_row_leaves_the_rows_and_an_added_row_arrives_unconfirmed(stored):
    # the reword and the removal touch the same row: only the first accepted change stands (one change per row)
    got = rows()
    view.apply(got, stored)
    keys = [r["crs_row_key"] for r in got]
    assert "k-rev" not in keys and "k-fail" in keys
    new = next(r for r in got if r.get("ai_review_added"))
    assert (
        new["row_kind"] == "needs_engineer_review"
        and new["engineer_confirmed"] is False
    )
    assert (
        new["ai_review_comment"].startswith("AI review: ")
        and new["comment_by"] == view.AUTHOR
    )
    assert (
        new["page_section"] == "p.2 - Set pressure"
        and new["standard_reference"] == "SAES-X-100 cl. 5.1"
    )


def test_a_restore_puts_the_row_back_and_the_undo_removes_it_again(stored):
    arpass.restore(stored, "p1", "Eng One")
    got = rows()
    view.apply(got, stored)
    assert "k-rev" in [r["crs_row_key"] for r in got]
    arpass.restore(stored, "p1", "Eng One", undo=True)
    got = rows()
    view.apply(got, stored)
    assert "k-rev" not in [r["crs_row_key"] for r in got]


def test_an_engineers_confirmed_row_is_never_removed_or_reworded(stored):
    got = rows()
    got[0]["engineer_confirmed"] = True
    view.apply(got, stored)
    row = next(r for r in got if r["crs_row_key"] == "k-rev")
    assert "ai_review_comment" not in row


def test_a_reword_prints_beside_the_template_with_its_reason(monkeypatch):
    monkeypatch.setattr(settings, "ai_engineering_review_pass_enabled", True)
    arpass.run("rv2", [dict(ROW)], pages=PAGES, held=HELD, provider=Stub([REWORD]))
    got = [dict(ROW)]
    view.apply(got, "rv2")
    assert got[0]["comment"] == ROW["comment"]
    assert (
        got[0]["ai_review_comment"] == REWORD["text"] + "\nAI review: Clearer wording."
    )


def test_the_pass_reads_the_draft_rows_not_its_own_changes(stored):
    got = rows()
    with view.unapplied():
        view.apply(got, stored)
    assert [r["crs_row_key"] for r in got] == ["k-rev", "k-fail"]


def test_for_run_lists_the_removal_with_its_words_and_its_state(stored):
    view.apply(rows(), stored)  # the state is what apply found against the run's rows
    data = view.for_run(stored)
    assert data["understanding"]["equipment"] == "Relief valve"
    (item,) = data["removed"]
    assert (
        item["state"] == "removed from the CRS"
        and item["words"] == ROW["comment"]
        and item["reason"]
    )
    arpass.restore(stored, "p1", "Eng One")
    assert view.for_run(stored)["removed"][0]["state"] == view.STATE_RESTORED
    assert view.for_run("never-ran") is None


def test_the_internal_meta_carries_it_and_the_issue_meta_does_not(stored):
    run = {"id": stored}
    assert run_record.crs_meta(run, {}, [], [], "issue", frozenset()) == {}
    assert "ai_review" in run_record.crs_meta(run, {}, [], [], "internal", frozenset())


def test_the_internal_workbook_has_the_sheet_and_the_issue_workbook_does_not(stored):
    findings = [
        {
            "document_name": "d",
            "page_section": "p.2 - Set pressure",
            "comment": "c",
            "comment_by": "b",
        }
    ]
    data = view.for_run(stored)
    internal = openpyxl.load_workbook(
        io.BytesIO(
            crs_export.build_crs(findings, {"copy": "internal", "ai_review": data})
        )
    )
    assert view.SHEET in internal.sheetnames
    text = json.dumps(
        [[c.value for c in row] for row in internal[view.SHEET].iter_rows()]
    )
    assert "Different tags have different MAWP" in text and ROW["comment"][:20] in text
    issue = openpyxl.load_workbook(
        io.BytesIO(crs_export.build_crs(findings, {"copy": "issue", "ai_review": data}))
    )
    assert view.SHEET not in issue.sheetnames
