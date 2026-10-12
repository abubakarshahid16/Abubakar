"""#653: the figure check compares number AND unit, for any standard.

Live, 2026-10-09, local model: the cited page printed a worked example as a
row label - "Allowable overpressure, psi (kPa) 11.0 (76)" - and the model
wrote "up to 11%". The unit was the label's, written BEFORE the number, so
the page figure looked bare, and a bare page figure grounds any claim. The
sentence passed as the document's.

Now (`answer.ground_numbers` -> `answer.figure_check`, the one check every
lane uses):
  * a label's unit before its number binds to it ("psi (kPa) 11.0 (76)");
  * % never matches psi, kPa or bar; gauge never matches absolute;
  * the same quantity in another unit of the same kind matches when the
    conversion agrees at the sentence's printed precision (16 psi = 110 kPa);
  * a sentence whose number matches but whose unit does not is removed with
    the reason "unit does not match the source";
  * a bare number on both sides keeps the old behaviour.

Invented text only. Mutations M4001-M4012.
"""
from __future__ import annotations

import pytest

from app import answer, synthesis


def _check(source: str, said: str) -> tuple[str, list[dict]]:
    return answer.ground_numbers(said, [{"text": source}])


# ------------------------------------------------- the five cases of #653

def test_psi_on_the_page_read_as_percent_is_removed_as_a_unit_mismatch():
    clean, removed = _check("The allowable overpressure is 11.0 psi.",
                            "Devices may go up to 11% [S1].")
    assert clean == ""
    assert removed == [{"value": "11", "cited": [1], "reason": answer.UNIT_MISMATCH}]


def test_percent_of_mawp_against_percent_of_mawp_is_kept():
    said = "The relieving pressure is 110% of MAWP [S1]."
    assert _check("Accumulation is limited to 110 % of MAWP.", said) == (said, [])


def test_the_same_quantity_in_its_bracketed_unit_is_kept():
    said = "The overpressure is 110 kPa [S1]."
    assert _check("The overpressure is 16.0 psi (110 kPa).", said) == (said, [])


def test_gauge_read_as_absolute_is_removed():
    clean, removed = _check("The test pressure is 100 psig.", "Test at 100 psia [S1].")
    assert clean == "" and removed[0]["reason"] == answer.UNIT_MISMATCH


def test_bare_numbers_on_both_sides_keep_the_old_behaviour():
    assert _check("Use 5 bolts per joint, Table 5.", "Use 5 [S1].") == ("Use 5 [S1].", [])
    clean, removed = _check("Use 5 bolts.", "Use 7 [S1].")
    assert clean == "" and removed[0]["reason"] == answer.FIGURE_MISSING


# ------------------------------------------------- the live shape

LABELLED = ("Allowable overpressure, psi (kPa) 11.0 (76) "
            "Barometric pressure, psia (kPa) 14.7 (101)")


def test_a_label_unit_written_before_the_number_binds_to_it():
    figures = [(f["value"], f["unit"]) for f in answer._figure_occurrences(LABELLED)]
    assert ("11.0", "psi") in figures and ("76.0", "kpa") in figures
    assert ("14.7", "psia") in figures


def test_the_live_case_percent_over_a_labelled_psi_row_is_removed():
    """THE DEFECT: passed before, because 11.0 looked bare."""
    clean, removed = _check(LABELLED, "Up to 11% for additional devices [S1].")
    assert clean == "" and removed[0]["reason"] == answer.UNIT_MISMATCH


def test_the_labelled_row_still_grounds_its_own_units():
    for said in ("The allowable overpressure is 11.0 psi [S1].",
                 "The allowable overpressure is 76 kPa [S1]."):
        assert _check(LABELLED, said) == (said, [])


def test_a_short_english_word_before_a_number_is_not_a_unit():
    """"in 5 minutes": "in" is a unit spelling and an English word."""
    assert [f["unit"] for f in answer._figure_occurrences("Close the valve, in 5")] == [None]


# ------------------------------------------------- conversion

def test_a_correct_conversion_to_another_unit_is_kept():
    said = "The overpressure is 16 psi [S1]."
    assert _check("The overpressure is 110 kPa.", said) == (said, [])


@pytest.mark.parametrize("said", [
    "The overpressure is 17 psi [S1].",       # 117 kPa, not 110
    "The overpressure is 16 % [S1].",         # another kind of quantity
    "The thickness is 0.30 mm [S1].",          # 300 um, at its printed precision
])
def test_a_wrong_conversion_or_another_quantity_is_removed(said):
    source = "The overpressure is 110 kPa. The coat is 280 um thick."
    clean, removed = _check(source, said)
    assert clean == "", removed


def test_thousands_separators_are_not_printed_decimals():
    places = {f["value"]: f["places"] for f in answer._figure_occurrences(
        "0.30 mm, 3,300 kg, 1,5 bar")}
    assert places == {"0.3": 2, "3300.0": 0, "1.5": 1}


# ------------------------------------------------- the reason, shown

def test_the_notice_names_a_unit_mismatch_apart_from_a_missing_figure():
    notices = answer._numbers_notice([
        {"value": "11", "cited": [1], "reason": answer.UNIT_MISMATCH},
        {"value": "9", "cited": [1], "reason": answer.FIGURE_MISSING}])
    assert notices == [
        "1 sentence removed: a figure in it was not in the passage it cited.",
        "1 sentence removed: the unit does not match the source."]


def test_the_claude_lane_records_the_unit_reason_for_the_removed_point():
    dropped: list[dict] = []
    text, verification, _claims, _removed = answer.verify_claims(
        'Devices may go up to 11% [S1 "allowable overpressure is 11.0 psi"].',
        [{"text": "The allowable overpressure is 11.0 psi."}], dropped=dropped)
    assert verification["verified"] == 0
    assert [d["why"] for d in dropped] == ["unit does not match the source"]


# ------------------------------------------------- one check, every lane

def test_the_summary_lane_uses_the_same_unit_check():
    """`synthesis` kept its own copy, which did not know gauge from absolute."""
    assert synthesis.first_unit_conflict("Test at 100 psia.", "Test at 100 psig.") == "100 psia"
    kept, dropped = synthesis._cite("Test at 100 psia [S1].",
                                    [{"evidence_id": "e1", "text": "Test at 100 psig."}])
    assert kept == () and "with that unit" in dropped[0][1]


def test_the_summary_lane_accepts_the_same_conversion():
    kept, _dropped = synthesis._cite("The overpressure is 16 psi [S1].",
                                     [{"evidence_id": "e1", "text": "The overpressure is 110 kPa."}])
    assert len(kept) == 1
