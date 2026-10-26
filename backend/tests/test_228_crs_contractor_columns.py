"""Order 228.1, 228.2, 228.4: what the contractor's Standard Reference and
Page/Section columns print. Invented findings; no model, no document."""

from app import crs_mapping as cm


def _check(**kw):
    return {
        "origin": "datasheet_check",
        "requirement_source_text": "Datasheet check PSV-14: the set pressure shall be marked.",
        **kw,
    }


def test_a_checklist_row_prints_its_standard_and_clause_not_the_check_id():
    ref = cm._standard_reference(_check(standard_clause="API 520-I 3.20"))
    assert ref == "API 520-I 3.20"
    assert "PSV" not in ref and "Datasheet check" not in ref


def test_a_located_page_follows_the_clause():
    ref = cm._standard_reference(
        _check(standard_clause="API 520-I 3.20", standard_page=14)
    )
    assert ref == "API 520-I 3.20 (p.14)"


def test_a_check_with_no_clause_keeps_its_id():
    assert cm._standard_reference(_check()) == "Datasheet check PSV-14"


def test_an_ai_draft_names_the_standard_not_the_engine():
    f = {
        "origin": "ai_engineering_check",
        "ai_rationale": "Check the set pressure. Relates to: API 520-I. "
        "Written by ollama:hf.co/unsloth/Qwen3.",
    }
    assert cm._ai_relates_to(f) == "API 520-I"


def test_an_ai_draft_without_an_engine_note_is_unchanged():
    f = {"ai_rationale": "x. Relates to: API 520-I."}
    assert cm._ai_relates_to(f) == "API 520-I"
    assert (
        cm._ai_relates_to({"ai_rationale": "x. Relates to: no standard named."}) == ""
    )


def test_a_field_not_on_the_sheet_does_not_print_the_tag_list():
    f = {
        "origin": "datasheet_check",
        "contractor_section": "Set pressure",
        "equipment_tag": "PSV-1001, PSV-1002, PSV-1003",
        "compliance_status": "MISSING_INFORMATION",
    }
    out = cm._page_section([f])
    assert out.startswith("Not found on the datasheet")
    assert "PSV-1002" not in out


def test_a_field_read_on_a_page_keeps_its_page():
    f = {
        "origin": "datasheet_check",
        "contractor_section": "Set pressure",
        "contractor_page": 2,
        "fact_id": "f1",
    }
    assert cm._page_section([f]).startswith("p.2 - ")
