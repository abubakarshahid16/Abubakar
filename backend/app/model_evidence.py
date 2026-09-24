"""Verification of a local model's quoted evidence (B5 bounded model
assistance, owner-approved 2026-09-25).

A model-assisted value is only ever kept when its quote is found in the
document text the model was given. "Found" means EXACT, with ONE closed
normalisation the owner approved: runs of whitespace and line breaks
collapse to a single space on both sides before comparing. Nothing else is
normalised - not case, not dashes, not quotes, not punctuation - because
each of those would let a paraphrase pass as a quotation.

Why whitespace at all: a PDF's stored page text breaks a title across lines
("DATA SHEET FOR\\nPRESSURE SAFETY VALVES (PSVs)") while the model quotes it
as one line. Measured on the regression sheets: 2 of 4 quote rejections
were exactly this, and both were real quotations.
"""
from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")


def _collapse(text: str | None) -> str:
    return _WHITESPACE.sub(" ", text or "").strip()


def quote_verified(quote: str | None, source_text: str | None) -> bool:
    """True when `quote` occurs in `source_text` character for character,
    after collapsing whitespace and line breaks on both sides only."""
    needle = _collapse(quote)
    if not needle:
        return False
    return needle in _collapse(source_text)


# ------------------------------------------ STATED via approved vocabulary
#
# Owner decision 2026-09-25 (the wrong-field gap: "SOUR WATER DRUMS" was put
# into equipment_type). A controlled-vocabulary value counts as STATED only
# when one of ITS approved synonyms appears, as a whole word, in a verified
# quote that is itself an EVIDENCE LINE - the equipment title or a
# tag / service line - never anywhere on the page. "column" in a table
# header must never produce Pressure Vessel.
#
# The vocabulary is a PARAMETER, not a constant here: the list is still a
# proposal awaiting owner approval (.cowork/equipment-type-vocabulary-
# PROPOSED-v1.md), so no unapproved list is baked into code.

STATED_VIA_VOCABULARY = "STATED via approved vocabulary"

#: A tag / item / service LINE: the label opens the line. Anchored, so a
#: body sentence that merely contains the word "service" is not one.
_LABEL_LINE = re.compile(r"^\s*(?:TAG|ITEM|SERVICE|EQUIPMENT)\b", re.IGNORECASE)


def equipment_evidence_lines(title_lines: list[str], page_texts: list[str]) -> list[str]:
    """The lines a vocabulary match may come from: the document's own title
    block (as `classification.title_block_lines` returns it) plus every line,
    on any page, that OPENS with a TAG / ITEM / SERVICE / EQUIPMENT label."""
    lines = [line for line in title_lines if line and line.strip()]
    for text in page_texts:
        lines += [line for line in (text or "").splitlines() if _LABEL_LINE.match(line)]
    return lines


def stated_via_vocabulary(value: str | None, quote: str | None, *,
                          vocabulary: dict[str, tuple[str, ...]],
                          evidence_lines: list[str]) -> dict | None:
    """The evidence record when `value` is STATED via the approved
    vocabulary, else None (the caller then treats it as INFERRED or rejects).

    All must hold: `value` is a vocabulary key; the quote is verified against
    ONE evidence line (not against the whole page); one of that value's
    synonyms occurs in the quote as a whole word. The record names the
    synonym and the line, so it can never be mistaken for a literal match."""
    synonyms = vocabulary.get(value or "")
    if not synonyms or not _collapse(quote):
        return None
    line = next((l for l in evidence_lines if quote_verified(quote, l)), None)
    if line is None:
        return None
    for synonym in synonyms:
        if re.search(rf"\b{re.escape(synonym)}\b", _collapse(quote), re.IGNORECASE):
            return {"class": STATED_VIA_VOCABULARY, "value": value,
                    "synonym": synonym, "quote": quote, "evidence_line": line}
    return None
