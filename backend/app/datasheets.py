"""Phase 4: reading a contractor datasheet into facts.

WHICH EXTRACTION PATH, AND WHY - DECIDED BY MEASURING, NOT BY HOPE

Step zero of this phase was to ingest the two real KOC datasheets and measure
what `tables.py` actually recovers from them. The answer was different for each,
and that is the whole design:

  EF1975-DAS-M-03 (centrifugal pump, 7 pages) - `find_tables()` recovers a real
  grid on 7 of 7 pages, and reading it shows genuine data:

      ['VAPOR PRESSURE:', 'bar a (psia)', '0.42 (6.09)']
      ['SPECIFIC GRAVITY:', '0.974 @ 170 OF']

  EF1975-DAS-I-06 (pressure safety valves, 5 pages) - `find_tables()` reports a
  table on 5 of 5 pages too, and the rate is MEANINGLESS: every one of them is
  the two-row title block. The actual PSV data is not in it at all.

That second result is the one that mattered. Counting "pages with a table" would
have reported 100% for a datasheet whose every value was missed - the same
mistake phase 3B made and recorded as honesty-audit entry 14. The content was
read before the rate was believed.

What I-06's data is actually in is TEXT BLOCKS with a numbered label-value
shape, which is what master plan section 10 asks to preserve:

    5 | Design/Operating pressure | 23.5 / 9 barg (Note - 3) | 46 | ...
    8 | Set pressure | 340 psig (By Contractor, as per Code) | 49 | ...

So this module runs BOTH paths and neither is a fallback for the other:
the grid path where a grid exists, and coordinate-ordered label-value pairing
over text blocks where it does not. A form is not a table and forcing it
through a table parser would have produced nothing while reporting success.

`tables.py` is not duplicated - it is imported and used as the grid path.
`claims.py` is not duplicated - it does every unit.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from . import claims, submittal_review, tables
from .db import connect

#: Where a datasheet says a value is not filled in yet.
#:
#: These are MISSING INFORMATION, NEVER NON-COMPLIANCE. A form that says "By
#: Contractor" is telling you whose job it is, not that the equipment fails
#: anything, and a blank recorded as 0 would become a spurious finding against
#: a vendor who has not been asked yet.
#:
#: Taken verbatim from the two real datasheets, which write it several ways -
#: "By Contractor /Vendor", "By Contractor / Vendor", "(By Contractor, as per
#: Code)" - so the pattern is deliberately loose about the separator.
_BLANK_MARKERS = re.compile(
    r"\b(?:by\s+(?:the\s+)?(?:contractor|vendor|supplier|manufacturer)"
    r"(?:\s*/\s*(?:vendor|contractor|supplier))?"
    r"|to\s+be\s+(?:advised|confirmed|determined)|tba|tbc|tbd)\b",
    re.IGNORECASE,
)

#: A cell holding nothing but placeholder rules - "_______", "****", "---".
#: A form draws them where a value goes, and they are blanks, not values.
_PLACEHOLDER = re.compile(r"^[\s_\-*.·–—]{2,}$")

#: A referenced standard named inside a datasheet. Both real KOC sheets name a
#: stack of them, and phase 5 needs to know which standards a submittal itself
#: invokes. Spellings vary by vendor, so each family is matched on its own
#: shape rather than by one loose pattern that would also match a tag number.
_REFERENCED_STANDARD = re.compile(
    r"\b("
    r"API\s*(?:RP\s*)?\d{3}(?:\s*Pt[-\s]?\d)?"
    r"|KOC-[A-Z]{2}-\d{3}(?:\s*Pt[-\s]?\d)?"
    r"|NACE\s*MR[-\s]?\d{4}"
    r"|ISO\s*\d{4,5}"
    # ASME ONLY WITH A COMPLETE IDENTIFIER. The previous alternative was
    # `ASME\s*[IVXB]+(?:\.\d+)?`, which matched the two characters "ASME B" out
    # of "ASME B31.3" and reported that as a missing reference. "ASME B" names
    # no document: it is a whole family of codes, an engineer cannot look it up,
    # and it can never match a library entry - so it was a citation that was
    # guaranteed to be unresolvable, reported as though it were a real gap.
    #
    # Two complete shapes, and nothing else: a B-series number with its decimal
    # (B16.5, B31.3), or a section in roman numerals with an optional division
    # (Sec VIII, Section VIII Div 1).
    r"|ASME\s*B\d{1,2}\.\d{1,3}(?:\.\d{1,3})?"
    r"|ASME\s*SEC(?:T|TION)?\.?\s*[IVX]+(?:\s*DIV(?:\.|ISION)?\s*\d+)?"
    r"|ASTM\s*[A-Z]\d{1,4}"
    r"|IEC\s*\d{5}"
    # `\d{3,4}` so a four-digit series (SAES-R-1101) is a citation. The
    # two-digit form is deliberately NOT here - see `library_identifier`.
    r"|SAES-[A-Z]-\d{3,4}"
    # Saudi Aramco material system specifications, which this corpus's own
    # submittal cites ten times and which were invisible to every rule that
    # reads this pattern.
    r"|\d{2}-SAMSS-\d{3}"
    r"|EN\s*\d{3,5}"
    r")\b",
    re.IGNORECASE,
)

#: A label-value row in a numbered form: "5 | Design pressure | 23.5 barg".
#: The leading number is the sheet's own line number, not data.
_NUMBERED_LABEL = re.compile(r"^\s*(?P<no>\d{1,3})\s*[|.\)]?\s*(?P<rest>\S.*)$")

#: A value with a unit at the end: "9970 Kg/hr", "23.5 barg", "0.42 (6.09)".
#:
#: PARENTHESES BELONG INSIDE A UNIT when it starts with a letter, because
#: "dB(A)" is one unit and "dB" is a different one - A-weighting is part of
#: what the number means. Without this, a datasheet writing "95 dB(A)" was
#: read as 95 dB, and the comparison engine then correctly REFUSED to compare
#: it against a 90 dB(A) limit: the flagship case of the whole product,
#: silently unevaluable because of a character class. Found by phase 5B's
#: end-to-end test.
#:
#: "0.42 (6.09)" is unaffected: the unit group must START with a letter, so a
#: bare parenthetical is not a unit and is handled as a dual-unit remainder.
_VALUE_UNIT = re.compile(
    r"^(?P<value>[-+]?\d[\d.,]*)\s*(?P<unit>[A-Za-z%µμ°][A-Za-z0-9/%()µμ°.\-]{0,12})?"
)

#: A cell that is nothing but a number - "340", "0.892". Used to decide
#: whether trailing letters were a unit or the start of prose.
_BARE_NUMBER = re.compile(r"[-+]?\d[\d.,]*")

#: A trailing "(ga)" / "(a)" / "(abs)" - a pressure REFERENCE, not a dual-unit
#: alternate. Exactly the reference words and nothing else, so "(6.09)" and
#: "(Note - 3)" stay remainders.
_REFERENCE_PARENTHETICAL = re.compile(
    r"^\(\s*(?:ga|g|gauge|a|abs|absolute)\s*\)$", re.IGNORECASE)

#: How many pages a label must appear on before it is page furniture.
#:
#: THREE, not two. A real field can legitimately repeat on two pages of a
#: multi-section datasheet - "Design pressure" for a shell and again for a
#: jacket - and killing those would lose real data to remove a title block.
#: Three is where repetition stops looking like a form and starts looking like
#: a header.
FURNITURE_PAGE_THRESHOLD = 3

#: Values that are an ANSWER without being a quantity. A tick-box question
#: answered "Yes" is a fact about the equipment; the same label with a person's
#: name beside it is not.
_CATEGORICAL_VALUES = frozenset({
    "yes", "no", "n/a", "na", "not applicable", "not required", "none",
    "applicable", "required",
})


#: A date, in the spellings a document actually writes one.
#:
#: A DATE IS NOT A QUANTITY, and `2024.08.27` parses as one: the value pattern
#: reads digits and dots, so a signature block's timestamp became a numeric
#: fact whose field was the signatory's name. Nothing downstream can tell that
#: from a measurement - it has a number and no unit, exactly like a specific
#: gravity.
_DATE_VALUE = re.compile(
    r"^\s*(?:\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}|\d{1,2}[.\-/]\d{1,2}[.\-/]\d{4})\s*$")


def is_date_value(value: str | None) -> bool:
    """True when the cell is a date rather than a measurement."""
    return bool(_DATE_VALUE.match(value or ""))


def is_categorical_value(value: str | None) -> bool:
    """True when a non-numeric value is still a real answer.

    A form asks "Stress relieved: Yes/No" and the answer carries no unit and no
    number. That is a fact. "Prepared by: A. Engineer" has the same shape and
    is not - it is a signature block.

    The list is CLOSED, deliberately. Anything open would let a free-text
    answer back in, and free text beside a label is exactly what produced
    fields called "emad kishta" and "al khafji onshore facility".
    """
    return " ".join((value or "").strip().lower().split()) in _CATEGORICAL_VALUES


def furniture_labels(pairs_by_page: dict[int, list[tuple[str, str]]],
                     *, threshold: int = FURNITURE_PAGE_THRESHOLD) -> set[str]:
    """Normalised label names that repeat across `threshold` or more pages.

    A HEADER IS NOT A FIELD, AND REPETITION IS HOW YOU TELL. A datasheet's
    title block, its document number, its revision box and its "Company
    General Use" footer appear on every page; a real field appears where the
    form asks for it. Nothing here knows what a header looks like - it is
    counted, not recognised - so it works on a form this system has never
    seen, which a list of known header strings would not.

    Counted per PAGE, not per occurrence: a label appearing five times on one
    page is a five-row section, not furniture.
    """
    pages_per_label: dict[str, set[int]] = {}
    for page, pairs in pairs_by_page.items():
        for label, _value in pairs:
            pages_per_label.setdefault(normalise_field_name(label), set()).add(page)
    return {name for name, pages in pages_per_label.items() if len(pages) >= threshold}


def section_heading(chunk_section: str | None) -> str | None:
    """The heading a fact sits under, or None. NEVER A WRONG VALUE.

    `chunks.section` is the heading the CHUNKER found, and on a ruled two-column
    form it is routinely another column's text. Measured on the real submittal:
    "concrete bearing stress" was filed under the section `3.5 bar (ga)`, and
    others under `3 Mark` and `5.7 Extent of positive material identification
    (PMI) :` - none of which is the section that row belongs to.

    A wrong section is worse than no section. It tells a reader the value came
    from a part of the document it did not come from, and it does so with the
    same confidence as a right one.

    So a heading is kept only when it can BE a heading: it must not parse as a
    measurement, and it must read like a label rather than like data. Anything
    else is NULL, which is the honest answer for "this form does not tell us".
    Locating the true heading needs the form's visual structure, and any rule
    for that written against one sheet's geometry would be a rule about that
    sheet.
    """
    text = (chunk_section or "").strip()
    if not text:
        return None
    if measure_value(text)[0] is not None:
        return None
    return text if is_field_label(text) else None


def is_field_label(text: str) -> bool:
    """True when `text` can be a FIELD LABEL rather than a value.

    THIS EXISTS BECAUSE THE FIRST VERSION INVENTED 427 FACTS. Running the
    extractor over the real PSV sheet produced rows whose "label" was
    `0.01cP By Contractor` and `10-05-497 & 556-05-512` - values and drawing
    numbers promoted into labels by a pairing that walked off the end of a
    block - and whose value was empty, so every one of them was then recorded
    as a required field left blank. 439 facts from a five-page sheet, 427 of
    them blank, is not extraction; it is noise with a schema.

    A label names something. So it must contain real words, must not itself
    parse as a measurement, and must not be mostly digits.
    """
    candidate = (text or "").strip()
    if len(candidate) < 3 or len(candidate) > 80:
        return False
    letters = sum(1 for ch in candidate if ch.isalpha())
    if letters < 3:
        return False
    # A cell that reads as a quantity is a value, whatever position it landed
    # in. `measure_value` is the authority, so there is one definition of
    # "this is a number" in this module rather than two that can drift.
    if measure_value(candidate)[0] is not None:
        return False
    # "10-05-497 & 556-05-512" is a drawing reference: more digits than letters.
    digits = sum(1 for ch in candidate if ch.isdigit())
    if digits > letters:
        return False
    # A blank marker is what a value says, never what a field is called.
    return not _BLANK_MARKERS.search(candidate)


#: Label text that is a section heading rather than a field.
_HEADING_WORDS = frozenset({
    "process data", "spring and bonnet", "accessories", "general",
    "liquid characteristics", "materials", "notes", "remarks",
})


def normalise_field_name(label: str) -> str:
    """A field label reduced to a comparable name.

    Lowercased, punctuation dropped, whitespace collapsed, and the sheet's
    trailing clause references removed - "Design/Operating pressure (Note - 3)"
    and "DESIGN / OPERATING PRESSURE:" are the same field asked twice.

    THE ORIGINAL LABEL IS KEPT BESIDE THIS, always. A normalised name is for
    matching; the reader is shown what the document actually wrote.
    """
    text = re.sub(r"\((?:note|see|ref)[^)]*\)", " ", label or "", flags=re.IGNORECASE)
    text = re.sub(r"[^\w\s/]", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def is_blank_value(value: str | None) -> tuple[bool, str | None]:
    """`(is_blank, marker)`. A blank is recorded as blank, never as 0.

    Three ways a datasheet says "not filled in": an empty cell, a rule of
    underscores or asterisks where the value goes, and an explicit
    "By Contractor / Vendor". All three are MISSING INFORMATION.
    """
    text = (value or "").strip()
    if not text:
        return True, "empty"
    if _PLACEHOLDER.match(text):
        return True, "placeholder"
    marker = _BLANK_MARKERS.search(text)
    if marker:
        # "217C By Contractor /Vendor" carries a number AND the marker. It is
        # still blank: the number is a provisional process figure and the sheet
        # is saying the vendor has to confirm it. Treating it as a filled value
        # would compare a placeholder against a standard.
        return True, marker.group(0).strip()
    return False, None


def referenced_standards(text: str) -> list[str]:
    """Standards named in the datasheet text, de-duplicated, in order found.

    Spacing is normalised so "API RP 520" and "API  RP520" are one entry, but
    the document's own spelling of each family is kept - this is a citation,
    and a citation is quoted rather than canonicalised.
    """
    seen: dict[str, str] = {}
    for match in _REFERENCED_STANDARD.finditer(text or ""):
        raw = " ".join(match.group(1).split())
        # PUNCTUATION IS NOT IDENTITY. The key dropped spaces only, so
        # "ASME Sec VIII Div.1" and "ASME Sec.VIII Div.1" - the same code,
        # written twice in one document - were two references, and the second
        # one inflated the denominator that reference coverage is measured
        # against. The digits are the identity; everything else is spelling.
        key = re.sub(r"[^A-Z0-9]", "", raw.upper())
        seen.setdefault(key, raw)
    return list(seen.values())


#: A cell that is a bare number, with an optional comparator and sign. The
#: test for "is there a value here that a unit could belong to".
_NUMERIC_CELL = re.compile(r"^\s*[<>=~±]{0,2}\s*[-+]?\d[\d,]*(?:\.\d+)?\s*$")

#: A trailing parenthesised or bracketed token at the end of a label.
_LABEL_TAIL = re.compile(r"^(?P<label>.+?)\s*[\(\[]\s*(?P<tail>[^()\[\]]{1,14})\s*[\)\]]\s*$")


def _unit_follows(parts: list[str], index: int) -> bool:
    """Is the cell at `index` a bare unit token?

    The discriminator between a VALUE and this form's own line numbers: a line
    number is never followed by a unit, and a measurement in a three-column row
    always is.
    """
    if index >= len(parts):
        return False
    candidate = (parts[index] or "").strip()
    if not candidate or len(candidate) > 14:
        return False
    base, _reference = claims.split_reference(candidate)
    return claims.is_unit(base or "")


def _is_numeric_cell(text: str) -> bool:
    return bool(_NUMERIC_CELL.match(text or ""))


def _unit_in_label(label: str) -> tuple[str, str | None]:
    """`(label without the unit, the unit)` - or the label unchanged and None.

    A form writes `Design pressure (barg)` and puts the bare number in the next
    cell. The unit is real and is in the label; nothing was looking there.

    THE GUARD IS THAT THE PARENTHETICAL MUST BE A UNIT. Datasheets end labels
    with "(Note - 3)", "(see 5.2)" and "(Note M2)" far more often than with a
    unit, and stripping those would rename the field - two different labels
    collapsing into one field name, which is how a value ends up filed under
    someone else's requirement.
    """
    match = _LABEL_TAIL.match(label or "")
    if match is None:
        return label, None
    tail = match.group("tail").strip()
    base, _reference = claims.split_reference(tail)
    if not claims.is_unit(base or ""):
        return label, None
    return match.group("label").strip(), tail


def split_label_value(cells: list[str]) -> list[tuple[str, str]]:
    """Label-value pairs out of one row of a form.

    A KOC sheet is TWO FORMS SIDE BY SIDE - "5 | Design pressure | 23.5 barg |
    46 | Bonnet material | CS" - so a row yields more than one pair and the
    leading line numbers are dropped. Pairing is strictly left to right, which
    is the order the sheet is read in.
    """
    parts = [c.strip() for c in cells if c is not None]
    pairs: list[tuple[str, str]] = []
    index = 0
    while index < len(parts):
        part = parts[index]
        # A bare line number introduces the pair that follows it.
        if re.fullmatch(r"\d{1,3}", part):
            index += 1
            continue
        if not part:
            index += 1
            continue
        label = part
        value = parts[index + 1] if index + 1 < len(parts) else ""
        if re.fullmatch(r"\d{1,3}", value) and not _unit_follows(parts, index + 2):
            # The next cell is the NEXT pair's line number, so this label has
            # no value on the sheet - which is a blank, not a missing row.
            #
            # UNLESS A UNIT FOLLOWS IT. A small integer is exactly what this
            # form's line numbers look like AND exactly what a temperature in
            # °C, a wall thickness in mm or a design life in years looks like.
            # Discarding every one of them as a line number threw away most of
            # the numeric rows on a page: measured at 4 facts recovered from 15
            # numeric rows. A unit in the next cell is what tells the two
            # apart, because a line number is never followed by one.
            value = ""
            index += 1
        else:
            index += 2
            # THE UNIT IN ITS OWN COLUMN. `| Concrete bearing stress | 8300 |
            # kPa |` is a three-column form, and pairing strictly left to right
            # made `kPa` the label of an empty-valued pair - a field named
            # after a unit, dropped later for having no value, taking the unit
            # with it. Measured on the corpus: every engineering row lost its
            # unit this way.
            #
            # Absorbed ONLY when the value is a number and the next cell is a
            # unit `claims` recognises. A word that is not a unit stays what it
            # was, so a genuine two-column form is untouched.
            if index < len(parts) and _is_numeric_cell(value):
                nxt = parts[index]
                base, _reference = claims.split_reference(nxt)
                if nxt and len(nxt) <= 14 and claims.is_unit(base or ""):
                    value = f"{value} {nxt}"
                    index += 1
        # THE UNIT INSIDE THE LABEL. `| Design pressure (barg) | 3.5 |` puts it
        # where nothing looked for it, so nothing recorded that a unit existed
        # at all - worse than the case above, which at least left a trace.
        #
        # Stripped only when the parenthetical IS a unit: "(Note - 3)" and
        # "(see 5.2)" are not, and must stay part of the label.
        label, carried = _unit_in_label(label)
        if carried and value and _is_numeric_cell(value):
            value = f"{value} {carried}"
        if normalise_field_name(label) in _HEADING_WORDS:
            continue
        # THE LABEL MUST BE A LABEL. See is_field_label: without this the
        # pairing promotes values and drawing numbers into field names and
        # then records each one as a required field left blank.
        if not is_field_label(label):
            continue
        pairs.append((label, value))
    return pairs


def pairs_from_blocks(page_text_blocks: list[tuple[float, float, str]]) -> list[tuple[str, str]]:
    """Label-value pairs from a form's TEXT BLOCKS, in reading order.

    THE PATH FOR A FORM THAT HAS NO GRID. Sorted by y then x, which is reading
    order on a page whose structure is visual rather than ruled - master plan
    section 10's "preserve text blocks and coordinates".

    Each block on these sheets is one row with its cells separated by newlines,
    which is what `split_label_value` consumes.
    """
    out: list[tuple[str, str]] = []
    for _y, _x, text in sorted(page_text_blocks, key=lambda b: (round(b[0], 1), b[1])):
        cells = [c.strip() for c in (text or "").split("\n") if c.strip()]
        if len(cells) < 2:
            continue
        match = _NUMBERED_LABEL.match(cells[0])
        if match and re.fullmatch(r"\d{1,3}", cells[0].strip()):
            cells = cells[1:]
        out.extend(split_label_value(cells))
    return out


def measure_value(raw: str) -> tuple[str | None, str | None, claims.Measurement | None]:
    """`(value, unit, measurement)` out of a datasheet cell.

    The unit handling is `claims.normalise` and nothing else. An unknown unit
    leaves `normalized_value` None - never 0 - and the raw spelling is kept, so
    `340 psig` and `9970 Kg/hr` are both recorded exactly as written whether or
    not this system can convert them.
    """
    text = (raw or "").strip()
    if not text:
        return None, None, None
    match = _VALUE_UNIT.match(text)
    if not match:
        return None, None, None
    value = match.group("value")
    unit = (match.group("unit") or "").strip() or None

    # A MEASUREMENT ENDS WHERE IT ENDS. PROSE AFTER IT MEANS IT WAS NEVER ONE.
    #
    # Both defects this guards against were found by running this function over
    # the real sheet, not imagined:
    #
    #   "2nd Stage Desalter"      -> value 2, unit "nd"   - a location
    #   "10-05-498 & 556-05-513"  -> value 10             - a P&ID number
    #
    # The discriminator is NOT whether the unit is recognised. Using the unit
    # table for this dropped "9970 Kg/hr", which is a real value whose compound
    # unit simply is not in `claims` - and dropping it would break the rule
    # that an unknown unit yields None rather than losing the number.
    #
    # What actually separates them is what FOLLOWS. A measurement is the whole
    # cell, give or take a parenthetical alternate that datasheets use for
    # dual units - "0.42 (6.09)" is bar and psia. Words after the number mean
    # the cell was a sentence that happened to start with a digit.
    remainder = text[match.end():].strip()
    # A PARENTHETICAL CAN BE PART OF THE UNIT RATHER THAN AN ALTERNATE.
    # `3.5 bar (ga)` is one measurement in gauge pressure; `0.42 (6.09)` is one
    # measurement given twice in different units. Both end in brackets, and
    # treating the first like the second dropped the reference - which is a
    # whole atmosphere, in the direction that makes a vessel look compliant.
    #
    # The discriminator is the WORD inside: only a reference marker is absorbed.
    if unit and _REFERENCE_PARENTHETICAL.match(remainder):
        unit = f"{unit} {remainder}"
    # A UNIT CAN CONTAIN A SPACE. "Deg C" and "wt %" are two tokens and one
    # unit, and the pattern above stops at the space - so the cell was read as
    # value `-10`, unit `Deg`, remainder `C`, and thrown away as prose.
    #
    # Absorbed ONLY when the two tokens together are a unit `claims` knows, so
    # "2nd Stage Desalter" is still refused: `nd Stage` is not a unit and the
    # cell stays what it was, a location.
    elif unit and remainder and len(remainder) <= 6 and claims.is_unit(f"{unit} {remainder}"):
        unit = f"{unit} {remainder}"
        remainder = ""
    # A TAG IS NOT A UNIT, AND THE SHAPE IS THE TELL.
    #
    # A bill-of-materials row reads "6 VEFV1101M" in ONE cell - the row index
    # and the equipment tag together - so the column rule never saw a unit
    # column and this pattern took the tag as the unit. Ten of the twenty
    # numeric facts on a real submittal were that.
    #
    # The datasheet side cannot simply demand a recognised unit the way
    # `requirements_3b.unit_token` does: this module's own docstring protects
    # "9970 Kg/hr", a real value whose compound unit is not in the table, and
    # refusing it would lose the number. So the test is SHAPE, not membership.
    # An identifier is long and mixes letters with digits; a unit is short, and
    # the few that carry a digit (m3, g/m2, dB(A)) are in the table already.
    if unit and not claims.is_unit(claims.split_reference(unit)[0] or "") \
            and len(unit) > 5 and any(ch.isdigit() for ch in unit):
        return None, None, None
    if remainder and not remainder.startswith("("):
        return None, None, None
    return value, unit, claims.normalise(value, unit or "")


# ------------------------------------------------------------ persistence


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _scope_clause(allowed_document_ids: frozenset[str], column: str) -> tuple[str, list[str]]:
    """`submittal_review._scope_clause`'s rule, restated for this module."""
    if not allowed_document_ids:
        return " WHERE 1 = 0", []
    marks = ",".join("?" for _ in allowed_document_ids)
    return f" WHERE {column} IN ({marks})", sorted(allowed_document_ids)


class FactError(ValueError):
    """A fact could not be recorded. Carries a reason, never a row."""


def create_fact(
    *, submittal_document_id: str, chunk_id: str, field_label: str,
    raw_value: str | None, page: int | None, section: str | None = None,
    source_text: str | None = None, review_run_id: str | None = None,
    confidence: float | None = None, extraction_method: str = "extracted",
) -> dict:
    """Record one fact. REFUSES a fact whose citation does not resolve.

    The same three checks `standards.create_requirement` makes, for the same
    reasons: a fact without a resolving chunk is an assertion, a chunk from
    another document is a citation that opens the wrong page, and a page
    outside the chunk is a citation that opens the right document in the wrong
    place.

    A BLANK IS RECORDED AS A FACT, not skipped. "Set pressure: By Contractor"
    is information - it says the field exists, is required, and is not filled
    in - and skipping it would make a missing value indistinguishable from a
    field the sheet never asked for.
    """
    submittal_review.ensure_schema()
    chunk = connect().execute(
        "SELECT id, document_id, page_start, page_end FROM chunks WHERE id = ?",
        (chunk_id,)).fetchone()
    if chunk is None:
        raise FactError(f"no chunk {chunk_id!r}: the citation does not resolve")
    if chunk["document_id"] != submittal_document_id:
        raise FactError("the cited chunk belongs to a different document")
    if page is not None and not (chunk["page_start"] <= page <= chunk["page_end"]):
        raise FactError(f"page {page} is outside the cited chunk")

    blank, marker = is_blank_value(raw_value)
    value, unit, measurement = (None, None, None) if blank else measure_value(raw_value or "")
    # THE UNIT AS THE SHEET WROTE IT, AND THE UNIT THE TABLE UNDERSTANDS, kept
    # apart. `raw_unit` is `bar (ga)` because that is what the document says and
    # a reader checking a citation reads the document's words; `unit` is `bar`
    # because that is what `claims` can convert; `unit_reference` is `gauge`
    # because losing it changes the number by an atmosphere.
    raw_unit = unit
    base_unit, unit_reference = claims.split_reference(unit)
    if unit_reference is not None:
        # Re-normalised against the BASE, which the table knows. Without this
        # every gauge pressure kept a null normalised value.
        measurement = claims.normalise(value or "", base_unit or "")
    # `unit` HOLDS A UNIT OR NOTHING. A bill-of-materials row reads "6
    # VEFV1101M" and the tag landed in the unit column - measured at ten of
    # twenty numeric facts on the real submittal - where it reads as an
    # engineering unit to anything downstream. The spelling is still kept in
    # `raw_unit`, because the document did write it.
    unit = base_unit if claims.is_unit(base_unit or "") else None
    now = _now()
    row = {
        "id": str(uuid.uuid4()),
        "review_run_id": review_run_id,
        "submittal_document_id": submittal_document_id,
        "chunk_id": chunk_id,
        "field_name": normalise_field_name(field_label),
        "field_label": field_label,
        "field_value": (raw_value or "").strip() or None,
        "raw_value": value,
        # AS READ, always - even when normalisation fails. The document
        # said it, and a unit this system cannot convert is still evidence.
        "raw_unit": raw_unit,
        "unit_reference": unit_reference,
        "normalized_value": measurement.normalized_value if measurement else None,
        "normalized_unit": measurement.normalized_unit if measurement else None,
        "unit": unit,
        "is_blank": 1 if blank else 0,
        "blank_marker": marker,
        "page": page if page is not None else chunk["page_start"],
        "section": section,
        "source_text": source_text or (raw_value or ""),
        "extraction_method": extraction_method,
        "confidence": confidence,
        "created_at": now,
        "updated_at": now,
    }
    conn = connect()
    with conn:
        conn.execute(
            """INSERT INTO submittal_facts
               (id, review_run_id, submittal_document_id, chunk_id, field_name,
                field_label, field_value, raw_value, raw_unit,
                normalized_value, normalized_unit, unit, is_blank,
                blank_marker, page, section, source_text, extraction_method,
                confidence, created_at, updated_at, unit_reference)
               VALUES (:id, :review_run_id, :submittal_document_id, :chunk_id,
                       :field_name, :field_label, :field_value, :raw_value,
                       :raw_unit, :normalized_value, :normalized_unit, :unit,
                       :is_blank, :blank_marker, :page, :section, :source_text,
                       :extraction_method, :confidence, :created_at,
                       :updated_at, :unit_reference)""", row)
    return row


def _pairs_from_pdf_page(stored_path: str, page_no: int) -> list[tuple[str, str]]:
    """Text-block label-value pairs for one page, in reading order."""
    try:
        import fitz
    except ImportError:  # pragma: no cover
        return []
    try:
        with fitz.open(stored_path) as doc:
            if not (1 <= page_no <= doc.page_count):
                return []
            blocks = [(b[1], b[0], b[4]) for b in doc[page_no - 1].get_text("blocks")]
            return pairs_from_blocks(blocks)
    except Exception:  # noqa: BLE001 - an unreadable page yields no pairs
        return []


def extract_facts(
    document_id: str, *, allowed_document_ids: frozenset[str],
    review_run_id: str | None = None, replace: bool = True,
) -> dict:
    """Read one datasheet into facts, by whichever path its pages support.

    BOTH PATHS RUN, and neither is a fallback for the other: the grid path for
    pages `tables.py` can parse, and the text-block path for pages it cannot -
    which on the real PSV sheet is every page that matters.

    FACTS ARE PER DOCUMENT AND REUSED ACROSS RUNS (master plan section 24,
    "reuse cached extraction"). `review_run_id` records which run first
    produced them and is nullable, so a second review of the same datasheet
    does not re-read the PDF.

    A page that yields nothing is reported as unparsed WITH A REASON and lowers
    completeness. Nothing is invented from a page that could not be read.
    """
    submittal_review.ensure_schema()
    where, args = _scope_clause(allowed_document_ids, "document_id")
    chunks = connect().execute(
        "SELECT c.id, c.page_start, c.page_end, c.section, c.kind, c.text,"
        "       d.stored_path"
        " FROM chunks c JOIN documents d ON d.id = c.document_id" + where +
        " AND c.document_id = ? AND c.retrievable = 1 ORDER BY c.ordinal",
        [*args, document_id],
    ).fetchall()
    empty = {"document_id": document_id, "facts": 0, "blanks": 0,
             "pages_read": 0, "pages_unparsed": 0, "parsed_fraction": None,
             "referenced_standards": [], "unparsed": []}
    if not chunks:
        return empty

    if replace:
        conn = connect()
        with conn:
            conn.execute(
                "DELETE FROM submittal_facts"
                " WHERE submittal_document_id = ? AND confirmed_by IS NULL",
                (document_id,))

    stored_path = chunks[0]["stored_path"]
    # KEYED BY EVERY PAGE A CHUNK COVERS, not by the page it starts on.
    #
    # A chunk spanning pages 1 to 3 was filed under page 1 only, so page 2 was
    # never a key, never handed to the page parsers, and never reported as
    # unparsed either - it simply did not exist as far as extraction was
    # concerned. Any page fully enclosed by a multi-page chunk disappeared the
    # same way, which is a property of chunking rather than of any one form.
    #
    # The enclosing chunk is a valid citation for those pages: `create_fact`
    # requires the page to fall within the chunk's span, and it does.
    by_page: dict[int, list] = {}
    for chunk in chunks:
        for page_no in range(chunk["page_start"], (chunk["page_end"] or chunk["page_start"]) + 1):
            by_page.setdefault(page_no, []).append(chunk)

    written = blanks = 0
    unparsed: list[dict] = []
    corpus_text: list[str] = []

    # EVERY PAGE IS PAIRED BEFORE ANY FACT IS WRITTEN, because the furniture
    # rule is a statement about the DOCUMENT and cannot be decided one page at
    # a time: a label is a header precisely when it turns up on page after
    # page, which the first page cannot know.
    pairs_by_page: dict[int, list[tuple[str, str]]] = {}
    for page in sorted(by_page):
        found: list[tuple[str, str]] = []
        for shape in tables.parse_page_tables(stored_path, page):
            for row in shape:
                found.extend(split_label_value(list(row)))
        found.extend(_pairs_from_pdf_page(stored_path, page))
        pairs_by_page[page] = found
    furniture = furniture_labels(pairs_by_page)

    for page, page_chunks in sorted(by_page.items()):
        pairs = pairs_by_page[page]
        chunk = page_chunks[0]
        corpus_text.extend(c["text"] or "" for c in page_chunks)
        page_written = 0
        seen: set[str] = set()
        for label, value in pairs:
            key = f"{normalise_field_name(label)}|{(value or '').strip()}"
            if not label.strip() or key in seen:
                continue
            seen.add(key)
            blank, marker = is_blank_value(value)
            parsed_value, _unit, _measure = measure_value(value or "")
            # WHAT COUNTS AS A FACT. This is the line that stops the
            # extractor inventing them.
            #
            # A fact is recorded only where the sheet actually says
            # something: a value that parses as a quantity, or a value the
            # sheet EXPLICITLY marks as the contractor's to fill - "By
            # Contractor", "TBA", a drawn rule of underscores.
            #
            # AN EMPTY ADJACENT CELL IS NOT EVIDENCE OF ANYTHING. Measured
            # on the real PSV sheet, treating it as a blank required field
            # produced 375 phantom blanks out of 387 rows: every stray text
            # block became a field somebody had failed to fill in. An empty
            # cell beside a label is a pairing artefact of a two-column
            # form, not a statement by the document, and recording it
            # manufactures findings against a vendor who was never asked.
            if is_date_value(value):
                # A timestamp is not a measurement. Left here rather than in
                # `measure_value` so the cell still reads as what it is
                # everywhere else; it is only as a FACT that it is wrong.
                continue
            if parsed_value is None and marker in (None, "empty")                     and not is_categorical_value(value):
                # A LABEL WITH FREE TEXT BESIDE IT IS NOT A FACT. "Prepared by:
                # A. Engineer" and "Facility: Al Khafji" have exactly the shape
                # of a filled-in field and state nothing about the equipment.
                # A quantity, an explicit blank, or a closed categorical answer
                # - anything else is a caption.
                continue
            if normalise_field_name(label) in furniture:
                # Page furniture: this label appeared on three or more pages,
                # so it is the title block or the footer, not a field.
                continue
            try:
                create_fact(
                    submittal_document_id=document_id, chunk_id=chunk["id"],
                    field_label=label.strip(), raw_value=value, page=page,
                    section=section_heading(chunk["section"]),
                    review_run_id=review_run_id,
                    confidence=0.6,
                )
            except FactError:
                continue
            page_written += 1
            written += 1
            if blank:
                blanks += 1
        if page_written == 0:
            unparsed.append({
                "page": page,
                "reason": "no label-value pairs recovered from this page",
            })

    pages_read = len(by_page)
    return {
        "document_id": document_id,
        "facts": written,
        "blanks": blanks,
        "pages_read": pages_read,
        "pages_unparsed": len(unparsed),
        "parsed_fraction": (round((pages_read - len(unparsed)) / pages_read, 3)
                            if pages_read else None),
        "unparsed": unparsed,
        "referenced_standards": referenced_standards(" ".join(corpus_text)),
    }


def list_facts(document_id: str, *, allowed_document_ids: frozenset[str],
               blanks_only: bool = False) -> list[dict]:
    """One datasheet's facts, under the caller's grants, joined to their chunk."""
    submittal_review.ensure_schema()
    where, args = _scope_clause(allowed_document_ids, "f.submittal_document_id")
    sql = ("SELECT f.*, c.page_start AS chunk_page FROM submittal_facts f"
           " LEFT JOIN chunks c ON c.id = f.chunk_id" + where +
           " AND f.submittal_document_id = ?")
    params = [*args, document_id]
    if blanks_only:
        sql += " AND f.is_blank = 1"
    sql += " ORDER BY f.page, f.field_name"
    return [{**dict(r), "citation_resolves": r["chunk_page"] is not None}
            for r in connect().execute(sql, params).fetchall()]
