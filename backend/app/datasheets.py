"""Phase 4: reading a contractor datasheet into facts.

WHICH EXTRACTION PATH, AND WHY - DECIDED BY MEASURING, NOT BY HOPE

Step zero of this phase was to ingest the two real client datasheets and measure
what `tables.py` actually recovers from them. The answer was different for each,
and that is the whole design:

  DS-0000-DAS-M-01 (centrifugal pump, 7 pages) - `find_tables()` recovers a real
  grid on 7 of 7 pages, and reading it shows genuine data:

      ['VAPOR PRESSURE:', 'bar a (psia)', '0.42 (6.09)']
      ['SPECIFIC GRAVITY:', '0.974 @ 170 OF']

  DS-0000-DAS-I-01 (pressure safety valves, 5 pages) - `find_tables()` reports a
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

import json

from . import claims, orphan_guard, page_ledger, provenance, submittal_review, tables
from .config import settings
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

#: A referenced standard named inside a datasheet. Both real client sheets name a
#: stack of them, and phase 5 needs to know which standards a submittal itself
#: invokes. Spellings vary by vendor, so each family is matched on its own
#: shape rather than by one loose pattern that would also match a tag number.
_REFERENCED_STANDARD = re.compile(
    r"\b("
    r"API\s*(?:RP\s*)?\d{3}(?:\s*Pt[-\s]?\d)?"
    # KOC discipline codes are ONE letter (E electrical, G general, I
    # instrumentation, P painting, Q quality...) or TWO (ME mechanical
    # equipment, MP mechanical piping...) depending on the discipline, not a
    # fixed width - a real client datasheet's own reference list names both in
    # the same document. `{1,2}` reads either; a fixed `{2}` silently dropped
    # every one-letter citation (KOC-E-003, KOC-P-001, ...) as invisible to
    # the citation pattern, never applicable and never reported missing.
    r"|KOC-[A-Z]{1,2}-\d{3}(?:\s*Pt[-\s]?\d)?"
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
    fields called "emad kishta" and "onshore facility a".
    """
    return " ".join((value or "").strip().lower().split()) in _CATEGORICAL_VALUES


#: B4. A label naming a LIMIT of a measurable quantity - a limit word and a
#: quantity noun. Generic engineering vocabulary, not per-document: it only
#: ever REFUSES a checkbox answer, never a number.
_LIMIT_WORD = re.compile(
    r"\b(?:max|min|maximum|minimum|rated|normal|design|operating)\b", re.IGNORECASE)
_QUANTITY_NOUN = re.compile(
    r"\b(?:pressure|temperature|temp|flow|capacity|head|speed|power|density|"
    r"viscosity|diameter|weight|volume|thickness|level|rate|efficiency|npsh\w*|"
    r"current|voltage|frequency|noise|gravity)\b", re.IGNORECASE)


def checkbox_on_quantity(label: str | None, value: str | None) -> bool:
    """A closed yes/no answer sitting on the LIMIT of a measurable quantity.

    B4, measured on the pump regression sheet: a two-line question ("MAXIMUM
    DISCHARGE PRESSURE TO INCLUDE" / indented "MAX RELATIVE DENSITY") answered
    YES was split, and the second line was stored "max relative density =
    YES". A density cannot be YES - the answer belongs to a question the
    reader did not reassemble - so the pair is refused and the value stays
    UNKNOWN. A real question ("VARIABLE SPEED REQUIRED" = NO) carries no limit
    word and is untouched; a number on a limit ("MAX RELATIVE DENSITY" = 1.02)
    is not a checkbox and is untouched.
    """
    answer = (value or "").strip(" _*").strip().lower()
    if answer not in _CATEGORICAL_VALUES:
        return False
    text = label or ""
    return bool(_LIMIT_WORD.search(text) and _QUANTITY_NOUN.search(text))


def states_a_value(value: str | None) -> bool:
    """Does this cell say something a FACT can be made of?

    A quantity (one number, or a range - `-3 to 55 C` is a value stated as
    two), an explicit blank ("By Contractor", "TBA", a drawn rule), or a
    closed categorical answer. Anything else beside a label is a caption:
    "Prepared by: A. Engineer" has the shape of a filled field and states
    nothing about the equipment.

    ONE HOME (#179). `extract_facts` gates facts on it, and `furniture_labels`
    counts only these as answers - a title block's stray fragment (`OF` from
    "SHEET 3 OF 11") is not an answer, and counting it as one made a title-
    block row look like an answered field.
    """
    _blank, marker = is_blank_value(value)
    parsed, _unit, _measure = measure_value(value or "")
    if parsed is None and parse_range(value) is not None:
        parsed = "range"
    return not (parsed is None and marker in (None, "empty")
                and not is_categorical_value(value))


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

    AND THE VALUE DECIDES, NOT THE LABEL ALONE. Repetition by itself was wrong
    and it cost a whole document: `DS-0000-DAS-I-01` is FIVE INSTANCES OF ONE
    FORM, one pressure safety valve per page, so every real field - `Set
    pressure`, `Relieving temperature`, `Density at relieving temper.` -
    appears on every page. The page-count rule classified the entire form as a
    title block and the sheet extracted ZERO facts from 162 rows that carry a
    value. The same document had yielded 37 facts before this rule existed.

    A title block repeats the SAME TEXT: the document number is the document
    number on every page. A form field repeats the same LABEL against a
    DIFFERENT ANSWER, because that is what the form is for. So a label is
    furniture only when it repeats on enough pages AND says the same thing
    every time - two or more distinct answers and it is a field, whatever it
    is called.

    AND EMPTINESS IS THE SECOND HALF OF IT. Distinct answers alone is not
    enough, measured on the drum sheet: its title block `ONSHORE FACILITY
    A` is empty on six of the eight pages it appears on and picks up a
    stray neighbouring fragment on the other two - `D` on page 5, `2003` on
    page 7. That is two distinct non-empty answers, so a distinctness test
    alone promotes the title block to a field and `2003` becomes a fact.

    A form field is ANSWERED. It carries a value on the pages it appears on,
    because that is what somebody filled the form in for. A header carries
    text on the odd page where the extractor caught a neighbouring cell. So a
    repeating label is a FIELD only when BOTH hold:

      1. it has two or more distinct non-empty answers, and
      2. it is non-empty on MORE THAN HALF the pages it appears on.

    Otherwise it is furniture. `ONSHORE FACILITY A` fails the second
    at 2 of 8; `Set pressure` passes both at 4 distinct answers on 4 of 4
    pages.

    The residual, named so nobody assumes it is covered: a real field whose
    answer is identical on every page - `Lifting lever: Required` on all five
    valves - has one distinct answer, fails the first condition, and is still
    stripped. That is the accepted cost of the rule; it is a smaller loss than
    the whole form, and it is measured in
    docs/cold-evaluation-psv-2026-09-19.md rather than guessed at.
    """
    pages_per_label: dict[str, set[int]] = {}
    answered_pages: dict[str, set[int]] = {}
    answers_per_label: dict[str, set[str]] = {}
    for page, pairs in pairs_by_page.items():
        for label, value in pairs:
            name = normalise_field_name(label)
            pages_per_label.setdefault(name, set()).add(page)
            answered_pages.setdefault(name, set())
            answers_per_label.setdefault(name, set())
            # Compared as the reader sees it: case and spacing are spelling,
            # not different answers.
            answer = " ".join((value or "").split()).lower()
            # AN ANSWER IS SOMETHING A FACT COULD BE MADE OF (#179). The
            # vessel sheet's title-block row `<site name> | ... | OF` printed
            # the fragment `OF` (from "SHEET n OF 11") on four pages and a
            # stray `2003` on a fifth: counted as answers, that is "two
            # distinct answers on most pages", a FIELD - and `2003` became a
            # fact. `OF` answers nothing; only a value `states_a_value`
            # accepts is evidence that somebody filled the form in.
            if answer and states_a_value(value):
                answered_pages[name].add(page)
                answers_per_label[name].add(answer)
    furniture = set()
    for name, pages in pages_per_label.items():
        if len(pages) < threshold:
            continue
        distinct = len(answers_per_label[name])
        answered = len(answered_pages[name])
        is_field = distinct >= 2 and answered * 2 > len(pages)
        if not is_field:
            furniture.add(name)
    return furniture


# ------------------------------------------- degrees, ranges, compounds

#: `121OC` is 121 °C. The PSV sheet renders the degree sign as a capital or
#: lower-case O, and the extracted text carries it literally.
#:
#: ONLY IMMEDIATELY AFTER A DIGIT, with nothing between. `doc`, `bloc` and
#: `Proc.` end in the same two letters and are words; `121OC` cannot be
#: anything but a temperature. The lookbehind is what keeps the rule from
#: rewriting prose.
#:
#: AND THE MASCULINE ORDINAL `º` (U+00BA), which the same valve sheet uses
#: for the degree sign in `220ºC` and which looks identical on the page.
#: Unread, `201ºC` was not a quantity at all (#179).
_DEGREE_GLYPH = re.compile(r"(?<=\d)[Ooº]([CF])\b")


def normalise_degree_glyph(text: str | None) -> str:
    """`121OC` / `220ºC` -> `121°C` / `220°C`. Everything else untouched."""
    return _DEGREE_GLYPH.sub(r"°\1", text or "")


#: `-3 to 55 C`, `4-28 cP`, `0 to 100%`.
#:
#: THE HYPHEN IS ONLY A RANGE BETWEEN TWO NUMBERS, and the whole cell must be
#: the range. `10-05-497` is a P&ID reference: it starts like a range and then
#: carries `-497`, which lands in `rest` and refuses the match. A parenthetical
#: remainder is allowed for the same reason `measure_value` allows one - a
#: datasheet writes `(Note - 3)` after a real quantity.
_RANGE = re.compile(
    r"^\s*(?P<lo>[-+]?\d[\d.,]*)\s*(?:to|through|\.\.\.|–|—|-)\s*"
    r"(?P<hi>[-+]?\d[\d.,]*)\s*"
    r"(?P<unit>[A-Za-z%µμ°][A-Za-z0-9/%()µμ°.\-]{0,12})?\s*(?P<rest>.*)$",
    re.IGNORECASE)


def parse_range(raw: str | None) -> tuple[str, str, str | None] | None:
    """`(low, high, unit)` when the cell is a range, else None.

    A RANGE IS TWO NUMBERS AND ONE UNIT, and both numbers are kept. Nothing
    here averages them or picks one: an ambient of `-3 to 55 C` has no single
    value, and inventing one is how a range becomes a wrong verdict.

    The low must not exceed the high. That is what stops `10-05` - the first
    half of a drawing number - reading as a range from ten to five, and a
    genuinely descending range is refused rather than silently reordered.

    A RANGE WITHOUT A UNIT IS NOT A RANGE HERE. The drum sheet lists its own
    contents - `Mechanical Notes` against `8 to 9`, meaning sheets 8 to 9 -
    and a unitless pair of small integers beside a prose label is a cross
    reference, not a quantity. Requiring the unit loses nothing that could
    ever have been compared: `compare` needs a dimension to compare within,
    so a unitless range would reach it and be refused anyway. The raw text is
    kept either way, and the cell falls through to the ordinary value gate
    exactly as it did before ranges existed.

    The unit may arrive three ways and all three count: written on the range
    itself (`4-28 cP`), distributed from the other half of a compound value
    by `split_compound_pair` (`23.5 / 11.03 barg`), or recovered by the
    degree-glyph rule (`-3 to 121OC`). A bare symbol is a unit: `0 to 100%`
    is a percentage range and parses.
    """
    text = normalise_degree_glyph(" ".join((raw or "").split()))
    if not text:
        return None
    match = _RANGE.match(text)
    if not match:
        return None
    rest = (match.group("rest") or "").strip()
    if rest and not rest.startswith("("):
        return None
    # Named apart from `measure_value`'s local of the same shape: two
    # identical lines in one module make a mutation ambiguous, and the
    # harness reports that as no evidence rather than as a pass.
    range_unit = (match.group("unit") or "").strip() or None
    if range_unit and _looks_like_an_identifier(range_unit):
        return None
    if range_unit is None:
        return None
    low, high = match.group("lo"), match.group("hi")
    left, right = claims.parse_value(low), claims.parse_value(high)
    if left is None or right is None or left > right:
        return None
    return low, high, range_unit


#: A separator that joins two field names into one label. `&` must stand
#: alone between spaces - `P&ID` is one word and splitting it produced a field
#: called `P` - while `/` is written tight in `Design/Operating pressure`.
_COMPOUND_SEPARATORS = (("/", r"\s*/\s*"), ("&", r"\s+&\s+"))

#: Anything inside brackets is not a split point. `Specific heat ratio
#: (Cp/Cv)` carries a solidus that belongs to the ratio, and splitting on it
#: turned a real value into an unparsed compound.
_BRACKETED = re.compile(r"\([^()]*\)|\[[^\[\]]*\]")


def _outside_brackets(text: str) -> str:
    """The text with every bracketed span blanked, for separator counting."""
    return _BRACKETED.sub(lambda m: " " * len(m.group(0)), text or "")


def compound_label_parts(label: str) -> tuple[str, list[str]] | None:
    """`(separator, [name, name])` when the label names two fields, else None.

    A datasheet writes two questions on one line: `Design/Operating pressure`
    is the design pressure and the operating pressure, and
    `Ambient Temperature & Rel. humidity` is two different quantities sharing
    a row. Recorded as one field, the row is unusable: the value is a pair and
    no comparison can be made against it.

    THE SHARED WORD TRAVELS. `Design/Operating pressure` splits into `Design`
    and `Operating pressure`, and the first half is not a field name until the
    noun is carried across - the split is `Design pressure` and `Operating
    pressure`. It travels the other way too: `Back press. Constant/Variable`
    gives `Back press. Constant` and `Back press. Variable`. Which way is
    decided by which side is a bare word, because that is the side missing the
    noun.
    """
    text = " ".join((label or "").split())
    if not text:
        return None
    masked = _outside_brackets(text)
    for sep, pattern in _COMPOUND_SEPARATORS:
        hits = [m for m in re.finditer(pattern, masked)]
        if len(hits) != 1:
            continue
        cut = hits[0]
        left = text[:cut.start()].strip()
        right = text[cut.end():].strip()
        if not left or not right:
            continue
        left_words, right_words = left.split(), right.split()
        if len(left_words) == 1 and len(right_words) > 1:
            # The noun is on the right: "Design" + "Operating pressure".
            left = f"{left} {right_words[-1]}"
        elif len(right_words) == 1 and len(left_words) > 1:
            # The noun is on the left: "Back press. Constant" + "Variable".
            right = f"{' '.join(left_words[:-1])} {right}"
        if not is_field_label(left) or not is_field_label(right):
            return None
        return sep, [left, right]
    return None


def _part_unit(text: str) -> str | None:
    """The unit of one half of a compound value, range or single."""
    found = parse_range(text)
    if found is not None:
        return found[2]
    return measure_value(text)[1]


def split_compound_pair(label: str, value: str) -> list[tuple[str, str]]:
    """One label-value pair in, one or two out.

    TWO FACTS ONLY WHEN THE VALUE AGREES WITH THE LABEL. The label says two
    fields and the value must say two answers, separated the same way and the
    same number of times. `Design/Operating pressure` against
    `23.5 / 11.03 barg` is a pair of pressures; the same label against a
    single `23.5 barg` is a cell this function will not guess at, and it comes
    back as one pair whose value `create_fact` then refuses to parse.

    A TRAILING UNIT DISTRIBUTES, AND ONLY WHEN NOTHING ELSE CARRIES ONE.
    `23.5 / 11.03 barg` is two pressures in barg, so the unit reaches both.
    `10.15psig/97.18psig` already gives each half its own and nothing is
    added. A unit invented onto a half that had one of its own would be the
    worst outcome available here.
    """
    parts = compound_label_parts(label)
    if parts is None:
        return [(label, value)]
    sep, names = parts
    pattern = dict(_COMPOUND_SEPARATORS)[sep]
    text = " ".join((value or "").split())
    # Cut the ORIGINAL text at the offsets found in the masked copy, so a
    # bracketed note that was masked for counting is still carried onto its
    # own half. ONE COUNT DECIDES, below: an earlier length check here was a
    # second guard on the same question, and a rule with two homes is a rule
    # whose mutation proves nothing.
    cuts = [m.start() for m in re.finditer(pattern, _outside_brackets(text))]
    ends = [m.end() for m in re.finditer(pattern, _outside_brackets(text))]
    values, start = [], 0
    for cut, end in zip(cuts, ends):
        values.append(text[start:cut].strip())
        start = end
    values.append(text[start:].strip())
    if len(values) != len(names) or not all(values):
        return [(label, value)]
    units = [_part_unit(v) for v in values]
    if units[-1] and not any(units[:-1]):
        values = [f"{v} {units[-1]}" for v in values[:-1]] + [values[-1]]
    return list(zip(names, values))


# ------------------------------------------------ which equipment is this

#: The label that introduces an equipment tag. Matched at the START of the
#: label, because a datasheet writes the tag two ways and both must read:
#:
#:   `Tag number :` | `2003-47-V-0001A/B`     - label and value, two cells
#:   `Tag No. PSV-4301 A/B (for GC-9, 10 & 19)` | ``   - all one cell
#:
#: The second is the client PSV sheet, where the text block carries the key and
#: the tag together and there is no value beside it. A reader that only
#: understood the first shape would find no tag on any page of it.
#:
#: `Tag description` is deliberately not a key: it names what the equipment
#: IS, not which one it is.
_TAG_LABEL = re.compile(
    r"^\s*(?:tag\s*(?:no\.?|number)|item\s*no\.?)\s*[.:\-]*\s*(?P<tail>.*)$",
    re.IGNORECASE)


def tag_from_pair(label: str, value: str) -> str | None:
    """The equipment tag this row carries, or None.

    NEVER GUESSED AND NEVER CLEANED beyond collapsing whitespace. A tag is an
    identifier somebody will type into a search box or read off a P&ID, so
    `PSV-4301 A/B (for GC-9, 10 & 19)` is stored exactly as the sheet wrote
    it. Stripping the bracket, the `A/B` or the service note would produce a
    tag that matches nothing a person would look for.
    """
    match = _TAG_LABEL.match(" ".join((label or "").split()))
    if match is None:
        return None
    # The tag sits in whichever half the sheet put it in: after the key when
    # the whole row is one cell, otherwise in the value beside it.
    tail = " ".join((match.group("tail") or "").split())
    return tail or " ".join((value or "").split()) or None


def page_tags(pairs_by_page: dict[int, list[tuple[str, str]]]) -> dict[int, str]:
    """The equipment tag each page states, for the pages that state one.

    A page with two tag rows saying the same thing yields it once; a page
    whose tag rows disagree yields nothing, because "which equipment is this
    page about" has no answer there and inventing one is worse than a NULL.
    """
    found: dict[int, set[str]] = {}
    for page, pairs in pairs_by_page.items():
        for label, value in pairs:
            tag = tag_from_pair(label, value)
            if tag:
                found.setdefault(page, set()).add(tag)
    return {page: next(iter(tags)) for page, tags in found.items()
            if len(tags) == 1}


def stamp_tags(pairs_by_page: dict[int, list[tuple[str, str]]]) -> dict[int, str | None]:
    """Which tag each page's facts belong to, page by page.

    TWO RULES, AND THE SECOND IS WHAT MAKES A ONE-VESSEL SHEET USABLE:

      * a page that states its own tag stamps its own facts with it;
      * a document whose pages state exactly ONE distinct tag stamps EVERY
        page with it, including the pages that say nothing. The drum sheet
        names `2003-47-V-0001A/B` once, on its data page, and every fact in
        the document is about that vessel.

    WHEN THE TAGS DIFFER, NOTHING IS INHERITED. The PSV sheet is four valves
    on four pages; carrying page 1's tag onto page 2 would file one valve's
    set pressure against another. A page without a tag row gets NULL, which
    is the true answer - this system does not know which valve that page is
    about.
    """
    tags = page_tags(pairs_by_page)
    # COUNTED OVER EVERY TAG THE DOCUMENT MENTIONS, not only the pages that
    # resolved cleanly. A page naming two different tags yields none of its
    # own - see `page_tags` - and counting only the resolved pages would make
    # a document that mentions A-1 and B-2 look like a one-tag sheet and stamp
    # B-2's page with A-1.
    mentioned = {tag for pairs in pairs_by_page.values()
                 for tag in (tag_from_pair(label, value)
                             for label, value in pairs) if tag}
    if len(mentioned) == 1:
        only = next(iter(mentioned))
        return {page: only for page in pairs_by_page}
    return {page: tags.get(page) for page in pairs_by_page}


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


def primary_unit(cell: str | None) -> str | None:
    """The unit a two-unit cell states first - "m3/h (USGPM)" -> "m3/h".

    B4. Datasheets print a quantity in two unit systems, the second in
    brackets. The unit outside the brackets is the one the first number is in;
    None when that part is not a unit `claims` recognises (a gauge reference
    such as "bar g" is split off before the check, as `create_fact` does).
    Nothing is guessed from words that are not a unit.
    """
    outside = re.sub(r"\([^)]*\)", " ", cell or "")
    outside = re.sub(r"\s+", " ", outside).strip()
    if not outside:
        return None
    base, _reference = claims.split_reference(outside)
    return outside if claims.is_unit(base or "") else None


def is_unit_cell(text: str | None) -> bool:
    """A TWO-UNIT cell - a unit with its bracketed alternate, "m3/h (USGPM)",
    "bar (psi)" - which names how a quantity is measured, never a field.

    The bracket is required: a bare "RPM" is a real field label on a pump
    sheet (the rated speed's slot), measured by the #179 layout tests.
    """
    return "(" in (text or "") and primary_unit(text) is not None


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
    # B4: A UNIT CELL NAMES HOW A QUANTITY IS MEASURED, NOT WHICH QUANTITY.
    # "m3/h (USGPM)" beside "CAPACITY / FLOW:" was stored as the field
    # "m3/h usgpm" - the value under it stays UNKNOWN rather than that.
    if is_unit_cell(candidate):
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


#: B4: a bracket holding only standard-clause references - "(6.3.10)",
#: "(8.3.3.2 b)", "(8.1.1 c, 8.3.3.5)". A dotted number is required, so a
#: note number "(1)", a unit "(USGPM)" or a location "(MSL)" never matches.
_CLAUSE_REF_BRACKET = re.compile(
    r"\(\s*\d+(?:\.\d+)+(?:\s*[a-z]\b)?"
    r"(?:\s*[,;&]?\s*\d+(?:\.\d+)+(?:\s*[a-z]\b)?)*\s*\)", re.IGNORECASE)


def normalise_field_name(label: str) -> str:
    """A field label reduced to a comparable name.

    Lowercased, punctuation dropped, whitespace collapsed, and the sheet's
    trailing clause references removed - "Design/Operating pressure (Note - 3)"
    and "DESIGN / OPERATING PRESSURE:" are the same field asked twice.

    B4: AN API CLAUSE REFERENCE IS NOT PART OF THE NAME. "CASING TYPE:
    (6.3.10)" was stored as the field "casing type 6 3 10" - the dots and
    brackets went and the digits stayed - so no requirement about the casing
    type could ever name it. Measured: 58 of the pump sheet's 175 facts.

    THE ORIGINAL LABEL IS KEPT BESIDE THIS, always. A normalised name is for
    matching; the reader is shown what the document actually wrote.
    """
    text = re.sub(r"\((?:note|see|ref)[^)]*\)", " ", label or "", flags=re.IGNORECASE)
    text = _CLAUSE_REF_BRACKET.sub(" ", text)
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


def _looks_like_an_identifier(token: str) -> bool:
    """Is this an equipment tag rather than a unit?

    A bill-of-materials row reads "6 VEFV1101M" in one cell, so the unit-column
    rule never sees a unit column and any trailing word becomes the unit. Ten
    of twenty numeric facts on a real submittal were that.

    THIS CANNOT SIMPLY DEMAND A RECOGNISED UNIT the way the standards side does:
    this module's own docstring protects "9970 Kg/hr", a real value whose unit
    is not in the table, and refusing it would lose the number.

    THE FIRST VERSION USED LENGTH, AND THAT WAS LUCK. It discarded anything
    unrecognised longer than five characters carrying a digit - which is
    `kg/cm2`, `kg/cm2g` and `lb/ft3`, all real pressures and densities. The
    five that survived did so only by being short enough, not by being
    understood. Those eight compound units are now in `claims`, and the test
    here no longer turns on length:

    A tag mixes SEVERAL digits with SEVERAL letters: `VEFV1101M` is four digits
    and five letters. A compound unit carries at most one digit - kg/cm2,
    N/mm2, W/m2K, lb/ft3, m3/hr - and the two-digit threshold is what separates
    them.

    A first version also required the absence of a solidus, on the theory that
    compound units contain one and tags do not. Mutation M125 showed that
    condition was DEAD: not one of the eight compound units carries two digits,
    so the digit test alone already protects every one of them, and a condition
    no test can distinguish is a condition that should not be there.

    A token `claims` recognises is never an identifier, whatever its shape.
    """
    text = (token or "").strip()
    if not text:
        return False
    if claims.is_unit(claims.split_reference(text)[0] or ""):
        return False
    digits = sum(1 for ch in text if ch.isdigit())
    letters = sum(1 for ch in text if ch.isalpha())
    return digits >= 2 and letters >= 3


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


#: A pointer to somewhere else on the sheet: "Figure 1", "Table 3", "Note 5",
#: "Detail A", "Sheet 2 of 4". Never the name of a field.
#: A DOTTED CLAUSE NUMBER IS THE SAME KIND OF POINTER. The drum sheet's
#: weight rows read `19 | 4.2.1 | Fabricated weight (L1) : | 4410 | kg`, so
#: after the line number is dropped the clause reference takes the label
#: position and the real label becomes its value - the same defect as
#: `Figure 1`, in a different spelling, and it cost three weights.
#:
#: TWO DOTS MINIMUM, deliberately: `4.2.1` is a clause and `1.6` is a
#: corrosion allowance, and a rule that could not tell them apart would throw
#: away values.
_CROSS_REFERENCE = re.compile(
    r"(?:figure|fig\.?|table|note|detail|drawing|dwg\.?|sheet|item|ref\.?)"
    r"\s*[-:]?\s*[A-Za-z0-9]{1,4}(?:\s+of\s+\d{1,3})?"
    r"|\d{1,3}(?:\.\d+){2,}",
    re.IGNORECASE)

#: An annex clause (`D.6.1`, `A.4`) or a list of two or more clauses
#: (`4.7.1.3, 8.2.1, A.5`). Never a value: a letter before the first dot, or
#: a comma-separated run of dotted numbers, is not how a quantity is written.
_LETTERED_CLAUSE = re.compile(
    r"[A-Za-z]\.\d+(?:\.\d+)*"
    r"|(?:[A-Za-z]|\d{1,3})(?:\.\d+)+(?:\s*,\s*(?:[A-Za-z]|\d{1,3})(?:\.\d+)+)+")

#: A cell that is ONLY a bracketed qualifier.
_PARENTHETICAL_ONLY = re.compile(r"\(([^()]{1,60})\)")


def _join_continuations(parts: list[str]) -> list[str]:
    """Attach a bracket-only cell to the cell it qualifies.

    A LINE THAT IS ONLY A PARENTHETICAL IS A CONTINUATION, NOT A LABEL. The
    drum sheet writes a corrosion allowance over two lines:

        Design corrosion allowance for removable internal parts
        (material 2)

    and the text-block path reads each line as its own cell. `(material 2)`
    then became a label in its own right, paired with the `0` beneath it, and
    `normalise_field_name` dropped the brackets - producing a field called
    `material 2` whose value was 0 mm. That is not a field on any datasheet;
    it is the tail of one.

    Merged into whatever precedes it, whatever that is: a qualifier on a value
    ("3.5", "(ga)") belongs to the value for the same reason. A parenthetical
    with nothing before it is left alone, because there is nothing to attach
    it to.
    """
    out: list[str] = []
    for part in parts:
        if out and out[-1] and _PARENTHETICAL_ONLY.fullmatch(part):
            out[-1] = f"{out[-1]} {part}"
            continue
        out.append(part)
    return out


def split_label_value(cells: list[str]) -> list[tuple[str, str]]:
    """Label-value pairs out of one row of a form.

    A client sheet is TWO FORMS SIDE BY SIDE - "5 | Design pressure | 23.5 barg |
    46 | Bonnet material | CS" - so a row yields more than one pair and the
    leading line numbers are dropped. Pairing is strictly left to right, which
    is the order the sheet is read in.
    """
    joined = _join_continuations([c.strip() for c in cells if c is not None])
    # A cell written on a drawn answer line (`split_drawn_slots`) is a value.
    slot = [p.startswith(_SLOT_MARK) for p in joined]
    parts = [p[len(_SLOT_MARK):] if is_slot else p for p, is_slot in zip(joined, slot)]
    pairs: list[tuple[str, str]] = []
    index = 0
    while index < len(parts):
        part = parts[index]
        # AN ANSWER WITH NO LABEL BEFORE IT names nothing, and is not paired
        # with whatever follows it either - that would file it under the
        # next field's label.
        if slot[index]:
            index += 1
            continue
        # A bare line number introduces the pair that follows it.
        if re.fullmatch(r"\d{1,3}", part):
            index += 1
            continue
        # SO DOES A CROSS-REFERENCE CELL, for the same reason: it is a pointer
        # to somewhere else on the sheet, not the name of a field.
        #
        # MEASURED DEFECT. The drum sheet's corrosion-allowance rows read
        # `Figure 1 | Design corrosion allowance for removable internal parts
        # (material 2) | 0 | mm`. Pairing strictly left to right made
        # `Figure 1` the label and the real label its value, so the row's only
        # surviving fact was named after the fragment left over - the field
        # that the model tier then paired with a weld-cleaning distance and
        # reported NON_COMPLIANT against the contractor.
        #
        # A NARROW CLASS, deliberately: "Figure 1", "Table 3", "Note 5",
        # "Detail A", "Sheet 2". Nothing else is dropped, because a rule of
        # the form "the value looks like a label, so re-anchor" also discards
        # `Insulation | None`, where `None` is a real answer that happens to
        # read like a word.
        if _CROSS_REFERENCE.fullmatch(part):
            index += 1
            continue
        # AND SO DOES AN ANNEX CLAUSE (`D.6.1`, `A.4`) OR A LIST OF CLAUSES
        # (`8.2.1, A.5, B.3.2`) - issue #179, measured on the real vessel
        # sheet: `10 | D.6.1 | <label, wrapped onto two lines> | not
        # applicable` made the clause the label and the label's FIRST line
        # its value, so the value was filed under the label's second line -
        # a fragment that names nothing. A plain `5.7` is NOT skipped here:
        # in a text block that is as likely a value (a 1.6 mm corrosion
        # allowance) as a clause.
        if _LETTERED_CLAUSE.fullmatch(part):
            index += 1
            continue
        if not part:
            index += 1
            continue
        label = part
        value = parts[index + 1] if index + 1 < len(parts) else ""
        value_on_a_slot = index + 1 < len(parts) and slot[index + 1]
        if (not value_on_a_slot and re.fullmatch(r"\d{1,3}", value)
                and not _unit_follows(parts, index + 2)):
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
            # AN EMPTY DRAWN SLOT HAS A UNIT TOO (#179): `RATED POWER
            # ___*___ kW  EFFICIENCY ...`. The unit is the slot's, not the
            # next field's label - left in place it became a rejected label
            # that swallowed `EFFICIENCY` as its value. Consumed, and not
            # glued onto the blank: a blank has no value for a unit to
            # qualify.
            #
            # UNLESS THE "UNIT" HAS A SLOT OF ITS OWN: `RPM ___*___` is a
            # field called RPM, and `rpm` is also a unit. A unit is never
            # followed by its own drawn slot; a label is.
            elif index < len(parts) and is_blank_value(value)[1] == "placeholder":
                nxt = parts[index]
                base, _reference = claims.split_reference(nxt)
                owns_a_slot = (index + 1 < len(parts)
                               and is_blank_value(parts[index + 1])[1] == "placeholder")
                if (nxt and len(nxt) <= 14 and claims.is_unit(base or "")
                        and not owns_a_slot):
                    index += 1
        finished = _finish_pair(label, value)
        if finished is not None:
            pairs.append(finished)
    return pairs


def _finish_pair(label: str, value: str) -> tuple[str, str] | None:
    """The last checks every label:value pair passes, whichever reader built it.

    One home, shared by `split_label_value` and the numbered-table reader
    (#179), so the two cannot drift into two definitions of "a label".
    """
    # THE UNIT INSIDE THE LABEL. `| Design pressure (barg) | 3.5 |` puts it
    # where nothing looked for it, so nothing recorded that a unit existed
    # at all - worse than a unit in its own column, which at least left a
    # trace.
    #
    # Stripped only when the parenthetical IS a unit: "(Note - 3)" and
    # "(see 5.2)" are not, and must stay part of the label.
    label, carried = _unit_in_label(label)
    if carried and value and _is_numeric_cell(value):
        value = f"{value} {carried}"
    if normalise_field_name(label) in _HEADING_WORDS:
        return None
    # THE LABEL MUST BE A LABEL. See is_field_label: without this the
    # pairing promotes values and drawing numbers into field names and
    # then records each one as a required field left blank.
    if not is_field_label(label):
        return None
    return label, value


_SERIAL = re.compile(r"\d{1,3}")

#: A clause reference, or a list of them, in front of a numbered form's
#: label: `5.7`, `D.6.1`, `6.1.7, 8.2.2, A.4, B.2.3`. Only ever skipped in
#: the LABEL position of a numbered row, where a number cannot be the value
#: because nothing has named a field yet.
_CLAUSE_LIST = re.compile(
    r"[A-Za-z]?\d*(?:\.\d+)+(?:\s*,\s*[A-Za-z]?\d*(?:\.\d+)+)*")


def _serial_columns(rows: list[list[str]], width: int) -> list[int]:
    """The columns of a ruled table that hold the FORM'S OWN LINE NUMBERS.

    ISSUE #179. A numbered form's line number is not data, and neither is the
    column it sits in - but a value can be a small integer too (`Over
    pressure % | 21`). Deciding row by row whether "21" is a line number
    cannot be done; deciding COLUMN by column can, because a line-number
    column says so down its whole length:

      * at least three of its cells are bare 1-3 digit numbers,
      * they make up at least half of the column's non-empty cells (the
        rest being its header and the title block below the form), and
      * they INCREASE strictly down the page - a form counts its lines.

    Column 0 needs nothing more: a row serial is where a numbered form puts
    it. Any OTHER column must also introduce a label - the next non-empty
    cell to its right reads as a field label in most of its rows - because
    that is what separates the second sub-form's numbering on a two-forms-
    side-by-side sheet from, say, a column of nominal sizes that happens to
    increase.
    """
    serials = []
    for col in range(width):
        numbers: list[int] = []
        introduces_label = 0
        non_empty = 0
        for row in rows:
            cell = row[col]
            if not cell:
                continue
            non_empty += 1
            if not _SERIAL.fullmatch(cell):
                continue
            numbers.append(int(cell))
            following = next((c for c in row[col + 1:] if c), "")
            if following and is_field_label(following):
                introduces_label += 1
        if len(numbers) < 3 or len(numbers) * 2 < non_empty:
            continue
        if any(b <= a for a, b in zip(numbers, numbers[1:])):
            continue
        if col > 0 and introduces_label * 3 < len(numbers) * 2:
            continue
        serials.append(col)
    return serials


def _pairs_from_numbered_row(cells: list[str], serials: list[int]) -> list[tuple[str, str]]:
    """One pair per sub-form on a numbered row, read by COLUMN, not compacted.

    ISSUE #179. The row is cut at each line-number column; each piece is one
    sub-form's line. Within it:

      * leading cells that cannot be a label - a clause reference (`5.7`,
        `D.6.1`, `4.2.1`, `Table 2`) or an empty spacer - are skipped: they
        sit in front of the label, they do not name the field;
      * the label is the first cell that reads as one;
      * the value is the next non-empty cell after it, WHATEVER IT LOOKS
        LIKE - a `21` in the value column is a value, because this reader
        already knows where the line numbers are;
      * a numeric value takes the unit from its own unit column when the
        next cell is a unit `claims` recognises.

    One pair per piece. Anything further right on the piece (a notes column)
    is not paired: a note beside a value is not a second field.
    """
    out: list[tuple[str, str]] = []
    bounds = [*serials, len(cells)]
    for start, end in zip(bounds, bounds[1:]):
        piece = cells[start + 1:end]
        label_at = None
        for i, cell in enumerate(piece):
            if not cell or _CROSS_REFERENCE.fullmatch(cell) or _CLAUSE_LIST.fullmatch(cell):
                continue
            # The first cell that is not a pointer IS the label position. If
            # it cannot be a label (too long, mostly digits), the piece has
            # no pair - never the NEXT cell promoted into its place, which is
            # how a value ends up filed under a label fragment.
            if is_field_label(cell):
                label_at = i
            break
        if label_at is None:
            continue
        rest = [c for c in piece[label_at + 1:] if c]
        value = rest[0] if rest else ""
        if value and len(rest) > 1 and _is_numeric_cell(value):
            base, _reference = claims.split_reference(rest[1])
            if len(rest[1]) <= 14 and claims.is_unit(base or ""):
                value = f"{value} {rest[1]}"
        finished = _finish_pair(piece[label_at], value)
        if finished is not None:
            out.append(finished)
    return out


def pairs_from_table_shape(shape: list[list[str]]) -> list[tuple[str, str]]:
    """Label:value pairs from one RULED table shape, respecting its columns.

    CAUSE (#175 cascaded-extractor work, layout/table tier), measured against
    a real datasheet's real ruled table (`tables.parse_page_tables` already
    finds it correctly - the shape that comes back is byte-for-byte right,
    header rows and all). The defect was downstream: every row, header AND
    data, was run through `split_label_value`, which pairs a row's cells as
    an ALTERNATING SEQUENCE (label, value, label, value, ...) - correct for
    the "two forms side by side" TEXT-BLOCK shape it was built for, wrong for
    "one row label, several values under several different column headers".
    The first value paired correctly with the row label; every value after
    that got cross-paired against its NEIGHBOUR instead of being scoped to
    the row label - a row meaning "RADIOGRAPHY: METHODS=X, FABRICATIONS=Y,
    CASTINGS=Z" became "RADIOGRAPHY -> X" (right) plus a spurious "Y -> Z"
    (wrong), and the fact that Y and Z both belong to RADIOGRAPHY was lost
    entirely. That is worse than missing data: it is two real values
    reported as if one were the other's label.

    NARROW SHAPES FALL THROUGH TO `split_label_value` UNCHANGED. A shape
    under three columns wide has no "several values, several headers"
    problem - it is exactly the row split_label_value was built for, and
    this function must not touch it.

    HEADER DETECTION, width >= 3 only: row 0 is always the header. A
    header can run to a SECOND line - `TYPE OF INSPECTION | METHODS |
    ACCEPTANCE CRITERIA | ''` then `'' | '' | FOR FABRICATIONS | FOR
    CASTINGS` - and row 1 is recognised as that continuation by one signal:
    ITS OWN FIRST CELL IS EMPTY. Every genuine data row in this shape needs
    something naming it in column 0 (a row with nothing in column 0 is not
    a fact about anything), so an empty column 0 on row 1 means row 1 is
    still naming columns, not yet reporting a value.

    CARRY-FORWARD FOR SPANNING HEADER CELLS. A header cell that names more
    than one column beneath it - "ACCEPTANCE CRITERIA" over both
    "FABRICATIONS" and "CASTINGS" - is written ONCE in the source table,
    with the column(s) after it left empty. Read literally, the CASTINGS
    column would lose that it is an acceptance-criteria column at all.
    Carrying the last non-empty header cell rightward across the empty
    ones it left behind restores the property a merged cell always had -
    every column under it is still that column.
    """
    if not shape:
        return []
    width = max((len(row) for row in shape), default=0)
    if width < 3:
        out: list[tuple[str, str]] = []
        for row in shape:
            out.extend(split_label_value(list(row)))
        return out

    def _padded(row: list[str]) -> list[str]:
        return [(c or "").strip() for c in row] + [""] * (width - len(row))

    def _carry_forward(row: list[str]) -> list[str]:
        # Column 0 is the label column and never receives a carried header.
        out_row = list(row)
        for i in range(2, width):
            if not out_row[i] and out_row[i - 1]:
                out_row[i] = out_row[i - 1]
        return out_row

    row0 = _carry_forward(_padded(shape[0]))
    data_start = 1
    header = row0
    if len(shape) > 1:
        row1 = _padded(shape[1])
        if not row1[0]:
            # Row 1 continues the header: merge, the more specific (lower)
            # line naming the column, carrying its parent super-header ahead
            # of it when the two say different things.
            merged = []
            for h0, h1 in zip(row0, row1):
                if h1 and h0 and h0 != h1:
                    merged.append(f"{h0} - {h1}")
                else:
                    merged.append(h1 or h0)
            header = merged
            data_start = 2

    # A CAPTION IS NOT A COLUMN HEADER (issue #179). The carry-forward above
    # exists for a super-header over two or three sub-columns that a second
    # header line then tells apart. A page's own title in row 0 is carried
    # the same way - across EVERY column - and then appended to every field
    # beneath it, including the title block's rows and the equipment tag
    # row, measured on a real pressure-vessel sheet. One text over three or
    # more columns, not told apart by anything beneath it, distinguishes no
    # column from any other, so it names none of them.
    spread: dict[str, int] = {}
    for text in header[1:]:
        if text:
            spread[text] = spread.get(text, 0) + 1
    header = [text if i == 0 or spread.get(text, 0) < 3 else ""
              for i, text in enumerate(header)]

    padded_rows = [_padded(row) for row in shape]
    serials = _serial_columns(padded_rows[data_start:], width)

    out = []
    for row in shape[data_start:]:
        cells = _padded(row)
        label = cells[0]
        # A LABEL WITH NO LETTER NAMES NOTHING (#179). The vessel sheet's
        # empty hold list is a ruled grid of `--` cells; this path scoped
        # them into a field called `--`, blank-marked by its own dashes, and
        # it was stored as a required field left blank. The pump sheet's
        # line-number strip, merged by the table finder into one cell
        # (`1 2 3 ... 57`), became a "label" the same way. A bare row
        # serial never reaches here - it is read as a numbered row below.
        if not re.search(r"[^\W\d_]", label) and not re.fullmatch(r"\d{1,3}", label):
            continue
        # A ROW WHOSE OWN COLUMN 0 IS A BARE LINE NUMBER, measured on two
        # real regression documents (issue #179). Column 0 is not a label
        # here - it is a client-style row serial, exactly what split_label_value
        # already strips wherever it appears - and this function's "one row
        # label, several values under several headers" scoping does not
        # apply to it.
        #
        # I-06 pairs a PROCESS DATA sub-form and a SPRING AND BONNET sub-form
        # on the SAME physical row, each introduced by its own line number:
        # `1 | Fluid | | Crude Oil/Gas (Dual Service) | | 42 | Bonnet type/
        # style | Bolted/ closed`. Treating cells[0] ("1") as the row's one
        # label turned the two REAL labels ("Fluid", "Bonnet type/ style")
        # into VALUES paired against that bare digit, and the digit itself
        # became the field_name recorded on the fact - 49 of the document's
        # 268 facts were labelled "11", "12", "15" etc. this way, and the
        # true label/value pairing was lost, not just misnamed.
        #
        # A second regression document is the same shape with one sub-form per row rather than
        # two: the real label sits one cell past the row number
        # (`5 | | Tag number : | 2003-47-V-0001A/B | ...`). Scoped-to-header
        # naming then quoted the page's own repeating title text as if it
        # were a column name, because that furniture line is what this
        # table's ROW 0 actually contains - 8 of 10 spot-checked facts had
        # `field_label` polluted with it.
        #
        # SECOND PASS (#179 again): READ BY COLUMN WHEN THE COLUMNS ARE
        # KNOWN. Compacting the row threw its geometry away, and with it the
        # only evidence that `15 | Over pressure % | 21 | 56 | Weather hood`
        # has a VALUE of 21 rather than a line number 21 - so every such
        # value was lost - and it let a clause column (`6 | 5.7 | Design
        # life : | 25 | years`) take the label's place. When the table's
        # line-number columns can be identified (`_serial_columns`), each
        # sub-form is read from its own columns instead.
        #
        # The compacted split_label_value path stays for a shape too short
        # to identify its columns from: it drops a bare line number wherever
        # it sits and pairs what is left, strictly left to right, with the
        # blank spacer columns compacted out so a spacer is never paired as
        # the value.
        if re.fullmatch(r"\d{1,3}", label):
            if 0 in serials:
                out.extend(_pairs_from_numbered_row(cells, serials))
                continue
            compact = [c for c in cells if c]
            out.extend(split_label_value(compact))
            continue
        for i in range(1, width):
            value = cells[i]
            if not value:
                continue
            col_header = header[i] if i < len(header) else ""
            field = f"{label} - {col_header}" if col_header else label
            out.append((field, value))
    return out


#: A drawn answer line: three or more underscores in a row.
_DRAWN_RULE = re.compile(r"_{3,}")

#: Prefixed by `split_drawn_slots` to a cell that is a drawn SLOT's answer,
#: and stripped by `split_label_value`, the only reader of it. It carries one
#: fact across that boundary: this cell was written on an answer line, so it
#: is a VALUE - never a label, and never the next line's line number, which
#: is what a `2` written on a rule otherwise looks exactly like.
_SLOT_MARK = "⁣"

#: Slot content that is itself only placeholder ink - `*`, `-`, `.`.
_PLACEHOLDER_INK = re.compile(r"[*\-.·–—]+")


def split_drawn_slots(cell: str) -> list[str]:
    """One text line of an underscore-slot form, cut into its cells.

    ISSUE #179, THE PUMP DATASHEET. An API-style datasheet prints several
    fields on ONE text line, each answered on a drawn line of underscores:

        RATED POWER  _______*_______      kW      EFFICIENCY  ____*____  (%)
        Number of Accelerometers                 __________2____________
        MOUNTED AT:            _____GRADE___          • TROPICALISATION REQD

    The text-block reader splits cells only at line breaks, so each of those
    lines was ONE cell - one "label" with no value - and 309 of the 393
    field slots the owner's gold sheet records for that document never
    became a label at all. Measured, not guessed: that was the largest
    single cause of its 2/196 recall.

    THE RULE, read off the drawing and nothing else:

      * only a line that contains a drawn rule (`___`) is touched - a
        value like `220ºC    By Contractor` on another sheet keeps its
        spaces and stays one cell;
      * a gap of three or more spaces separates cells;
      * text written ON a rule (touching the underscores, no space between)
        is that slot's answer: `_____GRADE___`, `__8.5_`, `PROPOSAL_____`;
      * a rule with no text on it is an EMPTY slot and becomes `___`, which
        `is_blank_value` reads as a drawn placeholder - a blank, never 0;
      * a slot holding only placeholder ink (`____*____`, the sheet's own
        "manufacturer to advise" mark) stays a placeholder too.

    No label list and no knowledge of any one form: it is the underscore
    geometry that says where a slot is.
    """
    if not _DRAWN_RULE.search(cell or ""):
        return [cell]
    out: list[str] = []
    for chunk in re.split(r"\s{3,}", cell.strip()):
        tokens = re.split(r"(_+)", chunk)
        touched: set[int] = set()
        pieces: list[tuple[int, str]] = []
        for i, token in enumerate(tokens):
            if not token or token.startswith("_") or not token.strip():
                continue
            left = i > 0 and tokens[i - 1].startswith("_") and not token[0].isspace()
            right = (i + 1 < len(tokens) and tokens[i + 1].startswith("_")
                     and not token[-1].isspace())
            text = token.strip()
            if left:
                touched.add(i - 1)
            if right:
                touched.add(i + 1)
            if (left or right) and _PLACEHOLDER_INK.fullmatch(text):
                text = f"___{text}___"
            pieces.append((i, _SLOT_MARK + text if (left or right) else text))
        for i, token in enumerate(tokens):
            if token.startswith("_") and i not in touched:
                pieces.append((i, _SLOT_MARK + "___"))
        out.extend(text for _i, text in sorted(pieces))
    return out


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
        cells = [piece for c in (text or "").split("\n") if c.strip()
                 for piece in split_drawn_slots(c.strip())]
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
    # `121OC` IS A TEMPERATURE, and the sheet writes the degree sign as a
    # letter. Rewritten here so every caller sees the same cell.
    text = normalise_degree_glyph((raw or "").strip())
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
    if unit and _looks_like_an_identifier(unit):
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
    equipment_tag: str | None = None, commit: bool = True,
    validation_state: str | None = None,
    extractor_version: str | None = None, input_hash: str | None = None,
    unit: str | None = None, value_column: str | None = None,
    one_quantity: bool = False,
    blank: tuple[bool, str | None] | None = None, bbox: str | None = None,
    printed_unit: str | None = None,
) -> dict:
    """Record one fact. REFUSES a fact whose citation does not resolve.

    `unit` (B4): the unit a layout states for this value OUTSIDE the value's
    own cell - a grid row's unit column, whose primary unit `primary_unit`
    read. Used only when the value itself prints no unit: "24.8 (109)" under
    "m3/h (USGPM)" is 24.8 m3/h. A unit printed in the value always wins.

    `commit=False` writes INSIDE the caller's open transaction and commits
    nothing, so `extract_facts` can make a whole datasheet all-or-nothing
    (B19). It also skips `ensure_schema`, whose own `with conn:` would commit
    that transaction half-way; the caller has already ensured the schema.

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
    if commit:
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

    # B4 (geometry reader): `blank` is the caller's OWN evidence of a blank
    # field - the drawn run or printed marker the geometry reader saw, which
    # it has already separated from any printed unit ("____ bar g"). None
    # (every other caller) keeps the one text rule below.
    blank, marker = blank if blank is not None else is_blank_value(raw_value)
    unit_hint = unit
    value, unit, measurement = (None, None, None) if blank else measure_value(raw_value or "")
    if value is not None and unit is None and unit_hint:
        unit = unit_hint
        measurement = claims.normalise(value, unit)
    # A RANGE, KEPT AS TWO NUMBERS. `parse_range` returns None for an ordinary
    # cell, so a single value is untouched and its min/max stay NULL.
    value_min = value_max = None
    found = None if blank else parse_range(raw_value)
    if found is not None:
        low, high, range_unit = found
        value, unit = None, range_unit
        value_min, value_max = claims.parse_value(low), claims.parse_value(high)
        measurement = None
    # A COMPOUND LABEL WHOSE VALUE DID NOT SPLIT IS NOT PARSED AT ALL.
    #
    # `Design/Operating pressure` names two quantities. When the cell beside
    # it carries one number, there is no way to tell which of the two it
    # answers, and recording it against the compound label would attach a real
    # number to a field that is half wrong. The row is kept - the sheet does
    # say something - with its text and no parsed value.
    # B4: `one_quantity` - the caller's layout evidence (a grid row stating one
    # unit for a bare-noun pair like "CAPACITY / FLOW") that the label names
    # ONE quantity twice. A shared-noun compound never gets it.
    if not blank and not one_quantity and compound_label_parts(field_label) is not None:
        value, unit, measurement = None, None, None
        value_min = value_max = None
    # THE UNIT AS THE SHEET WROTE IT, AND THE UNIT THE TABLE UNDERSTANDS, kept
    # apart. `raw_unit` is `bar (ga)` because that is what the document says and
    # a reader checking a citation reads the document's words; `unit` is `bar`
    # because that is what `claims` can convert; `unit_reference` is `gauge`
    # because losing it changes the number by an atmosphere.
    raw_unit = unit
    if raw_unit is None and printed_unit and not blank and value is None and found is None:
        # B4 (geometry reader): a unit the READER split off a value that is
        # not a plain quantity ("<85" + "dBA"). Kept as printed, so the unit
        # is not lost; it never turns the value into a number.
        raw_unit = printed_unit
    base_unit, unit_reference = claims.split_reference(raw_unit)
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
    # #175: LOW CONFIDENCE NEVER READS AS A CONFIDENT FACT. Whatever the
    # caller passed for `validation_state` stands (an explicit call always
    # wins); otherwise a fact below `LOW_CONFIDENCE_THRESHOLD` is routed to
    # NEEDS_ENGINEER_REVIEW here, in the ONE function every fact is written
    # through, rather than by each caller re-deciding it (CLAUDE.md rule 8 -
    # a routing rule with two homes is a routing rule that drifts).
    if validation_state is None and confidence is not None                     and confidence < LOW_CONFIDENCE_THRESHOLD:
        validation_state = NEEDS_ENGINEER_REVIEW
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
        # WHICH EQUIPMENT THIS FACT DESCRIBES, or NULL when the sheet does not
        # say. A datasheet can carry four valves; a fact that does not know
        # which one it belongs to is a fact nobody can act on.
        "equipment_tag": equipment_tag,
        "value_min": value_min,
        "value_max": value_max,
        "is_blank": 1 if blank else 0,
        "blank_marker": marker,
        "page": page if page is not None else chunk["page_start"],
        "section": section,
        "source_text": source_text or (raw_value or ""),
        "extraction_method": extraction_method,
        "confidence": confidence,
        "validation_state": validation_state,
        # #177 provenance - see `provenance.py`. NULL when the caller did not
        # say (a hand-entered fact has no extractor).
        "extractor_version": extractor_version,
        "input_hash": input_hash,
        "value_column": value_column,
        # B4: where on the page the value sits (JSON), when the reader knows -
        # the geometry reader's boxes and table cell. NULL otherwise.
        "bbox": bbox,
        "created_at": now,
        "updated_at": now,
    }
    conn = connect()
    insert = (
        """INSERT INTO submittal_facts
           (id, review_run_id, submittal_document_id, chunk_id, field_name,
            field_label, field_value, raw_value, raw_unit,
            normalized_value, normalized_unit, unit, is_blank,
            blank_marker, page, section, source_text, extraction_method,
            confidence, created_at, updated_at, unit_reference,
            value_min, value_max, equipment_tag, validation_state,
            extractor_version, input_hash, value_column, bbox)
           VALUES (:id, :review_run_id, :submittal_document_id, :chunk_id,
                   :field_name, :field_label, :field_value, :raw_value,
                   :raw_unit, :normalized_value, :normalized_unit, :unit,
                   :is_blank, :blank_marker, :page, :section, :source_text,
                   :extraction_method, :confidence, :created_at,
                   :updated_at, :unit_reference, :value_min, :value_max,
                   :equipment_tag, :validation_state,
                   :extractor_version, :input_hash, :value_column, :bbox)""")
    if commit:
        with conn:
            conn.execute(insert, row)
    else:
        conn.execute(insert, row)
    return row


#: WHY A FILE COULD NOT BE READ, slug plus the sentence a person sees.
#:
#: B44. The slug names THE FILE'S condition, never the pipeline's - the rule
#: `chunker.py`'s exclusion vocabulary states for itself: "the old single rule
#: asserted 'OCR is not implemented', which is a property of the build and goes
#: false the day it ships". Each one was reproduced against PyMuPDF 1.28.2
#: before it was written down; none is taken from documentation.
UNREADABLE = {
    "pdf_missing": "the stored file is not there",
    "pdf_empty_file": "the stored file is empty",
    "pdf_damaged": "the stored file is not a readable PDF",
    "pdf_encrypted": "the stored file is password-protected",
}

#: NOT unreadable - readable and not to be trusted whole. MuPDF rebuilt the
#: cross-reference table to open it, which it does SILENTLY: a file truncated
#: to 60% opens, reports its page count, returns fewer blocks than it should
#: and raises nothing at all. Measured. Without this flag that page is
#: indistinguishable from a page that genuinely prints less.
REPAIRED = "file damaged, repaired on open, content may be missing"


def pdf_condition(stored_path: str) -> tuple[str | None, str, bool]:
    """`(slug, sentence, repaired)` for a stored PDF. `slug` is None when it reads.

    Checked ONCE per document, before any page is parsed, because every one of
    these conditions is a property of the file: if it holds, no page can be
    read, and reporting it per page would say the same thing seven times while
    still not naming it.

    `needs_pass` is read rather than caught: an encrypted document OPENS
    happily, reports its page count, and only raises a bare `ValueError`
    ("document closed or encrypted") when a page is touched - so catching it
    would mean matching on a message.
    """
    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        return None, "", False
    try:
        with pymupdf.open(stored_path) as doc:
            if doc.needs_pass:
                return "pdf_encrypted", UNREADABLE["pdf_encrypted"], False
            return None, "", bool(getattr(doc, "is_repaired", False))
    # EmptyFileError SUBCLASSES FileDataError, so it is caught first or never.
    except pymupdf.EmptyFileError:
        return "pdf_empty_file", UNREADABLE["pdf_empty_file"], False
    except pymupdf.FileNotFoundError:
        # pymupdf's own class, NOT the builtin: it inherits RuntimeError and
        # would slip past `except FileNotFoundError`.
        return "pdf_missing", UNREADABLE["pdf_missing"], False
    except pymupdf.FileDataError:
        return "pdf_damaged", UNREADABLE["pdf_damaged"], False


def _pairs_from_pdf_page(stored_path: str, page_no: int) -> list[tuple[str, str]]:
    """Text-block label-value pairs for one page, in reading order.

    B44: the file's own condition is decided by `pdf_condition` before this is
    called, so what is absorbed here is a failure INSIDE one page of a file
    that opened. An empty list from here means "this page yielded no pairs",
    which is the only thing its caller ever read it as.
    """
    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        return []
    try:
        with pymupdf.open(stored_path) as doc:
            if not (1 <= page_no <= doc.page_count):
                return []
            blocks = [(b[1], b[0], b[4]) for b in doc[page_no - 1].get_text("blocks")]
            return pairs_from_blocks(blocks)
    except (pymupdf.FileNotFoundError, pymupdf.FileDataError):
        return []  # the FILE; named by pdf_condition, not guessed at here
    except Exception:  # noqa: BLE001 - a failure inside one page of a readable file
        return []


# ------------------------------------------------ B4 fix 5: column grids
#
# THE PROCESS DATA SITS IN A GRID THE TEXT READER FLATTENS. A pump sheet's
# OPERATING CONDITIONS block prints a header "Units | Maximum | Rated | Normal
# | Minimum" and rows "CAPACITY / FLOW: | m3/h (USGPM) | ... 24.8 (109) ...".
# In reading order the unit column takes the value slot and the numbers are
# left over, so every row was dropped (measured: flow, temperature, pressures
# and head all missing on the pump regression sheet). WHICH column a value is
# in is read from its POSITION under the header - the words' x-coordinates -
# and a value whose box does not lie wholly inside one column band keeps its
# number and unit but NO column: an engineer places it.

#: Column-header words of an operating-conditions grid. Generic datasheet
#: vocabulary (API 610 / API 526 style); a header needs a Units column and at
#: least three of these on one line.
_GRID_COLUMN_WORDS = frozenset({
    "maximum", "minimum", "rated", "normal", "max", "min", "design", "operating"})
#: The degree sign this sheet's font renders as a letter, in its PAIRED form
#: only: "OC ( OF)" is Celsius printed with its Fahrenheit alternate.
_DEGREE_PAIR = {re.compile(r"^o\s*c\s*\(\s*o\s*f\s*\)$", re.IGNORECASE): "°C",
                re.compile(r"^o\s*f\s*\(\s*o\s*c\s*\)$", re.IGNORECASE): "°F"}


def grid_unit(cell: str | None) -> str | None:
    """The unit a grid row's Units cell states, or None.

    "OC ( OF)" is the degree sign rendered as a letter, and the printed
    Fahrenheit alternate is the evidence that it is one - decoded only in that
    paired form. A lone "OC" is not provably degrees and stays UNKNOWN.
    Everything else goes through `primary_unit`.
    """
    text = (cell or "").strip()
    for pattern, unit in _DEGREE_PAIR.items():
        if pattern.match(text):
            return unit
    return primary_unit(text)


def _one_quantity(label: str) -> bool:
    """A slash label whose parts are BARE NOUNS - "CAPACITY / FLOW" - names one
    quantity twice when its row states one unit. A shared-noun compound -
    "DESIGN / OPERATING PRESSURE" - names two, and stays unparsed."""
    found = compound_label_parts(label)
    if found is None:
        return False
    return all(len(part.strip(" :").split()) == 1 for part in found[1])


def grid_facts(words: list[tuple]) -> list[dict]:
    """Facts read from every column grid on one page's words.

    `words` are pymupdf `get_text("words")` tuples (x0, y0, x1, y1, text, ...).
    Returns dicts: label, value, unit (or None), column (or None when the
    value's position is not decisive), one_quantity, source.
    """
    lines: list[list[tuple]] = []
    for w in sorted(words, key=lambda w: (w[1], w[0])):
        if lines and abs(w[1] - lines[-1][0][1]) <= 2.5:
            lines[-1].append(w)
        else:
            lines.append([w])
    out: list[dict] = []
    i = 0
    while i < len(lines):
        header = lines[i]
        units = [w for w in header if w[4].strip(":").lower() == "units"]
        cols = [w for w in header if w[4].strip(":").lower() in _GRID_COLUMN_WORDS]
        if len(units) != 1 or len(cols) < 3:
            i += 1
            continue
        heads = sorted([units[0], *cols], key=lambda w: w[0])
        centres = [(w[0] + w[2]) / 2 for w in heads]
        names = [w[4].strip(":") for w in heads]
        bands = []
        for k, c in enumerate(centres):
            left = (centres[k - 1] + c) / 2 if k else c - (centres[1] - c) / 2
            right = ((c + centres[k + 1]) / 2 if k + 1 < len(centres)
                     else c + (c - centres[k - 1]) / 2)
            bands.append((left, right, names[k]))
        unit_band = next(b for b in bands if b[2].lower() == "units")
        value_bands = [b for b in bands if b is not unit_band]
        grid_left, grid_right = unit_band[0], bands[-1][1]
        pending: list[tuple] = []
        pending_y = None
        started = False
        i += 1
        while i < len(lines):
            line = lines[i]
            label_w, unit_w, value_w = [], [], []
            for w in sorted(line, key=lambda w: w[0]):
                centre = (w[0] + w[2]) / 2
                if centre < grid_left:
                    label_w.append(w)
                elif centre <= unit_band[1]:
                    unit_w.append(w)
                elif centre <= grid_right:
                    value_w.append(w)
            # A row number printed in the margin is not part of the label.
            if len(label_w) > 1 and label_w[0][4].isdigit():
                label_w = label_w[1:]
            if unit_w and not label_w and not value_w:
                pending, pending_y = unit_w, line[0][1]   # unit printed a line above
                i += 1
                continue
            if pending and pending_y is not None and line[0][1] - pending_y <= 12:
                unit_w = pending + unit_w
            pending, pending_y = [], None
            if not unit_w:
                if started:
                    break                                  # the grid has ended
                i += 1
                continue
            started = True
            label = " ".join(w[4] for w in label_w).strip()
            unit_text = " ".join(w[4] for w in unit_w)
            groups: list[list[tuple]] = []
            for w in value_w:
                if groups and w[0] - groups[-1][-1][2] < 3.0:
                    groups[-1].append(w)
                else:
                    groups.append([w])
            for group in groups:
                value = " ".join(w[4] for w in group)
                # A note reference ("[Note - 3]") is not a value: it names no
                # quantity, no blank marker and no categorical answer, so the
                # existing value gate in extract_facts (states_a_value)
                # refuses it - proved directly on that function's tests
                # rather than duplicated here as unreachable code.
                if not label:
                    continue
                x0, x1 = group[0][0], group[-1][2]
                column = next((name for left, right, name in value_bands
                               if x0 >= left - 0.5 and x1 <= right + 0.5), None)
                out.append({"label": label, "value": value,
                            "unit": grid_unit(unit_text), "column": column,
                            "one_quantity": _one_quantity(label),
                            "source": f"{label} {unit_text} {value}"})
            i += 1
    return out


def _grid_facts_from_pdf_page(stored_path: str | None, page_no: int) -> list[dict]:
    """`grid_facts` for one page of the stored PDF; [] when it cannot be read."""
    if not stored_path:
        return []
    try:
        import pymupdf
        with pymupdf.open(stored_path) as doc:
            if not (1 <= page_no <= doc.page_count):
                return []
            return grid_facts(doc[page_no - 1].get_text("words"))
    except Exception:  # noqa: BLE001 - the file's condition is pdf_condition's to name
        return []


# ------------------------------------------ B4 (#193 5.5): geometry reader
#
# Behind `settings.geometry_reader_enabled`, OFF by default. When ON, the
# geometry reader's form pairs and table cells are written beside the rule
# readers' facts. The rule reader WINS: a geometry reading of a page+label the
# rule readers already wrote is dropped when it agrees and kept as a
# `conflict` row when it does not - never written over the rule reader's.

#: `submittal_facts.validation_state` of a geometry reading that disagrees
#: with a rule-reader fact for the same page and label. Both rows stay; an
#: engineer decides. Never resolved silently.
GEOMETRY_CONFLICT = "conflict"
GEOMETRY_METHOD = "geometry"


def _geometry_rows_from_pdf_page(stored_path: str | None, page_no: int) -> list[dict]:
    """`geometry_reader.read_page_rows` for one page; [] when it cannot be read.

    A failure here never touches the rule readers' facts - the geometry
    reader only ever ADDS rows."""
    if not stored_path:
        return []
    try:
        import pymupdf

        from . import geometry_reader
        with pymupdf.open(stored_path) as doc:
            if not (1 <= page_no <= doc.page_count):
                return []
            return geometry_reader.read_page_rows(doc[page_no - 1])
    except Exception:  # noqa: BLE001 - the file's condition is pdf_condition's to name
        return []


def _geometry_raw_value(row: dict) -> tuple[str, str | None]:
    """(text for `create_fact`, unit to keep apart) for one geometry row.

    A blank hands over its printed text (its marker is passed separately).
    A value hands over "value unit" when that reads as a quantity or a
    range; when it does not ("<85" + "dBA"), the value alone and the unit
    APART, so the reader's split is not undone by gluing them back together.
    """
    if row["is_blank"]:
        return row["value_text"] or "", None
    joined = " ".join(p for p in (row["value"], row["unit"]) if p)
    if row["unit"] and measure_value(joined)[0] is None and parse_range(joined) is None:
        return row["value"] or "", row["unit"]
    return joined, None


def _fold(text: str | None) -> str:
    return " ".join((text or "").split()).lower()


def _geometry_agrees(raw_value: str, is_blank: bool, fact: dict) -> bool:
    """Does a geometry reading say what an already-written fact says?

    Blank against blank agrees. Otherwise the numbers decide when both have
    one (normalised when both normalise, raw otherwise), and the folded text
    decides when neither does."""
    if is_blank or fact["is_blank"]:
        return bool(is_blank) == bool(fact["is_blank"])
    number, _unit, measurement = measure_value(raw_value)
    if number is not None and fact["raw_value"] is not None:
        if (measurement is not None and fact["normalized_value"] is not None
                and measurement.normalized_unit == fact["normalized_unit"]):
            return abs(measurement.normalized_value - fact["normalized_value"]) <= 1e-9 * max(
                1.0, abs(fact["normalized_value"]))
        try:
            return float(number.replace(",", ".")) == float(str(fact["raw_value"]).replace(",", "."))
        except ValueError:
            return _fold(number) == _fold(fact["raw_value"])
    return _fold(raw_value) == _fold(fact["field_value"])


#: #175: the confidence written for a fact recovered only by the OCR (or
#: vision) fallback tier - below `LOW_CONFIDENCE_THRESHOLD`, so `create_fact`
#: routes it to NEEDS_ENGINEER_REVIEW rather than accepting it as confident.
#: Text/table-tier facts keep the pre-existing 0.6 unchanged.
OCR_FALLBACK_CONFIDENCE = 0.35

#: #175: a fact at or above this confidence is accepted; below it, it is
#: evidence a human has not yet confirmed. One threshold, read by
#: `create_fact` only, so "what counts as low confidence" has one home.
LOW_CONFIDENCE_THRESHOLD = 0.5

#: The `submittal_facts.validation_state` value a low-confidence fact is
#: written with. Never silently promoted to a confident fact - CLAUDE.md's
#: honesty invariants: "a guess is shown as a guess until a human confirms
#: it".
NEEDS_ENGINEER_REVIEW = "needs_engineer_review"


def _pairs_from_ocr_fallback(document_id: str, page_no: int) -> list[tuple[str, str]]:
    """Label:value pairs from a page's OCR'd text, when nothing else read it.

    #175, cascade tier 2. `ocr.py` (step 2b) already recognises scanned pages
    into `page_ocr` in the background, independently of fact extraction; this
    is the first caller that READS that table. Only reached when the
    text/table tier (native PDF text and `pairs_from_table_shape`) found
    NOTHING on this page - a page with real native text is never sent here,
    so this cannot override or compete with the primary tier's own pairing
    logic.

    OCR text carries no column geometry - `pairs_from_blocks`' reading-order
    logic needs the (y, x) position of each block, which recognition does not
    produce. This reads exactly the one shape OCR text still states
    unambiguously: a line written "LABEL: VALUE". A page whose OCR text has no
    such line yields nothing, honestly - it is not this function's job to
    guess a pairing a colon does not mark.

    Facts recovered here are marked low-confidence by the caller
    (`extract_facts`), which is what routes them to NEEDS_ENGINEER_REVIEW
    instead of being accepted as confident.
    """
    row = connect().execute(
        "SELECT text FROM page_ocr WHERE document_id = ? AND page_no = ?"
        " AND char_count > 0",
        (document_id, page_no)).fetchone()
    if row is None or not row["text"]:
        return []
    pairs: list[tuple[str, str]] = []
    for line in row["text"].splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        label, value = label.strip(), value.strip()
        if label and value and is_field_label(label):
            pairs.append((label, value))
    return pairs


def _pairs_from_vision_fallback(stored_path: str, page_no: int) -> list[tuple[str, str]]:
    """Label:value pairs from a vision-model reading of one page's image.

    #175, cascade tier 3 - OPTIONAL and CLEARLY GATED. This is deliberately a
    thin hook, not new model-serving code: `reasoning_provider.py` (B54)
    defines exactly one provider that can actually make a model call today,
    `OllamaProvider`, and it is a TEXT interface - no vision-capable provider
    is implemented or configured anywhere on this branch (`ClaudeProvider` is
    still the documented future adapter its own module describes, gated
    behind `settings.standards_reader_enabled` and
    `settings.standards_reader_allow_public_egress`, neither of which stands
    up a vision path). Building a new vision integration here would be
    exactly the "not a rebuild of the earlier vision experiments" scope this
    issue explicitly rules out.

    So: this tier is a DOCUMENTED NO-OP whenever no vision-capable provider
    is configured, which is every environment this system ships to today.
    The moment a real vision provider exists behind its own explicit flag,
    this is the one function that needs to change to call it - a single,
    obvious home for that future decision, not a rewrite of `extract_facts`.
    """
    return []


def _same_cell_key(label: str, value: str | None) -> tuple[str, str]:
    """Two readings of one printed cell compare equal under this key.

    The ruled-table reader collapses a cell's whitespace; the text-block
    reader keeps what the PDF drew. `0.01cP  By Contractor` and
    `0.01cP By Contractor` are one cell (#179).
    """
    return normalise_field_name(label), " ".join((value or "").split())


def collapse_double_reads(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """One page's pairs with each printed cell counted ONCE.

    ISSUE #179, MEASURED ON THE REAL VALVE SHEET. Both readers run over
    every page by design (`extract_facts`), so every cell both of them can
    read arrives twice. Identical readings were already dropped, but the
    comparison was on the raw strings, so two readings that differed only in
    whitespace were stored as two facts - and a wrapped cell, which the
    text-block reader cuts at the line break (`5 m3/hr By Contractor (based
    on`) while the table reader joins it, was stored twice as well. 8 facts
    on a four-valve sheet, one per page per wrapped or double-spaced cell.

    Within ONE PAGE only. The same value on another page is another
    valve's value, and it is kept - the 15 "exact duplicates" the audit
    counted on that sheet are all this, verified against the PDF pair by
    pair.

    The cut-at-the-wrap reading is dropped only when it has at least three
    words and the longer reading of the SAME label on the SAME page starts
    with it at a word boundary: a two-word value that happens to begin
    another is far more likely a different answer than a truncated one.
    """
    keys = [_same_cell_key(label, value) for label, value in pairs]
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for (label, value), (name, text) in zip(pairs, keys):
        if (name, text) in seen:
            continue
        if len(text.split()) >= 3 and any(
                other_name == name and other.startswith(text + " ")
                for other_name, other in keys):
            continue
        seen.add((name, text))
        out.append((label, value))
    return out


def _unparsed_reason(pairs: list, dropped: dict[str, int]) -> str:
    """Why this page produced no facts, in the page's own numbers.

    TWO DIFFERENT FAILURES WORE ONE MESSAGE. "no label-value pairs recovered
    from this page" is true of a scanned page with no text and of a page whose
    every pair was filtered out, and those want opposite responses: the first
    is an OCR question, the second is a rule that is too strict. The second is
    what happened to every page of DS-0000-DAS-I-01, and the message sent the
    reader looking for a parsing problem that was not there.

    So the sentence is only used when it is TRUE, and otherwise the page says
    what it recovered and where it went.
    """
    if not pairs:
        return "no label-value pairs recovered from this page"
    counts = ", ".join(f"{n} by {reason}"
                       for reason, n in sorted(dropped.items(),
                                               key=lambda kv: (-kv[1], kv[0]))
                       if n)
    return (f"{len(pairs)} label-value pairs were recovered and none became a "
            f"fact ({counts or 'no reason recorded'})")


def extract_facts(
    document_id: str, *, allowed_document_ids: frozenset[str],
    review_run_id: str | None = None, replace: bool = True,
) -> dict:
    """Read one datasheet into facts, by whichever path its pages support.

    `replace=True` SUPERSEDES the document's current unconfirmed facts (#179):
    they stay in the table with `superseded_at` set, so a finding that cited
    one still resolves it by id, and only the new rows are current. Nothing
    is deleted, so there is no orphaning to acknowledge any more - the
    `acknowledge_orphaned_findings` flag B40 needed is gone from this path.

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
        "       d.stored_path, d.sha256"
        " FROM chunks c JOIN documents d ON d.id = c.document_id" + where +
        " AND c.document_id = ? AND c.retrievable = 1 ORDER BY c.ordinal",
        [*args, document_id],
    ).fetchall()
    empty = {"document_id": document_id, "facts": 0, "blanks": 0,
             "pages_read": 0, "pages_unparsed": 0, "parsed_fraction": None,
             "referenced_standards": [], "unparsed": [],
             "pages_unreadable": 0, "unreadable": [], "repaired": False}
    if not chunks:
        # B3: no retrievable chunk at all - every page is accounted for as
        # never reached, rather than the document simply having no pages.
        page_ledger.refresh(document_id, as_submittal=True)
        return empty

    stored_path = chunks[0]["stored_path"]
    # #177 PROVENANCE: the code that reads this sheet (this module and the
    # table parser it leans on) and exactly what it read - the stored file's
    # hash plus every chunk's text, in order. See `provenance.py`. NOT
    # covered: `page_ocr` text read by the OCR fallback tier, which carries
    # its own engine/model/dpi record; a re-OCR is visible there, not here.
    extractor_version = provenance.code_version("datasheets", "tables")
    inputs = provenance.input_hash(chunks[0]["sha256"], *(c["text"] for c in chunks))
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

    # B44: THE FILE'S CONDITION, BEFORE A SINGLE PAGE IS PARSED.
    #
    # A file that cannot be opened used to reach `_unparsed_reason` with no
    # pairs and come back "no label-value pairs recovered from this page" - the
    # sentence that function's own docstring warns is an OCR question. So a PDF
    # nobody could open was reported as a scanned page, and the reader was sent
    # after a recognition problem that did not exist. It was counted as READ
    # too, because `pages_read` is keyed off chunk spans rather than parse
    # success, which put pages that were never opened into the denominator of
    # `parsed_fraction`.
    #
    # `parsed_fraction` is None here rather than 0.0, the same distinction the
    # no-chunks return makes: nothing was read, so there is no fraction to
    # state. A fraction of zero would claim a measurement.
    condition, sentence, repaired = pdf_condition(stored_path)
    if condition is not None:
        pages = sorted(by_page)
        # B3: the file's condition goes on every page's ledger row, so a page
        # nobody could open is never read later as a page with no values.
        conn = connect()
        with conn:
            page_ledger.record_fact_pages(
                conn, document_id,
                {page: ("unreadable", 0, f"{condition}: {sentence}") for page in pages},
                extractor_version=extractor_version)
        page_ledger.refresh(document_id, as_submittal=True)
        return {**empty,
                "pages_unreadable": len(pages),
                "unreadable": [{"page": page, "rule": condition,
                                "reason": sentence} for page in pages],
                "referenced_standards": []}

    written = blanks = 0
    seen: set[tuple] = set()
    unparsed: list[dict] = []
    outcomes: dict[int, tuple] = {}
    corpus_text: list[str] = []

    # EVERY PAGE IS PAIRED BEFORE ANY FACT IS WRITTEN, because the furniture
    # rule is a statement about the DOCUMENT and cannot be decided one page at
    # a time: a label is a header precisely when it turns up on page after
    # page, which the first page cannot know.
    pairs_by_page: dict[int, list[tuple[str, str]]] = {}
    # #175 CASCADE: native text/table extraction is tried first (below); a
    # page that yields NOTHING from that tier falls through to OCR text
    # already sitting in `page_ocr` (step 2b, `ocr.py`) when it exists, and
    # facts recovered that way are marked low-confidence (see
    # `_LOW_CONFIDENCE_PAGES` and the write loop's confidence assignment
    # further down). A page resolved by the first tier never reaches the
    # second - the cascade stops at the first tier that produces evidence.
    low_confidence_pages: set[int] = set()
    grid_by_page: dict[int, list[dict]] = {}
    # B4 (#193 5.5): read ONCE per extraction, so a flag flipped mid-run
    # cannot give one datasheet two different extractions.
    geometry_on = bool(settings.geometry_reader_enabled)
    geometry_by_page: dict[int, list[dict]] = {}
    for page in sorted(by_page):
        found: list[tuple[str, str]] = []
        for shape in tables.parse_page_tables(stored_path, page):
            # #175 / parked B58: a ruled shape's rows are column-scoped, not
            # an alternating label/value sequence - see
            # pairs_from_table_shape's docstring for the measured cause.
            # Shapes under three columns wide fall through to
            # split_label_value unchanged inside that function.
            found.extend(pairs_from_table_shape([list(row) for row in shape]))
        found.extend(_pairs_from_pdf_page(stored_path, page))
        # B4 fix 5: column grids, read by word position (see grid_facts).
        grid_by_page[page] = _grid_facts_from_pdf_page(stored_path, page)
        if geometry_on:
            # B4 (#193 5.5): read, not yet written - see the write loop.
            geometry_by_page[page] = _geometry_rows_from_pdf_page(stored_path, page)
        if not found and not grid_by_page[page]:
            ocr_found = _pairs_from_ocr_fallback(document_id, page)
            if ocr_found:
                found = ocr_found
                low_confidence_pages.add(page)
            else:
                # Tier 3: vision-model fallback. Thin, gated hook - see
                # `_pairs_from_vision_fallback` docstring. A documented
                # no-op whenever no vision-capable provider is configured,
                # which is every environment this branch ships to today.
                vision_found = _pairs_from_vision_fallback(stored_path, page)
                if vision_found:
                    found = vision_found
                    low_confidence_pages.add(page)
        # SPLIT BEFORE THE FURNITURE COUNT, so a repeated compound row is
        # counted as the two fields it becomes rather than as one label that
        # exists nowhere in the output.
        split: list[tuple[str, str]] = []
        for one_label, one_value in found:
            split.extend(split_compound_pair(one_label, one_value))
        # #179: both readers ran over this page, so a cell they can both
        # read is here twice - see collapse_double_reads.
        pairs_by_page[page] = collapse_double_reads(split)
    furniture = furniture_labels(pairs_by_page)
    geometry_furniture: set[str] = set()
    geometry_version = None
    geometry_written = geometry_conflicts = 0
    if geometry_on:
        # The geometry reader reads title blocks too; the same counted rule
        # (a label with the same answer on three or more pages) sets its
        # page furniture aside.
        geometry_furniture = furniture_labels(
            {page: [(row["label"], row["value_text"] or "") for row in rows]
             for page, rows in geometry_by_page.items()})
        geometry_version = provenance.code_version("datasheets", "tables", "geometry_reader")
    # WHICH EQUIPMENT EACH PAGE IS ABOUT, decided over the whole document
    # because the one-tag rule cannot be seen from a single page.
    tags = stamp_tags(pairs_by_page)

    # B19: ONE DATASHEET, ONE TRANSACTION. Every fact used to commit on its
    # own, so an extraction that died on page 5 left pages 1-4 behind - and
    # the review path's "has no facts" guard then read that partial set as
    # done and never extracted the sheet again. The replace=True supersession
    # is in the same transaction, so a failed re-extraction cannot leave the
    # datasheet with FEWER current facts than it had either. Pages are parsed
    # above, before this block, so the write lock is held only for the writes.
    #
    # B40 -> #179 SUPERSESSION. replace=True used to DELETE the document's
    # unconfirmed facts, and `review_findings.fact_id` (no foreign key) was
    # left pointing at nothing; `orphan_guard` could only count and refuse.
    # Now the old rows STAY, marked `superseded_at`: every finding that cited
    # one still resolves it by id (comparison's by-id lookups), while every
    # reader of CURRENT facts - `list_facts`, `list_submittal_facts`, the
    # has-no-facts guard, `_document_is_tag_scoped` - leaves them out, so a
    # review never sees two readings of one cell. A CONFIRMED fact is never
    # superseded: a human's word outlives a re-parse. The audit row is in
    # the same transaction as the mark, so neither exists without the other.
    superseded_where = ("submittal_document_id = ? AND confirmed_by IS NULL"
                        " AND superseded_at IS NULL")
    conn = connect()
    with conn:
        if replace:
            findings_citing = orphan_guard.findings_orphaned_by_facts(
                superseded_where, (document_id,))
            superseded = conn.execute(
                "UPDATE submittal_facts SET superseded_at = ? WHERE " + superseded_where,
                (datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 document_id)).rowcount
            if superseded:
                orphan_guard.record_facts_superseded(
                    conn, "re_extract_facts", document_id,
                    superseded=superseded, findings_citing=findings_citing)
        for page, page_chunks in sorted(by_page.items()):
            pairs = pairs_by_page[page]
            chunk = page_chunks[0]
            corpus_text.extend(c["text"] or "" for c in page_chunks)
            page_written = 0
            # B4: the rule readers' facts on this page, by normalised label -
            # what a geometry reading is checked against. Filled only when the
            # geometry reader is on.
            rule_facts: dict[str, list[dict]] = {}
            page_geometry = 0
            # WHY EACH PAIR WAS DROPPED, counted per page. The reason string below
            # used to say "no label-value pairs recovered" whatever had happened,
            # so a page whose pairs were all FILTERED read exactly like a page that
            # could not be parsed at all - and it sent the reader to the wrong half
            # of the pipeline. On DS-0000-DAS-I-01 that message was printed for five
            # pages from which 190 pairs each had been recovered and discarded.
            dropped: dict[str, int] = {}
            for label, value in pairs:
                # Whitespace-insensitive, the same key collapse_double_reads
                # uses (#179) - one definition of "the same cell", not two.
                # THE PAGE IS PART OF THE KEY: the same value on another page
                # is another valve's value on a one-valve-per-page sheet, and
                # it is kept (the 15 "duplicates" #179 verified in the PDF).
                key = (page, *_same_cell_key(label, value))
                if not label.strip():
                    dropped["empty label"] = dropped.get("empty label", 0) + 1
                    continue
                if key in seen:
                    dropped["duplicate"] = dropped.get("duplicate", 0) + 1
                    continue
                seen.add(key)
                blank, _marker = is_blank_value(value)
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
                if tag_from_pair(label, value) is not None:
                    # THE TAG ROW IS NOT A FACT ABOUT THE EQUIPMENT, it is the
                    # equipment's name. It is read above and stamped onto the
                    # rows that ARE facts.
                    dropped["tag row"] = dropped.get("tag row", 0) + 1
                    continue
                if is_date_value(value):
                    # A timestamp is not a measurement. Left here rather than in
                    # `measure_value` so the cell still reads as what it is
                    # everywhere else; it is only as a FACT that it is wrong.
                    dropped["date"] = dropped.get("date", 0) + 1
                    continue
                if not states_a_value(value):
                    # A LABEL WITH FREE TEXT BESIDE IT IS NOT A FACT. "Prepared by:
                    # A. Engineer" and "Facility: Example Bay" have exactly the shape
                    # of a filled-in field and state nothing about the equipment.
                    # A quantity, an explicit blank, or a closed categorical answer
                    # - anything else is a caption.
                    dropped["value gate"] = dropped.get("value gate", 0) + 1
                    continue
                if checkbox_on_quantity(label, value):
                    # B4: a yes/no answer on a quantity's limit belongs to a
                    # question the reader did not reassemble - UNKNOWN, not
                    # a density of YES.
                    dropped["checkbox on quantity"] = dropped.get("checkbox on quantity", 0) + 1
                    continue
                if normalise_field_name(label) in furniture:
                    # Page furniture: this label appeared on three or more pages
                    # WITH THE SAME ANSWER EVERY TIME, so it is the title block or
                    # the footer, not a field. See `furniture_labels`.
                    dropped["furniture"] = dropped.get("furniture", 0) + 1
                    continue
                try:
                    # #175: a page resolved only by the OCR (or vision) tier
                    # of the cascade is evidence of a lower grade than native
                    # text/table extraction - the source text was recognised,
                    # not read - so it is written at a confidence below
                    # `LOW_CONFIDENCE_THRESHOLD` and `create_fact` routes it
                    # to `NEEDS_ENGINEER_REVIEW` rather than accepting it as
                    # a confident fact. See create_fact's validation_state.
                    fact_confidence = (
                        OCR_FALLBACK_CONFIDENCE if page in low_confidence_pages
                        else 0.6)
                    written_row = create_fact(
                        submittal_document_id=document_id, chunk_id=chunk["id"],
                        field_label=label.strip(), raw_value=value, page=page,
                        section=section_heading(chunk["section"]),
                        review_run_id=review_run_id,
                        confidence=fact_confidence,
                        extraction_method=(
                            "ocr_fallback" if page in low_confidence_pages
                            else "extracted"),
                        equipment_tag=tags.get(page),
                        commit=False,
                        extractor_version=extractor_version,
                        input_hash=inputs,
                    )
                except FactError:
                    dropped["refused by create_fact"] = dropped.get(
                        "refused by create_fact", 0) + 1
                    continue
                if geometry_on:
                    rule_facts.setdefault(written_row["field_name"], []).append(written_row)
                page_written += 1
                written += 1
                if blank:
                    blanks += 1
            # B4 fix 5: GRID ROWS, each value under the column its position
            # proves - or under no column, routed to an engineer.
            for cell in grid_by_page.get(page, []):
                key = (page, *_same_cell_key(cell["label"], cell["value"]),
                       cell["column"] or "")
                if key in seen:
                    dropped["duplicate"] = dropped.get("duplicate", 0) + 1
                    continue
                seen.add(key)
                if not states_a_value(cell["value"]):
                    dropped["value gate"] = dropped.get("value gate", 0) + 1
                    continue
                grid_blank, _marker = is_blank_value(cell["value"])
                try:
                    written_row = create_fact(
                        submittal_document_id=document_id, chunk_id=chunk["id"],
                        field_label=cell["label"], raw_value=cell["value"], page=page,
                        section=section_heading(chunk["section"]),
                        source_text=cell["source"], review_run_id=review_run_id,
                        confidence=0.6, extraction_method="grid",
                        equipment_tag=tags.get(page), commit=False,
                        validation_state=(None if cell["column"] or grid_blank
                                          else NEEDS_ENGINEER_REVIEW),
                        extractor_version=extractor_version, input_hash=inputs,
                        unit=cell["unit"], value_column=cell["column"],
                        one_quantity=cell["one_quantity"] and cell["unit"] is not None,
                    )
                except FactError:
                    dropped["refused by create_fact"] = dropped.get(
                        "refused by create_fact", 0) + 1
                    continue
                if geometry_on:
                    rule_facts.setdefault(written_row["field_name"], []).append(written_row)
                page_written += 1
                written += 1
                if grid_blank:
                    blanks += 1
            # B4 (#193 5.5): GEOMETRY READINGS, only with the flag on, and
            # only AFTER both rule readers so the rule reader always wins.
            for row in geometry_by_page.get(page, []):
                label = (row["label"] or "").strip()
                if not label:
                    dropped["empty label"] = dropped.get("empty label", 0) + 1
                    continue
                name = normalise_field_name(label)
                raw, printed_unit = _geometry_raw_value(row)
                if (name in furniture or name in geometry_furniture
                        or tag_from_pair(label, row["value_text"] or "") is not None
                        or is_date_value(raw)):
                    dropped["geometry: furniture, tag or date"] = dropped.get(
                        "geometry: furniture, tag or date", 0) + 1
                    continue
                same_label = rule_facts.get(name, [])
                if any(_geometry_agrees(raw, row["is_blank"], f) for f in same_label):
                    # The rule reader already wrote this reading: no duplicate.
                    dropped["geometry: same as rule reader"] = dropped.get(
                        "geometry: same as rule reader", 0) + 1
                    continue
                key = (page, name, "<blank>" if row["is_blank"] else _fold(raw), "geometry")
                if key in seen:
                    dropped["duplicate"] = dropped.get("duplicate", 0) + 1
                    continue
                seen.add(key)
                provenance_box = {
                    "reader": "geometry_reader", "source": row["source"],
                    "value_bbox": row["bbox"], "label_bbox": row["label_bbox"],
                    "position": row["position"], "table_id": row["table_id"],
                    "row": row["row"], "column": row["column"],
                    "condition": row["condition"], "note": row["note"],
                    # A DISAGREEMENT IS RECORDED, NOT RESOLVED: the rule
                    # facts this reading contradicts, by id.
                    "conflicts_with": [f["id"] for f in same_label] or None,
                }
                try:
                    geometry_row = create_fact(
                        submittal_document_id=document_id, chunk_id=chunk["id"],
                        field_label=label, raw_value=raw, page=page,
                        section=section_heading(chunk["section"]),
                        source_text=row["value_text"], review_run_id=review_run_id,
                        confidence=0.6, extraction_method=GEOMETRY_METHOD,
                        equipment_tag=tags.get(page), commit=False,
                        validation_state=GEOMETRY_CONFLICT if same_label else None,
                        extractor_version=geometry_version, input_hash=inputs,
                        value_column=row["column_label"],
                        # The reader's own blank evidence; a filled reading
                        # still goes through the text rule, so "217C By
                        # Contractor" stays the blank it is everywhere else.
                        blank=((True, row["blank_marker"] or "______")
                               if row["is_blank"] else None),
                        bbox=json.dumps(provenance_box, sort_keys=True),
                        printed_unit=printed_unit,
                    )
                except FactError:
                    dropped["refused by create_fact"] = dropped.get(
                        "refused by create_fact", 0) + 1
                    continue
                geometry_written += 1
                geometry_conflicts += 1 if same_label else 0
                # NOT `page_written`: see the ledger note below.
                page_geometry += 1
                written += 1
                if geometry_row["is_blank"]:
                    blanks += 1
            if page_written == 0:
                reason = _unparsed_reason(pairs, dropped)
                if page_geometry:
                    # B4: A GEOMETRY READING DOES NOT MAKE A PAGE "READ INTO
                    # FIELDS". The ledger's word decides whether an unmatched
                    # requirement is the contractor's MISSING_INFORMATION or
                    # an engineer's question (comparison.qualify_by_pages).
                    # Measured on a copy (2026-09-25, PSV sheet): ONE geometry reading on an otherwise
                    # unread page turned 79 engineer-review findings into
                    # contractor omissions. The page keeps the rule readers'
                    # verdict until the owner decides otherwise.
                    reason = (f"{reason}; {page_geometry} geometry-reader reading(s) "
                              "recorded, not counted as the page read into fields")
                unparsed.append({"page": page, "reason": reason})
                outcomes[page] = ("no_facts", 0, reason)
            else:
                outcomes[page] = ("facts", page_written, None)
        # B3: THE PER-PAGE OUTCOME IS KEPT, in the same transaction as the
        # facts it describes. It used to be returned and discarded, so nothing
        # downstream could tell a page with no values from a page never read.
        page_ledger.record_fact_pages(conn, document_id, outcomes,
                                      extractor_version=extractor_version)

    page_ledger.refresh(document_id, as_submittal=True)
    pages_read = len(by_page)
    # Only with the flag on, so the OFF result is exactly the pre-B4 one.
    geometry_counts = ({"geometry_facts": geometry_written,
                        "geometry_conflicts": geometry_conflicts} if geometry_on else {})
    return {
        **geometry_counts,
        "document_id": document_id,
        "facts": written,
        "blanks": blanks,
        "pages_read": pages_read,
        "pages_unparsed": len(unparsed),
        "parsed_fraction": (round((pages_read - len(unparsed)) / pages_read, 3)
                            if pages_read else None),
        "unparsed": unparsed,
        "referenced_standards": referenced_standards(" ".join(corpus_text)),
        # B44: this file opened, so nothing here is unreadable. `repaired` is
        # the third answer between "read" and "unreadable" - MuPDF rebuilt the
        # xref to open it and may have dropped content on the way, without
        # raising. Reported rather than silently trusted.
        "pages_unreadable": 0,
        "unreadable": [],
        "repaired": repaired,
    }


def list_facts(document_id: str, *, allowed_document_ids: frozenset[str],
               blanks_only: bool = False) -> list[dict]:
    """One datasheet's facts, under the caller's grants, joined to their chunk.

    #175 REVISION-VERSIONING: `f.submittal_document_id` is a foreign key to
    `documents.id`, and a `documents` row is never edited in place - a
    changed revision is a NEW row with its own id and its own `sha256`
    (Part 2's finding: today that new row has no automatic link back to the
    old one, which is a separate, larger gap this issue does not reopen).
    What that DOES already give for free is exactly what this issue asks
    for: every fact this function returns is traceable to the *exact*
    document revision it was read from, because it can only ever have come
    from the one immutable, content-addressed row named by
    `document_sha256` below. No new column on `submittal_facts` was needed
    for that - the existing foreign key already carries it, one join away.
    """
    submittal_review.ensure_schema()
    where, args = _scope_clause(allowed_document_ids, "f.submittal_document_id")
    sql = ("SELECT f.*, c.page_start AS chunk_page,"
           " d.sha256 AS document_sha256, d.filename AS document_filename"
           " FROM submittal_facts f"
           " LEFT JOIN chunks c ON c.id = f.chunk_id"
           " JOIN documents d ON d.id = f.submittal_document_id" + where +
           " AND f.submittal_document_id = ?"
           # Current facts only (#179); superseded rows live on for the
           # findings that cite them by id.
           " AND f.superseded_at IS NULL")
    params = [*args, document_id]
    if blanks_only:
        sql += " AND f.is_blank = 1"
    sql += " ORDER BY f.page, f.field_name"
    return [{**dict(r), "citation_resolves": r["chunk_page"] is not None}
            for r in connect().execute(sql, params).fetchall()]
