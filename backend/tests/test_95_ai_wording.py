"""Order 95 piece 6b: an engineer's edit keeps the machine's wording beside it.

A CRS row carries `ai_comment` (the machine's own wording) and `edited` (an
engineer replaced it with different words). The internal copy prints the
machine wording in its "AI Review Comments" cell, and the Comment cell stays
the engineer's words alone (M1086-M1089); the contractor's copy carries only
the edit. An unedited row has no "AI wording" at all.

Invented findings only.
"""

from __future__ import annotations

from app import crs_export
from app.crs_mapping import ROW_KIND_DATASHEET_CHECK, build_crs_rows

NC = {
    "id": "f1",
    "compliance_status": "NON_COMPLIANT",
    "standard_name": "SAES-X-001.pdf",
    "standard_clause": "5.1",
    "standard_page": 7,
    "contractor_page": 4,
    "requirement_source_text": "shall not exceed 5 g/L",
    "contractor_evidence_text": "8 g/L",
    "ai_rationale": "8 exceeds 5.",
    "equipment_tag": "V-001",
}
EDIT = "Reduce the content to 5 g/L or less and resubmit."
EDITED = dict(NC, engineer_comment=EDIT, confirmed_by="u1", confirmed_by_name="Eng One")


def _view(rows, copy):
    return crs_export.build_crs_view(rows, {"copy": copy, "review_run_id": "run-1"})


def test_an_edited_row_keeps_the_machine_wording_and_says_it_was_edited():
    [plain] = build_crs_rows([NC], [], "sheet.pdf")
    [edited] = build_crs_rows([EDITED], [], "sheet.pdf")
    assert plain["edited"] is False and plain["ai_comment"] == plain["comment"]
    assert edited["edited"] is True and edited["comment"] == EDIT
    assert edited["ai_comment"] == plain["comment"] and "8 g/L" in edited["ai_comment"]


def test_an_edit_that_keeps_the_machine_words_is_not_printed_twice():
    [plain] = build_crs_rows([NC], [], "sheet.pdf")
    same = dict(NC, engineer_comment=plain["comment"] + " ", confirmed_by="u1")
    [row] = build_crs_rows([same], [], "sheet.pdf")
    assert row["edited"] is False
    [internal] = _view([row], "internal")["rows"]
    assert internal["ai_review_comment"] == ""


def test_a_datasheet_check_keeps_its_own_machine_wording():
    check = {
        "id": "c1",
        "origin": "datasheet_check",
        "compliance_status": "NON_COMPLIANT",
        "finding": "Design pressure is below test pressure.",
        "required_action": "Correct the design pressure.",
        "engineer_comment": "Design pressure must exceed test pressure.",
    }
    [row] = build_crs_rows([check], [], "sheet.pdf")
    assert row["row_kind"] == ROW_KIND_DATASHEET_CHECK
    assert row["edited"] is True
    assert row["ai_comment"] == (
        "Design pressure is below test pressure. Correct the design pressure."
    )


def test_the_internal_copy_shows_the_ai_wording_beside_the_edit_the_issue_copy_does_not():
    [row] = build_crs_rows([EDITED], [], "sheet.pdf")
    [internal] = _view([row], "internal")["rows"]
    [issue] = _view([row], "issue")["rows"]
    # replaced, never appended to (the first line is the row's Ref)
    assert internal["comment"].endswith(EDIT) and "8 g/L" not in internal["comment"]
    assert internal["ai_review_comment"] == (
        f"{crs_export.AI_WORDING_LABEL}: {row['ai_comment']}"
    )
    assert "8 g/L" in internal["ai_review_comment"]
    assert issue["comment"].endswith(EDIT) and issue["ai_review_comment"] == ""


def test_an_unedited_row_prints_its_comment_once_with_no_ai_wording_line():
    [row] = build_crs_rows([dict(NC, confirmed_by="u1")], [], "sheet.pdf")
    [internal] = _view([row], "internal")["rows"]
    assert internal["ai_review_comment"] == ""
    assert internal["comment"].endswith(row["comment"])
