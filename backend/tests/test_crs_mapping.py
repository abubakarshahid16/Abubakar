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


def test_breaches_come_first_then_missing_values_then_questions_never_a_pass():
    """CRS quick wins: NC, then MISSING_INFORMATION (now itemised), then the
    engineer's questions; a COMPLIANT result is never a row."""
    rows = build_crs_rows([MI, NER, OK, NC], [], "sheet.pdf")
    assert [r["row_kind"] for r in rows] == [
        ROW_KIND_NON_COMPLIANT, ROW_KIND_MISSING_INFORMATION, ROW_KIND_NEEDS_ENGINEER_REVIEW]
    assert "8 g/L" in rows[0]["comment"]
    # the question's reason, in words, WITHOUT its machine code
    assert "no comparison made" in rows[2]["comment"]
    assert "table_row" not in rows[2]["comment"]


BLANK = {"compliance_status": "MISSING_INFORMATION", "id": "b1",
         "standard_name": "SAES-G-905.pdf", "standard_clause": "4.1", "standard_page": 1,
         "requirement_source_text": "4.1 The noise level shall not exceed 85 dB(A) at 1 m.",
         "contractor_evidence_text": "*", "contractor_page": 1, "fact_id": "fa",
         "crs_field_label": "NOISE LEVEL", "crs_is_blank": True, "equipment_tag": "P-101A",
         "ai_rationale": "the submittal leaves this field to be provided (*)"}


def test_every_missing_value_is_its_own_row_one_per_field():
    """CRS QUICK WINS (audit crs.md defect 2), THE MUTATION TARGET (M1300).
    The one summary row ("4 requirements ... not itemized here") hid a
    vibration breach, a hydrotest shortfall and a nozzle-size breach on the
    audit's planted sheets. Every blank / vendor-to-advise field is a row:
    three different fields are three rows, each naming its field, clause and
    the marker the sheet printed; the SAME field and value for two tags is one
    row naming both tags."""
    motor = dict(BLANK, id="b2", fact_id="fb", standard_clause="4.7", crs_field_label="MOTOR RATING",
                 requirement_source_text="4.7 The motor rating shall be at least 110 % of the rated pump power.")
    seal = dict(BLANK, id="b3", fact_id="fc", standard_clause="4.5", crs_field_label="SEAL TYPE",
                contractor_evidence_text="VENDOR TO ADVISE",
                requirement_source_text="4.5 Mechanical seals shall be in accordance with API 682.")
    other_tag = dict(BLANK, id="b4", fact_id="fd", equipment_tag="P-101B")
    rows = build_crs_rows([BLANK, motor, seal, other_tag], [], "pump.pdf")
    assert len(rows) == 3
    assert all(r["row_kind"] == ROW_KIND_MISSING_INFORMATION for r in rows)
    noise = rows[0]
    assert noise["page_section"] == "p.1 - Noise level (P-101A, P-101B)"
    assert noise["standard_reference"] == "SAES-G-905 cl. 4.1 (p.1)"
    assert noise["comment"] == (
        'SAES-G-905 cl. 4.1 (p.1): "The noise level shall not exceed 85 dB(A) at 1 m." '
        "Datasheet p.1, Noise level (P-101A, P-101B) is left to be provided ('*'). "
        "Contractor to provide Noise level.")
    assert "VENDOR TO ADVISE" in rows[2]["comment"] and "Seal type" in rows[2]["page_section"]
    assert not any("not itemized" in r["comment"] for r in rows)
    # 20,000 findings about ONE field and value are still one row
    assert len(build_crs_rows([BLANK] * 20000, [], "s.pdf")) == 1


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
        ROW_KIND_NON_COMPLIANT, ROW_KIND_MISSING_INFORMATION,
        ROW_KIND_NEEDS_ENGINEER_REVIEW,
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
    assert rows[0]["standard_reference"] == "SAES-X-001 cl. 5.1 (p.7); STD-OTHER cl. 9.9 (p.3)"
    assert rows[0]["comment"].startswith("SAES-X-001 cl. 5.1 (p.7); STD-OTHER cl. 9.9 (p.3):")


def test_page_section_is_the_datasheet_and_the_standard_has_its_own_column():
    """CRS quick wins (audit crs.md defect 8), THE MUTATION TARGET (M1301):
    Page/Section names the DATASHEET's page, field and tag - never the
    standard's file name, which moved to `standard_reference`."""
    rows = build_crs_rows([dict(NC, crs_field_label="SULPHUR CONTENT")], [], "s.pdf")
    assert rows[0]["page_section"] == "p.4 - Sulphur content (V-001)"
    assert rows[0]["standard_reference"] == "SAES-X-001 cl. 5.1 (p.7)"
    assert ".pdf" not in rows[0]["page_section"] + rows[0]["standard_reference"]


def test_the_comment_is_an_engineers_with_a_contractor_action():
    """THE MUTATION TARGET (M1302): "<Standard> cl. <clause>: requires
    <required>. Datasheet <page/field> states <provided>. Contractor to
    <action>." - with the operator in words, never a symbol or a machine
    reason code."""
    nc = dict(NC, crs_field_label="CORROSION ALLOWANCE", contractor_evidence_text="1.5 mm",
              requirement_limit={"subject": "corrosion allowance for carbon steel vessels",
                                 "operator": ">=", "raw_value": "3", "raw_unit": "mm"})
    comment = build_crs_rows([nc], [], "s.pdf")[0]["comment"]
    assert comment == (
        "SAES-X-001 cl. 5.1 (p.7): requires corrosion allowance for carbon steel "
        "vessels not less than 3 mm. Datasheet p.4, Corrosion allowance (V-001) "
        "states 1.5 mm. Contractor to revise Corrosion allowance to meet the "
        "requirement, or submit a deviation request with justification for "
        "Company approval.")
    assert ">=" not in comment and "8 exceeds 5" not in comment


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
