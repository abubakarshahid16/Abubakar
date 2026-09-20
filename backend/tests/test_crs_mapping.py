"""Mapping rules: which findings enter a CRS. Standalone, no db."""
from app.crs_mapping import build_crs_rows

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


def test_only_nc_and_ner_enter_and_nc_comes_first():
    rows = build_crs_rows([MI, NER, OK, NC], [], "sheet.pdf")
    assert len(rows) == 2
    assert "8 exceeds 5" in rows[0]["comment"]
    assert "table_row" in rows[1]["comment"]


def test_missing_information_never_enters_individually():
    assert build_crs_rows([MI] * 1578, [], "s.pdf") == []


def test_missing_references_become_one_row_each():
    rows = build_crs_rows([], ["32-SAMSS-004", "01-SAMSS-016"], "s.pdf")
    assert len(rows) == 2
    assert "32-SAMSS-004" in rows[0]["comment"]
    assert rows[0]["page_section"] == "References"


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
          "ai_rationale": "unit_mismatch"}], ["32-SAMSS-004"], "drum.pdf")

    assert rows[0]["finding_id"] == "f-1"
    assert "f-1" not in rows[0]["comment"] + rows[0]["page_section"]
    # A gap row has no finding behind it; the standard it names is what makes
    # it the same row on the next export.
    assert rows[1]["finding_id"] == "missing-reference:32-SAMSS-004"
