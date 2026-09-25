"""The quote check a model-assisted value must pass: exact, after the owner's
CLOSED normalisation list (2026-09-25) and nothing else - curly quotes to
straight, en/em dash to hyphen, non-breaking space to space, whitespace
collapse and trim.

Mutations: M527 (drop the collapse), M528 (fold case), M538 (drop the en dash
item), M539 (drop the curly double quote item) - all must be DETECTED."""
import pytest

from app.model_evidence import APPROVED_CHARACTER_MAP, quote_verified

# A synthetic page - no client document text.
PAGE = ("OPERATING COMPANY\nDATA SHEET FOR\nPRESSURE SAFETY VALVES (PSVs)\n"
        "PROJECT NO.: P – 1000001\n"
        "Selection of flanges (hereinafter called “flanges”) and the owner’s gaskets\n"
        "Design pressure 10 barg — see note 4\n"
        "Minimum temperature −29 °C, 150 mm, Class 300.\n")


def test_an_exact_quote_is_verified():
    assert quote_verified("PRESSURE SAFETY VALVES (PSVs)", PAGE)


def test_a_quote_joining_a_line_break_is_verified():
    """THE MUTATION TARGET (M527): the page breaks the title across two
    lines; the model quotes it as one."""
    assert quote_verified("DATA SHEET FOR PRESSURE SAFETY VALVES (PSVs)", PAGE)


def test_extra_spaces_inside_the_quote_are_verified():
    assert quote_verified("DATA   SHEET  FOR\tPRESSURE", PAGE)


# ------------------------------------------------- the closed list, item by item

def test_curly_double_quotes_match_straight():
    """THE MUTATION TARGET (M539) - the scope-pilot failure shape."""
    assert quote_verified('(hereinafter called "flanges")', PAGE)


def test_curly_single_quote_matches_straight():
    assert quote_verified("the owner's gaskets", PAGE)


def test_en_dash_matches_hyphen():
    """THE MUTATION TARGET (M538)."""
    assert quote_verified("P - 1000001", PAGE)
    assert quote_verified("P – 1000001", PAGE)


def test_em_dash_matches_hyphen():
    assert quote_verified("10 barg - see note 4", PAGE)


def test_non_breaking_space_matches_space():
    assert quote_verified("Design pressure 10 barg", PAGE)


def test_the_list_is_exactly_the_approved_one():
    """Closed list: seven characters, and each maps where the owner said."""
    assert APPROVED_CHARACTER_MAP == {
        "‘": "'", "’": "'", "“": '"', "”": '"',
        "–": "-", "—": "-", " ": " "}


# ------------------------------------------- nothing outside the list is normalised

def test_a_case_difference_is_not_verified():
    """THE MUTATION TARGET (M528)."""
    assert not quote_verified("data sheet for pressure safety valves", PAGE)


@pytest.mark.parametrize("quote", [
    "Minimum temperature -29 °C",   # minus sign U+2212 is NOT a dash on the list
    "Minimum temperature −29 C",     # the degree sign is not optional
    "Minimum temperature −29 degC",  # units are not translated
    "150 mm, Class 300,",                 # punctuation: full stop is not a comma
    "150 mm, Class 600.",                 # digits exact
    "15O mm",                             # letter O is not zero
    "flanges (hereinafter called 'flanges')",  # double quote is not single quote
    "10 bar g",                           # spacing INSIDE a token is not whitespace collapse
], ids=["minus-sign", "degree-sign", "units", "punctuation", "digits", "letter-O",
        "quote-kind", "inner-space"])
def test_nothing_outside_the_list_is_normalised(quote):
    assert not quote_verified(quote, PAGE)


@pytest.mark.parametrize("quote", [None, "", "   ", "\n\t", " "],
                         ids=["none", "empty", "spaces", "newline-tab", "nbsp"])
def test_an_empty_quote_is_never_verified(quote):
    assert not quote_verified(quote, PAGE)


def test_a_quote_against_no_text_is_not_verified():
    assert not quote_verified("DATA SHEET", None)
