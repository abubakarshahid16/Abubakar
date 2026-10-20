"""#882 (PF2, orders 180 / 180.1, items 3, 4, 8): blank fields no clause asks
about are ONE CRS row in full sentences; a blank a clause requires keeps its
own row. Invented findings only."""

from __future__ import annotations

from app import crs_blank_fields, crs_mapping
from app.crs_mapping import build_crs_rows, crs_groups

CHECK = {
    "origin": "datasheet_check",
    "compliance_status": "MISSING_INFORMATION",
    "requirement_source_text": "Datasheet checklist DS-M2: X is a mandatory field.",
    "standard_clause": None,
    "approval_status": "pending",
    "severity": "minor",
    "equipment_tag": "P-1",
}


def _blank(fid, label, page, **over):
    return {
        **CHECK,
        "id": fid,
        "fact_id": f"fact-{fid}",
        "crs_field_label": label,
        "contractor_section": label,
        "contractor_page": page,
        **over,
    }


def _rows(findings):
    return build_crs_rows(findings, [], "sheet.pdf")


def test_blank_fields_with_no_clause_are_one_row_listing_each_with_its_page():
    found = [
        _blank("a", "Fittings", 1),
        _blank("b", "Ultrasonic", 2),
        _blank("c", "Radiography", 2),
    ]
    rows = _rows(found)
    assert len(rows) == 1
    assert rows[0]["comment"] == (
        "These fields are left blank; contractor to complete: "
        "Fittings (p.1); Radiography (p.2); Ultrasonic (p.2)."
    )
    assert rows[0]["page_section"] == "p.1-2 - Fields left blank"
    assert sorted(rows[0]["finding_ids"]) == ["a", "b", "c"]


def test_a_blank_a_clause_requires_keeps_its_own_row():
    with_clause = _blank("k", "Ultrasonic", 2, standard_clause="STD 4.2")
    rows = _rows([_blank("a", "Fittings", 1), _blank("b", "Gaskets", 1), with_clause])
    assert len(rows) == 2
    assert sum(len(r["finding_ids"]) for r in rows) == 3
    assert [r["finding_ids"] for r in rows if "k" in r["finding_ids"]] == [["k"]]


def test_two_findings_of_one_field_are_one_entry_with_the_full_label():
    group = [
        _blank("a", "Radial", 1, crs_field_label="Radial"),
        _blank("b", "Radial - Offered", 3, crs_field_label="Radial - Offered"),
    ]
    assert crs_blank_fields.entries(group) == [("Radial - Offered", [1, 3])]


def test_the_row_number_does_not_depend_on_which_fields_are_blank():
    one = crs_groups([_blank("a", "Fittings", 1)])
    two = crs_groups([_blank("a", "Fittings", 1), _blank("b", "Gaskets", 2)])
    assert one[0]["comment_key"] == two[0]["comment_key"]
    assert len(two) == 1


def test_a_blank_with_a_clause_is_not_grouped_and_a_breach_is_untouched():
    f = _blank("k", "Fittings", 1, standard_clause="STD 4.2")
    assert not crs_blank_fields.is_unrequired_blank(f)
    assert not crs_blank_fields.is_unrequired_blank(
        {**f, "standard_clause": None, "compliance_status": "NON_COMPLIANT"}
    )
    assert crs_mapping._group_key(f)[0] != "blanks"


def test_a_group_with_no_readable_label_still_says_what_to_do():
    assert crs_blank_fields.comment([_blank("a", "", None)]).startswith(
        "Contractor to complete"
    )


def test_page_list_keeps_the_shape_the_findings_use():
    assert crs_blank_fields.page_list([7, 1, 2, 3]) == "1-3, 7"
    assert crs_mapping._page_list([2]) == "2"
