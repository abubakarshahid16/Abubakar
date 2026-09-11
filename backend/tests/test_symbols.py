"""Symbol-font repair: the micro sign, and the rules it must never break.

The defect: `NORSOKM501Rev5.pdf` renders µ in SymbolMT, which extracts as a
capital "P". "the coating thickness is 1000 Pm NDFT" therefore yielded NO
measurement at all - in a coatings corpus, where µm is the unit every question
is about, the product was silently dropping the answers it exists to find.

The danger: P is a real letter and a real SI prefix. Every test below that
looks like an over-fit is there because a broader rule was measured against
the corpus and rejected.
"""

from __future__ import annotations

import pytest

from app import claims, quality, symbols

#: Verbatim from NORSOKM501Rev5.pdf, with µ as it actually extracts.
NORSOK = (
    "In accordance with 10.1, the coating thickness is  1000 Pm NDFT and "
    "provided relevant successful field experience is documented.",
    "1 coat zinc ethyl silicate primer with 15 Pm thickness.",
    "The dry film thickness shall be  maximum 25 Pm. Use of shop primer.",
)

#: Verbatim from book2-Differential-Equations.pdf p443. P is genuinely P -
#: Legendre polynomials - and it is even preceded by a digit, which is why the
#: rule needs the character AFTER "Pm" as well.
LEGENDRE = "The orthogonality relation is 1 1 Pm(x)Pn(x) dx 0, m n."


@pytest.mark.parametrize("text", NORSOK)
def test_the_micro_sign_is_recovered(text):
    assert "Pm" not in symbols.repair(text)
    assert "um" in symbols.repair(text)


def test_the_measurement_that_was_lost_is_now_extracted():
    """The whole point. Before this, 1000 um yielded nothing at all."""
    repaired = quality.normalise_text(NORSOK[0])
    values = {(m.raw_value, m.raw_unit) for m in claims.extract_measurements(repaired)}
    assert ("1000", "um") in values


def test_a_genuine_capital_p_is_never_touched():
    """Legendre polynomials, from the real corpus. A blind P -> µ corrupts
    them, and the digit in front is why a looser rule would have."""
    assert symbols.repair(LEGENDRE) == LEGENDRE
    assert "Pm(x)Pn(x)" in quality.normalise_text(LEGENDRE)


@pytest.mark.parametrize("text", [
    "Pressure P m is the mean value.",       # spaced - two separate tokens
    "The Pm ratio is defined below.",        # no digit in front
    "Compare Pmax against the limit.",       # longer token
    "Section Pm.4 covers this.",             # followed by a word character
    "Values of Pm(x) are tabulated.",        # followed by an opening bracket
])
def test_contexts_a_micro_sign_never_appears_in(text):
    assert symbols.repair(text) == text


def test_the_rule_is_narrow_enough_to_count():
    """Across the whole corpus this fires 3 times, all in NORSOK.

    A repair that fires thousands of times is not a repair, it is a rewrite -
    which is what happened to the bullet rule that used to live beside this
    one. Asserting the SHAPE of the rule here; the corpus figure is in
    docs/limitations.md because it moves when documents are added.
    """
    assert symbols.micro_repairs("a 15 Pm coat and a 25 Pm coat") == 2
    assert symbols.micro_repairs(LEGENDRE) == 0


def test_repair_is_idempotent():
    once = symbols.repair(NORSOK[0])
    assert symbols.repair(once) == once


def test_empty_text_is_not_an_error():
    assert symbols.repair("") == ""
    assert symbols.repair(None) == ""


def test_the_comparator_is_not_invented():
    """U+0095 in "thickness is <?> 1000 um" could be ">" or ">=".

    They mean different things to a claim comparison, and the byte does not
    say which. Guessing would be the invented-measurement defect one level up,
    so the character is dropped and the loss is recorded in limitations.md
    rather than papered over.
    """
    mangled = "the coating thickness is \x95 1000 Pm NDFT"
    out = quality.normalise_text(mangled)
    assert "1000 um" in out
    for invented in (">", "≥", "<", "≤"):
        assert invented not in out, f"a comparator was invented: {invented!r}"
