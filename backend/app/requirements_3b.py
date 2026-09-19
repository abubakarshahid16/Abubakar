"""Phase 3B: structured requirements - limits, units, conditions, exceptions.

DETERMINISTIC, IN PYTHON, NEVER THE MODEL (master plan section 14). Nothing in
this module calls Ollama. A numeric limit that depends on a language model is a
limit nobody can reproduce, and the whole point of extracting a standard once
is that the answer is stable.

WHAT IS REUSED, NOT REWRITTEN

`claims.py` already does unit handling, and it does it better than a second
attempt would: `normalise`, `normalise_strict`, `Measurement`, `parse_value`,
`parse_comparator`, `unit_dimension`, `UnknownUnit`, `_UNIT_TABLE`. It already
refuses Fahrenheit by design ("a wrong temperature conversion is a safety
defect"), already reads NORSOK comma decimals, and already keeps the raw
spelling beside the normalised pair. There is no second unit table here.

THE CONSEQUENCE, MEASURED, AND IT IS NOT A DEFECT: the units an engineering
standard states its noise limits in - `dB(A)` - and the ones this corpus's real
tables use - `pcf` - are BOTH unknown to that table. `normalise` returns
`normalized_value = None` for them and preserves `raw_value`/`raw_unit`
exactly. That is the honesty rule working: an unknown unit is None, never 0 and
never a guess. The value is still extracted, still cited and still quotable; it
simply cannot be compared across unit systems until someone adds the unit
deliberately.
"""

from __future__ import annotations

import json
import re

from . import claims

#: What kind of thing a requirement states. Enforced in Pydantic
#: (`schemas.RequirementType`), stored as plain TEXT.
#:
#: NOTHING IS INVENTED FOR TEXT THE PARSER DID NOT UNDERSTAND. A sentence that
#: states an obligation but no recognisable limit stays `statement` - which is
#: a true description of it - rather than being forced into `numeric_limit`
#: with a null value, a shape that reads as a limit nobody recorded.
REQUIREMENT_TYPES = (
    "numeric_limit",
    "statement",
    "table_value",
)

#: A unit spelling sitting in a table header: "Southern Pine Creosote (pcf)".
_HEADER_UNIT = re.compile(r"\(([^)]{1,16})\)\s*$")

#: "shall not exceed 90 dB(A)", "shall be at least 12 mm", "maximum 2.5 pcf".
#: The comparator words are `claims.parse_comparator`'s vocabulary; the number
#: and unit are handed to `claims.normalise`, which owns both.
_LIMIT = re.compile(
    r"(?P<cmp>shall\s+not\s+exceed|shall\s+exceed|not\s+less\s+than|at\s+least"
    r"|no\s+more\s+than|not\s+more\s+than|maximum|minimum|max|min|up\s+to"
    r"|greater\s+than|less\s+than)\s*"
    r"(?:of\s+)?"
    r"(?P<value>[-+]?\d[\d.,]*)\s*"
    r"(?P<unit>[A-Za-z%µμ°][A-Za-z0-9()/%µμ°.\-]{0,15})?",
    re.IGNORECASE,
)

#: How a comparator phrase maps onto an operator. `claims.parse_comparator`
#: handles the bare forms; these are the multi-word ones a specification uses.
_OPERATOR = {
    "shall not exceed": "<=", "no more than": "<=", "not more than": "<=",
    "up to": "<=", "maximum": "<=", "max": "<=", "less than": "<",
    "not less than": ">=", "at least": ">=", "minimum": ">=", "min": ">=",
    "greater than": ">", "shall exceed": ">",
}

#: An exception clause. "except for pressure relief valves", "other than ...",
#: "with the exception of ...". The master plan's worked case is a 90 dB(A)
#: general limit with a 115 dB(A) exception for pressure relief valves, and an
#: exception that is dropped turns a compliant PSV into a false finding.
_EXCEPTION = re.compile(
    r"\b(?:except(?:\s+for|\s+that|ing)?|other\s+than|with\s+the\s+exception\s+of)\b"
    r"\s*(?P<rest>.+)", re.IGNORECASE)

#: A condition the requirement only holds under. "for new equipment",
#: "where the service is sour", "in marine environments".
#: The clause STOPS AT THE COMMA. "For new equipment, the noise level shall
#: not exceed 90 dB(A)" conditions on "new equipment", not on "new equipment,
#: the noise level" - the comma is where the circumstance ends and the subject
#: begins. Running past it produced a condition containing the thing being
#: limited, which would never match anything and would silently narrow the
#: requirement to nothing.
_CONDITION = re.compile(
    r"\b(?:for|where|when|in\s+the\s+case\s+of|applicable\s+to)\b\s+"
    r"(?P<rest>[^.;,]{3,80})", re.IGNORECASE)


#: A table cell that IS a number, rather than prose containing one.
#:
#: `claims.parse_value` deliberately tolerates a leading prefix so that "<= 90"
#: and "max 90" yield 90 - correct for a sentence, wrong for a cell. A cell
#: reading "see 5.2" is a cross-reference to clause 5.2 and parses as the
#: number 5.2, which would be recorded as a limit of five point two. Found by
#: the test for exactly that case.
#:
#: A cell may carry a comparator symbol and a footnote marker and still be a
#: value; it may not carry words.
_CELL_VALUE = re.compile(r"^\s*[<>=≤≥±]{0,2}\s*[-+]?\d[\d.,]*\s*[*†‡]?\s*$")


def cell_value(cell: str) -> str | None:
    """The number in a table cell, or None when the cell is not a number."""
    if not cell or not _CELL_VALUE.match(cell):
        return None
    return cell.strip()


def header_unit(header: str) -> str | None:
    """The unit spelling out of a table header, or None.

    "Southern Pine Creosote (pcf)" -> "pcf". Returns the SPELLING, never a
    normalised unit: whether `pcf` means anything is `claims`'s decision, not
    this function's, and the raw spelling is what the document said.
    """
    match = _HEADER_UNIT.search(header or "")
    if not match:
        return None
    candidate = match.group(1).strip()
    # A parenthesised phrase is not a unit. "(after AASHTO 2014)" is a
    # citation; "(pcf)" is a unit. Length and the absence of spaces are the
    # discriminator, and a wrong guess here would attach a bogus unit to a
    # real number.
    if " " in candidate or not candidate:
        return None
    return candidate


#: The sentence DEFERS to a table rather than stating a limit itself.
#:
#: "The internal design pressure shall be according to the following table"
#: carries a mandatory verb and a number, and the number is a ROW BOUNDARY of
#: the table that follows - "Up to 6,900 kPa". Read as a limit it says design
#: pressure must not exceed 6,900 kPa, which the standard does not say.
_TABLE_REFERENCE = re.compile(
    r"\b(?:according\s+to|per|see|as\s+(?:given|shown|tabulated|specified)\s+in|"
    r"in\s+accordance\s+with)\s+(?:the\s+)?(?:following\s+)?table\b"
    r"|\bthe\s+following\s+table\b"
    r"|\bas\s+tabulated\b"
    r"|\btable\s+\d+(?:\.\d+)*\b",
    re.IGNORECASE)

#: A TABLE ROW, not a sentence: a boundary phrase with no obligation in it.
#: "Up to 6,900 kPa (1,000 psi)" is a column heading for a lookup, and it is
#: only ever a requirement by being read out of context.
_BOUNDARY_FRAGMENT = re.compile(
    r"\b(?:up\s+to|over|above|below|under)\s+[-+]?\d"
    r"|\b[-+]?\d[\d.,]*\s*(?:to|–|—)\s*[-+]?\d[\d.,]*\s*[A-Za-z%°]"
    # The unit sits between the number and the phrase - "6,900 kPa and above" -
    # so one optional unit-shaped token is allowed to intervene.
    r"|\b\d[\d.,]*\s*(?:[A-Za-z%°/()]{1,10}\s*)?"
    r"(?:and\s+(?:above|below|over|under|greater|less))\b",
    re.IGNORECASE)


def is_table_row(sentence: str) -> bool:
    """True when this text is a table reference or a table row, not a limit.

    TWO SHAPES, MEASURED ON THE CORPUS:

      * the sentence carries a mandatory verb AND defers to a table. SAES-D-001
        6.2.2 and SAES-E-014 7.2.4 are both of this kind, and both matched a
        real submitted pressure in the first end-to-end review. Neither states
        a limit; both point at a lookup whose rows the extractor then read as
        one.

      * the fragment has NO mandatory verb and is shaped like a row boundary.
        "Up to 6,900 kPa", "15 to 25 mm", "1,100 kPa and above" are cells, and
        a cell that happens to contain a number is not an obligation.

    A sentence that states its own limit is untouched, whatever else is in it:
    "shall not exceed 5 g/L" is a requirement even if a table appears later in
    the clause, because the obligation and the number are in the same sentence.
    """
    text = " ".join((sentence or "").split())
    if not text:
        return False
    # A SENTENCE THAT STATES ITS OWN COMPARATOR STATES ITS OWN LIMIT, whatever
    # else it mentions. "shall not exceed 5 g/L (see Table 3)" is a real
    # requirement that happens to cite a table, and this check comes first so
    # such a sentence can never be reclassified away.
    if _COMPARATOR_PRESENT.search(text):
        return False
    # Otherwise the number belongs to a table if the text either defers to one
    # or is shaped like one of its rows. The boundary shape is searched
    # ANYWHERE in the text, not just at the start: a table flattened into prose
    # by the extractor reads "Maximum Operating Pressure (MOP) Design Pressure
    # Up to 6,900 kPa ... and above", where the boundary phrase is in the
    # middle and the row it belongs to is the whole line.
    return bool(_TABLE_REFERENCE.search(text) or _BOUNDARY_FRAGMENT.search(text))


#: Mandatory wording, duplicated from `standards` deliberately: importing it
#: would make this module depend on the one that depends on it.
_MANDATORY_HERE = re.compile(
    r"\b(shall|must|is\s+required\s+to|are\s+required\s+to|is\s+to\s+be"
    r"|are\s+to\s+be)\b", re.IGNORECASE)

#: A comparator phrase the sentence states for ITSELF.
_COMPARATOR_PRESENT = re.compile(
    r"\b(?:not\s+exceed|no\s+greater\s+than|no\s+more\s+than|less\s+than|"
    r"greater\s+than|at\s+least|at\s+most|minimum\s+of|maximum\s+of|"
    r"or\s+less|or\s+more|not\s+less\s+than|not\s+more\s+than)\b",
    re.IGNORECASE)


def subject_phrase(sentence: str) -> str | None:
    """The text before the comparator, or None when there is no comparator.

    Exposed so `standards.subject_of` does not have to reach for `_LIMIT`
    itself - the limit pattern is this module's, and a second module splitting
    on it would be a second place to fix when it changes.
    """
    if not sentence or not _LIMIT.search(sentence):
        return None
    head = _LIMIT.split(sentence)[0]
    return " ".join(head.split()).strip() or None


def unit_token(candidate: str | None) -> str | None:
    """The word after a number, IF it is a unit. Otherwise None.

    THE PREVIOUS RULE WAS "keep whatever word follows the number, because the
    document said it". Measured against the standards corpus that produced
    `raw_unit` values of 'locations', 'print', 'times' and 'day' - from "in 3
    locations", "9 print" and "2 times" - stored beside a real number in a row
    typed `numeric_limit`. A reader sees a limit of 3 locations; there is no
    such quantity, and no comparison can ever be made against it.

    `claims` is the authority on what a unit is, and this asks it. An
    unrecognised word means the number HAS no unit, which is a true statement
    about the sentence - the count is still recorded in `raw_value`.

    TRAILING PUNCTUATION IS STRIPPED FIRST, and that single character was the
    whole defect behind the product's own worked example: SAES-A-008 says "the
    maximum solids loading limit shall not exceed 5 g/L." and the sentence's
    full stop was captured into the unit, so `g/L.` was not `g/L`, did not
    normalise, and the limit was stored with a null value.

    What is NOT stripped: a leading character, anything inside the token, and
    the raw spelling itself - only trailing `.,;:)` go, and only for the
    purpose of asking `claims` whether it knows the word. The spelling handed
    back is the cleaned one, because `g/L.` is not something any reader wants
    to see in a unit column.
    """
    text = (candidate or "").strip()
    if not text:
        return None
    cleaned = text.rstrip(".,;:")
    # A CLOSING BRACKET IS ONLY PUNCTUATION WHEN NOTHING OPENED IT. "dB(A)" is
    # one unit and "dB" is a different one, so stripping the bracket off the
    # end turns the corpus's noise limits into a unit nobody recognises - the
    # phase 5B defect, arriving from the other side. Stripped only when
    # unbalanced, which is the "(see 5 m)" case.
    while cleaned.endswith(")") and cleaned.count("(") < cleaned.count(")"):
        cleaned = cleaned[:-1].rstrip(".,;:")
    if not cleaned:
        return None
    return cleaned if claims.is_unit(cleaned) else None


def measure(raw_value: str, raw_unit: str | None) -> claims.Measurement:
    """`claims.normalise`, and nothing else.

    Wrapped only so this module has one call site and so the contract is
    stated here: an unknown unit yields `normalized_value = None`, and the raw
    strings are preserved exactly. It never raises - `normalise_strict` is the
    raising variant and is used where a caller must not proceed on an unknown
    unit.
    """
    return claims.normalise(raw_value, raw_unit or "")


def parse_limit(sentence: str) -> dict | None:
    """A numeric limit out of one sentence, or None.

    None means "this sentence states no limit I recognise", and the caller
    records the requirement as a `statement`. It does NOT mean the sentence is
    not a requirement.
    """
    match = _LIMIT.search(sentence)
    if not match:
        return None
    phrase = " ".join(match.group("cmp").lower().split())
    operator = _OPERATOR.get(phrase)
    if operator is None:
        return None
    raw_value = match.group("value")
    raw_unit = unit_token(match.group("unit"))
    measurement = measure(raw_value, raw_unit)
    return {
        "operator": operator,
        "raw_value": raw_value,
        "raw_unit": raw_unit,
        "value": measurement.normalized_value,
        "unit": measurement.normalized_unit,
    }


def parse_exceptions(sentence: str) -> list[dict]:
    """Exception clauses, each with its own limit when it states one.

    THE WORKED CASE: "The noise level shall not exceed 90 dB(A), except for
    pressure relief valves, which shall not exceed 115 dB(A)." Two limits, and
    the second one is the reason a compliant PSV is not reported as a finding.

    An exception with no limit of its own is still recorded - "except where
    otherwise specified" changes what the general limit means even though it
    states no number.
    """
    match = _EXCEPTION.search(sentence)
    if not match:
        return []
    rest = match.group("rest").strip().rstrip(".")
    limit = parse_limit(rest)
    applies_to = rest
    if limit:
        # Trim the limit clause off the subject so "pressure relief valves,
        # which shall not exceed 115 dB(A)" yields the equipment, not the
        # sentence.
        applies_to = _LIMIT.split(rest)[0]
        applies_to = re.split(r",?\s*which\b|,?\s*that\b", applies_to)[0]
    applies_to = applies_to.strip().strip(",").strip()
    out = {"applies_to": applies_to or rest}
    if limit:
        out.update({k: v for k, v in limit.items()})
    return [out]


def parse_condition(sentence: str) -> str | None:
    """The condition a requirement holds under, or None.

    Deliberately conservative. A wrong condition NARROWS a requirement, which
    silently excuses a real deviation - the opposite failure from a wrong
    limit, and harder to notice. When the sentence opens with the obligation
    rather than the circumstance, there is no condition.
    """
    # Only a LEADING circumstance counts. "For new equipment, the noise level
    # shall not exceed..." is conditional; "...shall be applied for corrosion
    # protection" is a purpose, not a condition.
    head = sentence.split(" shall")[0].split(" must")[0]
    if head == sentence:
        return None
    match = _CONDITION.match(head.strip())
    if not match:
        return None
    condition = match.group("rest").strip().rstrip(",").strip()
    return condition or None


#: A requirement whose number belongs to a LOOKUP TABLE, not to a limit.
TABLE_ROW = "table_row"


def classify(sentence: str, limit: dict | None) -> str:
    """What kind of requirement this is. Never invented.

    A sentence with a recognised limit is a `numeric_limit`; everything else is
    a `statement`, which is a true description rather than a guess at one.

    UNLESS THE NUMBER BELONGS TO A TABLE. Checked before the limit, because
    such a sentence DOES parse as a limit and that is the whole problem:
    SAES-D-001 6.2.2 says design pressure "shall be according to the following
    table", the parser read the table's first row boundary - "Up to 6,900 kPa" -
    and stored a limit of <= 6,900 kPa that the standard never states. In the
    first end-to-end review it matched a real submitted pressure, and only a
    mismatch of unit spellings stopped it becoming a confident wrong verdict.
    """
    if not limit:
        # NO NUMBER, NO TABLE ROW. A sentence that merely MENTIONS a table -
        # "inspection shall follow the procedure in Table 4" - states an
        # obligation and no quantity, and it was already a `statement`. Calling
        # it a table row moved 71 requirements out of `statement` into a status
        # that says "an engineer must read this table", which is neither true
        # nor useful: there is no number in it to misread.
        #
        # `table_row` exists for exactly one failure - a number lifted out of a
        # lookup and stored as a limit - so it applies only where a number was
        # actually lifted.
        return "statement"
    if is_table_row(sentence):
        return TABLE_ROW
    return "numeric_limit"


def field_name(sentence: str, header: str | None = None) -> str | None:
    """A short name for what is being limited, or None.

    From a TABLE, the row label or column header is the field and is used
    verbatim - the document named it. From a SENTENCE there is no reliable
    field name without parsing English, so this returns None rather than
    guessing one, and 3B records the requirement text instead.
    """
    if header:
        cleaned = _HEADER_UNIT.sub("", header).strip()
        return cleaned or None
    return None


def encode_exceptions(exceptions: list[dict]) -> str | None:
    """Exceptions as JSON, or None when there are none.

    None rather than "[]" so that "no exceptions recorded" and "this clause was
    read and has none" do not have to be distinguished by an empty string in
    the column - the read path treats both as empty.
    """
    return json.dumps(exceptions) if exceptions else None


def decode_exceptions(raw: str | None) -> list[dict]:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


# ----------------------------------------------------------------- conflicts

def find_conflicts(rows: list[dict]) -> list[dict]:
    """Requirements from DIFFERENT standards that limit the same field
    differently.

    SURFACED, NEVER RESOLVED. Two standards disagreeing about a limit is a
    fact about the library that an engineer has to decide, and picking one
    silently would hide exactly the thing they need to see. There is no
    precedence rule here and there must not be one: seniority between two
    company standards is not something this system can know.

    Compared on the NORMALISED value when both sides have one, because 12 mm
    and 12000 um are the same limit written differently. When either side is
    unnormalised - an unknown unit - the pair is NOT reported as a conflict:
    two values this system cannot compare are not evidence of disagreement,
    and claiming one would be inventing a finding.
    """
    by_field: dict[str, list[dict]] = {}
    for row in rows:
        field = (row.get("field") or "").strip().lower()
        if not field or row.get("value") is None:
            continue
        by_field.setdefault(field, []).append(row)

    conflicts: list[dict] = []
    for field, group in by_field.items():
        documents = {r.get("standard_document_id") for r in group}
        if len(documents) < 2:
            continue          # one standard restating itself is not a conflict
        distinct = {(r.get("operator"), r.get("value"), r.get("unit")) for r in group}
        if len(distinct) < 2:
            continue          # the same limit in two standards agrees
        conflicts.append({
            "field": field,
            "requirements": [
                {
                    "id": r.get("id"),
                    "standard_document_id": r.get("standard_document_id"),
                    "clause": r.get("clause"),
                    "page": r.get("page"),
                    "operator": r.get("operator"),
                    "value": r.get("value"),
                    "unit": r.get("unit"),
                    "raw_value": r.get("raw_value"),
                    "raw_unit": r.get("raw_unit"),
                }
                for r in group
            ],
        })
    return conflicts
