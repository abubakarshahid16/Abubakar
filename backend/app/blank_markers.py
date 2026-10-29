"""ONE HOME for "this datasheet cell says the value is not provided yet".

CRS quick wins (2026-09-27, audit crs.md defect 12). Three readers each kept
their own list - `datasheets._BLANK_MARKERS` / `_PLACEHOLDER`, the geometry
reader's `_BLANK_MARKER` and the `placeholders` list in
`reference/datasheet_checks.json` - and they disagreed: a lone `*` (the
enquiry-sheet convention "* = vendor to advise") was not blank to the text
reader because its placeholder rule needed two characters, "VENDOR TO ADVISE"
was blank to none of them, and "later" was blank to the geometry reader only.
CLAUDE.md rule 8: one list, read by every reader.

A BLANK IS MISSING INFORMATION, NEVER NON-COMPLIANCE. It says whose job the
value is, not that the equipment fails anything.

"N/A" IS NOT A BLANK. It is an answer - the field does not apply - and turning
it into "to be provided" would ask a vendor for a value the sheet has already
said does not exist. The same for "NONE", "NIL", "NOT REQUIRED", "NO".

Pure: no app imports, so the geometry reader (which imports nothing from the
app) can use it too.
"""

from __future__ import annotations

import re

#: A marker ANYWHERE in the cell makes it blank: "340 psig By Contractor" is a
#: provisional figure the vendor must confirm, not a value. Loose about the
#: separator because the real sheets write "By Contractor /Vendor",
#: "By Contractor / Vendor" and "(By Contractor, as per Code)".
_ANYWHERE = re.compile(
    r"\b(?:by\s+(?:the\s+)?(?:contractor|vendor|supplier|manufacturer|seller|bidder)"
    r"(?:\s*/\s*(?:vendor|contractor|supplier|manufacturer))?"
    r"|to\s+be\s+(?:advised|confirmed|determined|specified|furnished|provided|decided)"
    r"|(?:vendor|contractor|supplier|manufacturer|seller|bidder)\s+to\s+"
    r"(?:advise|confirm|specify|furnish|provide|state|determine|decide)"
    r"|tba|tbc|tbd)\b",
    re.IGNORECASE,
)

#: A marker that is the WHOLE cell. Kept apart from `_ANYWHERE` because these
#: words mean something else inside a longer value: "later" in "later
#: revision", "hold" in "hold-down bolts", "by others" in a scope sentence.
_WHOLE_CELL = re.compile(
    r"^(?:\*|-|–|—|\?+|vta|later|to\s+follow|hold|tbn|by\s+[a-z][\w\s/&.-]*"
    r"|as\s+per\s+(?:the\s+)?(?:vendor|supplier|manufacturer|contractor)"
    r"|[\[(]?\s*note\s*[-–—]?\s*\d+\s*[\])]?)$",
    re.IGNORECASE,
)

#: A cell of nothing but drawn placeholder ink - "_______", "****", "---".
_PLACEHOLDER = re.compile(r"^[\s_\-*.·–—]{2,}$")

#: ANSWERS, not blanks. Checked first so no rule above can swallow one.
_ANSWERS = frozenset({
    "n/a", "na", "n.a.", "n.a", "not applicable", "nil", "none", "not required",
    "no", "not req'd", "not reqd",
})


def classify(value: str | None) -> tuple[bool, str | None]:
    """`(is_blank, marker)` for one cell's text.

    `marker` is "empty" for an empty cell, "placeholder" for drawn ink, and
    otherwise the marker text as the sheet printed it ("*", "VENDOR TO
    ADVISE", "TBA"). `(False, None)` for anything that states a value -
    including "N/A", which is an answer.
    """
    text = " ".join((value or "").split())
    if not text:
        return True, "empty"
    folded = text.lower()
    if folded in _ANSWERS:
        return False, None
    if _WHOLE_CELL.match(text):
        return True, text
    if _PLACEHOLDER.match(text):
        return True, "placeholder"
    marker = _ANYWHERE.search(text)
    if marker:
        return True, marker.group(0).strip()
    return False, None


def names_a_marker(text: str | None) -> bool:
    """True when `text` CONTAINS a phrase marker ("vendor to advise", "TBA",
    "by contractor") - what a value says, never what a field is called. The
    whole-cell forms are left out on purpose: "BY PASS VALVE" is a label."""
    return bool(_ANYWHERE.search(text or ""))


def is_marker(text: str | None) -> bool:
    """True when the whole of `text` is a printed "not provided" marker (not
    an empty cell): the geometry reader's question about a cell's residue."""
    folded = " ".join((text or "").split())
    return bool(folded) and classify(folded)[0]


#: A cell that BEGINS with a figure (an optional sign or comparator, then digits): "10 barg By
#: Contractor", "<85 dBA TBC". Not a reference number before a phrase ("Note 3 - vendor to advise",
#: "Per API 520, by contractor", "Item 2 TBA", "ASME Class 300, TBC") and not a list number ("3. By
#: contractor").
_STARTS_WITH_FIGURE = re.compile(
    r"^[\s(]*[<>≤≥=~±+\-]*\s*\d+(?:[.,]\d+)*(?!\d)(?![.):]\s)"
)


#: A STANDALONE star or underscore run in a printed cell ("THERMAL * m3/h", "___*___ m3/h"): the enquiry
#: sheet's "vendor to advise" ink, which `classify` sees only when it is the whole cell. Not a star inside a
#: word or a size ("2*4", "5* stage").
_LONE_INK = re.compile(r"(?:^|[\s_(])(?:\*+|_{2,})(?=[\s_)]|$)")


#: A figure standing on its own in a cell ("RATED FLOW * 24.8 m3/h", "Head 78 m *"): not the digit of a
#: unit ("m3/h"), and not a number that only points elsewhere ("see note 3", "Item 2", "Class 300", "API 526").
_FIGURE = re.compile(r"(?<![A-Za-z0-9_.,/])(?<![A-Za-z]-)\d+(?:[.,]\d+)*(?!\d)")
_POINTER_WORD = re.compile(
    r"(?<![A-Za-z0-9])(?:note|item|class|ref|see|section|sec|clause|table|tab|page|no|para|paragraph|fig|figure"
    r"|annex|appendix|sheet|dwg|drawing|spec|rev|revision|part|pt|api|asme|iso|en|din|bs|iec|ansi|nace|std)"
    r"[.:#]*\s*$",
    re.IGNORECASE,
)


def _has_standalone_figure(text: str) -> bool:
    return any(
        not _POINTER_WORD.search(text[: m.start()]) for m in _FIGURE.finditer(text)
    )


def fact_is_placeholder(fact: dict, *, figure_wins: bool = False) -> bool:
    """True when the fact is marked blank, or its printed text or bare value is a
    placeholder. With a unit the printed text is "* m3/h", which alone looks
    like a value, so the bare value is judged too.

    `figure_wins`: for a test that asks whether a value IS STATED. A cell that
    begins with a figure ("10 barg By Contractor") states that figure (#725 F3:
    the phrase is a note on it), so the phrase after it does not make it a
    placeholder. A bare "*", "TBA", a phrase first, or a number that is only a reference ("Note 3",
    "Item 2", "Class 300") still does. A standalone `*` or `___` in the printed
    cell with no standalone figure anywhere in it ("THERMAL * m3/h", "Rated flow * see note 3") is a
    placeholder on every path; "RATED FLOW * 24.8 m3/h" states its figure."""
    if fact.get("is_blank"):
        return True
    printed = str(fact.get("field_value") or fact.get("raw_value") or "")
    starts = _STARTS_WITH_FIGURE.search(printed)
    if figure_wins and starts:
        return False
    if _LONE_INK.search(printed) and not _has_standalone_figure(printed):
        return True
    return any(
        v and classify(str(v))[0]
        for v in (
            fact.get("field_value"),
            fact.get("raw_value"),
            fact.get("blank_marker"),
        )
    )
