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
