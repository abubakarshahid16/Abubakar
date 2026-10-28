"""28 Oct planner audit, fix 5(b)/(c): a checklist item held for the engineer is a CRS row, and a
draft checklist says so. Invented findings only."""

from __future__ import annotations

from app import crs_mapping
from app.datasheet_checks import DRAFT_MARK

HELD = {
    "id": "h1",
    "origin": "datasheet_check",
    "compliance_status": "NEEDS_ENGINEER_REVIEW",
    "approval_status": "pending",
    "severity": "minor",
    "equipment_tag": "P-1",
    "standard_clause": "STD-A 5.1",
    "fact_id": "f1",
    "contractor_page": 7,
    "contractor_section": "Casing material",
    "contractor_evidence_text": "CS / SS",
    "requirement": f"The casing material is stated (STD-A 5.1; {DRAFT_MARK})",
    "requirement_source_text": f"Datasheet check C1: The casing material is stated (STD-A 5.1; {DRAFT_MARK})",
    "ai_rationale": "Datasheet check C1: the casing material has two different values on the sheet",
}


def _rows(*findings):
    return crs_mapping.build_crs_rows(list(findings), [], "sheet.pdf")


def test_a_held_checklist_item_is_a_crs_row_and_says_it_is_a_draft():
    [row] = _rows(HELD)
    assert row["row_kind"] == "datasheet_check"
    assert row["finding_id"] == "h1"
    assert "Draft checklist, engineer to confirm" in row["reasoning"]
    assert "engineer to check" in row["reasoning"]


def test_a_signed_off_checklist_does_not_say_draft():
    signed = {
        **HELD,
        "requirement": "The casing material is stated (STD-A 5.1)",
        "requirement_source_text": "Datasheet check C1: The casing material is stated (STD-A 5.1)",
    }
    [row] = _rows(signed)
    assert "Draft checklist" not in row["reasoning"]


def test_a_held_datasheet_check_that_is_not_a_checklist_item_is_still_no_row():
    other = {**HELD, "standard_clause": None, "requirement": "Two values agree"}
    assert _rows(other) == []
    assert crs_mapping.crs_bucket(other) is None


def test_a_checklist_pass_is_still_no_row():
    assert _rows({**HELD, "compliance_status": "COMPLIANT"}) == []


def test_the_screen_and_the_file_agree_on_the_bucket():
    assert crs_mapping.crs_bucket(HELD) == crs_mapping.BUCKET_CHECK
