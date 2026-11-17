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


# ---------------------------------------------------------------- order 14 lane D: "*" where a value is expected

#: A star that FILLS a value's place: a drawn blank with a star in it or at its end ("___*___", "*_____", "_____*") that touches
#: no letter or figure (so not a part number such as "ABC_*_DEF", "AB__*__CD" or "SK_*"); a lone star followed by a unit that ends the
#: cell, that is the end of the line or a column gap of two spaces or more ("FLUSH * m3/h", "* kW   EFFICIENCY"); or a cell
#: that is only a star. A unit followed by running words ("marked * in this sheet") is a sentence, and a lone star at the END
#: of a line is a footnote ("A216 WCB *"). One-letter units and units that are also words (a, c, f, k, n, s, v, w, h, in,
#: min) are left out of the lone form: after a star they are more often a word or a grade letter than a unit.
_UNIT = (
    r"\(?(?:m3/h|m3/hr|m³/h|l/s|l/min|gpm|kg/h|t/h|m|mm|cm|ft|kw|hp|bar|barg|bara|mbar|psi|psig|psia|pa|kpa|mpa"
    r"|°c|°f|deg\s?c|deg\s?f|%|rpm|r/min|dba|db\(a\)|db|kg|kg/m3|cp|cst|mm2/s|hz|kv|nm)\)?"
)
_FILL_STAR = re.compile(
    r"(?:(?<![A-Za-z0-9_])(?:_{2,}\*+_*|_*\*+_{2,}|_\*+_)(?![A-Za-z0-9_])"
    r"|(?:^|(?<=\s))\*+(?=[ ]+" + _UNIT + r"(?:[ ]{2,}|[ ]*$))"
    r"|^[ ]*\*+[ ]*$)",
    re.IGNORECASE | re.MULTILINE,
)

#: A line that OPENS with a star and then words is a legend or a footnote ("* vendor to advise / complete",
#: "*see note 3", "* values marked ___*___ are by the vendor"): the star points at other cells, it does not stand in one.
_NOTE_STAR = re.compile(r"^\s*\(?\*+\)?\s*[A-Za-z]")

#: A cell that is only a star and a unit ("* kW", "* (%)"): a value to fill, not a legend.
_UNIT_CELL = re.compile(r"^\s*\*+\s+" + _UNIT + r"\s*$", re.IGNORECASE)

#: A star that leads into a pointer ("* see note 3", "___* note 2", "* ref. 4"), or that a sentence names as a mark ("fields
#: marked * ...", "denoted *", "shown with *"): a note mark, not a blank.
_STAR_POINTER = re.compile(
    r"\*+\s*(?:see|note|notes|ref|remark|remarks)\b|\b(?:marked|denoted|indicated|shown|with)\s*\(?\*",
    re.IGNORECASE,
)

#: A clause number in brackets inside a label ("ALLOWED RANGE (9.4.2)"): it points at a book, it is no value.
_BRACKETED_CLAUSE = re.compile(r"\(\s*\d+(?:\.\d+){2,}\s*\)")


def star_fills_value(text: str | None) -> bool:
    """True when `text` (one printed line or one quoted cell) carries the enquiry sheet's "* = vendor to fill" mark where a
    value is expected (`_FILL_STAR`: a star in a drawn blank, a lone star before a unit that ends the cell, or a cell that
    is only a star) AND no figure stands on the line (a figure the line states wins: "RATED FLOW 24.8 m3/h *" states its
    flow, the star is that value's footnote). Never a note mark: a line that opens with a star and words (a legend), a star
    before "see / note / ref" or named by "marked / denoted / with", a lone star at the end of a line, a star glued to a
    word or a figure, an underscore part number. A clause number in brackets ("(6.1.11)") and a pointer number ("note 3",
    "Class 300") are no figure. Column gaps are read as printed (tabs as spaces). General: marks, units and figures only,
    no field name, no layout."""
    raw = (text or "").replace("\t", "    ")
    line = " ".join(raw.split())
    if not line or "*" not in line:
        return False
    legend = _NOTE_STAR.match(line) and not _UNIT_CELL.match(line)
    if legend or _STAR_POINTER.search(line):
        return False
    if not any(_FILL_STAR.search(part) for part in raw.splitlines()):
        return False
    return not _has_standalone_figure(_BRACKETED_CLAUSE.sub(" ", line))


def defers_value(text: str | None) -> bool:
    """THE deferral question for a printed line or a paper quote: a phrase marker ("By Contractor", "TBA", "vendor to
    advise": `names_a_marker`) OR the lone "*" vendor-to-fill mark where a value is expected (`star_fills_value`).
    `names_a_marker` stays phrases only, because the readers use it on single cells, where a lone star is handled by
    `classify`; the deferral finders read whole lines and quotes, so they ask this."""
    return names_a_marker(text) or star_fills_value(text)


# ---------------------------------------------------------------- FTU-16: what a quote holds besides its markers

#: A WHO phrase: says whose job the value is ("By Contractor", "as per vendor"). Alone it is ambiguous: a scope answer ("Painting: By
#: Contractor") or a value left to someone; only a field that asks for a value reads it as a value to be given.
_WHO = re.compile(
    r"\bby\s+(?:the\s+)?(?:contractor|vendor|supplier|manufacturer|seller|bidder|others)"
    r"(?:\s*/\s*(?:vendor|contractor|supplier|manufacturer))?\b"
    r"|\bas\s+per\s+(?:the\s+)?(?:vendor|supplier|manufacturer|contractor)\b",
    re.IGNORECASE,
)
#: A TO-BE-GIVEN phrase: the value itself is still to come ("TBA", "to be confirmed", "vendor to advise", "to follow").
_GIVEN = re.compile(
    r"\b(?:to\s+be\s+(?:advised|confirmed|determined|specified|furnished|provided|decided)"
    r"|(?:vendor|contractor|supplier|manufacturer|seller|bidder)\s+to\s+"
    r"(?:advise|confirm|specify|furnish|provide|state|determine|decide)"
    r"|tba|tbc|tbd|tbn|vta|to\s+follow)\b",
    re.IGNORECASE,
)
_DASH = re.compile(r"(?:^|(?<=[\s|(:;,]))[-\u2013\u2014]+(?=[\s|):;,]|$)")  # a hyphen, an en or an em dash
_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[.,/][A-Za-z0-9]+)*")
_UNIT_TOKEN = re.compile(
    r"^" + _UNIT.replace(r"\(?", "").replace(r"\)?", "") + r"$", re.IGNORECASE
)


def strip_markers(text: str | None) -> tuple[list[str], set[str]]:
    """(the words and figures `text` holds besides its markers and units, the kinds of marker found: "given" a to-be-given phrase, "who"
    a whose-job phrase, "fill" placeholder ink (a star or an underscore run), "dash" a dash standing alone). Pure; the words are the
    printed ones, in order. Whether what is left is the field's own label is the caller's question."""
    t = " ".join(str(text or "").split())
    kinds: set[str] = set()
    for pattern, kind in ((_GIVEN, "given"), (_WHO, "who")):
        if pattern.search(t):
            kinds.add(kind)
            t = pattern.sub(" ", t)
    if re.search(r"[_*]", t):
        kinds.add("fill")
        t = re.sub(r"[_*]+", " ", t)
    if _DASH.search(t):
        kinds.add("dash")
        t = _DASH.sub(" ", t)
    return [w for w in _TOKEN.findall(t) if not _UNIT_TOKEN.match(w)], kinds
