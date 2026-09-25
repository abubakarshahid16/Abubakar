"""The quote check a model-assisted value must pass (owner-approved closed
normalisation: whitespace and line breaks only).

Mutations: M527 (drop the collapse), M528 (fold case) - both must be DETECTED."""
import pytest

from app.model_evidence import quote_verified

PAGE = "KUWAIT OIL COMPANY\nDATA SHEET FOR\nPRESSURE SAFETY VALVES (PSVs)\nPROJECT NO.: RFP – 2034573\n"


def test_an_exact_quote_is_verified():
    assert quote_verified("PRESSURE SAFETY VALVES (PSVs)", PAGE)


def test_a_quote_joining_a_line_break_is_verified():
    """THE MUTATION TARGET (M527): the page breaks the title across two
    lines; the model quotes it as one. Whitespace-only normalisation makes
    that a match."""
    assert quote_verified("DATA SHEET FOR PRESSURE SAFETY VALVES (PSVs)", PAGE)


def test_extra_spaces_inside_the_quote_are_verified():
    assert quote_verified("DATA   SHEET  FOR\tPRESSURE", PAGE)


def test_a_case_difference_is_not_verified():
    """THE MUTATION TARGET (M528): case is NOT on the approved list - a
    lower-cased quote is a paraphrase, not a quotation."""
    assert not quote_verified("data sheet for pressure safety valves", PAGE)


def test_a_different_dash_is_not_verified():
    """The page prints an en dash; a hyphen is a different character."""
    assert not quote_verified("RFP - 2034573", PAGE)
    assert quote_verified("RFP – 2034573", PAGE)


@pytest.mark.parametrize("quote", [None, "", "   ", "\n\t"])
def test_an_empty_quote_is_never_verified(quote):
    assert not quote_verified(quote, PAGE)


def test_a_quote_against_no_text_is_not_verified():
    assert not quote_verified("DATA SHEET", None)
