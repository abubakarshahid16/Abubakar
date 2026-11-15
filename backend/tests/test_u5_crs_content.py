"""U5d: the one CRS carries each point's own content: field, paper value, rule text, action, reason, Checked by, pages, rule reference.
Invented findings only; nothing here depends on a stored paper."""

from __future__ import annotations

from app import crs_one, review_points
from app import review_points_content as c
from tests.test_b1_review_points import world_with_both
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture
from tests.test_k4_one_crs import on, rows_after, scope_all, sheet  # noqa: F401 - fixtures and helpers

CTX = {"run_id": "r", "paper_document_id": "doc1", "readable": frozenset({"doc1"})}
PLACEHOLDER = "AI suggestion awaiting an engineer's decision - its words are in AI Review Comments. Not issued to the contractor until an engineer confirms it."


def row(kind="clause_review", **kw) -> dict:
    return {"row_kind": kind, "finding_id": "f1", "page_section": "", "comment": PLACEHOLDER, "standard_reference": "STD-9 (edition not recorded) cl. 5.3",
            "ai_review_comment": "Check that both assessments follow the procedure.", **kw}  # fmt: skip


FINDING = {"id": "f1", "standard_clause": "5.3", "requirement": "Both assessments shall follow the written procedure.", "requirement_source_text": "",
           "contractor_evidence_text": "Assessments are done by the team.", "contractor_page": 8, "compliance_status": "NEEDS_ENGINEER_REVIEW"}  # fmt: skip


# ------------------------------------------------------------------------------------------------ the pieces


def test_a_placeholder_or_a_page_label_is_never_the_field():
    assert c.field_of("p.22", row(), FINDING).startswith("STD-9 (edition not recorded) cl. 5.3: Both assessments")
    assert c.field_of(PLACEHOLDER, row(), FINDING).startswith("STD-9")
    assert "clause clause" not in c.field_of("", row(), FINDING) and "5.3 clause 5.3" not in c.field_of("", row(), FINDING)  # the clause is said once
    assert c.field_of("Set pressure", row(), FINDING) == "Set pressure"
    assert c.field_of("", row("playbook_check", comment="HAZOP scope and objectives", standard_reference=""), None) == "HAZOP scope and objectives"


def test_the_words_the_placeholder_points_to_are_in_the_cell_labelled_as_the_ais():
    text, source = c.action_of(row(), FINDING)
    assert (text, source) == ("Check that both assessments follow the procedure.", "ai_suggestion")
    assert c.action_of(row(comment="Contractor to confirm the rating."), FINDING) == ("Contractor to confirm the rating.", "check")
    assert c.action_of(row(comment=PLACEHOLDER, ai_review_comment=""), {"required_action": "Provide the procedure."}) == ("Provide the procedure.", "ai_suggestion")
    assert c.action_of(row(comment="", ai_review_comment=""), {}) == ("", "")


def test_stored_values_are_returned_as_stored_and_nothing_is_invented():
    assert c.paper_value(FINDING) == ("Assessments are done by the team.", 8)
    assert c.paper_value({}) == ("", None)
    assert c.rule_text(FINDING) == "Both assessments shall follow the written procedure."
    assert c.rule_text({}) == ""
    assert c.rule_ref(row(), FINDING) == {"name": "STD-9 (edition not recorded) cl. 5.3", "clause": "", "page": None}  # the clause already in the name
    assert c.rule_ref(row(standard_reference="STD-9"), FINDING)["clause"] == "5.3"


def test_the_reason_is_plain_words_per_kind_never_the_source_label():
    for kind in ("datasheet_check", "clause_review", "playbook_check", "ai_engineering_check", "needs_engineer_review", "standard_not_cited", "safety_tick"):
        got = c.reason_words(kind, FINDING)
        assert got and got.lower() not in ("datasheet check", "clause review", "playbook check", "ai engineering check", kind.replace("_", " "))
        assert "_" not in got
    assert "not compare" in c.reason_words("needs_engineer_review", {"reason_code": "quantity_kind_unsure"})
    assert c.checked_by("clause_review") == "Rule check: clause review (AI)" and c.checked_by("playbook_check") == "Rule check: playbook check"


# ------------------------------------------------------------------------------------------------ the point and the cells


def test_a_clause_review_point_carries_its_own_content():
    p = review_points.rule_point(row(), CTX, FINDING, {})
    assert p["name"].startswith("STD-9") and "awaiting" not in p["name"]
    assert p["action"] == "Check that both assessments follow the procedure." and p["action_source"] == "ai_suggestion"
    assert p["paper_value"] == "Assessments are done by the team." and p["paper_quote"] is None  # stored, NOT verified
    assert p["rule_text"].startswith("Both assessments") and p["checked_by"] == "Rule check: clause review (AI)"
    assert p["page"] == 8 and p["reason_words"]


def test_the_cells_say_stored_not_verified_and_say_nothing_recorded_once():
    p = review_points.rule_point(row(), CTX, FINDING, {})
    assert 'not verified by code' in crs_one.paper_shows(p) and '"Assessments are done by the team."' in crs_one.paper_shows(p)
    assert "verified by code)" not in crs_one.paper_shows(p).replace("not verified by code)", "")  # never worded as verified
    assert "not verified by code" in crs_one.rule_requires(p)
    empty = review_points.rule_point(row(), CTX, {"id": "f2"}, {})
    assert crs_one.paper_shows(empty) == c.NOTHING and crs_one.rule_requires(empty) == c.NOTHING
    assert "No verified quote" not in crs_one.paper_shows(p) + crs_one.rule_requires(p) + crs_one.paper_shows(empty)


def test_the_ai_suggestion_is_labelled_internal_and_never_reaches_the_contractor():
    p = review_points.rule_point(row(), CTX, FINDING, {})
    action = crs_one.full_texts({**p, "decision": {}})["action"]
    assert action.startswith("The AI's suggestion (internal") and "Check that both assessments" in action
    proven = {**p, "rank": 1, "decision": {"state": "keep"}}  # even a kept rank-1 point: the AI's suggestion is not issued
    assert crs_one.issuable_text(proven) == ""
    edited = {**p, "decision": {"state": "edit", "text": "Revise the procedure."}}
    assert crs_one.issuable_text(edited) == "Revise the procedure."


# ------------------------------------------------------------------------------------------------ the file


def test_the_team_file_has_no_placeholder_no_blanket_quote_wall_and_a_checked_by_column():
    doc, rc, ai, client = world_with_both()
    data = crs_one.build_team(doc, scope_all())
    head, rows = rows_after(sheet(data), "Comment")
    text = "\n".join(str(x) for r in rows for x in r if x is not None)
    assert "AI suggestion awaiting" not in text and "No verified quote" not in text
    by = head.index("Checked by")
    assert all(r[by] for r in rows)
    for col in ("Rule books and clauses",):  # said, or plainly not recorded; never a silent empty
        assert head.index(col) is not None


def test_the_pages_line_cannot_contradict_itself_and_the_files_line_has_no_api_path():
    assert crs_one.pages_line({"pages_total": 7, "pages_read": []}, []) == "7 pages: 0 not fully read; how many were read in full is not recorded"
    assert crs_one.pages_line({"pages_total": 69, "pages_read": [1, 2, 3]}, [4, 5]) == "69 pages: 3 read, 2 not fully read (pages 4, 5)"
    doc, rc, ai, client = world_with_both()
    data = crs_one.build_team(doc, scope_all())
    from openpyxl import load_workbook
    from io import BytesIO

    wb = load_workbook(BytesIO(data))
    every = "\n".join(str(x) for ws in wb.worksheets for r in ws.iter_rows(values_only=True) for x in r if x is not None)
    assert "/api/" not in every and "GET " not in every
