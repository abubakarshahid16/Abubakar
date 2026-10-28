"""Order 308: the CRS AI wording may not turn "no field was read" into
"missing from the datasheet". A rewrite that states an absence the template
does not state is refused (`absence_not_in_template`) and the template stays.
Invented row only."""

from __future__ import annotations

import pytest

from app import crs_wording

MISSING_ROW = {
    "row_kind": "datasheet_check",
    "crs_row_key": "k9",
    "standard_reference": "",
    "page_section": "",
    "comment": "Design pressure was not found in the fields read from the datasheet.",
}


@pytest.mark.parametrize(
    "text, reason",
    [
        (
            "Design pressure was not found in the fields read from the datasheet; please confirm.",
            None,
        ),
        (
            "Design pressure is missing from the datasheet; please provide the required value.",
            crs_wording.ABSENCE_ADDED,
        ),
        (
            "Design pressure was not provided in the datasheet; please confirm.",
            crs_wording.ABSENCE_ADDED,
        ),
    ],
)
def test_wording_never_turns_no_field_read_into_missing_from_the_datasheet(
    text, reason
):
    assert crs_wording.lock(text, MISSING_ROW) == reason


ROW_11 = {
    **MISSING_ROW,
    "comment": "Inlet rating was not read as a value, and no label for it was found in the "
    "text of pages 1-4; the contractor is to provide it.",
}


@pytest.mark.parametrize(
    "text",
    [
        "Inlet rating has no value on the datasheet.",
        "The datasheet lacks the inlet rating.",
        "Inlet rating is not specified.",
        "Inlet rating is blank on the datasheet.",
        "Inlet rating is empty.",
        "Inlet rating is without a value.",
        "The datasheet does not have the inlet rating.",
        "Inlet rating has not been given.",
        "Inlet rating was never provided.",
        "Inlet rating is not available.",
    ],
)
def test_every_listed_absence_phrase_is_refused_against_a_no_label_template(text):
    assert crs_wording.lock(text, ROW_11) == crs_wording.ABSENCE_ADDED


def test_an_absence_the_template_itself_states_may_be_kept():
    row = {**MISSING_ROW, "comment": "Design pressure is missing from the sheet."}
    text = "Design pressure is missing from the sheet; please add it."
    assert crs_wording.lock(text, row) is None
