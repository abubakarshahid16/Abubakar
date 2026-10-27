"""Order 245: a library requirement no field on the sheet answers is one grouped
engineer line per standard, not a contractor row.

With the 35B reading every page and an API standard of 1,161 requirements in
the library, M-03's comment sheet grew from 50 to 226 rows: 184 were clauses no
read field answered, each a "missing information" row for the contractor. A
requirement paired with a field (a value, or a blank the sheet marks) or naming
a datasheet field the sheet lacks is still a row; the rest is counted per
standard in the review notes, internal copy only, with every reference listed.
Invented findings only.
"""

from __future__ import annotations

from app import crs_mapping, crs_no_field


def _missing(i, standard="STD-A.pdf", **extra):
    return {
        "id": f"m{i}",
        "compliance_status": "MISSING_INFORMATION",
        "standard_name": standard,
        "standard_clause": f"{i}.1",
        "standard_page": i,
        "requirement_source_text": f"{i}.1 The item {i} shall be of a type that the buyer approves.",
        "ai_rationale": "",
        **extra,
    }


def _notes(findings):
    return [
        n
        for n in crs_mapping.build_review_notes(findings, [])
        if n["note"] == crs_no_field.NOTE_NO_FIELD_ANSWERS
    ]


def test_a_requirement_with_no_field_behind_it_is_no_row_but_a_counted_note():
    findings = [_missing(i) for i in range(1, 6)]
    assert crs_mapping.build_crs_rows(findings, [], "s.pdf") == []
    assert crs_mapping.crs_groups(findings) == []
    [note] = _notes(findings)
    assert note["count"] == 5 and note["standard"] == "STD-A.pdf"
    assert "5 of this run's requirements from STD-A.pdf" in note["detail"]
    assert "not comments for the contractor" in note["detail"]


def test_every_reference_is_listed_for_the_internal_copy():
    findings = [_missing(i) for i in range(1, 12)]
    [note] = _notes(findings)
    assert note["detail"].count("STD-A") >= 11, note["detail"]
    assert "and 5 more" not in note["detail"]


def test_one_note_per_standard():
    findings = [_missing(1), _missing(2), _missing(3, standard="STD-B.pdf")]
    notes = {n["standard"]: n["count"] for n in _notes(findings)}
    assert notes == {"STD-A.pdf": 2, "STD-B.pdf": 1}


def test_a_requirement_that_names_a_field_the_sheet_lacks_stays_a_row():
    findings = [_missing(1, crs_field_label="DESIGN PRESSURE"), _missing(2)]
    rows = crs_mapping.build_crs_rows(findings, [], "s.pdf")
    assert [r["finding_id"] for r in rows] == ["m1"]
    [note] = _notes(findings)
    assert note["count"] == 1


def test_a_blank_the_sheet_marks_stays_a_row():
    blank = _missing(1, fact_id="fa", contractor_page=1)
    rows = crs_mapping.build_crs_rows([blank], [], "s.pdf")
    assert [r["finding_id"] for r in rows] == ["m1"]
    assert _notes([blank]) == []


def test_other_kinds_of_finding_are_not_counted_here():
    others = [
        _missing(1, origin="datasheet_check"),
        _missing(2, origin="ai_engineering_check"),
        _missing(3, origin="chat"),
        _missing(4, crs_skip=True),
        _missing(5, approval_status="rejected"),
        {**_missing(6), "compliance_status": "NEEDS_ENGINEER_REVIEW"},
    ]
    assert _notes(others) == []


def test_the_origins_this_module_leaves_alone_are_the_ones_crs_mapping_names():
    assert set(crs_no_field.OTHER_ORIGINS) == {
        crs_mapping._DATASHEET_ORIGIN,
        crs_mapping._AI_ORIGIN,
        crs_mapping._WEB_ORIGIN,
        "chat",
    }
