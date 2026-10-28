"""Order 283.3: a CRS row whose standard the datasheet does not cite says so (invented standards)."""

from __future__ import annotations

import pytest

from app import crs_cited
from app.crs_mapping import build_crs_rows

SHEET = "sheet.pdf"


def finding(fid, standard, status="NON_COMPLIANT", **extra):
    return {
        "id": fid,
        "compliance_status": status,
        "standard_name": standard,
        "standard_clause": "5.1",
        "standard_page": 7,
        "contractor_page": 4,
        "requirement_source_text": "The design pressure shall not exceed 5 bar.",
        "contractor_evidence_text": "8 bar",
        "ai_rationale": "8 exceeds 5.",
        "equipment_tag": "P-101A",
        "crs_field_label": "DESIGN PRESSURE",
        **extra,
    }


def rows_for(findings, cited):
    return build_crs_rows(findings, [], SHEET, standards_check=cited)


def test_a_row_of_a_standard_the_sheet_does_not_cite_says_so_and_stays_a_row():
    [row] = rows_for([finding("f1", "SAES-G-005.pdf")], {"cited": ["API 610"]})
    assert row["standard_cited"] is False
    assert row["comment"].startswith(crs_cited.LABEL)
    assert row["ai_comment"].startswith(crs_cited.LABEL)
    assert not row["edited"]  # label is not an engineer's edit
    assert row["row_kind"] == "non_compliant"


def test_a_row_of_a_cited_standard_is_unchanged():
    [row] = rows_for([finding("f1", "API 610 11th Ed.pdf")], {"cited": ["API 610"]})
    assert "standard_cited" not in row
    assert crs_cited.LABEL not in row["comment"]


@pytest.mark.parametrize("check", [None, {}, {"required_not_cited": []}])
def test_without_a_cited_list_nothing_is_labelled(check):
    [row] = rows_for([finding("f1", "SAES-G-005.pdf")], check)
    assert "standard_cited" not in row


def test_a_standard_whose_name_is_not_a_known_family_is_never_called_not_cited():
    [row] = rows_for([finding("f1", "House Rule Book.pdf")], {"cited": ["API 610"]})
    assert "standard_cited" not in row


def test_a_row_standing_on_one_cited_standard_among_others_is_not_labelled():
    group = [
        finding("f1", "SAES-G-005.pdf", crs_is_blank=True, status="MISSING_INFORMATION"),
        finding("f2", "API 610.pdf", crs_is_blank=True, status="MISSING_INFORMATION"),
    ]
    rows = rows_for(group, {"cited": ["API 610"]})
    shared = [r for r in rows if len(r.get("finding_ids", [])) == 2]
    assert len(shared) == 1, "the two findings must stand in one row for this test"
    assert "standard_cited" not in shared[0]


def test_a_row_standing_only_on_uncited_standards_is_labelled_whatever_their_number():
    group = [
        finding("f1", "SAES-G-005.pdf", crs_is_blank=True, status="MISSING_INFORMATION"),
        finding("f2", "SAES-G-006.pdf", crs_is_blank=True, status="MISSING_INFORMATION"),
    ]
    [row] = rows_for(group, {"cited": ["API 610"]})
    assert len(row["finding_ids"]) == 2 and row["standard_cited"] is False


def test_an_engineers_own_wording_is_kept_without_the_label_but_the_row_is_marked():
    f = finding("f1", "SAES-G-005.pdf", engineer_comment="Please confirm the design pressure.")
    [row] = rows_for([f], {"cited": ["API 610"]})
    assert row["comment"] == "Please confirm the design pressure."
    assert row["standard_cited"] is False


def test_a_datasheet_check_names_its_own_source_and_is_not_labelled():
    f = finding("f1", "SAES-G-005.pdf", origin="datasheet_check")
    rows = rows_for([f], {"cited": ["API 610"]})
    assert all("standard_cited" not in r for r in rows)


def test_mark_counts_the_rows_it_labelled_marks_once_and_numbering_does_not_move():
    fs = [finding("f1", "SAES-G-005.pdf"), finding("f2", "API 610.pdf", crs_field_label="TEMP")]
    check = {"cited": ["API 610"]}
    plain = rows_for(fs, None)
    rows = rows_for(fs, check)
    assert {r["comment_key"] for r in rows} == {r["comment_key"] for r in plain}
    assert crs_cited.mark(rows, fs, check) == 0  # already marked by build_crs_rows: never twice
    assert sum(r["comment"].count(crs_cited.LABEL) for r in rows) == 1
    assert crs_cited.mark(plain, fs, check) == 1
