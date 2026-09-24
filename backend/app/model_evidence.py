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
