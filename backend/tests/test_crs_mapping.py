"""Mapping rules: which findings enter a CRS. Standalone, no db."""
from app.crs_mapping import (ROW_KIND_MISSING_INFORMATION,
                             ROW_KIND_NEEDS_ENGINEER_REVIEW,
                             ROW_KIND_NON_COMPLIANT,
                             build_crs_rows, build_review_notes)

NC = {"compliance_status": "NON_COMPLIANT", "standard_name": "SAES-X-001.pdf",
      "standard_clause": "5.1", "standard_page": 7, "contractor_page": 4,
      "requirement_source_text": "shall not exceed 5 g/L",
      "contractor_evidence_text": "8 g/L", "ai_rationale": "8 exceeds 5.",
      "equipment_tag": "V-001"}
NER = {"compliance_status": "NEEDS_ENGINEER_REVIEW",
       "standard_name": "SAES-D-001.pdf", "standard_clause": "6.2.2",
       "standard_page": 14, "contractor_page": 4,
       "requirement_source_text": "per the following table",
       "ai_rationale": "table_row: no comparison made."}
MI = {"compliance_status": "MISSING_INFORMATION"}
OK = {"compliance_status": "COMPLIANT"}
ROD = {"compliance_status": "NOT_IN_DOCUMENT_SCOPE",
       "ai_rationale": ("requires_other_document: this requirement names its "
                        "own evidence - a calibration certificate")}


def test_only_nc_and_ner_enter_individually_and_nc_comes_first():
    rows = build_crs_rows([MI, NER, OK, NC], [], "sheet.pdf")
    individual = [r for r in rows if r["finding_id"] not in (
        "missing-information-summary", "requires-other-document-summary")]
    assert len(individual) == 2
    assert "8 exceeds 5" in individual[0]["comment"]
    assert "table_row" in individual[1]["comment"]


def test_missing_information_never_enters_individually():
    """20,000 MISSING_INFORMATION findings still collapse to ONE row - a
    count, not a list. Never zero rows either: issue #165 found that silence
    reads as "no such requirements existed", which is its own false claim."""
    rows = build_crs_rows([MI] * 20000, [], "s.pdf")
    assert len(rows) == 1
    assert "20000 requirements" in rows[0]["comment"]
    assert rows[0]["row_kind"] == ROW_KIND_MISSING_INFORMATION


def test_requires_other_document_is_a_review_note_by_standard_not_a_crs_row():
    """Owner order 2f/2e: an internal note, grouped by standard with a count -
    never a row in the contractor's COMPANY Comments column."""
    a, b = dict(ROD, standard_name="STD-A.pdf"), dict(ROD, standard_name="STD-B.pdf")
    assert build_crs_rows([a] * 540 + [b] * 7, [], "s.pdf") == []
    notes = build_review_notes([a] * 540 + [b] * 7, [])
    assert [(n["standard"], n["count"]) for n in notes] == [("STD-A.pdf", 540), ("STD-B.pdf", 7)]
    assert "540 of this run's requirements from STD-A.pdf" in notes[0]["detail"]


def test_not_in_document_scope_without_the_marker_is_not_counted():
    """B9/B22 owner-approved text; this module reads the marker rather than
    assuming every NOT_IN_DOCUMENT_SCOPE reason is "needs another document" -
    a future reason with no marker must not be silently folded in here."""
    unmarked = {"compliance_status": "NOT_IN_DOCUMENT_SCOPE",
                "ai_rationale": "some future reason with no marker"}
    assert build_crs_rows([unmarked], [], "s.pdf") == []


def test_the_three_and_a_half_buckets_are_tagged_with_distinct_row_kinds():
    """CRITERION 4. `crs_export` colours a row off `row_kind` alone, so every
    bucket this module can produce must carry its own distinct tag."""
    rows = build_crs_rows([NC, NER, MI, ROD], ["XYZ-STD-004"], "s.pdf")
    kinds = [r["row_kind"] for r in rows]
    # 2f: the requires-another-document and missing-standard rows are Review
    # notes now, not rows of this sheet.
    assert kinds == [
        ROW_KIND_NON_COMPLIANT, ROW_KIND_NEEDS_ENGINEER_REVIEW,
        ROW_KIND_MISSING_INFORMATION,
    ]
    assert len(set(kinds)) == len(kinds), "two buckets share one row_kind"


def test_missing_references_become_one_review_note_each_and_no_crs_row():
    assert build_crs_rows([], ["XYZ-STD-004", "XYZ-STD-016"], "s.pdf") == []
    notes = build_review_notes([], ["XYZ-STD-004", "XYZ-STD-016"])
    assert [n["standard"] for n in notes] == ["XYZ-STD-004", "XYZ-STD-016"]
    assert notes[0]["note"] == "Standard not in your library - upload required"


def test_the_same_rule_from_two_standards_is_one_comment_citing_both():
    """Owner order 2e: identical requirement text, same value, same page and
    same status - one row, both sources. A different value stays its own row."""
    other = dict(NC, standard_name="STD-OTHER.pdf", standard_clause="9.9", standard_page=3)
    rows = build_crs_rows([NC, other, dict(NC, contractor_evidence_text="9 g/L")], [], "s.pdf")
    assert len(rows) == 2
    assert f"{NC['standard_name']} clause 5.1" in rows[0]["page_section"]
    assert "STD-OTHER.pdf clause 9.9" in rows[0]["page_section"]
    assert "The same requirement is in: STD-OTHER.pdf clause 9.9" in rows[0]["comment"]


def test_citation_carries_both_sides():
    rows = build_crs_rows([NC], [], "s.pdf")
    assert rows[0]["page_section"] == "SAES-X-001.pdf clause 5.1 p7 / submittal p4"


def test_comment_carries_requirement_value_rationale_tag():
    comment = build_crs_rows([NC], [], "s.pdf")[0]["comment"]
    for piece in ("shall not exceed", "8 g/L", "8 exceeds 5", "V-001"):
        assert piece in comment


def test_confirmed_finding_names_the_engineer():
    f = dict(NC, confirmed_by="usman")
    assert build_crs_rows([f], [], "s.pdf")[0]["comment_by"] == \
        "AI Review, confirmed by usman"


def test_absent_fields_leak_nothing():
    bare = {"compliance_status": "NON_COMPLIANT"}
    row = build_crs_rows([bare], [], "s.pdf")[0]
    assert "None" not in row["comment"] and "None" not in row["page_section"]


def test_a_rows_identity_is_carried_but_never_printed():
    """`crs_export` mints the sheet's reference from the finding's own stored
    id; the id itself is a uuid an engineer cannot read back, so it travels
    beside the row and appears in none of its text."""
    rows = build_crs_rows(
        [{"id": "f-1", "compliance_status": "NON_COMPLIANT",
          "ai_rationale": "unit_mismatch"}], [], "drum.pdf")

    assert rows[0]["finding_id"] == "f-1"
    assert "f-1" not in rows[0]["comment"] + rows[0]["page_section"]
