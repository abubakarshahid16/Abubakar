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

#: An obligation with no field, subject or value a sheet could fill in. Named
#: because `comparison` routes it (B9: NOT_IN_DOCUMENT_SCOPE when unmatched).
STATEMENT = "statement"

#: A sentence whose obligation is "go and read that other document", stated
#: under a condition that happens to contain a number.
#:
#: SAES-D-001 9.2.5 is the worked case: "temperatures greater than 260°C
#: (500°F) shall be in accordance with PIP VEFV1100". The parser read
#: "greater than 260" as a limit of `> 260 °C`, the model tier paired it with
#: a datasheet field reading 60 °C, and the engine reported the contractor
#: NON_COMPLIANT for not exceeding 260 °C. The standard states no such
#: requirement: it says that IF the temperature is above 260 °C, a different
#: document governs.
#:
#: The 260 is the THRESHOLD OF APPLICABILITY, not a limit on anything. Never
#: compared.
APPLICABILITY_TRIGGER = "applicability_trigger"

#: A limit stated as a DIFFERENCE from something else: "at least 28°C warmer
#: than the calculated dew point".
#:
#: SAES-D-001 14.3 is the worked case. The parser read `>= 28 °C`, the model
#: tier paired it with an internal design temperature of 95 °C, and the engine
#: reported COMPLIANT - 95 >= 28 - which is arithmetic against a number that
#: is not a temperature at all but a margin between two of them. The reference
#: value (a dew point computed from the process stream) is nowhere in the
#: submittal, so no comparison can be made without a person.
#:
#: Matched but never compared: `compare` raises it to NEEDS_ENGINEER_REVIEW
#: and quotes the sentence.
RELATIVE_LIMIT = "relative_limit"

#: A unit spelling sitting in a table header: "Southern Pine Creosote (pcf)".
_HEADER_UNIT = re.compile(r"\(([^)]{1,16})\)\s*$")

#: "shall not exceed 90 dB(A)", "shall be at least 12 mm", "maximum 2.5 pcf".
#: The comparator words are `claims.parse_comparator`'s vocabulary; the number
#: and unit are handed to `claims.normalise`, which owns both.
#: A negation that sits several words away from the comparative it negates:
#: "but in no case shall it be less than 190 L/s". Nothing between "no" and
#: "less than" is a comparator, so a pattern that only widens around the word
#: "not" walks past this one too and reads `< 190` for a MINIMUM.
_IN_NO_CASE_RE = r"in\s+no\s+case\s+(?:shall|may|should|will)\s+(?:it\s+)?(?:be\s+)?"

#:
#: THE NEGATION MUST BE PART OF THE MATCH. "shall not be less than 45 m" was
#: read as `< 45`: no alternative covered the "be", so the scan walked past
#: the negation and matched the bare "less than" that follows it. A flipped
#: operator is worse than a missing rule - it passes a non-compliant value and
#: fails a compliant one, with a citation attached. 129 of 1,731 stored limits
#: across 79 standards carried a flipped operator before this was widened.
#: The negated forms therefore come FIRST and absorb "no"/"not", an optional
#: "be", and the comparative word, so the bare alternatives at the end can
#: only ever match a comparison that really is bare.
#: "in excess of" - ONLY when the sentence negates it.
#:
#: SAES-A-105 5.3.3 states this standard's PRIMARY limit as "new equipment
#: shall not generate noise in excess of 90 dB(A)" and its four exceptions as
#: "may not exceed 105/97/105/115 dB(A)". Only the exceptions parsed, so the
#: corpus held the exceptions to a rule it did not hold.
#:
#: THE NEGATION IS NOT OPTIONAL HERE, and this is the whole subtlety. Bare
#: "in excess of" is overwhelmingly a TRIGGER, not a limit: "equipment that
#: will generate noise in excess of 85 dB(A) ... shall submit Form 7305-ENG"
#: obliges a submission, and "oxygen transfer rates in excess of 1.22 kg/kWh
#: shall be justified" obliges a justification. Neither forbids the value.
#: Reading them as limits would invent ceilings no standard states - the
#: false-rule failure this parser exists to avoid - so only the negated form
#: is admitted. The trigger sense belongs to `applicability_trigger`, not
#: here.
#:
#: Up to four words may sit between the negation and the phrase, which covers
#: "shall not generate noise in excess of" and "shall not be in excess of"
#: while stopping short of "shall not be exposed to continuous occupational
#: noise levels in excess of those listed in Table 3" - which states no number
#: of its own and must stay a statement.
_IN_EXCESS_RE = (r"(?:shall|must|may|should|will)\s+not\s+"
                 r"(?:\w+\s+){0,4}?in\s+excess\s+of")


#: B5/#193: comparative adjectives beside "less/more/greater" a standard's
#: prose uses with the same "than" grammar - SAME WORD FAMILY `_RELATIVE_TAIL`
#: already vets below, one vocabulary rather than two (`contradicts_source`'s
#: own docstring warns against exactly that drift). Split by which side of
#: "smaller" each adjective means, so `_OPERATOR` below can map them without
#: a second list to keep in step with this one.
_SMALLER_THAN = ("closer", "smaller", "thinner", "lower", "shorter", "narrower")
_LARGER_THAN = ("larger", "thicker", "higher", "longer", "wider")
_COMPARATIVE_THAN = r"(?:" + "|".join(_SMALLER_THAN + _LARGER_THAN) + r")\s+than"

_LIMIT = re.compile(
    r"(?P<cmp>" + _IN_NO_CASE_RE + r"(?:less|more|greater)\s+than"
    r"|" + _IN_NO_CASE_RE + r"exceed"
    r"|" + _IN_EXCESS_RE + r"|(?:shall|must|may|should|will)\s+not\s+exceed"
    r"|(?:no|not)\s+(?:be\s+)?less\s+than"
    r"|(?:no|not)\s+(?:be\s+)?(?:more|greater)\s+than"
    r"|shall\s+exceed|at\s+least"
    r"|maximum|minimum|max|min|up\s+to"
    r"|greater\s+than|less\s+than"
    r"|" + _COMPARATIVE_THAN +
    # Single-word prepositions meaning "less/more than" - "the design
    # temperature shall be below 441degC" - not covered by any "than" form.
    # `\b` on both sides, so this never matches inside a longer word.
    r"|\b(?:below|under|beneath|above|over)\b)\s*"
    r"(?:of\s+)?"
    r"(?P<value>[-+]?\d[\d.,]*)\s*"
    r"(?P<unit>[A-Za-z%µμ°][A-Za-z0-9()/%µμ°.\-]{0,15}"
    r"(?:\s*\([A-Za-z]\))?)?",
    re.IGNORECASE,
)

#: How a comparator phrase maps onto an operator. `claims.parse_comparator`
#: handles the bare forms; these are the multi-word ones a specification uses.
#: Keyed by the CANONICAL phrase - see `_canonical_comparator`, which folds
#: "no less than" and "not be less than" onto "not less than" so one key
#: covers every spelling `_LIMIT` admits.
_OPERATOR = {
    "shall not exceed": "<=", "must not exceed": "<=", "may not exceed": "<=",
    "not more than": "<=", "not greater than": "<=", "not exceed": "<=",
    "up to": "<=", "maximum": "<=", "max": "<=", "less than": "<",
    "not less than": ">=", "at least": ">=", "minimum": ">=", "min": ">=",
    "greater than": ">", "shall exceed": ">",
    # B5/#193: the comparative-adjective and single-word forms above, mapped
    # from the same two lists `_LIMIT` builds its pattern from - generated,
    # not hand-duplicated, so the two can never drift apart.
    **{f"{word} than": "<" for word in _SMALLER_THAN},
    **{f"{word} than": ">" for word in _LARGER_THAN},
    "below": "<", "under": "<", "beneath": "<", "above": ">", "over": ">",
}

#: The leading negation of a negated comparison: "no", "not", "not be", and
#: the long-range "in no case shall it be".
_NEGATION = re.compile(r"^(?:" + _IN_NO_CASE_RE + r"|(?:no|not)\s+(?:be\s+)?)")


#: Any negated "in excess of", however many words sit in its middle.
_IN_EXCESS_FOLD = re.compile(r"\bnot\b.*\bin\s+excess\s+of\b")


def _canonical_comparator(phrase: str) -> str:
    """The phrase as `_OPERATOR` keys it: lowercased, single-spaced, and with
    every spelling of the negation folded onto "not "."""
    folded = " ".join(phrase.lower().split())
    # "shall not generate noise in excess of" and "shall not be in excess of"
    # are the same comparison with different prose in the middle; one key
    # cannot be written for every verb a standard might use, so the whole
    # negated phrase folds onto "not exceed", which `_OPERATOR` already maps.
    if _IN_EXCESS_FOLD.search(folded):
        return "not exceed"
    folded = re.sub(r"^(?:shall|must|may|should|will)\s+not\s+exceed$",
                    "not exceed", folded)
    return _NEGATION.sub("not ", folded)

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


#: "shall be in accordance with", "refer to", "shall conform to". The wording
#: a specification uses to hand the question to another document.
_DEFERRAL = re.compile(
    r"\b(?:in\s+accordance\s+with|according\s+to|as\s+specified\s+in"
    r"|as\s+defined\s+in|as\s+given\s+in|refer\s+to|shall\s+conform\s+to"
    r"|conform\s+to|comply\s+with|shall\s+follow|follow|as\s+per|per)\b",
    re.IGNORECASE)

#: A NAMED DOCUMENT, not a table and not a quantity. Two shapes, both taken
#: from the corpus: a standard's designation (PIP VEFV1100, SAES-D-001,
#: ASME VIII, API 650, ISO 15156, NACE MR0175) and an internal cross-reference
#: (paragraph 7.4.4, clause 5.2, section 11).
#:
#: The designation needs TWO OR MORE CAPITALS so an ordinary capitalised word
#: at the start of a sentence is not read as a document.
#: A DESIGNATION'S OWN PARTS ARE NOT QUANTITIES. "ASME Section VIII Division
#: 2", "ASTM A516 Grade 70", "clause 5.2" - the numbers in these name pieces
#: of a document, and leaving them behind made the bare-number test below
#: reject a real trigger because "Division 2" still had a digit in it.
_DOCUMENT_PART = (r"paragraph|clause|section|appendix|annex|division|div"
                  r"|part|chapter|revision|rev|edition|class|grade|type|level")
#: CASE MATTERS ON THE FIRST ARM AND NOT ON THE SECOND, so the flag is scoped
#: rather than applied to the pattern. `[A-Z]{2,}` under `re.IGNORECASE`
#: matches any two letters, which would make every word in the sentence a
#: document reference and the check below would pass on anything.
#:
#: SPLIT OUT AS ITS OWN PATTERN (`_DOCUMENT_DESIGNATION`) so `cited_document`
#: below can search for JUST the designation shape - never the internal
#: cross-reference arm ("clause 5.2" is not a document to look up in a
#: library) - while `_DOCUMENT_REF` still combines both, unchanged, built
#: FROM this pattern rather than a second copy of it, so the two definitions
#: cannot drift apart.
_DOCUMENT_DESIGNATION = re.compile(r"\b[A-Z]{2,}[A-Z0-9]*(?:[-\s][A-Z0-9]+){0,3}\b")

_DOCUMENT_REF = re.compile(
    _DOCUMENT_DESIGNATION.pattern +
    rf"|(?i:\b(?:{_DOCUMENT_PART})\s+(?:\d+(?:\.\d+)*|[IVXLC]+)\b)")

#: A number that is the sentence's OWN quantity: a digit that is not part of a
#: document designation. Applied after the designations have been removed.
_BARE_NUMBER = re.compile(r"\d")

#: A limit stated as a difference from a reference: "at least 28°C warmer
#: than the dew point", "within 5 % of the design value".
#:
#: The relative word comes AFTER the value, which is what separates this from
#: an ordinary limit: "greater than 5 mm" is a limit and "5 mm greater than
#: the nominal" is a margin. `within N unit of X` is the same shape written
#: the other way round and is included explicitly.
#: The tail of a relative limit, ANCHORED AT THE PARSED VALUE: the number
#: itself, its unit, an optional bracketed conversion - "28°C (50°F)" - and
#: then the comparative word.
#:
#: Anchoring is the whole correctness of this check. Searched anywhere in the
#: sentence it fired on SAES-L-XXX 11.1.3, "In areas within 100 m of a
#: platform structure, submarine cable shall be buried a minimum of 1 m": the
#: parsed limit is the 1 m burial depth, which is an ordinary absolute limit,
#: and the relative phrase belongs to a CONDITION about where the rule
#: applies. A sentence may contain a relative phrase and still state a plain
#: limit, so what matters is whether the phrase follows THE NUMBER THAT WAS
#: TAKEN AS THE LIMIT.
_RELATIVE_TAIL = re.compile(
    r"[-+]?\d[\d.,]*\s*"
    r"(?:[A-Za-z%µμ°][A-Za-z0-9()/%µμ°.\-]{0,15})?\s*"
    r"(?:\([^)]{1,20}\)\s*)?"
    r"(?:warmer|cooler|hotter|colder|higher|lower|greater|less|more|"
    r"thicker|thinner|longer|shorter|wider|narrower)\s+than\b",
    re.IGNORECASE)


def is_relative_limit(sentence: str) -> bool:
    """True when the number taken as the limit is a DIFFERENCE from something.

    "at least 28°C warmer than the calculated dew point" states a margin. The
    thing it is a margin from is not on the datasheet and usually is not a
    fixed quantity at all, so comparing the 28 against any submitted number is
    arithmetic with no meaning - and it produced a confident COMPLIANT in the
    model tier's evaluation.

    "shall be at least 300 mm" is untouched: nothing follows the number, so
    the number is the limit.

    NOT IMPLEMENTED, AND NAMED SO NOBODY ASSUMES IT IS: the "within 5 % of the
    design value" spelling. `within` is not a comparator `_LIMIT` recognises,
    so such a sentence yields no limit and is already a `statement` before
    this check is reached. An arm for it here could never fire, and this
    project deletes dead branches rather than carrying them (M125).
    """
    text = " ".join((sentence or "").split())
    if not text:
        return False
    match = _LIMIT.search(text)
    if not match:
        return False
    return bool(_RELATIVE_TAIL.match(text[match.start("value"):]))


def _applicability_remainder(sentence: str) -> str | None:
    """The deferral remainder when `sentence` passes every applicability-
    trigger gate, else None. THE ONE PLACE THE THREE GATES ARE CHECKED -
    `is_applicability_trigger` and `cited_document` both build on this, so
    a sentence can never be a trigger for one and not the other.

    THREE THINGS MUST ALL HOLD, and each one is what stops a real requirement
    being reclassified away:

      * the text after the mandatory verb DEFERS - "shall be in accordance
        with", "refer to";
      * it defers to a NAMED DOCUMENT, not to a table. A table deferral is
        `table_row`, which already exists and is checked first;
      * that remainder states NO quantity of its own. "for design temperatures
        above 260°C, wall thickness shall be at least 12 mm" carries a real
        limit after the verb and stays `numeric_limit`, however conditional
        its opening is.

    The document designations are removed before looking for the remaining
    number, because `PIP VEFV1100`, `API 650` and `ISO 15156` all contain
    digits and none of them is a quantity.
    """
    text = " ".join((sentence or "").split())
    if not text:
        return None
    verb = _MANDATORY_HERE.search(text)
    if not verb:
        return None
    remainder = text[verb.end():]
    if not _DEFERRAL.search(remainder):
        return None
    if _TABLE_REFERENCE.search(remainder):
        # A table is not another document. `table_row` is that case and is
        # decided before this one.
        return None
    if not _DOCUMENT_REF.search(remainder):
        return None
    without_documents = _DOCUMENT_REF.sub(" ", remainder)
    if _BARE_NUMBER.search(without_documents):
        return None
    return remainder


def is_applicability_trigger(sentence: str) -> bool:
    """True when the obligation is "another document governs", under a
    condition that carries the number. See `_applicability_remainder` for
    the three gates."""
    return _applicability_remainder(sentence) is not None


def cited_document(sentence: str) -> str | None:
    """The document `sentence` defers to, as printed - or None when the
    sentence is not an applicability trigger at all, or defers only to an
    internal cross-reference ("clause 5.2") rather than a real document.

    `_applicability_remainder` already establishes THAT a real document is
    named (the `_DOCUMENT_REF` gate); this reads WHICH one, searching the
    same remainder with `_DOCUMENT_DESIGNATION` alone so an internal
    cross-reference can never be returned as if it were a cited standard -
    "refer to clause 5.2" is not a document this system can look up in the
    library.
    """
    remainder = _applicability_remainder(sentence)
    if remainder is None:
        return None
    match = _DOCUMENT_DESIGNATION.search(remainder)
    return match.group(0).strip() if match else None


#: Mandatory wording, duplicated from `standards` deliberately: importing it
#: would make this module depend on the one that depends on it.
_MANDATORY_HERE = re.compile(
    r"\b(shall|must\s+not|must|is\s+required\s+to|are\s+required\s+to"
    r"|is\s+to\s+be|are\s+to\s+be|may\s+not\s+exceed\s+[-+]?\d)",
    re.IGNORECASE)

#: A comparator phrase the sentence states for ITSELF.
_COMPARATOR_PRESENT = re.compile(
    r"\b(?:not\s+exceed|no\s+greater\s+than|no\s+more\s+than|less\s+than|"
    r"greater\s+than|at\s+least|at\s+most|minimum\s+of|maximum\s+of|"
    r"or\s+less|or\s+more|not\s+less\s+than|not\s+more\s+than)\b",
    re.IGNORECASE)


#: WHERE ONE SENTENCE ENDS AND THE NEXT BEGINS, for the comparator-less half
#: of `subject_phrase`. The PDF extractor routinely flattens a heading and the
#: clause under it into one string - "Commentary Note: Cables and pipes shall
#: be sleeved", "Cathodic Protection (CP) Requirements 9.3.1 The extent of
#: external coating application on onshore well casings shall ..." - and the
#: text before the mandatory verb then carries the heading as well as the
#: subject.
#:
#: A DIGIT BEFORE THE STOP BLOCKS THE CUT. "10.1 The selection ..." and
#: "SAES-T-911." put a full stop between two digits or at the end of a
#: designation, and cutting there would slice a clause number or a document
#: name in half. Only a stop that follows a non-digit and precedes whitespace
#: is a sentence boundary; a bullet is one wherever it sits.
_SENTENCE_BOUNDARY = re.compile(r"(?<!\d)[.;:](?=\s)|•")

#: A head has to contain a WORD to be a subject. "14.3", "•", "(2)" and the
#: bare clause numbers the extractor leaves in front of a verb are not things
#: a requirement can be about. Three letters rather than one, so an orphaned
#: "a"/"of" left by a bad cut is not mistaken for a noun.
_SUBJECT_WORD = re.compile(r"[A-Za-z]{3,}")


def subject_phrase(sentence: str) -> str | None:
    """What the sentence is ABOUT: the text before the comparator, or - when
    there is no comparator - the text before the mandatory verb.

    Exposed so `standards.subject_of` does not have to reach for `_LIMIT`
    itself - the limit pattern is this module's, and a second module splitting
    on it would be a second place to fix when it changes.

    THE COMPARATOR USED TO BE A PRECONDITION, AND THAT COST FOUR FIELDS, NOT
    ONE. This opened `if not _LIMIT.search(sentence): return None`, so "The
    allowable concrete bearing stress to be used for the design of base plates
    shall be 8,300 kPa" - a mandatory sentence stating a flat value with no
    comparator word - lost its operator, its value, its unit AND its subject.
    The first three are honest: this module records no limit it cannot read.
    The subject was collateral damage of the IMPLEMENTATION - the head was
    produced by splitting on `_LIMIT`, so no comparator meant nothing to split
    on - and nothing about the sentence justifies it. What the clause is about
    is stated whether or not a comparator follows.

    IT IS NOT A COSMETIC FIELD. `comparison.match_by_containment` joins a
    requirement to a datasheet value THROUGH this subject, so a row with
    subject NULL can never match anything however perfectly the rest of it is
    stored. Measured: promoting 313 such rows to comparable produced ZERO new
    matches on a real vessel datasheet, because every one of them had a null
    subject to join on.

    THE COMPARATOR PATH IS UNTOUCHED, BYTE FOR BYTE. Every sentence `_LIMIT`
    matches takes exactly the branch it always took; the new branch can only
    be reached where the old function had already decided to return None.
    Verified over the 34,938 stored requirement texts: 1,742 produce a subject
    today and all 1,742 produce the identical string after this change.

    NO LENGTH CAP, measured rather than assumed. The heads this new branch
    produces are SHORTER than the ones the comparator branch already yields -
    69 characters at the 90th percentile against 131 - and long subjects are
    something `subject_of` has always allowed ("it is allowed to be long, and
    it is allowed to be imperfect"). Capping the new branch alone would be a
    rule the older and longer half of the corpus does not follow.
    """
    if not sentence:
        return None
    if _LIMIT.search(sentence):
        head = _LIMIT.split(sentence)[0]
        return " ".join(head.split()).strip() or None
    # NO COMPARATOR: the subject is what stands before the obligation. The
    # FIRST mandatory verb, not the last - "The drain sample shall be taken
    # into an open container (such as a glass jar, which shall be internally
    # coated ...)" is about the drain sample, and the second "shall" belongs
    # to a subordinate clause that has already described the container.
    verb = _MANDATORY_HERE.search(sentence)
    if not verb:
        return None
    head = sentence[:verb.start()]
    boundaries = list(_SENTENCE_BOUNDARY.finditer(head))
    if boundaries:
        head = head[boundaries[-1].end():]
    head = " ".join(head.split()).strip()
    # NOTHING BEFORE THE VERB IS NOT A SUBJECT, and this is what keeps the
    # unusable sentences out. "shall be in accordance with SAEP-35" and
    # "shall be specified on the data sheet" - a cross-reference and a process
    # instruction, both of which the extractor emits as bare fragments - have
    # no noun phrase in front of the verb at all, so they stay None rather
    # than acquiring an invented one.
    if not _SUBJECT_WORD.search(head):
        return None
    return head or None


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
    # PDF extraction commonly separates an acoustic weighting suffix from its
    # unit: `dB (A)`. It is still the single recognised unit `dB(A)`, not a dB
    # value followed by unrelated prose. Collapse only this terminal,
    # single-letter parenthesised qualifier; arbitrary internal whitespace is
    # not normalised.
    cleaned = re.sub(r"\s+(?=\([A-Za-z]\)$)", "", cleaned)
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
    phrase = _canonical_comparator(match.group("cmp"))
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


#: Operators that point the OPPOSITE way to each other. `=` and None are
#: absent deliberately: neither contradicts anything, and a check that fires on
#: "cannot tell" is a check people learn to ignore.
_OPPOSITE: dict[str, frozenset[str]] = {
    "<=": frozenset({">=", ">"}), "<": frozenset({">=", ">"}),
    ">=": frozenset({"<=", "<"}), ">": frozenset({"<=", "<"}),
}


def contradicts_source(limit: dict | None, sentence: str) -> bool:
    """True when a parsed limit points the OPPOSITE way to its own sentence.

    THE TRIPWIRE FOR THE WORST FAILURE THIS PARSER HAS. On 2026-09-20, 129 of
    1,731 stored limits across 79 standards carried an operator reversed from
    the sentence they cite - "shall not be less than 45 m" stored as `< 45`.
    Every other field of those rows was right: clause, page, value, unit and
    the quoted sentence. A reviewer checking the citation would have found the
    citation correct and moved on. They were found by a person reading fifteen
    rows at random, which is 0.04% of the corpus.

    So the check that found them runs on every extraction from now on, and a
    row that fails it does not reach a reviewer as a requirement.

    IT ASKS THE SENTENCE, NOT THE ROW'S OTHER FIELDS. The comparator taken is
    the one standing immediately before this limit's own value, which is why
    it is not fooled by a sentence stating two limits - "not less than 63 L/s
    but not more than 252 L/s" holds both directions, and a check scanning the
    whole sentence flags the correct row. Measured: scanning the whole
    sentence reported 129 rows of which 25 were false alarms; this reported 0
    false alarms on the same corpus after the fix.

    SILENT WHEN IT CANNOT TELL. No phrase before the value, or a phrase this
    system has no operator for, returns False rather than True. A tripwire
    that fires on uncertainty is one that gets switched off.

    EVERY OCCURRENCE OF THE VALUE MUST DISAGREE, and every one must be
    readable. A flattened table states one number in both directions -
    "Less than or equal to 5 ... Greater than 5 and equal to or less than 10
    ... Greater than 10" arrives as a single sentence out of a PDF, and so
    does "up to 50 C, ... for fluid temperature more than 50 C". Reading only
    the first occurrence reported all four such rows in this corpus, and all
    four were correct: the row came from a later occurrence.

    An occurrence this system has no comparator for is a READING IT CANNOT
    RULE OUT, so it silences the check rather than being skipped. That is not
    hypothetical: "up to" is in this module's `_OPERATOR` and is NOT in
    `claims._COMPARATOR_WORDS`, so "up to 50 C" reads as no comparator at all
    and the correct half of that sentence is invisible here. Until those two
    vocabularies are made one, silence is the honest answer.

    The 129 flipped rows are still caught: each stated its value once, with a
    comparator, pointing the other way.
    """
    if not limit:
        return False
    operator, raw_value = limit.get("operator"), limit.get("raw_value")
    if not operator or raw_value is None or operator not in _OPPOSITE:
        return False
    disagreed = False
    for match in re.finditer(re.escape(str(raw_value)), sentence):
        implied = claims.comparator_ending(sentence[:match.start()])
        if implied is None or implied not in _OPPOSITE[operator]:
            return False          # a reading that does not contradict the row
        disagreed = True
    return disagreed


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
    # THE NUMBER IS THE THRESHOLD, NOT THE LIMIT. Checked before
    # `numeric_limit` for the same reason `table_row` is: the sentence DOES
    # parse as a limit, and that is the defect. See `APPLICABILITY_TRIGGER`.
    if is_applicability_trigger(sentence):
        return APPLICABILITY_TRIGGER
    # THE NUMBER IS A MARGIN, NOT A VALUE. Same reasoning again.
    if is_relative_limit(sentence):
        return RELATIVE_LIMIT
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


#: THE ONE `required_evidence_type` VALUE THAT NAMES WHAT THIS ENGINE ACTUALLY
#: READS. Issue #163: a requirement whose own sentence demands a DIFFERENT
#: document ("submit a calibration certificate") is not answerable from a
#: datasheet no matter how well a field name happens to match its subject -
#: comparison.compare() reads this constant, not the literal, so the
#: vocabulary stays defined in one place.
DATA_SHEET_EVIDENCE = "data_sheet"

#: A verb that puts an obligation on producing a DOCUMENT, not on a physical
#: property of the equipment. "shall submit a calibration certificate" names
#: evidence to hand over; "shall not exceed 90 dB(A)" does not, and must not
#: be read as if it did.
_EVIDENCE_VERB = re.compile(
    r"\b(?:submit|submitted|provide|provided|furnish|furnished|present|"
    r"presented|make\s+available|made\s+available|accompanied\s+(?:by|with)|"
    r"traceable\s+to)\b", re.IGNORECASE)

#: A fixed, narrow vocabulary of document kinds, longest/most specific first
#: so "data sheet" is not shadowed by a later, broader match. Anything not on
#: this list stays None rather than being guessed from context - the same
#: discipline `header_unit` already applies to units.
_EVIDENCE_NOUNS: tuple[tuple[str, str], ...] = (
    ("calibration certificate", "certificate"),
    ("test certificate", "certificate"),
    ("mill test certificate", "certificate"),
    ("certificate", "certificate"),
    ("certification", "certificate"),
    ("data sheet", DATA_SHEET_EVIDENCE),
    ("datasheet", DATA_SHEET_EVIDENCE),
    ("vendor drawing", "drawing"),
    ("shop drawing", "drawing"),
    ("as-built drawing", "drawing"),
    ("drawing", "drawing"),
    ("calculation", "calculation"),
    ("test report", "report"),
    ("inspection report", "report"),
    ("report", "report"),
    ("procedure", "procedure"),
    ("test record", "record"),
    ("record", "record"),
    ("plan", "plan"),
)


def required_evidence_type(sentence: str) -> str | None:
    """The kind of document a requirement says must be handed over, or None.

    Genuinely new (Part 3's contract review): `standard_requirements` has no
    column for what evidence a clause expects, and `category`/
    `requirement_type` are not close substitutes - `category` is only ever
    'prohibition' or None, and `requirement_type` describes the SHAPE of the
    clause (numeric_limit, table_value, ...), not what document satisfies it.

    POPULATED ONLY WHEN THE SENTENCE ITSELF SAYS SO: it must carry a
    submission verb (submit/provide/furnish/present/make available, or the
    two other real corpus phrasings "accompanied by/with" and "traceable
    to") AND name one of a fixed vocabulary of document nouns. "The wall thickness shall
    not be less than 12 mm" has neither and stays None - there is nothing to
    submit for it. This is deliberately conservative: a requirement that
    implies evidence without naming its kind ("shall be verified") is left
    None rather than guessed, matching this project's rule that a guess is
    never shown as a fact.
    """
    if not sentence or not _EVIDENCE_VERB.search(sentence):
        return None
    lowered = sentence.lower()
    for noun, canonical in _EVIDENCE_NOUNS:
        if noun in lowered:
            return canonical
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
