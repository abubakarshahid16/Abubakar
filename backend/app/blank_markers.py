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
