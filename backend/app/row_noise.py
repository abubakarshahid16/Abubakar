"""Page furniture and fragments that are not fields (#193 plan B4, item 3).

CODE ONLY - NO MODEL. A fixed list of shapes, each one a thing a datasheet
prints that a reader can mistake for a label/value pair: the row-number
ruler down the margin, the revision table, the sheet number, a column
heading read as an answer, a note reference standing where a value would
be, a whole block of the page glued into one "label".

Each rule names ONE shape and is document-independent: no document's words,
no answer key. `noise_reason` returns the rule's name (a drop reason the
page ledger counts) or None. It is applied in `datasheets.extract_facts`
to every reader's rows - rule reader, grid, geometry and vision alike. It ran
only behind `settings.geometry_reader_enabled` until 2026-09-25; being code
only, with no model and no egress, it now runs on the default path too, so a
title block is filtered whether or not the geometry reader is on.

A BLANK IS NEVER NOISE HERE. "[Note - 3]" beside DISCHARGE PRESSURE is the
sheet saying the value is elsewhere; `is_blank_value` decides what that is.
This module only removes rows that would be stored as VALUES.
"""
from __future__ import annotations

import re

RULER = "noise: row-number ruler"
REVISION = "noise: revision table"
DOCUMENT_ID = "noise: title block (document or sheet number)"
HEADER_AS_VALUE = "noise: column heading read as a value"
REFERENCE_ONLY = "noise: value is only a note or clause reference"
FRAGMENT_LABEL = "noise: label is a fragment"
MERGED_BLOCK = "noise: a block of the page read as one field"
IDENTIFIER_NUMBER = "noise: an identifier's number is not a measurement"

RULES = (RULER, REVISION, DOCUMENT_ID, HEADER_AS_VALUE, REFERENCE_ONLY,
         FRAGMENT_LABEL, MERGED_BLOCK, IDENTIFIER_NUMBER)

_WS = re.compile(r"\s+")

#: Five or more consecutive integers opening the label: the margin's line
#: numbers ("1 2 3 4 5 6 ... DATA SHEET NO.").
_RULER = re.compile(r"^\s*(\d{1,3})(\s+\d{1,3}){4,}")

#: The revision-history table's own wording.
_REVISION = re.compile(
    r"\b(issued\s+for|re-?issued|revised\b|comments\s+incorporated)\b|^\s*rev(ision)?\b\.?",
    re.IGNORECASE)

#: A label that is the document's or the sheet's identity, not the equipment's.
_DOCUMENT_LABEL = re.compile(
    r"^\s*(project|(data\s*)?sheet\s*no\.?|sp\s*sht\s*no\.?|page|"
    r"(contractor\s+|licensor\s+|subcontractor\s+)?doc(ument)?\.?\s*no\.?|"
    r"contract\s*no\.?|(service\s+|purchase\s+)?order\s*no\.?|"
    r"job\s*no\.?|p\.?\s*o\.?\s*no\.?|requisition\s*no\.?|"
    r"(inquiry|enquiry|proposal|quotation)\s*no\.?)\s*:?\s*$", re.IGNORECASE)

#: B4: a label that NAMES something by number - it ends "No.", "Number" or
#: "#" - with a bare, unitless integer beside it. "JOB NO. 21087" and "P.O.
#: NO. 4500012345" were stored as numeric facts that no requirement can be
#: about. A count ("NUMBER OF STAGES 2") asks HOW MANY and does not end on
#: the word; a tag ("ITEM NO. 09-G-411 A/B") is not a bare integer.
_IDENTIFIER_LABEL = re.compile(r"(?:\bno\.?|\bnumber|#)\s*:?\s*$", re.IGNORECASE)
_BARE_INTEGER = re.compile(r"^\d{1,12}$")
#: A title block glued into a label: "NO.: ABC - 1234567 ATA SHEE".
_DOCUMENT_GLUE = re.compile(r"\bNO\.\s*:", re.IGNORECASE)
#: A value that is a sheet or revision number: "Sheet 5", "of 7", "Rev. No.: 4".
_SHEET_VALUE = re.compile(
    r"^\s*((sheet|page)\s*\d+(\s*(of|/)\s*\d+)?|of\s+\d+|rev\.?\s*no\.?\s*:?\s*\w{1,3})\s*$",
    re.IGNORECASE)

#: Words a table prints as COLUMN HEADINGS. A value made only of these is the
#: heading row, not an answer.
_HEADER_WORDS = frozenset(
    "rev rev. revision note notes by date status description checked approved "
    "prepared min max min. max. normal rated minimum maximum".split())

#: "[Note - 3]", "(Note A12)", "SEE NOTE 3", "Refer Note A9", "(6.12.1.9)".
_NOTE_REF = re.compile(
    r"^[\[(]?\s*((see|refer(\s+to)?)\s+)?notes?\s*[-–:.]?\s*[A-Z]?\d+[A-Z]?\s*[\])]?\.?$",
    re.IGNORECASE)
#: A clause number: bracketed "(6.1.11)", or bare with at least two dots
#: ("6.12.1.9"). A bare "0.911" is a NUMBER and is never matched.
_CLAUSE_REF = re.compile(r"^(\(\d+(\.\d+)+[a-z]?\)|\d+(\.\d+){2,}[a-z]?)$", re.IGNORECASE)

#: A label that is only a connector or a limit word is a piece of a label.
_FRAGMENT_WORDS = frozenset("to and or of min max min. max. minimum maximum".split())
#: "1 Facing": a table row keyed by a VALUE (the count 1), not by its heading.
_NUMBER_KEYED = re.compile(r"^\d+\s+[A-Za-z]+\.?$")

_BLOCK_WORDS = 15
_BLOCK_CHARS = 120


def _clean(text: str | None) -> str:
    return _WS.sub(" ", (text or "")).strip()


def noise_reason(label: str | None, value: str | None) -> str | None:
    """The rule this (label, value) row breaks, or None when it may be a field."""
    label, value = _clean(label), _clean(value)
    if _RULER.match(label):
        return RULER
    if _REVISION.search(label) or _REVISION.search(value) and len(value.split()) >= 2:
        return REVISION
    if _DOCUMENT_LABEL.match(label) or _DOCUMENT_GLUE.search(label) or _SHEET_VALUE.match(value):
        return DOCUMENT_ID
    words = [w.lower() for w in re.split(r"[\s/]+", value) if w]
    if words and all(w in _HEADER_WORDS for w in words):
        return HEADER_AS_VALUE
    if _NOTE_REF.match(value) or _CLAUSE_REF.match(value):
        return REFERENCE_ONLY
    if label.lower().rstrip(": ") in _FRAGMENT_WORDS or _NUMBER_KEYED.match(label):
        return FRAGMENT_LABEL
    if len(label.split()) > _BLOCK_WORDS or len(label) > _BLOCK_CHARS:
        return MERGED_BLOCK
    if _IDENTIFIER_LABEL.search(label) and _BARE_INTEGER.match(value):
        return IDENTIFIER_NUMBER
    return None
