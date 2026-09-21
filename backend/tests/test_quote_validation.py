"""B23 — a model-supplied quote is verified against its source, or it is not used.

The Phase 0.5 run produced the failure this guards: told in the prompt that every
quote must appear verbatim, the model returned the clause with the typographic inch
mark `1/16”` rewritten as a straight `1/16"`. Harmless in itself; the proof that a
model edits source text it was told to reproduce, and that nothing checked.

The normalisation list is CLOSED. Every entry is typography or whitespace, which
cannot change what an engineer reads. Nothing that could change a meaning is
normalised — which is the whole reason `1.6` never becomes `1.5`, `at least` never
becomes `approximately`, and `>=` never becomes `>`.

Test 10 is the mutation, run by `scripts/mutation_check.py`.
"""

from __future__ import annotations

import pytest

from app import quotes

CLAUSE_SOURCE = ('7.1.2.1 For carbon steel, low-alloy steel and alloy steel '
                 'systems, a minimum C.A. of at least 1.6 mm (1/16”) shall '
                 'be used. Thicker allowances may be specified.')
SHEET_SOURCE = 'Design corrosion allowance for welded internal parts: 0 mm'


# ------------------------------------------------- the five required cases

def test_case_1_typographic_inch_mark_is_accepted():
    """`1/16”` vs `1/16"` — rule 1 only. The exact Phase 0.5 failure."""
    ok, reason = quotes.validate('a minimum C.A. of at least 1.6 mm (1/16")',
                                 CLAUSE_SOURCE)
    assert ok is True, reason
    assert reason == quotes.OK


def test_case_2_whitespace_difference_is_accepted():
    """`1.6 mm` vs `1.6mm` — rule 4 collapses whitespace.

    Both directions, because normalisation must be symmetric: the source may be
    the one with the extra space.
    """
    assert quotes.validate("1.6 mm", "a minimum of 1.6  mm shall be used")[0] is True
    assert quotes.validate("at   least   1.6 mm", CLAUSE_SOURCE)[0] is True


def test_case_3_a_changed_digit_is_rejected():
    """`1.6 mm` vs `1.5 mm` — digits are never normalised."""
    ok, reason = quotes.validate("a minimum C.A. of at least 1.5 mm", CLAUSE_SOURCE)
    assert ok is False
    assert reason == quotes.NOT_FOUND


def test_case_4_a_changed_comparison_word_is_rejected():
    """`at least` vs `approximately` — meaning changed."""
    ok, reason = quotes.validate("a minimum C.A. of approximately 1.6 mm",
                                 CLAUSE_SOURCE)
    assert ok is False
    assert reason == quotes.NOT_FOUND


def test_case_5_a_changed_operator_is_rejected():
    """`>=` vs `>` — operators are never normalised."""
    source = "the ratio shall be >= 0.85 at all times"
    assert quotes.validate(">= 0.85", source)[0] is True
    assert quotes.validate("> 0.85", source)[0] is False


# ------------------------------------------- the closed list, and its edges

@pytest.mark.parametrize("raw,expected", [
    ("“quoted”", '"quoted"'),
    ("it’s", "it's"),
    ("1/16″", '1/16"'),
    ("6′", "6'"),
    ("a – b", "a - b"),
    ("a — b", "a - b"),
    ("a b", "a b"),
    ("  a   b  ", "a b"),
    ("a\t\n b", "a b"),
])
def test_the_closed_list_and_only_the_closed_list(raw, expected):
    assert quotes.normalise(raw) == expected


@pytest.mark.parametrize("text", [
    "1.6", "1,6", "MM", "mm", ">=", ">", "<=", "at least", "approximately",
    "carbon steel", "Carbon Steel", "1/16", "0.85", "(a)", "[a]", "a;b",
])
def test_nothing_outside_the_closed_list_is_touched(text):
    """Case, digits, units, operators, commas and brackets all survive."""
    assert quotes.normalise(text) == text.strip()


def test_case_is_never_folded():
    assert quotes.validate("CARBON STEEL", "carbon steel systems")[0] is False


def test_an_empty_or_missing_quote_fails_closed():
    assert quotes.validate("", CLAUSE_SOURCE) == (False, quotes.EMPTY_QUOTE)
    assert quotes.validate(None, CLAUSE_SOURCE) == (False, quotes.EMPTY_QUOTE)
    assert quotes.validate("1.6 mm", "") == (False, quotes.NO_SOURCE)
    assert quotes.validate("1.6 mm", None) == (False, quotes.NO_SOURCE)


# --------------------------------- document and page must resolve, not just text

def test_a_verbatim_quote_attributed_to_the_wrong_document_is_invalid():
    out = quotes.validate_citation(
        "at least 1.6 mm", source_text=CLAUSE_SOURCE,
        expected_document_id="doc_1e545335e562",
        actual_document_id="doc_somethingelse")
    assert out["valid"] is False
    assert "document_mismatch" in out["failures"]


def test_a_verbatim_quote_attributed_to_the_wrong_page_is_invalid():
    out = quotes.validate_citation(
        "at least 1.6 mm", source_text=CLAUSE_SOURCE,
        expected_page=48, actual_page=4)
    assert out["valid"] is False
    assert "page_mismatch" in out["failures"]


# ------------------------------------- 9. a proposal may not carry a verdict

def _proposal(**over) -> dict:
    base = {
        "status": "NON_COMPLIANT",
        "contractor_quote": "Design corrosion allowance for welded internal parts: 0 mm",
        "contractor_page": 4,
        "requirement_quote": 'a minimum C.A. of at least 1.6 mm (1/16")',
        "requirement_page": 48,
    }
    base.update(over)
    return base


def test_9_a_proposal_whose_quotes_resolve_is_accepted():
    out = quotes.check_proposal(
        _proposal(), contractor_source=SHEET_SOURCE,
        requirement_source=CLAUSE_SOURCE,
        contractor_page=4, requirement_page=48)
    assert out["valid"] is True
    assert out["safe_status"] is None, (
        "a valid proposal is not forced to any status by B23")
    assert out["unverified_text"] is None


@pytest.mark.parametrize("bad,label", [
    ({"requirement_quote": "a minimum C.A. of at least 1.5 mm"}, "digit changed"),
    ({"requirement_quote": "a minimum C.A. of approximately 1.6 mm"}, "word changed"),
    ({"contractor_quote": "Design corrosion allowance: 5 mm"}, "invented value"),
    ({"contractor_quote": ""}, "empty quote"),
    ({"requirement_page": 4}, "wrong page"),
])
def test_9b_a_proposal_whose_quote_fails_cannot_carry_a_verdict(bad, label):
    out = quotes.check_proposal(
        _proposal(**bad), contractor_source=SHEET_SOURCE,
        requirement_source=CLAUSE_SOURCE,
        contractor_page=4, requirement_page=48)
    assert out["valid"] is False, label
    assert out["safe_status"] == "NEEDS_ENGINEER_REVIEW", label
    assert out["unverified_text"] is not None, (
        "the model's text must be preserved separately, not discarded and not "
        "stored as evidence")


def test_9c_the_model_output_is_preserved_not_repaired():
    """A failed quote is never corrected to the source text. Repairing it would
    launder a model's edit into a verified citation."""
    out = quotes.check_proposal(
        _proposal(requirement_quote="a minimum C.A. of at least 1.5 mm"),
        contractor_source=SHEET_SOURCE, requirement_source=CLAUSE_SOURCE)
    assert out["unverified_text"]["requirement_quote"] == \
        "a minimum C.A. of at least 1.5 mm"
    assert "1.6" not in out["unverified_text"]["requirement_quote"]
