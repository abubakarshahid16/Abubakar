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


# ------------------------------ which vocabulary value a quote names (addendum 4)
#
# Owner addendum 2026-09-25, section 4.5-4.7: a keyword in the quote is NOT
# proof of the type. Several equipment words in one title ("PUMP MOTOR",
# "TANK HEATER"), a word with a non-equipment meaning ("SUPPLY VESSEL" is a
# ship, "battery limit" a plant boundary) or a table header ("COLUMN A") must
# never become a confident type - they are UNKNOWN or NEEDS_ENGINEER_REVIEW,
# because a wrong type can hide an applicable standard.

UNKNOWN_TYPE = "UNKNOWN"
NEEDS_ENGINEER_REVIEW = "NEEDS_ENGINEER_REVIEW"


def _vocabulary_hits(text: str, vocabulary: dict[str, tuple[str, ...]]) -> list[tuple[str, str]]:
    """(value, synonym) for every synonym in `text`, whole word, optional
    plural; longest synonyms first, and a synonym inside an already-matched
    longer one does not count again ("PRESSURE SAFETY VALVE" is not also
    "valve", "CENTRIFUGAL PUMP" is not also "pump")."""
    pairs = sorted(((s.lower(), v) for v, syns in vocabulary.items() for s in syns),
                   key=lambda p: len(p[0]), reverse=True)
    hits, taken = [], []
    for synonym, value in pairs:
        for m in re.finditer(rf"\b{re.escape(synonym)}(?:s|es)?\b", text):
            if any(m.start() >= a and m.end() <= b for a, b in taken):
                continue
            taken.append((m.start(), m.end()))
            hits.append((value, synonym))
    return hits


def classify_via_vocabulary(quote: str | None, *, vocabulary: dict[str, tuple[str, ...]],
                            evidence_lines: list[str], ambiguous: frozenset[str] = frozenset(),
                            not_equipment: tuple[str, ...] = ()) -> dict:
    """The equipment type a verified evidence-line quote names, or why not.

    - the quote must verify against ONE evidence line, else UNKNOWN;
    - `not_equipment` phrases ("battery limit", "instrument air") are removed
      first - they name no equipment;
    - no synonym left: UNKNOWN;
    - synonyms of TWO OR MORE values: NEEDS_ENGINEER_REVIEW, all candidates
      listed (the model may propose one; code never picks);
    - one value, but only through an `ambiguous` synonym ("vessel" may be a
      ship, "column" a table column): NEEDS_ENGINEER_REVIEW with that value
      as a proposal;
    - otherwise STATED via approved vocabulary (still a proposal until the
      vocabulary itself is approved).
    `vocabulary`, `ambiguous` and `not_equipment` are PARAMETERS: all three
    lists await owner approval."""
    out = {"status": UNKNOWN_TYPE, "value": None, "candidates": [], "synonyms": [], "evidence_line": None}
    text = _collapse(quote).lower()
    line = next((l for l in evidence_lines if quote_verified(quote, l)), None) if text else None
    if line is None:
        return {**out, "reason": "quote is not an equipment evidence line"}
    for phrase in not_equipment:
        text = re.sub(rf"\b{re.escape(phrase.lower())}\b", " ", text)
    hits = _vocabulary_hits(text, vocabulary)
    values = sorted({v for v, _ in hits})
    out.update({"candidates": values, "synonyms": [s for _, s in hits], "evidence_line": line})
    if not values:
        return {**out, "reason": "no vocabulary word names equipment here"}
    if len(values) > 1:
        return {**out, "status": NEEDS_ENGINEER_REVIEW,
                "reason": f"names {len(values)} vocabulary values - engineer to choose"}
    if all(s in ambiguous for _, s in hits):
        return {**out, "status": NEEDS_ENGINEER_REVIEW, "value": values[0],
                "reason": "only an ambiguous word names it - engineer to confirm"}
    return {**out, "status": STATED_VIA_VOCABULARY, "value": values[0], "reason": "one value, unambiguous word"}


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
