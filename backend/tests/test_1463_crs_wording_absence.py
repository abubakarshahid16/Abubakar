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
        # cloud-3's twelve (closed set of negation words, not a phrase list)
        "Inlet rating was not found on the datasheet.",
        "Inlet rating is not shown.",
        "Inlet rating is not listed.",
        "Inlet rating does not appear.",
        "Inlet rating is not present.",
        "There is no inlet rating on the sheet.",
        "Inlet rating was left out.",
        "Inlet rating is not entered.",
        "The datasheet doesn't state the inlet rating.",
        "The datasheet gives no inlet rating.",
        "Inlet rating is not indicated.",
        "Inlet rating is not mentioned.",
        # s3's residual three, and the neighbours with no "not" in them
        "There is an absence of an inlet rating.",
        "The datasheet is silent on the inlet rating.",
        "The inlet rating is wanting from the datasheet.",
    ],
)
def test_every_listed_absence_phrase_is_refused_against_a_no_label_template(text):
    assert crs_wording.lock(text, ROW_11) == crs_wording.ABSENCE_ADDED


def test_an_absence_the_template_itself_states_may_be_kept():
    row = {**MISSING_ROW, "comment": "Design pressure is missing from the sheet."}
    text = "Design pressure is missing from the sheet; please add it."
    assert crs_wording.lock(text, row) is None


def test_a_rewrite_that_keeps_the_templates_own_negated_words_is_kept():
    kept = (
        "Inlet rating was not read as a value, and no label for it was found in the text of "
        "pages 1-4; the contractor is to provide it."
    )
    assert crs_wording.lock(kept, ROW_11) is None
    moved = (
        "The contractor is to provide the inlet rating, which was not read as a value."
    )
    assert crs_wording.lock(moved, ROW_11) is None


@pytest.mark.parametrize(
    "text",
    [
        "The reader was unable to find the inlet rating.",
        "The inlet rating fails to appear.",
    ],
)
def test_other_absence_wordings_are_refused_whichever_check_catches_them_first(text):
    # the new-words check may refuse these before the absence check does; either way the template stays
    assert crs_wording.lock(text, ROW_11) in (
        crs_wording.ABSENCE_ADDED,
        crs_wording.CLAIM_ADDED,
    )
