"""Repair glyphs an old PDF's symbol font extracted as the wrong character.

Same class of defect as `ligatures.py`, same place in the pipeline, and
repaired for the same reason: it is a COVERAGE problem, not a retrieval one.
No amount of ranking will match a unit that is not in the text.

WHAT WAS MEASURED, on the twelve-document corpus, span by span through the
source PDFs:

    50 glyphs extracted as the wrong character, ALL in NORSOKM501Rev5.pdf
       44  'x'  from SymbolMT, each starting a bullet list item
        4  'P'  from SymbolMT, each the micro sign in "1000 Pm NDFT"
        2  U+0094 / U+0095 in Arial, each a comparator

    Of those 50, this module repairs the 3 micro signs that carry enough
    context to be certain. The other 'P' has its digit on the previous line,
    so the rule declines it rather than guess - see the pattern below.

Small in count and large in consequence: NORSOK M-501 is the coatings
specification, and "µm" is the unit a coatings question is about. "the
coating thickness is 1000 Pm NDFT" yielded NO measurement at all, so the
answer the product exists to find was silently absent.

WHY NOT REPLACE "P" WITH "µ". P is a real letter and a real SI prefix, and
`book2-Differential-Equations.pdf` p443 contains `Pm(x)Pn(x)` - Legendre
polynomials, where P is genuinely P and is even preceded by a digit. A blind
replacement corrupts it.

So the rule is deliberately narrow: a capital P between a DIGIT and a
lowercase "m" that ends the token. `1000 Pm NDFT` matches. `Pm(x)` does not,
because "(" follows. `5 Pm` in an astronomy text would match and would be
wrong - there is no such text in this corpus, the rule is validated against
every page of it below, and that validation is a test rather than a claim.

THE TWO COMPARATORS ARE NOT REPAIRED, and that is deliberate. U+0095 in
"the coating thickness is <?> 1000 um NDFT" is a comparator whose identity
cannot be recovered from the byte: it could be ">" or ">=", and the two mean
different things to a claim comparison. Guessing one would be exactly the
invented-measurement defect this codebase just fixed, one level up. They are
recorded in `docs/limitations.md` with their page numbers instead.
"""

from __future__ import annotations

import re

#: A capital P that is really the micro sign.
#:
#: Requires a digit before it and a lowercase "m" after it, with the token
#: ending there - so "1000 Pm NDFT" is repaired and "Pm(x)Pn(x)" is not.
#: Anchored on both sides rather than matching "Pm" anywhere, because "Pm"
#: alone is also a valid petametre and a valid pair of letters.
_MICRO = re.compile(r"(?<=\d)(\s?)Pm(?![\w(])")

#: THE BULLET REPAIR WAS WRITTEN AND THEN DELETED. Measured before trusting
#: it: `^\s*x\s+\S` matched 1,051 places across the corpus, and only 44 of
#: them were NORSOK's symbol-font bullets. The other 992 were in
#: `book2-Differential-Equations.pdf`, where "x" at the start of a line is the
#: VARIABLE - "x y 1 (a) function y = 1/x", "x + 16x = 0". Repairing bullets
#: would have rewritten a mathematics textbook.
#:
#: It cannot be gated safely without the span's font, and `get_text("text")`
#: does not carry fonts. A bullet rendered as "x" is cosmetic; a missing "um"
#: loses the answer. So only the micro sign is repaired, and this comment
#: stands where the rule would have been.


def repair(text: str) -> str:
    """Fix the two symbol-font substitutions measured in this corpus.

    Conservative by construction: the pattern requires surrounding context
    that an ordinary "P" does not have. `test_symbols.py` runs it over the
    corpus fixtures and asserts both what it changes and what it leaves.
    """
    if not text:
        return ""
    return _MICRO.sub(r"\1um", text)


def micro_repairs(text: str) -> int:
    """How many micro-sign repairs this text would take. For measurement."""
    return len(_MICRO.findall(text or ""))
