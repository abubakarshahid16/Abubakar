"""Verification of a local model's quoted evidence (B5 bounded model
assistance, owner-approved 2026-09-25).

A model-assisted value is only ever kept when its quote is found in the
document text the model was given. "Found" means EXACT, after the owner's
CLOSED normalisation list (2026-09-25), applied to both sides:

  1. curly quotes to straight: U+2018 U+2019 -> '   U+201C U+201D -> "
  2. en dash U+2013 and em dash U+2014 -> hyphen-minus
  3. non-breaking space U+00A0 -> space
  4. whitespace and line breaks collapse to one space; ends trimmed

Nothing else - not case, not digits, not other punctuation or symbols (the
minus sign U+2212, the degree sign, units) - because each of those would let
a paraphrase pass as a quotation.

Why these: a PDF's stored page text breaks a title across lines ("DATA SHEET
FOR\\nPRESSURE SAFETY VALVES (PSVs)") while the model quotes it as one line
(2 of 4 quote rejections on the regression sheets); and a model re-types a
typographic quote or dash as the plain keyboard character (the scope pilot
lost SAES-L-109's real quotation to curly vs straight quotes).
"""
from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")

#: The owner's closed list, items 1-3. Item 4 is `_WHITESPACE`.
APPROVED_CHARACTER_MAP = {
    "‘": "'", "’": "'",   # curly single quotes
    "“": '"', "”": '"',   # curly double quotes
    "–": "-",                  # en dash
    "—": "-",                  # em dash
    " ": " ",                  # non-breaking space
}
_APPROVED = str.maketrans(APPROVED_CHARACTER_MAP)


def _collapse(text: str | None) -> str:
    text = (text or "").translate(_APPROVED)
    return _WHITESPACE.sub(" ", text).strip()


def quote_verified(quote: str | None, source_text: str | None) -> bool:
    """True when `quote` occurs in `source_text` character for character,
    after the closed normalisation list on both sides only."""
    needle = _collapse(quote)
    if not needle:
        return False
    return needle in _collapse(source_text)


# ------------------------------------------- a quote offered as a CLAIM's proof
#
# `quote_verified` answers "are these characters on the page?" and is right
# for a VALUE the model read off a page (a tag, "10", a unit), where a short
# needle is the whole point. A generated SENTENCE that cites
# [S1 "the"] is a different question: is this quote evidence for the
# sentence? A bare substring test said yes - "the" is inside every page, and
# inside "theory" too - so "The design pressure is 999 barg [S1 "the"]" was
# shown as verified (audit 2026-09-30). The rule below is what a quote must
# be before it can stand behind a claim.

#: The fewest words a claim's quote may have. Three is the shortest span that
#: can carry a relation ("design pressure 10", "shall be galvanised"); one
#: and two-word spans ("the", "shall be", "10 barg") occur on nearly every
#: engineering page, so finding one there proves nothing about the sentence.
#: A "word" is a whitespace-separated token holding a letter or digit, so
#: "3.0 mm/s RMS" is three words and a stray "-" is none.
MIN_CLAIM_QUOTE_WORDS = 3

_TOKEN_WITH_SUBSTANCE = re.compile(r"[^\W_]")
#: A word broken across a line by a hyphen in the PDF text layer ("thick-\n
#: ness"). Letters on both sides only, so "10-\n20" and "P-\n1001" are never
#: joined.
_LINE_BREAK_HYPHEN = re.compile(r"(?<=[^\W\d_])-[ \t]*\r?\n[ \t]*(?=[^\W\d_])")


def _source_variants(source_text: str | None) -> tuple[str, ...]:
    """The page as stored, plus the two ways a line-break hyphen can be read
    back (a split word joined; a real compound kept with its hyphen). Layout
    only: no character the page printed on one line is ever changed."""
    text = source_text or ""
    if not _LINE_BREAK_HYPHEN.search(text):
        return (_collapse(text),)
    return (_collapse(text), _collapse(_LINE_BREAK_HYPHEN.sub("", text)),
            _collapse(_LINE_BREAK_HYPHEN.sub("-", text)))


def claim_quote_verified(quote: str | None, source_text: str | None) -> bool:
    """True when `quote` is MEANINGFUL evidence found on the page:

    - at least MIN_CLAIM_QUOTE_WORDS words (see there for why three);
    - found in the page after the owner's closed normalisation list
      (`_collapse`), on WORD BOUNDARIES: a quote that starts or ends with a
      letter or digit must not start or end inside a longer word or number
      on the page ("design pressure 10" is not found in "design pressure
      100");
    - a word the PDF text layer hyphenated across a line break matches the
      unbroken word, and a compound broken at its hyphen matches with the
      hyphen (`_source_variants`) - the model re-types the word as printed.

    Case, digits and every other character still compare exactly, as in
    `quote_verified`. This proves the words are on the page; whether the
    sentence's FIGURES are is checked separately (`answer.verify_claims`)."""
    needle = _collapse(quote)
    fragments = [f.strip() for f in _ELLIPSIS.split(needle)]
    fragments = [f for f in fragments if f]
    if not fragments:
        return False
    counts = [len([w for w in f.split(" ") if _TOKEN_WITH_SUBSTANCE.search(w)])
              for f in fragments]
    if sum(counts) < MIN_CLAIM_QUOTE_WORDS:
        return False
    if len(fragments) > 1 and min(counts) < MIN_ELLIPSIS_FRAGMENT_WORDS:
        return False
    return any(_fragments_in_order(fragments, page)
               for page in _source_variants(source_text))


#: A quote the model shortened with "..." or the one-character ellipsis. The
#: page shows the words either side; the dots themselves are not on it.
_ELLIPSIS = re.compile(r"\s*(?:\.{3,}|\u2026)\s*")
#: Each piece of a quote cut by an ellipsis must itself carry a relation.
MIN_ELLIPSIS_FRAGMENT_WORDS = 2


def _fragments_in_order(fragments: list[str], page: str) -> bool:
    """Every fragment found on the page, whole-word, each AFTER the one before.
    A quote with no ellipsis is one fragment: the exact rule above."""
    pos = 0
    for frag in fragments:
        pattern = re.compile(
            (r"(?<!\w)" if re.match(r"\w", frag) else "") + re.escape(frag)
            + (r"(?!\w)" if re.search(r"\w$", frag) else ""))
        m = pattern.search(page, pos)
        if not m:
            return False
        pos = m.end()
    return True




# ------------------------------------------------ discipline: STATED or INFERRED
#
# Owner rule 2026-09-25 (title-block matrix): a discipline value whose quote does
# not LITERALLY state it is INFERRED and goes to engineer review - never
# accepted automatically. Measured failures it stops: the single word "Process"
# quoted from a signature cell, and "Mechanical" inferred from a
# document-number line. A verified quote proves the words are on the page, not
# that they say what the model concluded.

STATED, INFERRED, REJECTED = "STATED", "INFERRED", "REJECTED"

#: A line that names the kind of document ("MECHANICAL DATA SHEET",
#: "PIPING SPECIFICATION") - where a sheet states its own discipline.
_TITLE_CUE = re.compile(r"\b(?:DATA\s*SHEETS?|DATASHEETS?|SPECIFICATIONS?|DRAWINGS?|REQUISITIONS?)\b",
                        re.IGNORECASE)


def discipline_evidence(value: str | None, quote: str | None, *,
                        title_lines: list[str], source_text: str | None) -> dict:
    """STATED only when ALL hold: the quote is on the page; it lies inside ONE
    title line that names the document kind; and the quote itself contains
    the discipline word (whole word). Anything else with a verified quote is
    INFERRED (needs_engineer_review); an unverified quote is REJECTED."""
    if not value or not str(value).strip():
        return {"class": None, "value": None, "needs_engineer_review": False}
    if not quote_verified(quote, source_text):
        return {"class": REJECTED, "value": value, "needs_engineer_review": False,
                "reason": "quote not found on the page"}
    line = next((ln for ln in title_lines if quote_verified(quote, ln)), None)
    states = re.search(rf"\b{re.escape(str(value).strip())}\b", _collapse(quote), re.IGNORECASE)
    if line is not None and _TITLE_CUE.search(line) and states:
        return {"class": STATED, "value": value, "needs_engineer_review": False,
                "quote": quote, "evidence_line": line}
    why = ("the quote does not state the discipline" if not states
           else "the quote is not on a sheet-title line")
    return {"class": INFERRED, "value": value, "needs_engineer_review": True,
            "quote": quote, "reason": why}
