"""figure_compare (Part of #805, step 3): one figure against one clause figure, by code. All values here are INVENTED."""

import re

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
    assert verdict("20 degC", "not less than 30 degC") is False


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


# --- #1689 third review: the figure must be one clean token; qualifiers are checked on the clause too ---
@pytest.mark.parametrize(
    "document, clause",
    [
        ("8 bar", "at least 1 000 kPa"),
        ("8 bar", "at least 1\u00a0000 kPa"),
        ("8 bar", "at least 1\u202f000 kPa"),
        ("8 bar", "at least 1\u2009000 kPa"),
        ("8 bar", "at least 1'000 kPa"),
        ("8 bar", "at least 1\u2019000 kPa"),
        ("8 bar", "at least 2 500 kPa"),
        ("1 000 kPa", "at least 8 bar"),
        ("1'000 kPa", "not more than 8 bar"),
        ("8 bar", "at least 10 000 kPa"),
        ("12 bar", "at least 3.5 10 bar"),
        ("12 bar", "Class 300 12 bar is the minimum, at least 10 bar"),
    ],
)
def test_a_digit_group_beside_the_figure_is_not_decided(document, clause):
    _undecided(document, clause)


@pytest.mark.parametrize(
    "document, clause",
    [
        ("52 degC", "shall not exceed ambient +10 degC"),
        ("52 degC", "shall not exceed ambient + 10 degC"),
        ("52 degC", "not more than +10 degC"),
        ("-20 degC", "not less than -30 degC"),
        ("20 degC", "not less than -30 degC"),
        ("20 degC", "not less than \u221230 degC"),
        ("20 degC", "not less than \u201330 degC"),
        ("+20 degC", "not less than 30 degC"),
        ("20 degC", "at least \u00b110 degC"),
        ("12 bar", "at least - 10 bar"),
        ("5 mm", "at least ambient -2 mm"),
    ],
)
def test_a_sign_character_beside_the_figure_is_not_decided(document, clause):
    _undecided(document, clause)


@pytest.mark.parametrize(
    "clause",
    [
        "at least approx. 10 bar",
        "at least ca. 10 bar",
        "at least circa 10 bar",
        "at least approximately 10 bar",
        "at least about 10 bar",
        "at least ~10 bar",
        "at least \u224810 bar",
        "at least nominal 10 bar",
        "at least typically 10 bar",
        "at least 10 bar nominal",
        "at least around 10 bar",
        "at least abt 10 bar",
    ],
)
def test_an_approximation_word_on_the_clause_figure_is_not_decided(clause):
    _undecided("12 bar", clause)


@pytest.mark.parametrize(
    "document, clause",
    [
        ("12 bar", "at least 10 bar or less required"),
        ("12 bar", "at least 10 bar or more or less"),
        ("12 bar", "not more than 10 bar or more"),
        ("10 Mm", "at least 8 mm"),
        ("10 MM", "at least 8 mm"),
        ("10 mm", "at least 8 Mm"),
        ("10 mpa", "at least 8 bar"),
        ("12 bar. A", "at least 10 bar"),
        ("12 bar. g", "at least 10 bar"),
        ("12 %. absolute", "at least 10 %"),
        ("12 % absolute", "at least 10 %"),
    ],
)
def test_the_low_severity_leaks_are_not_decided(document, clause):
    _undecided(document, clause)


def test_the_third_review_positive_controls_still_decide():
    assert verdict("12 bar", "shall be at least 10 bar") is True
    assert verdict("12 bar", "at least 10 bar or more") is True
    assert verdict("8 bar", "maximum 10 bar") is True
    assert verdict("1,5 MPa", "not more than 20 bar") is True
    assert verdict("10 mm", "at least 8 mm") is True


_FUZZ_PAIRS = [
    ("12 bar", "shall be at least 10 bar", True),
    ("8 bar", "shall be at least 10 bar", False),
    ("12 bar", "pressure shall not exceed 10 bar", False),
    ("8 bar", "pressure shall not exceed 10 bar", True),
    ("40 degC", "temperature not less than 30 degC", True),
    ("20 mm", "thickness not less than 25 mm", False),
    ("5 mm", "maximum 8 mm", True),
    ("12 %", "at most 10 %", False),
]
_FUZZ_NOISE = [
    "approx", "approx.", "ca.", "circa", "about", "min", "max", "typical", "nominal", "~", "\u2248", "\u00b1",
    "+", "-", "\u2212", "\u2013", "plus", "minus", "negative", "+10", "-5", "1", "000", "1000", ",", ".", "'",
    "\u00a0", "\u202f", "\u2009", "*", "\u00b9", "\u00b2", "\u2020", "(1)", "[2]", "(see note)", "(g)", "(a)",
    "g", "a", "abs", "gauge", "unless", "except", "or", "and", "if", "when", "where", "not", "no", "less", "more",
    "than", "or less", "or more", "at", "for", "per", "each", "excl.", "save", "in winter", "000 kPa",
    "x", "\u00d7", "^", "2 x", "10^2", "2*10", "during 3 cycles", "for Class 150", "In sour service", "with 3 bearings", "on 3 pumps",
    "two", "twice", "double", "half", "should", "preferably", "c.", "recommended", "normally", "may", "typically", "up to",
]  # fmt: skip


def _numbers(text):
    return re.findall(r"\d+(?:[.,]\d+)?", text)


def _fuzz_variants(sentence):
    """Every sentence made by putting one noise token at a token boundary within two tokens of the figure, in three ways.
    Not noise, so not produced: a number changed by gluing digits into it, a word glued into another word."""
    tokens = sentence.split(" ")
    first = next(i for i, t in enumerate(tokens) if any(c.isdigit() for c in t))
    original = _numbers(sentence)
    for i in range(max(0, first - 2), min(len(tokens), first + 1 + 3) + 1):
        for noise in _FUZZ_NOISE:
            made = [" ".join([*tokens[:i], noise, *tokens[i:]])]  # a token of its own
            if not noise[0].isalnum():
                if i > 0:  # glued to the token before
                    made.append(
                        " ".join([*tokens[: i - 1], tokens[i - 1] + noise, *tokens[i:]])
                    )
                if i < len(tokens):  # glued in front of the token after
                    made.append(
                        " ".join([*tokens[:i], noise + tokens[i], *tokens[i + 1 :]])
                    )
            for text in made:
                found = _numbers(text)
                if all(found.count(n) >= original.count(n) for n in set(original)):
                    yield text


def test_fuzz_noise_beside_the_figure_never_gives_the_opposite_verdict():
    wrong = []
    for document, clause, expected in _FUZZ_PAIRS:
        assert verdict(document, clause) is expected
        for noisy in _fuzz_variants(document):
            result = fc.compare(noisy, clause)
            if result is not None and result.verdict not in (None, expected):
                wrong.append((noisy, clause))
        for noisy in _fuzz_variants(clause):
            result = fc.compare(document, noisy)
            if result is not None and result.verdict not in (None, expected):
                wrong.append((document, noisy))
    assert not wrong, wrong[:20]


# --- #1689 fourth review: one number, a plain lead-in, no advisory words (invented text) ---
@pytest.mark.parametrize(
    "clause",
    [
        "at most 10^2 bar",
        "at most 2 x 10 bar",
        "at most 2 \u00d7 10 bar",
        "at most 2*10 bar",
        "at most 2 ** 10 bar",
        "at most 10\u00b2 bar",
        "at most two times 10 bar",
        "at most twice 10 bar",
        "at most half of 10 bar",
        "at most double 10 bar",
        "at most 5 x 10 bar",
        "at least 3 x 4 bar",
    ],
)
def test_a_power_or_a_product_in_the_clause_is_not_decided(clause):
    result = fc.compare(
        "12 bar", clause
    )  # None: the clause shows no readable figure at all
    assert result is None or result.verdict is None


@pytest.mark.parametrize(
    "clause",
    [
        "not exceed 10 bar during 3 cycles",
        "not exceed 10 bar for the first 3 years",
        "not exceed 10 bar on 3 pumps",
        "not exceed 10 bar with 3 bearings",
        "not exceed 10 bar after 2 hours",
        "not exceed 10 bar in 3 stages",
        "not exceed 10 bar for ten years",
        "not exceed 10 bar at 2 sites",
        "at least 10 bar per 3 units",
        "at least 10 bar over 5 days",
    ],
)
def test_a_second_number_in_the_clause_tail_is_not_decided(clause):
    _undecided("8 bar", clause)


@pytest.mark.parametrize(
    "clause",
    [
        "For Class 150 flanges pressure shall not exceed 10 bar",
        "In sour service pressure shall not exceed 10 bar",
        "Class 150: pressure shall not exceed 10 bar",
        "For flanges pressure shall not exceed 10 bar",
        "In sour service pressure shall not exceed 10 bar",
        "During start-up pressure shall not exceed 10 bar",
        "Under test pressure shall not exceed 10 bar",
        "With the lid closed pressure shall not exceed 10 bar",
        "After cooling the pressure shall not exceed 10 bar",
        "Where fitted the pressure shall not exceed 10 bar",
        "Per the data sheet the pressure shall not exceed 10 bar",
        "The pressure of the line to the north pump house inlet shall not exceed 10 bar",
    ],
)
def test_a_condition_or_long_lead_in_without_a_comma_is_not_decided(clause):
    _undecided("12 bar", clause)


@pytest.mark.parametrize(
    "document, clause",
    [
        ("c. 8 bar", "at least 5 bar"),
        ("12 bar", "should preferably not exceed 10 bar"),
        ("12 bar", "pressure should not exceed 10 bar"),
        ("12 bar", "pressure may not exceed 10 bar"),
        ("12 bar", "pressure is recommended to be at least 10 bar"),
        ("12 bar", "pressure normally at least 10 bar"),
        ("12 bar", "pressure is typically at least 10 bar"),
        ("12 bar", "pressure ideally at least 10 bar"),
        ("12 bar", "pressure up to 10 bar"),
        ("typically 12 bar", "at least 10 bar"),
        ("12 bar, recommended", "at least 10 bar"),
        ("about 12 bar", "at least 10 bar"),
    ],
)
def test_advisory_and_hedge_words_are_not_decided(document, clause):
    _undecided(document, clause)


def test_the_fourth_review_positive_controls_still_decide():
    assert verdict("12 bar", "pressure shall not exceed 10 bar") is False
    assert verdict("8 bar", "pressure must not exceed 10 bar") is True
    assert verdict("12 bar", "the pressure is to be at least 10 bar") is True
    assert verdict("8 bar", "maximum 10 bar") is True
    assert verdict("12 bar", "minimum 10 bar") is True
    assert verdict("12 bar", "not more than 10 bar") is False
    assert verdict("12 bar", "not less than 10 bar") is True
    assert verdict("12 bar", "at least 10 bar") is True
    assert verdict("12 bar", "at most 10 bar") is False
    assert (
        verdict("12 bar", "design pressure is required to be at least 10 bar") is True
    )


@pytest.mark.parametrize(
    "clause",
    [
        "Pumps, at least 8 bar",
        "Pumps; at least 8 bar",
        "Pumps: at least 8 bar",
        "Pumps (all) at least 8 bar",
        "Pumps [all] at least 8 bar",
    ],
)
def test_a_split_lead_in_without_a_number_is_not_decided(clause):
    _undecided("10 bar", clause)


def test_a_lead_in_longer_than_six_words_is_not_decided():
    _undecided("10 bar", "The pressure of the main line shall be at least 8 bar")
    _undecided("10 bar", "Every one of the vessels in the plant needs at least 8 bar")


@pytest.mark.parametrize(
    "clause",
    [
        "pressure ^ at least 8 bar",
        "pressure \u00d7 at least 8 bar",
        "pressure * at least 8 bar",
        "pressure shall be at least 8 bar\u00b9",
    ],
)
def test_a_power_or_product_mark_without_a_second_number_is_not_decided(clause):
    result = fc.compare("10 bar", clause)
    assert result is None or result.verdict is None


@pytest.mark.parametrize(
    "document, clause",
    [
        ("\u00bd 12 bar", "at least 10 bar"),
        ("12 bar", "at least \u00bd 10 bar"),
        ("12 bar \u2153", "at least 10 bar"),
        ("12 bar", "at least 10 bar \u00bc"),
    ],
)
def test_a_vulgar_fraction_beside_the_figure_is_a_second_number(document, clause):
    _undecided(document, clause)


@pytest.mark.parametrize(
    "clause",
    [
        "pressure unless agreed at least 10 bar",
        "pressure otherwise at least 10 bar",
        "pressure except vents at least 10 bar",
        "pressure at flanges above 10 bar",
        "pressure with flow below 10 bar",
    ],
)
def test_defect5_an_exception_inside_a_plain_lead_in_is_not_decided(clause):
    _undecided("12 bar", clause)


@pytest.mark.parametrize(
    "clause",
    [
        "minimum and maximum 10 bar",
        "pressure at least and at most 10 bar",
        "pressure at least 10 bar maximum",
    ],
)
def test_defect6_two_directions_with_one_number_are_not_decided(clause):
    _undecided("12 bar", clause)


def test_per_hour_against_per_day_is_converted_not_guessed():
    assert verdict("5 m3/h", "at least 3 m3/day") is True  # 3 per day is 0.125 per hour
    assert verdict("0.1 m3/h", "at least 3 m3/day") is False


# --- #1689 fifth review: the document decides only as a bare value or a labelled value; the clause only with requirement force ---
_STATUS_WORDS = [
    "Superseded", "Previous", "Previously", "Former", "Old", "Obsolete", "Voided", "Cancelled", "Void", "Estimated", "Draft",
    "Proposed", "Target", "Was", "Were", "Expected", "Assumed", "Pending", "Likely", "Planned", "Provisional", "Tentative",
    "Preliminary", "Future", "Revised from",
]  # fmt: skip


@pytest.mark.parametrize("word", _STATUS_WORDS)
def test_a_status_word_before_the_document_figure_is_not_decided(word):
    for document in (
        f"{word} 5 bar",
        f"{word}: 5 bar",
        f"Design pressure | {word.lower()} 5 bar",
        f"5 bar {word.lower()}",
    ):
        _undecided(document, "pressure shall not exceed 10 bar")
        _undecided(document, "pressure shall not exceed 3 bar")


@pytest.mark.parametrize(
    "document",
    [
        "Design pressure 5 bar",
        "Value 5 bar",
        "Max design pressure rating 5 bar",
        "Rated 5 bar",
        "Design pressure at the inlet nozzle: 5 bar",
        "Design pressure (bar): 5 bar",
        "pressure; 5 bar",
        "Note 5 bar",
        "Design pressure - 5 bar",
        "A very long label before the value is: 5 bar",
    ],
)
def test_a_label_without_a_delimiter_or_a_long_label_is_not_decided(document):
    _undecided(document, "pressure shall not exceed 10 bar")


@pytest.mark.parametrize(
    "document, expected",
    [
        ("5 bar", True),
        ("5 bar.", True),
        ("Design pressure: 5 bar", True),
        ("Design pressure | 5 bar", True),
        ("Design pressure = 5 bar", None),
        ("Design pressure is 5 bar", True),
        ("Design pressure \u2013 5 bar", None),
        ("Design pressure \u2014 5 bar", None),
        ("Table | Design pressure | 5 bar", True),
        ("Design pressure\t5 bar", True),
        ("Pressures of 5 bar", True),
        ("15 bar", False),
        ("Design pressure: 15 bar", False),
    ],
)
def test_a_bare_or_labelled_document_value_still_decides(document, expected):
    result = fc.compare(document, "pressure shall not exceed 10 bar")
    assert result is not None
    assert result.verdict is expected


@pytest.mark.parametrize(
    "clause",
    [
        "pressure is allowed to be less than 10 bar",
        "pressure need not be less than 10 bar",
        "pressure needs not be less than 10 bar",
        "pressure does not need to be less than 10 bar",
        "pressure is optional at 10 bar minimum",
        "pressure was at least 10 bar",
        "pressure were at least 10 bar",
        "pressure is expected not to exceed 10 bar",
        "pressure is intended not to exceed 10 bar",
        "pressure is assumed not to exceed 10 bar",
        "pressure is anticipated not to exceed 10 bar",
        "pressure is permitted to be at least 10 bar",
        "pressure is permissible up to 10 bar maximum",
        "pressure can be at least 10 bar",
        "pressure could be at least 10 bar",
        "pressure would be at least 10 bar",
        "pressure at least 10 bar is not required",
        "pressure at least 10 bar is not necessary",
        "pressure at least 10 bar is unnecessary",
        "pressure shall be at least 10 bar unless otherwise stated",
    ],
)
def test_permission_or_option_wording_in_the_clause_is_not_decided(clause):
    _undecided("12 bar", clause)


@pytest.mark.parametrize(
    "clause",
    [
        "pressure 10 bar or so is typical",
        "the pressure is 10 bar at least when hot",
        "pressure is 10 bar",
        "pressure 10 bar",
        "pressure less than 10 bar",
        "pressure above 10 bar",
    ],
)
def test_a_clause_without_a_requirement_marker_is_not_decided(clause):
    _undecided("12 bar", clause)


@pytest.mark.parametrize(
    "clause, expected",
    [
        ("pressure shall be at least 10 bar", True),
        ("pressure must be at least 10 bar", True),
        ("pressure is required to be at least 10 bar", True),
        ("pressure is to be at least 10 bar", True),
        ("minimum 10 bar", True),
        ("at least 10 bar", True),
        ("limited to 10 bar maximum", False),
        ("not more than 10 bar", False),
        ("no more than 10 bar", False),
        ("not higher than 10 bar", False),
        ("pressure not to exceed 10 bar", False),
        ("pressure is not to exceed 10 bar", False),
    ],
)
def test_requirement_wording_in_the_clause_still_decides(clause, expected):
    result = fc.compare("12 bar", clause)
    assert result is not None
    assert result.verdict is expected, clause


@pytest.mark.parametrize(
    "document",
    [
        "TBA: 12 bar",
        "None: 12 bar",
        "By others | 12 bar",
        "Not applicable: 12 bar",
        "Excluded: 12 bar",
        "Omitted | 12 bar",
    ],
)
def test_a_placeholder_label_with_a_delimiter_is_not_decided(document):
    _undecided(document, "pressure shall be at least 10 bar")


@pytest.mark.parametrize(
    "document",
    [
        "Max: 12 bar",
        "Minimum: 12 bar",
        "Rated: 12 bar",
        "Average: 12 bar",
        "Mean: 12 bar",
        "Limit: 12 bar",
        "Nom: 12 bar",
        "Ca: 12 bar",
    ],
)
def test_a_qualifier_label_with_a_delimiter_is_not_decided(document):
    _undecided(document, "pressure shall be at least 10 bar")


@pytest.mark.parametrize(
    "clause",
    [
        "pressure shall be 10 bar",
        "pressure is required to be 10 bar",
        "pressure must be 10 bar",
    ],
)
def test_a_clause_with_a_marker_but_no_readable_comparator_is_not_decided(clause):
    _undecided("12 bar", clause)


@pytest.mark.parametrize(
    "clause",
    [
        "pressure shall never exceed 10 bar",
        "pressure shall without fail be at least 10 bar",
        "pressure shall be prohibited above 10 bar",
        "pressure shall be unacceptable below 10 bar",
        "pressure shall neither be below 10 bar",
    ],
)
def test_defect2_a_negation_word_inside_a_clause_with_a_marker_is_not_decided(clause):
    _undecided("12 bar", clause)


@pytest.mark.parametrize(
    "clause",
    [
        "pressure shall be at max least 10 bar",
        "pressure shall be at least at least 10 bar",
        "pressure shall be not less more than 10 bar",
        "pressure shall be at most at most 10 bar",
    ],
)
def test_a_split_or_repeated_comparator_phrase_is_not_decided(clause):
    _undecided("12 bar", clause)


# --- #1689 sixth review: a closed vocabulary. Every word of the clause and of the document label must be a known plain word ---
_NOT_THE_LIVE_VALUE = [
    "Rejected", "Alternative", "Alternate", "Option B", "Case B", "Example", "Sample", "Vendor standard", "Withdrawn", "Replaced",
    "Legacy", "Struck", "Initial", "Unapproved", "Unverified", "Deviation", "Bidder proposal", "Offered", "Quoted", "Submitted",
    "Customer", "Contractor", "Supplier", "Reference", "Basis", "Budget", "Scenario", "Mockup", "Placeholder", "Illustrative",
    "Indicative", "Sketch", "Superceded", "Retired", "Discarded", "Abandoned", "Optional", "Variant", "Revision A", "Rev 0",
    "Interim", "Trial", "Pilot", "Concept", "Option", "Counter offer", "Rework", "Spare part",
]  # fmt: skip


@pytest.mark.parametrize("label", _NOT_THE_LIVE_VALUE)
def test_a_document_label_outside_the_closed_vocabulary_is_not_decided(label):
    _undecided(f"{label}: 5 bar", "pressure shall not exceed 10 bar")
    _undecided(f"{label} | 5 bar", "pressure shall not exceed 3 bar")


_ADVISORY_CLAUSE_WORDS = [
    "suggested", "advised", "desired", "wanted", "hoped", "proposed", "recommended", "encouraged", "favoured", "favored",
    "advisable", "wished", "requested", "invited", "supposed", "believed", "thought", "considered", "judged", "deemed",
    "aimed", "targeted", "foreseen", "projected", "planned", "scheduled", "prospective", "customary", "usual", "ordinary",
    "acceptable", "tolerable", "adequate", "sufficient", "appropriate", "suitable", "reasonable", "approximate", "roughly",
]  # fmt: skip


@pytest.mark.parametrize("word", _ADVISORY_CLAUSE_WORDS)
def test_an_advisory_word_in_the_clause_outside_the_closed_vocabulary_is_not_decided(
    word,
):
    _undecided("12 bar", f"pressure is {word} at least 10 bar")
    _undecided("12 bar", f"pressure is {word} to be at most 10 bar")
    _undecided("8 bar", f"pressure {word} maximum 10 bar")


@pytest.mark.parametrize(
    "clause",
    [
        "pressure is suggested at least 10 bar",
        "pressure is advised to be at most 10 bar",
        "pressure ought to be at least 10 bar",
        "pressure is desired to be at least 10 bar",
        "pressure ought at most 10 bar",
    ],
)
def test_the_reviewer_advisory_clauses_are_not_decided(clause):
    _undecided("12 bar", clause)
    _undecided("8 bar", clause)


def test_the_closed_vocabulary_does_not_hold_a_status_or_hedge_word():
    for word in _NOT_THE_LIVE_VALUE + _ADVISORY_CLAUSE_WORDS:
        for part in word.lower().split():
            assert fc.unknown_words(part) == [part] or part in {"rev", "a", "b", "0"}, (
                part
            )


def test_ordinary_plain_clauses_and_labels_still_decide():
    assert (
        verdict("12 bar", "relief valve set pressure shall be at least 10 bar") is True
    )
    assert verdict("8 bar", "vessel design pressure shall be at least 10 bar") is False
    assert (
        verdict(
            "Wall thickness: 12 mm", "the wall thickness shall be not less than 10 mm"
        )
        is True
    )
    assert (
        verdict(
            "Design temperature | 40 degC",
            "design temperature shall not exceed 50 degC",
        )
        is True
    )
    assert (
        verdict(
            "Corrosion allowance is 2 mm",
            "the corrosion allowance shall be at least 3 mm",
        )
        is False
    )


# --- each older guard is tested ALONE: the closed vocabulary is opened so it cannot catch the input first ---
@pytest.fixture
def open_vocabulary(monkeypatch):
    monkeypatch.setattr(fc, "unknown_words", lambda text: [])


_LAYER_DOCUMENTS = [
    "TBA: 12 bar", "None: 12 bar", "By others | 12 bar", "Not applicable: 12 bar", "Excluded: 12 bar",
    "Draft: 12 bar", "Superseded: 12 bar", "Estimated: 12 bar", "Was: 12 bar", "Expected: 12 bar", "Future: 12 bar",
    "Design pressure | minus 12 bar", "Negative: 12 bar", "Plus: 12 bar",
]  # fmt: skip
_LAYER_CLAUSES = [
    "pressure shall never exceed 10 bar",
    "pressure shall without fail be at least 10 bar",
    "pressure shall be prohibited above 10 bar",
    "pressure shall be unacceptable below 10 bar",
    "pressure unless agreed shall be at least 10 bar",
    "pressure otherwise shall be at least 10 bar",
    "pressure except vents shall be at least 10 bar",
    "pressure when hot shall be at least 10 bar",
    "pressure shall at flanges above 10 bar",
    "pressure shall with flow below 10 bar",
    "pressure should be at least 10 bar",
    "pressure shall preferably be at least 10 bar",
    "pressure shall typically be at least 10 bar",
    "pressure shall be up to 10 bar",
    "pressure is allowed to be at least 10 bar",
    "pressure shall be optional at 10 bar minimum",
    "pressure was at least 10 bar",
    "pressure shall be expected at least 10 bar",
    "The pressure of the main line shall be at least 10 bar",
    "Every one of the vessels in the plant shall be at least 10 bar",
]  # fmt: skip


@pytest.mark.parametrize("document", _LAYER_DOCUMENTS)
def test_layer_each_document_guard_alone(open_vocabulary, document):
    _undecided(document, "pressure shall be at least 10 bar")


@pytest.mark.parametrize("clause", _LAYER_CLAUSES)
def test_layer_each_clause_guard_alone(open_vocabulary, clause):
    _undecided("12 bar", clause)


def test_a_plural_of_a_vocabulary_word_is_accepted():
    assert verdict("Diameters: 5 mm", "diameters shall not exceed 10 mm") is True
