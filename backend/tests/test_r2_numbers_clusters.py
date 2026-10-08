"""Round-2 N7: two different limits are not agreement; one dual-unit value
printed twice is not a conflict. Invented names only."""

from __future__ import annotations

from app import claims


def _row(sentence: str, n: int) -> claims.Claim:
    return claims.Claim(f"e{n}", "STD-A-001.pdf", 1, None, sentence, (), (),
                        claims.extract_measurements(sentence), frozenset({"vibration"}))


def _label(*sentences: str) -> str:
    return claims.label_cluster([_row(s, i) for i, s in enumerate(sentences)])[0]


def test_two_different_upper_limits_are_a_possible_conflict():
    assert _label("Vibration shall not exceed 3.0 mm/s.",
                  "Vibration shall not exceed 4.5 mm/s.") == "possible_conflict"


def test_two_different_lower_limits_are_a_possible_conflict():
    assert _label("Vibration shall be at least 3.0 mm/s.",
                  "Vibration shall be at least 4.5 mm/s.") == "possible_conflict"


def test_identical_upper_limits_are_agreement():
    assert _label("Vibration shall not exceed 3.0 mm/s.",
                  "Vibration shall not exceed 3.0 mm/s.") == "agreement"


def test_a_min_and_a_max_in_one_row_are_not_two_limits_in_conflict():
    assert _label("Vibration min 3.0 mm/s and max 4.5 mm/s.",
                  "Vibration max 4.5 mm/s.") == "agreement"


def test_dual_unit_value_printed_twice_is_not_a_conflict():
    sentence = "Test pressure is 1,000 psi (6.89 MPa)."
    assert _label(sentence, sentence) == "agreement"


def test_dual_unit_values_that_really_differ_are_a_conflict():
    assert _label("Test pressure is 1,000 psi (6.89 MPa).",
                  "Test pressure is 1,200 psi (8.27 MPa).") == "possible_conflict"


def test_same_unit_values_that_differ_by_a_last_digit_are_still_a_conflict():
    # the printed-precision tolerance is for a conversion between units only
    assert _label("Vibration is 3.0 mm/s.", "Vibration is 3.1 mm/s.") == "possible_conflict"
