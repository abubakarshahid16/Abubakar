"""figure_compare (Part of #805, step 3): one figure against one clause figure, by code. All values here are INVENTED."""

import pytest

from app import figure_compare as fc


def verdict(document, clause):
    result = fc.compare(document, clause)
    assert result is not None
    return result.verdict


@pytest.mark.parametrize(
    "document, clause, expected",
    [
        # the negated forms: both directions of each
        ("15 bar", "not more than 10 bar", False),
        ("8 bar", "not more than 10 bar", True),
        ("15 bar", "not higher than 10 bar", False),
        ("8 bar", "not higher than 10 bar", True),
        ("15 bar", "shall not exceed 10 bar", False),
        ("8 bar", "shall not exceed 10 bar", True),
        ("8 bar", "not less than 10 bar", False),
        ("12 bar", "not less than 10 bar", True),
        ("8 bar", "shall not be less than 10 bar", False),
        ("12 bar", "shall not be less than 10 bar", True),
        ("12 bar", "at least 10 bar", True),
        ("12 bar", "at most 10 bar", False),
        ("12 bar", "no more than 10 bar", False),
        # units are converted, decimal commas are read
        ("12 bar", "not more than 1,5 MPa", True),
        ("20 bar", "not more than 1,5 MPa", False),
        ("200 kPa", "at least 1 bar", True),
        ("340 psi", "not more than 25 bar", True),
    ],
)
def test_the_code_decides_the_direction_and_the_units(document, clause, expected):
    assert verdict(document, clause) is expected


@pytest.mark.parametrize(
    "document, clause",
    [
        ("5 to 15 bar", "not more than 10 bar"),  # a range
        ("10 bar +/- 2 bar", "at least 8 bar"),  # a tolerance
        ("max 10 bar", "not more than 12 bar"),  # a limit printed, not a value
        ("Pressure 12 bar, TBA", "at least 10 bar"),  # a placeholder
        ("12 bar by contractor", "at least 10 bar"),
        ("not 12 bar", "at least 10 bar"),  # a negation
        ("n/a 12", "at least 10 bar"),
        ("10 bar", "shall be less than 10 bar"),  # equal to a strict limit
        ("10 bar", "shall be greater than 10 bar"),
        ("12 bar", "exceeding 10 bar is prohibited"),  # no readable comparator
        ("12 bar", "the design pressure is 10 bar"),  # a figure with no comparator at all
        ("12 bar", "shall be at least 10 bar and not more than 20 bar"),  # two figures
        ("12 m", "at least 10 bar"),  # not the same kind of quantity
        ("12 barg", "at least 10 bara"),  # gauge against absolute
        ("12 bar and 14 bar", "at least 10 bar"),  # several figures
    ],
)
def test_what_cannot_be_compared_is_not_decided(document, clause):
    result = fc.compare(document, clause)
    assert result is not None
    assert result.verdict is None
    assert result.reason


def test_a_clause_that_asks_no_figure_returns_none():
    assert fc.compare("ASTM A216 WCB", "The body material shall be stated.") is None


def test_the_models_own_figures_are_not_an_input():
    # only the two quotes are read: there is no parameter for a value, a limit or a relation.
    import inspect

    assert list(inspect.signature(fc.compare).parameters) == [
        "document_quote",
        "clause_quote",
    ]


# --- #1689 review: anything the code cannot read with certainty is "cannot decide" (invented text) ---
def _undecided(document, clause):
    result = fc.compare(document, clause)
    assert result is not None
    assert result.verdict is None, (document, clause)


@pytest.mark.parametrize(
    "document, clause",
    [
        ("12 bar(g)", "at least 10 bar(a)"),
        ("12 bar g", "at least 10 bar"),
        ("12 bar abs", "at least 10 bar(g)"),
        ("12 bar", "at least 10 bar gauge"),
        ("12 psig", "at least 10 psia"),
    ],
)
def test_defect1_a_stated_pressure_reference_that_differs_is_not_decided(document, clause):
    _undecided(document, clause)


def test_defect1_the_same_stated_reference_still_decides():
    assert verdict("12 bar(g)", "at least 10 bar(g)") is True
    assert verdict("12 bar abs", "at least 10 bar(a)") is True


@pytest.mark.parametrize(
    "document, clause",
    [
        ("5 bar", "less than 10 bar is not acceptable"),
        ("12 bar", "pressure below 10 bar is not permitted"),
        ("12 bar", "not more than 10 bar, which is forbidden"),
    ],
)
def test_defect2_a_negation_after_the_figure_is_not_decided(document, clause):
    _undecided(document, clause)


def test_defect2_a_plain_negated_comparator_still_decides():
    assert verdict("8 bar", "shall not exceed 10 bar") is True
    assert verdict("12 bar", "shall not be less than 10 bar") is True


@pytest.mark.parametrize(
    "document, clause",
    [
        ("1.500 bar", "not more than 2 bar"),
        ("1,500 bar", "not more than 2 bar"),
        ("2 bar", "at least 1.000 bar"),
        ("3 bar", "at least 1,000 bar"),
    ],
)
def test_defect3_an_ambiguous_thousands_separator_is_not_decided(document, clause):
    _undecided(document, clause)


def test_defect3_a_clear_decimal_still_decides():
    assert verdict("12,5 bar", "at least 10 bar") is True
    assert verdict("12 bar", "at least 0.5 bar") is True


@pytest.mark.parametrize(
    "document, clause",
    [
        ("10 bar min", "at least 8 bar"),
        ("10 % max", "at least 8 %"),
        ("approx 10 bar", "at least 8 bar"),
        ("~10 bar", "at least 8 bar"),
        ("10 bar typical", "at least 8 bar"),
        ("nominal 10 bar", "at least 8 bar"),
    ],
)
def test_defect4_a_qualifier_on_the_document_figure_is_not_decided(document, clause):
    _undecided(document, clause)


def test_defect4_a_plain_document_figure_still_decides():
    assert verdict("10 bar", "at least 8 bar") is True
    assert verdict("10 %", "at least 12 %") is False


@pytest.mark.parametrize(
    "document, clause",
    [
        ("12 bar", "at least 10 bar or as agreed"),
        ("12 bar", "at least 10 bar except for vents"),
        ("12 bar", "at least 10 bar unless the owner agrees"),
        ("12 bar", "for design pressure above 10 bar, class 300 is required"),
        ("12 bar", "where the line is hot, at least 10 bar"),
        ("12 bar", "at least 10 bar if the fluid is gas"),
    ],
)
def test_defect5_an_exception_or_a_condition_is_not_decided(document, clause):
    _undecided(document, clause)


def test_defect5_a_plain_requirement_still_decides():
    assert verdict("12 bar", "design pressure shall be at least 10 bar") is True


@pytest.mark.parametrize(
    "document, clause",
    [
        ("12 bar", "at least 10 bar not more than 10 bar"),
        ("12 bar", "minimum 10 bar, maximum 10 bar"),
        ("12 bar", "not less than 10 bar and not more than 10 bar"),
    ],
)
def test_defect6_two_directions_are_not_decided(document, clause):
    _undecided(document, clause)


def test_defect6_one_direction_with_two_units_still_decides():
    assert verdict("12 bar", "at least 10 bar") is True
    assert verdict("12 bar", "not more than 10 bar") is False


@pytest.mark.parametrize(
    "document, clause",
    [
        ("50 degC", "at most 100 K"),  # temperature offset units
        ("50 degC", "at most 100 degF"),
        ("5 %", "at least 3 ppm"),  # percent against absolute
        ("5 m3/h", "at least 3 m3/day"),  # per hour against per day
        ("5 m3/h", "at least 3 m3"),
    ],
)
def test_wider_class_unlike_units_never_give_a_pass_or_a_fail(document, clause):
    result = fc.compare(document, clause)
    assert result is None or result.verdict is None
