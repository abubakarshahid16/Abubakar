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
        (
            "12 bar",
            "the design pressure is 10 bar",
        ),  # a figure with no comparator at all
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
def test_defect1_a_stated_pressure_reference_that_differs_is_not_decided(
    document, clause
):
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


# --- #1689 second review: a whitelist. The figure decides only when nothing unread stands beside it (invented text) ---
@pytest.mark.parametrize(
    "document, clause",
    [
        ("10 bar-g", "not more than 12 bar-a"),
        ("10 bar", "not exceed 12 bar_g"),
        ("10 bar", "not more than 12 bar-g"),
        ("10 bar_a", "not more than 12 bar"),
        ("10 bar-a", "at least 8 bar-g"),
        ("10 bar.g", "at least 8 bar"),
        ("10 bar/g", "at least 8 bar"),
        ("10 psi-g", "not more than 100 psi"),
        ("10 kPa_a", "not more than 100 kPa"),
        ("10 barx", "not more than 12 bar"),
        ("10 bar", "not more than 12 bar-"),
        ("10 bar", "not more than 12 bar:g"),
    ],
)
def test_a_glued_or_joined_suffix_on_the_unit_is_not_decided(document, clause):
    _undecided(document, clause)


@pytest.mark.parametrize(
    "document, clause",
    [
        ("minus 40 degC", "not less than -30 degC"),
        ("minus 40 degC", "not more than -30 degC"),
        ("negative 5 mm", "at least 1 mm"),
        ("plus 40 degC", "not more than 50 degC"),
        ("40 degC below zero", "not less than -30 degC"),
        ("10 mm", "at least minus 5 mm"),
        ("10 mm", "at least negative 5 mm"),
        ("sub-zero 10 degC", "not more than 20 degC"),
        ("Minus 3 bar", "at least 1 bar"),
        ("10 mm", "not more than plus 20 mm"),
    ],
)
def test_a_sign_written_in_words_is_not_decided(document, clause):
    _undecided(document, clause)


@pytest.mark.parametrize(
    "document, clause",
    [
        ("10 bar*", "not more than 12 bar"),
        ("10 bar¹", "not more than 12 bar"),
        ("10 bar²", "at least 8 bar"),
        ("10 bar (1)", "at least 8 bar"),
        ("10 bar [2]", "at least 8 bar"),
        ("10 bar †", "at least 8 bar"),
        ("10 bar #", "at least 8 bar"),
        ("10 bar a)", "at least 8 bar"),
        ("10 bar, see note", "at least 8 bar"),
        ("10 bar at inlet", "at least 8 bar"),
        ("10 bar **", "at least 8 bar"),
        ("10 bar /", "at least 8 bar"),
    ],
)
def test_a_mark_or_word_after_the_document_figure_is_not_decided(document, clause):
    _undecided(document, clause)


@pytest.mark.parametrize(
    "clause",
    [
        "at least 8 bar excl. vents",
        "at least 8 bar save for vents",
        "at least 8 bar in winter",
        "at least 8 bar during start-up",
        "at least 8 bar upon owner approval",
        "at least 8 bar whichever is less",
        "at least 8 bar or the vendor rating",
        "at least 8 bar, vents excluded",
        "at least 8 bar. Vents are excluded.",
        "at least 8 bar on site",
        "at least 8 bar for pumps",
        "at least 8 bar after commissioning",
        "at least 8 bar as per the data sheet",
        "at least 8 bar (see note 3)",
        "at least 8 bar at the discharge flange",
    ],
)
def test_text_after_the_clause_figure_is_not_decided(clause):
    _undecided("10 bar", clause)


def test_the_plain_clear_cases_still_decide():
    assert verdict("12 bar", "shall be at least 10 bar") is True
    assert verdict("8 bar", "not more than 10 bar.") is True
    assert verdict("8 bar", "not less than 10 bar") is False
    assert verdict("8 bar", "maximum 10 bar") is True
    assert verdict("12 bar", "minimum 10 bar") is True
    assert verdict("12 bar.", "at least 10 bar or more") is True
    assert verdict("-20 degC", "not less than -30 degC") is True


@pytest.mark.parametrize(
    "clause",
    [
        "Class 300, at least 8 bar",
        "For pumps; at least 8 bar",
        "Pumps, valves, strainers and the other equipment listed in the schedule shall have a rated pressure of at least 8 bar",
    ],
)
def test_a_split_or_long_lead_in_before_the_clause_figure_is_not_decided(clause):
    _undecided("10 bar", clause)


@pytest.mark.parametrize(
    "clause",
    [
        "pressure unacceptable below 10 bar",
        "never allowed to be below 10 bar",
        "pressure shall not be allowed below 10 bar",
    ],
)
def test_defect2_a_negation_before_the_figure_with_a_clean_tail_is_not_decided(clause):
    _undecided("12 bar", clause)


@pytest.mark.parametrize(
    "clause",
    [
        "when hot at least 10 bar",
        "unless agreed at least 10 bar",
        "for pressures above 10 bar",
        "with flow below 10 bar",
    ],
)
def test_defect5_an_exception_or_condition_before_the_figure_with_a_clean_tail_is_not_decided(
    clause,
):
    _undecided("12 bar", clause)
