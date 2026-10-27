"""Order 245c (backlog 11): a missing library requirement keeps its contractor row only when
the field it names is one the system knows - a role of the checklist data or a spelling in
`field_synonyms.json`. Any other clean noun phrase is a sentence's subject, so the requirement
goes to the grouped engineer note. Invented findings only."""

from __future__ import annotations

from app import crs_mapping, crs_no_field
from app.datasheets import normalise_field_name


def _missing(i, **extra):
    return {
        "id": f"m{i}",
        "compliance_status": "MISSING_INFORMATION",
        "standard_name": "STD-A.pdf",
        "standard_clause": f"{i}.1",
        "standard_page": i,
        "requirement_source_text": f"{i}.1 The item {i} shall be approved.",
        "ai_rationale": "",
        **extra,
    }


def _row_ids(findings):
    return [r["finding_id"] for r in crs_mapping.build_crs_rows(findings, [], "s.pdf")]


def _noted(findings):
    return sum(
        n["count"]
        for n in crs_mapping.build_review_notes(findings, [])
        if n["note"] == crs_no_field.NOTE_NO_FIELD_ANSWERS
    )


def test_a_role_of_the_checklist_data_is_a_known_field():
    assert crs_no_field.is_known_field("DESIGN PRESSURE")
    assert crs_no_field.is_known_field("design pressure")


def test_a_spelling_of_the_synonym_data_is_a_known_field():
    from app import datasheet_checks

    group, spellings = next(iter(datasheet_checks._synonyms().items()))
    assert crs_no_field.is_known_field(spellings[0])
    assert crs_no_field.is_known_field(group)


def test_a_clean_noun_phrase_that_is_no_field_is_not_known():
    for label in ("the buyer approval", "Zorblat flange gasket", "", "  "):
        assert not crs_no_field.is_known_field(label), label


def test_a_known_field_stays_a_contractor_row_and_an_unknown_one_is_grouped():
    known = _missing(1, crs_field_label="Design pressure")
    unknown = _missing(2, crs_field_label="Zorblat flange gasket")
    both = [known, unknown]
    assert _row_ids(both) == ["m1"]
    assert _noted(both) == 1


def test_the_label_is_judged_by_the_same_folding_as_the_data():
    label = "  DESIGN   Pressure "
    assert normalise_field_name(label) == normalise_field_name("design pressure")
    assert _row_ids([_missing(1, crs_field_label=label)]) == ["m1"]


def test_an_unknown_phrase_does_not_count_as_naming_a_field():
    finding = _missing(1, crs_field_label="Zorblat flange gasket")
    assert crs_no_field.answered_by_no_field(
        finding, lambda f: f.get("crs_field_label")
    )
    assert crs_no_field.bucket_of_missing(finding, "blank", "not_found") is None


def test_a_blank_the_sheet_marks_keeps_its_row_whatever_it_is_called():
    blank = _missing(
        1, fact_id="fa", contractor_page=1, crs_field_label="Zorblat flange gasket"
    )
    assert _row_ids([blank]) == ["m1"]
    assert _noted([blank]) == 0


def test_other_kinds_of_finding_keep_their_rows_with_an_unknown_phrase():
    finding = _missing(
        1, origin="datasheet_check", crs_field_label="Zorblat flange gasket"
    )
    assert _row_ids([finding]) == ["m1"]
    assert _noted([finding]) == 0
