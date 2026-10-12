"""Round-2 figure checker (audit N4): units, signs, rounding and polarity.

Invented names only. Mutations: scripts/mutations/r2_numbers.py (M1990-M1999).
"""

from __future__ import annotations

from app import answer

PAGE_VIBRATION = ("Machine STD-A-001 vibration limit is 3.0 mm/s at the bearing housing. "
                  "Ambient range is -29 to 343 C.")


def _grounded(sentence: str, page: str) -> bool:
    clean, removed = answer.ground_numbers(sentence, [{"text": page}])
    return not removed and bool(clean)


# ------------------------------------------------------------ units
def test_a_number_from_another_unit_does_not_ground_a_unit_figure():
    # 343 is on the page - as a temperature. It is not a velocity.
    assert not _grounded("The vibration limit is 343 mm/s [S1].", PAGE_VIBRATION)


def test_the_right_unit_still_grounds():
    assert _grounded("The vibration limit is 3.0 mm/s [S1].", PAGE_VIBRATION)


def test_the_wrong_unit_for_the_same_number_is_refused():
    page = "The peak velocity shall not exceed 4.5 mm/s."
    assert not _grounded("The peak velocity is 4.5 in/s [S1].", page)
    assert _grounded("The peak velocity is 4.5 mm/s [S1].", page)


def test_equivalent_spellings_of_one_unit_ground():
    assert _grounded("The velocity is 3.0 mm/sec [S1].", "The velocity is 3.0 mm/s.")
    assert _grounded("The noise is 85 dBA [S1].", "The noise is 85 dB(A).")


def test_a_dual_unit_page_grounds_each_figure_only_to_its_own_unit():
    page = "The velocity is 114.3 mm/s (4.5 in/s)."
    assert _grounded("The velocity is 4.5 in/s [S1].", page)
    assert not _grounded("The velocity is 4.5 mm/s [S1].", page)


def test_only_a_correct_conversion_grounds():
    """#653 (owner order: "16 psi matches 110 kPa"): the same quantity in
    another unit of the same kind is the same figure - so 0.28 mm over a
    page saying 280 um is grounded. A WRONG conversion is still caught, at
    the sentence's own printed precision: 0.30 mm is 300 um, not 280."""
    assert _grounded("The thickness is 0.28 mm [S1].", "The coat is 280 um thick.")
    assert not _grounded("The thickness is 0.30 mm [S1].", "The coat is 280 um thick.")


def test_a_table_cell_with_the_unit_in_another_column_still_grounds():
    assert _grounded("The limit is 3.0 mm/s [S1].", "Vibration | 3.0 | Table 4")


def test_gauge_suffix_does_not_break_a_pressure_figure():
    assert _grounded("The pressure is 10 bar [S1].", "The design pressure is 10 barg.")


def test_unit_less_figures_keep_the_old_behaviour():
    assert _grounded("The limit is 3.0 [S1].", "Limit 3.0 mm/s")
    clean, removed = answer.ground_numbers("The limit is 9.0 [S1].", [{"text": "Limit 3.0 mm/s"}])
    assert removed


# ------------------------------------------------------------ sign
def test_a_dropped_minus_does_not_ground():
    page = "Ambient range is -29 to 343 C."
    assert not _grounded("The range is 29 to 343 C [S1].", page)
    assert _grounded("The range is -29 to 343 C [S1].", page)


def test_a_unicode_minus_on_the_page_counts_as_a_minus():
    page = "Ambient range is −29 to 343 C."
    assert not _grounded("The range is 29 to 343 C [S1].", page)
    assert _grounded("The range is -29 to 343 C [S1].", page)


def test_an_invented_minus_does_not_ground():
    assert not _grounded("The minimum is -5 C [S1].", "The minimum is 5 C.")


def test_a_hyphenated_range_is_not_read_as_a_sign():
    assert _grounded("Use 5 to 10 mm [S1].", "Use 5-10 mm.")
    assert _grounded("Tolerance 0.5 mm [S1].", "Tolerance +/-0.5 mm.")


# ------------------------------------------------------------ rounding
def test_ordinary_rounding_is_still_accepted_with_the_same_unit():
    assert _grounded("The gap is 2 mm [S1].", "The gap is 1.5 mm.")       # half up
    assert _grounded("The gap is 3 mm [S1].", "The gap is 3.4 mm.")       # nearest
    assert _grounded("The pressure is 17.2 barg [S1].", "The pressure is 17.24 barg.")


def test_rounding_the_wrong_way_or_to_more_precision_is_refused():
    assert not _grounded("The gap is 2 mm [S1].", "The gap is 1.4 mm.")
    assert not _grounded("The gap is 4 mm [S1].", "The gap is 3.4 mm.")
    assert not _grounded("The pressure is 17.4 barg [S1].", "The pressure is 17.24 barg.")


def test_rounding_does_not_cross_units():
    assert not _grounded("The speed is 3 mm/s [S1].", "The gap is 3.4 mm.")


# ------------------------------------------------------------ polarity
def _verified(sentence: str, page: str) -> int:
    clean, verification, _claims, removed = answer.verify_claims(sentence, [{"text": page}])
    return verification["verified"]


def test_shall_exceed_does_not_verify_against_shall_not_exceed():
    page = "The vibration velocity shall not exceed 3.0 mm/s at any bearing."
    quote = "shall not exceed 3.0 mm/s"
    assert _verified(f'The vibration velocity shall exceed 3.0 mm/s [S1 "{quote}"].', page) == 0
    assert _verified(f'The vibration velocity shall not exceed 3.0 mm/s [S1 "{quote}"].', page) == 1


def test_shall_be_used_does_not_verify_against_shall_not_be_used():
    page = "Galvanised fasteners shall not be used in the wet seal zone."
    quote = "shall not be used in the wet seal zone"
    assert _verified(f'Galvanised fasteners shall be used in the wet seal zone [S1 "{quote}"].', page) == 0
    assert _verified(f'Galvanised fasteners shall not be used in the wet seal zone [S1 "{quote}"].', page) == 1


def test_no_more_than_is_the_negated_exceed():
    page = "The skid noise level is no more than 85 dB(A) at one metre."
    quote = "no more than 85 dB(A) at one metre"
    assert _verified(f'The skid noise shall exceed 85 dB(A) at one metre [S1 "{quote}"].', page) == 0


def test_a_sentence_with_no_polarity_words_is_unchanged():
    page = "The vibration velocity limit is 3.0 mm/s at any bearing."
    quote = "limit is 3.0 mm/s at any bearing"
    assert _verified(f'The limit is 3.0 mm/s at any bearing [S1 "{quote}"].', page) == 1


def test_both_polarities_on_the_page_is_not_a_contradiction():
    assert answer.polarity_conflict("The load shall exceed 5 kN.",
                                    "The load shall exceed 5 kN. Elsewhere it shall not exceed 9 kN.") is None
