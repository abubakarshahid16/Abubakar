"""Mechanical claim extraction and comparison. No model, no database, no network.

Spec: docs/design-analysis-and-synthesis.md, "The claim algorithm" and
"Unmeasured becoming zero". The rules that matter most, restated:

  * A claim's subject is the EXACT SENTENCE, verbatim. Never a paraphrase.
  * Unit normalisation is a table lookup. An unknown unit gives
    normalized_value None - never a guess, never 0. `normalise_strict` raises
    UnknownUnit instead, the scores.ScaleMismatch discipline.
  * Clustering is by facet key: the question's distinctive terms present in
    the claim, plus the unit dimension. Never by wording similarity. A facet
    names a SUBJECT, so keys that are one subject at two levels of detail are
    merged afterwards (`_can_merge`), and a unit, a percent sign or a clause
    number never names one.
  * Labels are arithmetic. `possible_conflict`, never `conflict`: documents
    carry no revision or approval status, so supersession is undecidable.
  * Different designators (system 1 vs system 9) are two different things,
    not a conflict. That is `unresolved`, and the note says why.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

from . import keyword, lexical

NORMALIZER_VERSION = "1"

ClaimLabel = Literal["agreement", "addition", "possible_conflict", "unresolved"]

#: The one sentence a possible_conflict note must carry. Mandated by the design.
POSSIBLE_CONFLICT_NOTE = (
    "Values disagree. Whether one supersedes the other cannot be determined: "
    "documents carry no revision or approval status."
)


class UnknownUnit(ValueError):
    """A unit not in the normalisation table. Raised, never coerced."""


# ------------------------------------------------------------------ unit table
#: unit spelling (lowercased, µ/μ folded to "u", ° stripped) -> (dimension, canonical unit, factor)
#: One dimension family per entry. Fahrenheit is deliberately ABSENT: a wrong
#: temperature conversion is a safety defect, so F must raise / give None.
_UNIT_TABLE: dict[str, tuple[str, str, float]] = {
    # length -> um
    "um": ("length", "um", 1.0),
    "micron": ("length", "um", 1.0),
    "microns": ("length", "um", 1.0),
    "micrometre": ("length", "um", 1.0),
    "micrometres": ("length", "um", 1.0),
    "micrometer": ("length", "um", 1.0),
    "micrometers": ("length", "um", 1.0),
    "mm": ("length", "um", 1000.0),
    # Added after measuring the standards corpus: `m` and `inch` were already
    # RECOGNISED as length but had no conversion, so "buried with a minimum of
    # 1 m" parsed and then stored a null value - the number was read, believed,
    # and thrown away. Both factors are exact by definition, which is the only
    # reason they may be added here rather than left unconverted: 1 m is
    # 1,000,000 um and 1 inch is 25,400 um, neither is a rounding.
    "m": ("length", "um", 1_000_000.0),
    "metre": ("length", "um", 1_000_000.0),
    "metres": ("length", "um", 1_000_000.0),
    "meter": ("length", "um", 1_000_000.0),
    "meters": ("length", "um", 1_000_000.0),
    "inch": ("length", "um", 25_400.0),
    "inches": ("length", "um", 25_400.0),
    "in": ("length", "um", 25_400.0),
    # EACH ITS OWN DIMENSION, WITH A FACTOR OF 1. Measured as missing from the
    # standards corpus, and every one of them is the ONLY spelling of its
    # quantity that appears there - there is no second unit to convert between,
    # so the "conversion" is the identity and the dimension has one member.
    #
    # That is not a trick to fill the column. A dimension with one member still
    # does the job a dimension exists for: two values in g/L compare, and a
    # value in g/L and a value in mm do NOT, because `_compatible` refuses
    # across dimensions. Leaving them unconverted instead would have stored the
    # number and then refused to compare it with itself.
    "g/l": ("concentration", "g/L", 1.0),
    "g/m2": ("areal_density", "g/m2", 1.0),
    "kj/mm": ("heat_input", "KJ/mm", 1.0),
    "bhn": ("hardness", "BHN", 1.0),
    "kph": ("speed", "kph", 1.0),
    # "degC/hr" and "C/hr" both fold to this; `_fold_unit` drops the degree
    # sign. A RATE, not a temperature - 5 C/hr is a heating rate and must never
    # compare against a 5 C limit, which is why it is its own dimension.
    "c/hr": ("temperature_rate", "C/hr", 1.0),
    # pressure -> MPa
    "mpa": ("pressure", "MPa", 1.0),
    "bar": ("pressure", "MPa", 0.1),
    "kpa": ("pressure", "MPa", 0.001),
    "psi": ("pressure", "MPa", 0.00689476),
    # temperature -> C (Celsius only)
    "c": ("temperature", "C", 1.0),
    "degc": ("temperature", "C", 1.0),
    # percent
    "%": ("percent", "%", 1.0),
    # time -> h
    "h": ("time", "h", 1.0),
    "hr": ("time", "h", 1.0),
    "hrs": ("time", "h", 1.0),
    "hour": ("time", "h", 1.0),
    "hours": ("time", "h", 1.0),
    "min": ("time", "h", 1.0 / 60.0),
    "mins": ("time", "h", 1.0 / 60.0),
    "minute": ("time", "h", 1.0 / 60.0),
    "minutes": ("time", "h", 1.0 / 60.0),
    # voltage -> V
    "v": ("voltage", "V", 1.0),
    "kv": ("voltage", "V", 1000.0),
    # current -> A
    "a": ("current", "A", 1.0),
    "ma": ("current", "A", 0.001),
}

#: Canonical unit per dimension, for the human-readable facet string.
#: Indexed directly by `facet_label`, so a dimension added to `_UNIT_TABLE`
#: without an entry here is a KeyError at render time rather than a wrong
#: label. Kept adjacent for that reason.
_DIMENSION_UNIT = {
    "length": "um", "pressure": "MPa", "temperature": "C", "percent": "%",
    "time": "h", "voltage": "V", "current": "A",
    "concentration": "g/L", "areal_density": "g/m2", "heat_input": "KJ/mm",
    "hardness": "BHN", "speed": "kph", "temperature_rate": "C/hr",
}

#: Units extraction recognises but the table does NOT convert, with the
#: dimension they belong to when it is certain. Extracted with
#: normalized_value None and a dimension, so "350 °F" lands in the temperature
#: facet and is labelled unresolved there rather than silently converted. An
#: arbitrary word after a number ("no. 9 has") is NOT a measurement.
_UNCONVERTED_UNITS: dict[str, str | None] = {
    "f": "temperature", "degf": "temperature", "k": "temperature",
    "mil": "length", "mils": "length", "cm": "length", "km": "length",
    "ft": "length", "nm": "length",
    # Measured in the standards corpus and added so the extractor STOPS
    # treating them as non-units - the gate in `requirements_3b.parse_limit`
    # now refuses any token that is not recognised here, and without these
    # entries a real "5 g/L" limit would be discarded along with "3 locations".
    #
    # RECOGNISED, NOT CONVERTED, and deliberately so. There is no second
    # spelling of any of them in this corpus to convert BETWEEN, and inventing
    # a conversion for an energy-per-length or a hardness number to satisfy a
    # column would be the wrong kind of completeness. They carry a dimension
    # where the dimension is certain and None where it is not.
    # A TENTH ENTRY, BEYOND THE NINE THAT WERE MEASURED AS MISSING, and it is
    # here to prevent a regression rather than to add coverage. `db` was
    # already recognised and `db(a)` was not, so the new unit gate - which
    # discards any token `claims` does not know - would have thrown away the
    # A-weighting on every noise limit in the corpus: 16 chunks across 8
    # documents, and the worked example the master plan is written around.
    # `datasheets.py` was fixed in phase 5B precisely so that "95 dB(A)" keeps
    # its A-weighting, and a gate that dropped it on the STANDARDS side would
    # have re-opened that defect from the other direction.
    "db(a)": None, "dba": None,
    "psig": "pressure", "barg": "pressure", "mbar": "pressure",
    "s": "time", "sec": "time", "secs": "time", "second": "time", "seconds": "time",
    "d": "time", "day": "time", "days": "time",
    "mv": "voltage", "ka": "current",
    "ppm": None, "ppb": None, "mg": None, "g": None, "kg": None, "t": None, "n": None,
    "kn": None, "knm": None, "lb": None, "lbs": None, "rpm": None, "hz": None, "khz": None,
    "w": None, "kw": None, "mw": None, "ml": None, "l": None, "gpm": None, "mpy": None,
    "ohm": None, "kohm": None, "db": None, "wt": None, "vol": None,
}
_RECOGNISED_UNITS = set(_UNIT_TABLE) | set(_UNCONVERTED_UNITS)


def _fold_unit(unit_str: str) -> str:
    u = unit_str.strip().replace("µ", "u").replace("μ", "u").replace("°", "")
    u = u.replace("deg ", "deg").replace("degrees", "deg").replace("degree", "deg")
    return u.lower()


def is_unit(unit_str: str) -> bool:
    """Is this spelling a unit at all?

    Separate from `unit_dimension`, which answers None BOTH for "not a unit"
    and for "a unit whose dimension is not certain" - `ppm` and `locations`
    are indistinguishable through it. A caller deciding whether a word after a
    number is a unit needs those to be different answers, and this is that
    question asked directly.
    """
    return _fold_unit(unit_str) in _RECOGNISED_UNITS


def unit_dimension(unit_str: str) -> str | None:
    """The dimension family of a unit spelling, or None when unknown. A unit
    may have a dimension and still no conversion (°F): dimension says what
    facet it belongs to, the table says whether a value can be compared."""
    folded = _fold_unit(unit_str)
    entry = _UNIT_TABLE.get(folded)
    if entry:
        return entry[0]
    return _UNCONVERTED_UNITS.get(folded)


# ------------------------------------------------------------------ comparators
_COMPARATOR_WORDS: tuple[tuple[str, str], ...] = (
    (r"not\s+less\s+than", ">="),
    (r"not\s+more\s+than", "<="),
    (r"not\s+greater\s+than", "<="),
    (r"not\s+exceed(?:ing)?", "<="),
    (r"at\s+least", ">="),
    (r"at\s+most", "<="),
    (r"greater\s+than\s+or\s+equal\s+to", ">="),
    (r"less\s+than\s+or\s+equal\s+to", "<="),
    (r"greater\s+than", ">"),
    (r"more\s+than", ">"),
    (r"less\s+than", "<"),
    (r"minimum(?:\s+of)?", "min"),
    (r"maximum(?:\s+of)?", "max"),
    (r"min\.?", "min"),
    (r"max\.?", "max"),
    (r"≥", ">="),
    (r"⩾", ">="),
    (r">=", ">="),
    (r"=>", ">="),
    (r"≤", "<="),
    (r"⩽", "<="),
    (r"<=", "<="),
    (r"=<", "<="),
    (r">", ">"),
    (r"<", "<"),
    (r"=", "="),
)
_COMPARATOR_RE = "|".join(f"(?:{p})" for p, _ in _COMPARATOR_WORDS)

_NUMBER = r"\d+(?:[.,]\d+)?"
#: A number followed by a unit token. Numbers glued to identifiers ("5.3.2",
#: "8501-1", "P-101A") are filtered out afterwards by span overlap.
_MEASUREMENT = re.compile(
    r"(?<![\w.,/-])(?P<value>" + _NUMBER + r")(?![\d.,]*[.,]\d)\s?(?P<unit>[A-Za-zµμ°%][A-Za-z°]*)"
)


def parse_comparator(text: str) -> str | None:
    """">=" for ≥ / "at least" / "not less than"; "min"/"max" for the words; None otherwise."""
    t = text.strip()
    if not t:
        return None
    for pattern, symbol in _COMPARATOR_WORDS:
        if re.fullmatch(pattern, t, re.IGNORECASE):
            return symbol
    return None


def parse_value(value_str: str) -> float | None:
    """Parse a written number. Comma decimals ("9,0") are decimals - NORSOK
    writes them so. A comma followed by exactly three digits ("1,200") is a
    thousands separator. Anything unparseable is None, never a guess."""
    s = value_str.strip()
    m = re.fullmatch(r"(?P<cmp>[^\d]*?)\s*(?P<num>[-+]?\d[\d.,\s]*)", s)
    if not m:
        return None
    num = m.group("num").replace(" ", "")
    if re.fullmatch(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", num):
        num = num.replace(",", "")
    elif re.fullmatch(r"[-+]?\d+,\d+", num):
        num = num.replace(",", ".")
    try:
        return float(num)
    except ValueError:
        return None


# ------------------------------------------------------------------ dataclasses
@dataclass(frozen=True)
class Measurement:
    raw_value: str
    raw_unit: str
    normalized_value: float | None
    normalized_unit: str | None
    comparator: str | None

    @property
    def dimension(self) -> str | None:
        return unit_dimension(self.raw_unit)


@dataclass(frozen=True)
class Claim:
    evidence_id: str
    filename: str
    page_start: int
    section: str | None
    exact_span: str
    identifiers: tuple[str, ...]
    designators: tuple[str, ...]
    measurements: tuple[Measurement, ...]
    terms: frozenset[str]


@dataclass(frozen=True)
class Cluster:
    facet: str
    label: ClaimLabel
    rows: tuple[Claim, ...]
    note: str | None
    key: frozenset[str] = frozenset()


# ------------------------------------------------------------------ normalise
def _split_comparator(value_str: str) -> tuple[str | None, str]:
    """"≥ 250" -> (">=", "250"); "not less than 250" -> (">=", "250")."""
    s = value_str.strip()
    m = re.match(r"^(?P<cmp>" + _COMPARATOR_RE + r")\s*(?P<rest>.*)$", s, re.IGNORECASE)
    if m and m.group("rest"):
        return parse_comparator(m.group("cmp")), m.group("rest").strip()
    return None, s


def normalise(value_str: str, unit_str: str, comparator: str | None = None) -> Measurement:
    """Table lookup. Unknown unit or unparseable value -> normalized_value None.
    The raw fields are always preserved exactly as written."""
    cmp_from_value, number_part = _split_comparator(value_str)
    comparator = comparator or cmp_from_value
    value = parse_value(number_part)
    entry = _UNIT_TABLE.get(_fold_unit(unit_str))
    if entry is None or value is None:
        return Measurement(value_str, unit_str, None, None, comparator)
    _dimension, canonical, factor = entry
    return Measurement(value_str, unit_str, value * factor, canonical, comparator)


def normalise_strict(value_str: str, unit_str: str, comparator: str | None = None) -> Measurement:
    """As normalise, but an unknown unit RAISES UnknownUnit. This is the
    scores.ScaleMismatch discipline: a mismatch is an error, not a coercion."""
    if _fold_unit(unit_str) not in _UNIT_TABLE:
        raise UnknownUnit(
            f"unit {unit_str!r} is not in the normalisation table; refusing to guess a conversion"
        )
    m = normalise(value_str, unit_str, comparator)
    if m.normalized_value is None:
        raise UnknownUnit(f"value {value_str!r} could not be parsed as a number")
    return m


# ------------------------------------------------------------------ extraction
_ABBREVIATIONS = ("no", "nr", "min", "max", "approx", "fig", "rev", "e.g", "i.e", "cf", "ref", "para", "vs")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?;])\s+(?=[A-Z0-9\"“(\[])")


def split_sentences(text: str) -> list[str]:
    """Sentences, each stripped of surrounding whitespace only. Abbreviations
    such as "no." and "min." do not end a sentence."""
    if not text:
        return []
    pieces = _SENTENCE_BOUNDARY.split(text)
    out: list[str] = []
    for piece in pieces:
        if out:
            prev = out[-1]
            # `.rsplit()[-1]` on a piece that is nothing BUT dots raises:
            # "..." survives `prev.strip()`, becomes "" after `rstrip(".")`,
            # and rsplit then returns an empty list. Real corpus text contains
            # runs of dots - a table of contents leader, a dotted rule - so
            # this crashed extraction on documents that are otherwise fine.
            words = prev.rstrip().rstrip(".").rsplit(None, 1)
            tail = words[-1].lower() if words else ""
            if prev.rstrip().endswith(".") and tail in _ABBREVIATIONS:
                # rejoin with the original single whitespace run collapsed to one space
                out[-1] = prev + " " + piece
                continue
        out.append(piece)
    return [s.strip() for s in out if s.strip()]


def _identifier_spans(text: str) -> list[tuple[int, int]]:
    return [m.span() for m in keyword.IDENTIFIER.finditer(text)]


_DECIMAL = re.compile(r"\d+\.\d+")
#: keyword.IDENTIFIER's "API 610" alternative also matches "MDFT 280": letters,
#: a space, digits. When those digits carry a recognised unit ("MDFT 280 um")
#: the number is a measurement and the letters are the subject, not a code.
_WORD_SPACE_NUMBER = re.compile(r"[A-Z]{2,}\s\d+(?:[.,]\d+)?")


#: Words that introduce a NAME rather than a quantity. "system no. 5" is
#: coating system five, not five of anything, and the word in front of the
#: number is what says so. Anchored to the end so only the immediately
#: preceding word counts - "the NDFT for system 1 shall be 280 um" still
#: yields 280 um.
#: A percentage that NAMES A SUBMITTAL PHASE rather than measuring anything.
#: "submitted as 100% Design Documents" is the name of a deliverable stage, and
#: it was being extracted as the quantity 100 - which then formed a facet of its
#: own, so one run produced "documents (%)" beside "documents" and split one
#: subject across two rows on the strength of a number nobody wrote.
#:
#: THE RULE IS THE FOLLOWING NOUN, not the value. It fires only when the phrase
#: after the percent names a phase - Design/Construction/Contract/Schematic
#: Documents, a Submittal, Design Development - so a percentage followed by
#: anything else is untouched. "at least 30% below ASHRAE 90.1", "maximum 50 %
#: reduction", "95% of the surface" and "shall not exceed 85%" all still
#: extract, and are asserted to.
#:
#: A false negative here loses a real requirement, which is why the permitted
#: nouns are listed rather than inferred: an open-ended "percent followed by a
#: capitalised word" would have swallowed "30% ASHRAE".
_PHASE_PERCENT = re.compile(
    r"\s*(?:"
    r"(?:design|construction|contract|schematic|conceptual)\s+"
    r"(?:documents?|submittals?|development|drawings?)"
    r"|submittals?"
    r"|design\s+development"
    r")\b",
    re.IGNORECASE,
)


_DESIGNATOR_LEAD = re.compile(
    r"(?:\bno\.?|\bsystem|\bclass|\btype|\bgrade|\brev\.?|\btable)\s*$",
    re.IGNORECASE,
)


def _is_measurement_not_code(sentence: str, inside: list[tuple[int, int]], start: int, end: int, value: str) -> bool:
    if len(inside) != 1:
        return False
    a, b = inside[0]
    if (a, b) == (start, end) and _DECIMAL.fullmatch(value):
        return True  # "9.0" matched as a clause number, but it has a unit
    return b == end and _WORD_SPACE_NUMBER.fullmatch(sentence[a:b]) is not None


def _identifiers_for(sentence: str, measurements: tuple[Measurement, ...]) -> tuple[str, ...]:
    """IDENTIFIER matches minus those that turned out to be measurements."""
    measured = {m.raw_value for m in measurements}
    out = []
    for ident in dict.fromkeys(keyword.IDENTIFIER.findall(sentence)):
        if _DECIMAL.fullmatch(ident) and ident in measured:
            continue
        if _WORD_SPACE_NUMBER.fullmatch(ident) and ident.split()[-1] in measured:
            continue
        out.append(ident)
    return tuple(out)


def extract_measurements(sentence: str) -> tuple[Measurement, ...]:
    """Numbers with a recognised unit. keyword.IDENTIFIER also matches "9.0"
    (its clause-number alternative), so a plain decimal that is itself an
    identifier match AND is followed by a unit is a measurement, not a clause;
    "5.3.2" or "8501-1" glued to an identifier is never a measurement."""
    spans = _identifier_spans(sentence)
    found: list[Measurement] = []
    for m in _MEASUREMENT.finditer(sentence):
        start, end = m.span("value")
        inside = [(a, b) for a, b in spans if a <= start < b]
        if inside and not _is_measurement_not_code(sentence, inside, start, end, m.group("value")):
            continue
        unit = m.group("unit")
        if _fold_unit(unit) not in _RECOGNISED_UNITS:
            continue
        # A lone lowercase letter after a number ("3 a coat") is a word, not a unit.
        if len(unit) == 1 and unit.isalpha() and not unit.isupper():
            continue
        # A SINGLE letter glued to the digits with no space is a designator
        # suffix, not a unit: "coating system no. 5A and 5B" was read as five
        # AMPERES, and an invented measurement is worse than a missing one -
        # it enters a cluster and gets compared against real values.
        #
        # The rule is about the GLUING, not the letter. "5 A" with a space is
        # still amperes, so an electrical spec keeps its current ratings; and
        # the unit must be one character, so "125um" and "280um" are untouched.
        if not sentence[m.end("value"):m.start("unit")] and len(unit) == 1                 and unit.isalpha():
            continue
        # A number introduced as a designator is a name, not a quantity.
        if _DESIGNATOR_LEAD.search(sentence[:start]):
            continue
        # Nor is a percentage that names a submittal phase - see _PHASE_PERCENT.
        if unit == "%" and _PHASE_PERCENT.match(sentence[m.end("unit"):]):
            continue
        prefix = sentence[:start].rstrip()
        cmp_match = re.search(r"(?:" + _COMPARATOR_RE + r")\s*$", prefix, re.IGNORECASE)
        comparator = parse_comparator(cmp_match.group(0)) if cmp_match else None
        found.append(normalise(m.group("value"), unit, comparator))
    return tuple(found)


def claim_terms(
    sentence: str, *, allowed_document_ids: frozenset[str]
) -> frozenset[str]:
    return frozenset(t.lower() for t in lexical.distinctive_terms(
        sentence, allowed_document_ids=allowed_document_ids))


def question_terms(
    question: str, *, allowed_document_ids: frozenset[str]
) -> frozenset[str]:
    """The question's distinctive terms, lowercased, as a facet_key input.

    Scoped because `distinctive_terms` consults the corpus: it folds in the
    multi-word expansions the documents themselves define, so an unreadable
    document could otherwise decide how a caller's question was split into
    terms - and those terms become `facet_key` inputs the reader sees.
    """
    return frozenset(t.lower() for t in lexical.distinctive_terms(
        question, allowed_document_ids=allowed_document_ids))


def extract_claims(
    evidence: list[dict], *, allowed_document_ids: frozenset[str]
) -> list[Claim]:
    """One Claim per sentence carrying a measurement, identifier or designator.
    Sentences with none are not claims. The sentence is carried verbatim."""
    claims: list[Claim] = []
    for item in evidence:
        text = item.get("exact_span") or item.get("text") or ""
        for sentence in split_sentences(text):
            measurements = extract_measurements(sentence)
            identifiers = _identifiers_for(sentence, measurements)
            dropped = {i.lower() for i in keyword.IDENTIFIER.findall(sentence)} - {i.lower() for i in identifiers}
            designators = tuple(dict.fromkeys(keyword.find_designators(sentence)))
            if not (identifiers or designators or measurements):
                continue
            claims.append(
                Claim(
                    evidence_id=str(item.get("evidence_id", "")),
                    filename=str(item.get("filename", "")),
                    page_start=int(item.get("page_start") or 0),
                    section=item.get("section"),
                    exact_span=sentence,
                    identifiers=identifiers,
                    designators=designators,
                    measurements=measurements,
                    terms=claim_terms(
                        sentence,
                        allowed_document_ids=allowed_document_ids,
                    ) - frozenset(dropped),
                )
            )
    return claims


# ------------------------------------------------------------------ facets
def _dimensions(claim: Claim) -> frozenset[str]:
    return frozenset(m.dimension for m in claim.measurements if m.dimension)


#: A dimension that is an ATTRIBUTE of a claim rather than an identity of a
#: subject. A percentage is dimensionless - "100%" of what is decided by the
#: words around it, never by the symbol - so letting "dim:percent" into a
#: facet key split one subject in two: a live run produced "documents (%)"
#: beside "documents" and "models (%)" beside "models", four facet rows for
#: two subjects. Percentages are still EXTRACTED, still compared and still
#: capable of a possible_conflict; they simply do not name a facet, which is
#: also why no facet key or facet label can contain "%".
_ATTRIBUTE_DIMENSIONS = frozenset({"percent"})


def _is_subject_term(term: str) -> bool:
    """A subject is named by words. A token with no letter in it - "%", "(%)",
    "5", "7.1" - is a unit or a number, an attribute of a claim, never the
    thing the documents are agreeing or disagreeing about."""
    return any(ch.isalpha() for ch in term)


def subject_terms(key: frozenset[str]) -> frozenset[str]:
    """The naming half of a facet key: no "dim:" and no "designator:"."""
    return frozenset(k for k in key if not k.startswith(("dim:", "designator:")))


def _designator_tokens(key: frozenset[str]) -> frozenset[str]:
    return frozenset(k for k in key if k.startswith("designator:"))


def facet_key(claim: Claim, question_terms: frozenset[str]) -> frozenset[str] | None:
    """(question_terms ∩ claim.terms, words only) plus "dim:<dimension>" per
    identifying measurement. None when the intersection is empty and the claim
    has no designator: such a claim cannot be compared with anything and must
    not be clustered by wording. With no shared term but a designator, the
    designator words stand in.

    This key is an identity of CONVENIENCE, not of subject: two claims about
    the same thing at different levels of detail get different keys. `cluster`
    merges those afterwards - see `_can_merge`.
    """
    shared = frozenset(t.lower() for t in question_terms) & claim.terms
    shared = frozenset(t for t in shared if _is_subject_term(t))
    dims = frozenset(
        f"dim:{d}" for d in _dimensions(claim) if d not in _ATTRIBUTE_DIMENSIONS
    )
    if shared:
        return shared | dims
    if claim.designators:
        return frozenset(f"designator:{d}" for d in claim.designators) | dims
    return None


#: How a unit is written for a person rather than for a parser. "um" is what
#: the corpus contains and "µm" is what a coatings engineer reads.
_UNIT_DISPLAY = {"um": "µm", "degC": "°C"}

#: A word of running text, spelled as lexical._TERM spells a term so that a
#: term found in the question can be recognised again in a claim's sentence.
_PHRASE_WORD = re.compile(r"[A-Za-z][A-Za-z0-9./-]*")


def _term_runs(text: str, terms: frozenset[str]) -> list[tuple[str, ...]]:
    """Maximal runs of ADJACENT words of `text` that are all facet terms.

    Adjacency is textual: only whitespace or a hyphen may sit between two
    words of a run, so "structural models" is a run and "structural" ...
    "models" three clauses apart is two runs of one.
    """
    runs: list[tuple[str, ...]] = []
    current: list[str] = []
    prev_end: int | None = None
    for m in _PHRASE_WORD.finditer(text):
        word = m.group(0).lower().rstrip(".")
        gap = text[prev_end:m.start()] if prev_end is not None else ""
        prev_end = m.end()
        if word in terms:
            if current and gap.strip(" \t\r\n") not in ("", "-"):
                runs.append(tuple(current))
                current = []
            current.append(word)
        elif current:
            runs.append(tuple(current))
            current = []
    if current:
        runs.append(tuple(current))
    return runs


def _sub_runs(runs: list[tuple[str, ...]]) -> set[tuple[str, ...]]:
    out: set[tuple[str, ...]] = set()
    for run in runs:
        for i in range(len(run)):
            for j in range(i + 1, len(run) + 1):
                out.add(run[i:j])
    return out


#: A conservative singular/plural fold, applied to BOTH sides of a word
#: comparison so a question that wrote "structural model" can still recognise
#: "STRUCTURAL MODELS" in a claim.
#:
#: MEASURED, and this is the whole reason the phrase naming looked dead. On the
#: live question "compare structural model requirements in doc16.pdf and
#: doc15.pdf" the facet keyed {model, structural} was named "structural"
#: although its claim reads "6.3.1 STRUCTURAL MODELS The Structural systems
#: models may vary ...". `_term_runs` matched only the word "model" - the lone
#: singular, in "within a model", eleven words away from "structural" - because
#: the adjacent pair spells its second word "MODELS", and "models" is not the
#: term the question supplied. The run was there in the text and invisible to
#: the matcher. Nothing about the majority rule was involved.
#:
#: The fold is deliberately small: -ies -> -y, -ses/-xes/-zes/-ches/-shes ->
#: drop -es, otherwise a trailing -s that is not -ss. It never rewrites a word
#: shorter than five characters, so "gas", "bus" and "class" are untouched, and
#: because both the term and the claim's word go through it, a fold that is
#: linguistically wrong ("analysis" -> "analysi") still matches only itself. It
#: is a comparison key, never displayed.
_PLURAL_ES = ("ses", "xes", "zes", "ches", "shes")


def _canon_word(word: str) -> str:
    """The comparison key for one word. Never shown to a reader."""
    w = word.lower()
    if len(w) < 5:
        return w
    if w.endswith("ies"):
        return w[:-3] + "y"
    if w.endswith(_PLURAL_ES):
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _canon_terms(terms: frozenset[str]) -> dict[str, str]:
    """canon -> the term spelling that produced it, for the terms that are one
    word. A multi-word term (an acronym expansion the corpus defines) can never
    equal a single word of running text and is left out, as it always was.

    Ties are broken by the sorted term spelling, so the map does not depend on
    the iteration order of the frozenset.
    """
    out: dict[str, str] = {}
    for term in sorted(terms):
        if " " in term or not _is_subject_term(term):
            continue
        out.setdefault(_canon_word(term), term)
    return out


def _phrase_runs(text: str, canon: dict[str, str]) -> list[tuple[tuple[str, str], ...]]:
    """As `_term_runs`, but each word is carried as (canon, surface) and the
    membership test is on the canon. Adjacency is unchanged: only whitespace or
    a hyphen may sit between two words of a run."""
    runs: list[tuple[tuple[str, str], ...]] = []
    current: list[tuple[str, str]] = []
    prev_end: int | None = None
    for m in _PHRASE_WORD.finditer(text):
        word = m.group(0).lower().rstrip(".")
        gap = text[prev_end:m.start()] if prev_end is not None else ""
        prev_end = m.end()
        key = _canon_word(word)
        if key in canon:
            if current and gap.strip(" \t\r\n") not in ("", "-"):
                runs.append(tuple(current))
                current = []
            current.append((key, word))
        elif current:
            runs.append(tuple(current))
            current = []
    if current:
        runs.append(tuple(current))
    return runs


def _facet_phrase(rows: tuple[Claim, ...] | list[Claim], terms: frozenset[str]) -> str:
    """The noun phrase to PRINT for a facet, taken from the claims' own words.

    THE SUPPORT RULE, stated so it can be disagreed with. Every run of adjacent
    facet terms occurring in a claim is a candidate, counted once per ROW. A
    candidate is eligible when at least two rows contain it - one row, when the
    cluster has only one. Among the eligible candidates the LONGEST wins; ties
    in length go to the one more rows support, then to the longer spelling,
    then alphabetically.

    WHY TWO ROWS RATHER THAN A MAJORITY. A majority is the wrong shape for this
    data and it was measured to be: the facet keyed {model, structural} whose
    four claims include two spelling "STRUCTURAL MODELS" verbatim needs three
    of four under a majority and got named "structural". Two rows is the
    smallest number that still means "the documents share this phrase" rather
    than "one sentence happened to contain it", which matters because a facet
    exists to compare documents - a phrase only one row uses names that row,
    not the comparison.

    WHEN THE CLAIMS GENUINELY DISAGREE about the subject - two rows reading
    "structural models" and three reading "design documents" - length is
    decided first and both are two words, so the tie-break puts the phrase with
    MORE rows behind it first: "design documents". The minority phrase does not
    get to name the cluster. With equal support the alphabetically first
    spelling wins, which is arbitrary but stated, repeatable, and never depends
    on dict or set ordering.

    THE FALLBACK IS A BARE WORD, NEVER AN INVENTION. When nothing reaches the
    support floor this returns the best-supported SINGLE term, and when no term
    appears in any claim at all it returns "" and `_facet_string` falls back to
    the sorted terms as before. A wrong noun phrase reads as a finding; a bare
    word only reads as a word.

    The spelling shown is the one the CLAIMS use, chosen by row count then
    alphabetically - "structural models", not the question's "structural
    model" - because the reader is being shown what the documents say.
    """
    rows = tuple(rows)
    canon = _canon_terms(terms)
    if not rows or not canon:
        return ""
    # support: canon run -> rows containing it; spellings: canon run -> surface -> rows
    support: dict[tuple[str, ...], int] = {}
    spellings: dict[tuple[str, ...], dict[tuple[str, ...], int]] = {}
    for row in rows:
        seen: set[tuple[str, ...]] = set()
        surfaces: dict[tuple[str, ...], set[tuple[str, ...]]] = {}
        for run in _phrase_runs(row.exact_span.lower(), canon):
            for i in range(len(run)):
                for j in range(i + 1, len(run) + 1):
                    piece = run[i:j]
                    key = tuple(w[0] for w in piece)
                    seen.add(key)
                    surfaces.setdefault(key, set()).add(tuple(w[1] for w in piece))
        for key in seen:
            support[key] = support.get(key, 0) + 1
            bucket = spellings.setdefault(key, {})
            for surface in surfaces.get(key, ()):
                bucket[surface] = bucket.get(surface, 0) + 1
    if not support:
        return ""
    floor = 2 if len(rows) >= 2 else 1
    eligible = [run for run, n in support.items() if n >= floor and len(run) > 1]
    if not eligible:
        # No shared phrase. Name it after the best-supported single term - the
        # current behaviour, and honest: the rows share a word, not a phrase.
        eligible = [run for run in support if len(run) == 1]
        if not eligible:
            return ""
    def display(run: tuple[str, ...]) -> str:
        """The spelling to show for one candidate: the one most rows use,
        alphabetically on a tie."""
        return " ".join(sorted(
            spellings[run].items(), key=lambda kv: (-kv[1], " ".join(kv[0]))
        )[0][0])

    # The order is over the DISPLAYED spelling, not the canonical stem. Ranking
    # by the stem let the plural fold decide a tie between two unrelated words:
    # "documents" folds to "document" (8) and "submitted" does not fold (9), so
    # a facet whose rows share both was renamed "submitted" - a length
    # comparison between a stem and a word, which compares nothing.
    chosen = sorted(
        eligible,
        key=lambda r: (-len(r), -support[r], -len(display(r)), display(r)),
    )[0]
    return display(chosen)


def _shared_phrase(rows: tuple[Claim, ...] | list[Claim], terms: frozenset[str]) -> str:
    """The phrase basis for MERGE DECISIONS (`_head_term`, `_can_merge`).

    Not used for facet names any more - `_facet_phrase` does that, with a
    plural-tolerant match and a two-row support floor. This one is kept exactly
    as it was, on purpose: `_can_merge` decides which claims are compared
    together, and relaxing that on the strength of a change to how a facet is
    SPELLED would let a cosmetic fix reshape a gap analysis.

    Sorting the key's terms produced "models structural" and "analysis
    documents" - a bag of query words in alphabetical order, which no reader
    recognises as a subject. So: take every run of adjacent facet terms that
    appears in a claim, and name the facet after the LONGEST run a majority of
    the clustered claims actually contains. A single term always has the
    support of every row, so this never comes back empty when the key names
    anything at all, and it degrades to exactly one word when the rows share
    only one.
    """
    rows = tuple(rows)
    if not rows or not terms:
        return ""
    support: dict[tuple[str, ...], int] = {}
    for row in rows:
        for run in _sub_runs(_term_runs(row.exact_span.lower(), terms)):
            support[run] = support.get(run, 0) + 1
    if not support:
        return ""
    threshold = (len(rows) // 2) + 1
    eligible = [run for run, n in support.items() if n >= threshold] or list(support)
    best = sorted(eligible, key=lambda r: (-len(r), -len(" ".join(r)), " ".join(r)))[0]
    return " ".join(best)


def _head_term(rows: tuple[Claim, ...] | list[Claim], terms: frozenset[str]) -> str | None:
    """The head noun of a facet: the last word of the phrase its claims use.

    "drawing documents" is headed by "documents", so a facet keyed
    {documents, drawing} is a KIND of the facet keyed {documents}. That is
    what makes the two mergeable; {drawing} and {documents} are not, because
    neither is the other's head.
    """
    phrase = _shared_phrase(rows, terms)
    if phrase:
        return phrase.split()[-1]
    # No adjacency anywhere: fall back to the term each claim mentions LAST,
    # by majority. English puts the head of a noun phrase at its end.
    votes: dict[str, int] = {}
    for row in rows:
        low = row.exact_span.lower()
        last, pos = None, -1
        for term in terms:
            i = low.rfind(term)
            if i > pos:
                last, pos = term, i
        if last:
            votes[last] = votes.get(last, 0) + 1
    if not votes:
        return None
    return sorted(votes.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def _facet_string(key: frozenset[str], rows: tuple[Claim, ...] | list[Claim] = ()) -> str:
    """One dimension, named so a reader recognises it: "coating thickness (µm)".

    This used to join every term, designator and unit in the key with " · ",
    producing "coating · thickness · A · um" and "coating · % · A · MPa" - a
    facet that names four things names none of them, and a reader scanning a
    gap analysis cannot tell what is being compared. Sorting the terms instead
    was no better: it produced "models structural".

    The subject is the phrase the CLAIMS share (`_facet_phrase`); the unit goes
    in brackets where a unit belongs. Both are deterministic - two runs over
    the same corpus produce the same facet string.

    NAMING AND MERGING ARE DELIBERATELY SEPARATE FUNCTIONS. `_facet_phrase`
    names; `_shared_phrase` decides head nouns and equal-phrase merges and is
    left exactly as it was. They differ - `_facet_phrase` folds plurals and
    needs two rows rather than a majority - and that difference is the point: a
    naming change must not silently move a claim from one comparison to
    another. Feeding the looser rule into `_can_merge` was tried and measured
    (it folds {model} into {model, structural} on the live corpus); it changes
    WHICH claims are compared, which is a different decision from what the
    comparison is called, and is not made here.
    """
    terms = subject_terms(key)
    designators = sorted(k.split(":", 1)[1] for k in key if k.startswith("designator:"))
    units = sorted(
        _UNIT_DISPLAY.get(u, u)
        for u in (_DIMENSION_UNIT[k.split(":", 1)[1]] for k in key if k.startswith("dim:"))
    )

    subject = _facet_phrase(rows, terms) or " ".join(sorted(terms)) or ", ".join(designators)
    if terms and designators:
        subject = f"{subject} ({', '.join(designators)})"
    if not subject:
        return "unnamed"
    # More than one dimension in a facet is unusual and worth showing rather
    # than hiding: the reader is being told two different things are being
    # compared under one heading.
    return f"{subject} ({', '.join(units)})" if units else subject


# ------------------------------------------------------------------ labels
_INF = math.inf


def _interval(m: Measurement) -> tuple[float, float, bool, bool] | None:
    """(lo, hi, lo_closed, hi_closed) or None when un-normalised."""
    v = m.normalized_value
    if v is None:
        return None
    c = m.comparator
    if c in (">=", "min"):
        return (v, _INF, True, True)
    if c == ">":
        return (v, _INF, False, True)
    if c in ("<=", "max"):
        return (-_INF, v, True, True)
    if c == "<":
        return (-_INF, v, True, False)
    return (v, v, True, True)


def same_unit(a: Measurement, b: Measurement) -> bool:
    """True when both measurements are written in the SAME unit spelling.

    Folded, so `dB(A)` and `db(a)` are the same unit and `dB(A)` and `dB` are
    not - because they are not: A-weighting is part of what the number means.
    """
    ua, ub = _fold_unit(a.raw_unit or ""), _fold_unit(b.raw_unit or "")
    return bool(ua) and ua == ub


def _same_unit_view(m: Measurement) -> Measurement | None:
    """`m` re-expressed so the interval machinery can read it, or None.

    ONLY for a same-unit comparison. The value is the raw number and the unit
    is its own spelling - nothing is converted, because there is nothing to
    convert to. Returns None when the number itself cannot be parsed, which is
    still undecidable rather than a guess.
    """
    if m.normalized_value is not None:
        return m
    value = parse_value(m.raw_value)
    if value is None:
        return None
    return Measurement(
        raw_value=m.raw_value, raw_unit=m.raw_unit,
        normalized_value=value, normalized_unit=_fold_unit(m.raw_unit or ""),
        comparator=m.comparator,
    )


def _compatible(a: Measurement, b: Measurement) -> bool | None:
    """True when the values (as ranges) overlap, False when not, None if undecidable.

    SAME-UNIT COMPARISON NEEDS NO DIMENSION, and that unblocks the case this
    product is written around. `dB` is mapped to `None` in `_UNCONVERTED_UNITS`
    and that mapping is correct - a decibel is a logarithmic ratio and has no
    dimension to convert through, so `normalise` rightly leaves it
    unnormalised. But "is 95 dB(A) above the 90 dB(A) limit" is not a
    conversion question. It is a comparison of two numbers written on the same
    scale, and refusing it left the master plan's flagship requirement - a
    90 dB(A) limit with a 115 dB(A) relief-valve exception - permanently
    undecidable.

    So when both sides carry the IDENTICAL unit spelling, the raw numbers are
    compared directly and nothing is converted.

    CONVERSION BETWEEN DIFFERENT UNITS IS UNCHANGED and still refuses:
    `normalise_strict` raises `UnknownUnit` for a unit outside the table, and
    two different unconvertible spellings stay undecidable here. That is the
    `scores.ScaleMismatch` discipline and this does not weaken it - a mismatch
    is still an error rather than a coercion. What is relaxed is only the case
    where there is no mismatch to speak of.
    """
    if (a.normalized_value is None or b.normalized_value is None) and same_unit(a, b):
        a, b = _same_unit_view(a), _same_unit_view(b)
        if a is None or b is None:
            return None
    ia, ib = _interval(a), _interval(b)
    if ia is None or ib is None:
        return None
    lo = max(ia[0], ib[0])
    hi = min(ia[1], ib[1])
    if math.isclose(lo, hi, rel_tol=1e-9, abs_tol=1e-9):
        lo_closed = (ia[2] if ia[0] >= ib[0] else True) and (ib[2] if ib[0] >= ia[0] else True)
        hi_closed = (ia[3] if ia[1] <= ib[1] else True) and (ib[3] if ib[1] <= ia[1] else True)
        return lo_closed and hi_closed
    return lo < hi


def _designators_conflict(rows: tuple[Claim, ...]) -> tuple[str, str] | None:
    """Two rows that both name designators with no spelling in common."""
    named = [(r, set(r.designators)) for r in rows if r.designators]
    for i, (ra, da) in enumerate(named):
        for rb, db in named[i + 1:]:
            if da.isdisjoint(db):
                return (", ".join(sorted(da)), ", ".join(sorted(db)))
    return None


def label_cluster(rows: tuple[Claim, ...] | list[Claim]) -> tuple[ClaimLabel, str | None]:
    rows = tuple(rows)
    mismatch = _designators_conflict(rows)
    if mismatch:
        return (
            "unresolved",
            f"Designators differ ({mismatch[0]} vs {mismatch[1]}): these are two different "
            f"things, not a contradiction. Values are not compared.",
        )

    with_measurements = [r for r in rows if r.measurements]
    if len(with_measurements) >= 2:
        # Compare per dimension, only between rows that both speak to it.
        by_dim: dict[str, list[Measurement]] = {}
        unnormalised: list[Measurement] = []
        for r in with_measurements:
            for m in r.measurements:
                if m.normalized_value is None:
                    unnormalised.append(m)
                else:
                    by_dim.setdefault(m.dimension or "", []).append(m)
        conflict = False
        for ms in by_dim.values():
            for i, a in enumerate(ms):
                for b in ms[i + 1:]:
                    if _compatible(a, b) is False:
                        conflict = True
        if conflict:
            return ("possible_conflict", POSSIBLE_CONFLICT_NOTE)
        if unnormalised:
            units = ", ".join(sorted({f"{m.raw_value} {m.raw_unit}".strip() for m in unnormalised}))
            return (
                "unresolved",
                f"Unit could not be normalised ({units}); values cannot be compared. "
                f"Raw values are shown.",
            )
        raw_dims = {frozenset(m.dimension for m in r.measurements) for r in with_measurements}
        if len(raw_dims) > 1 and len(by_dim) > 1:
            return ("addition", "Rows measure different dimensions; no value is contradicted.")

    if len(rows) == 1:
        return ("addition", "Only one document speaks to this facet.")

    shapes = {(_dimensions(r), frozenset(r.identifiers)) for r in rows}
    if len(shapes) == 1:
        return ("agreement", None)
    return ("addition", "One row carries a measurement or identifier the others lack; nothing is contradicted.")


# ------------------------------------------------------------------ clustering
def _can_merge(small_key: frozenset[str], small_rows: list[Claim],
               big_key: frozenset[str], big_rows: list[Claim]) -> bool:
    """Are these two facets the SAME SUBJECT seen at two levels of detail?

    THE MERGE RULE, stated so it can be disagreed with. Two facets merge when
    all four hold:

      1. Both name a subject in words (a key that is only a dimension, only a
         unit or only a number names nothing and never merges).
      2. The smaller subject term set is a subset of the larger. {documents}
         and {documents, drawing} qualify; {documents} and {drawing} do not.
      3. The larger facet's HEAD NOUN - the last word of the phrase its own
         claims use - is one of the smaller facet's terms. "drawing documents"
         is a kind of "documents", so they merge; "document drawings" is a
         kind of "drawings", so a {documents} facet does NOT absorb it.
         Equal term sets (differing only in dimension) skip this: they are
         already the same words.
      4. Designators match exactly. System 1 and system 9 are two different
         things, and no amount of shared vocabulary makes them one.

    Rules 2 and 3 have one alternative: two facets that are NOT in a subset
    relation merge anyway when the phrase their own claims share is the same
    non-empty phrase. {analysis, models, structural} and {documents, models,
    structural} both read "structural models", and emitting that name twice is
    the same defect under a nicer label.

    Plus the RECALL GUARD below, which refuses any merge that would turn a
    possible_conflict into something quieter.
    """
    sa, sb = subject_terms(small_key), subject_terms(big_key)
    if not sa or not sb:
        return False
    if _designator_tokens(small_key) != _designator_tokens(big_key):
        return False
    if sa <= sb:
        if sa != sb:
            head = _head_term(big_rows, sb)
            if head is None or head not in sa:
                return False
    else:
        # NEITHER IS A SUBSET, but both sets of claims call the subject the
        # same thing: {analysis, models, structural} and {documents, models,
        # structural} both read "structural models", and two facets with one
        # name is the bag-of-query-words defect wearing a better label. Equal
        # phrases are one facet.
        phrase = _shared_phrase(small_rows, sa)
        if not phrase or phrase != _shared_phrase(big_rows, sb):
            return False
    # RECALL GUARD. A merge may only ever ADD evidence to a disagreement, never
    # dissolve one: absorbing a conflicting pair into a broader facet whose
    # other rows carry different designators would relabel it "unresolved" and
    # the finding would vanish from the report. If either side is a conflict
    # today and the merged rows are not, the two facets stay apart.
    merged = tuple(small_rows) + tuple(big_rows)
    was_conflict = (label_cluster(small_rows)[0] == "possible_conflict"
                    or label_cluster(big_rows)[0] == "possible_conflict")
    if was_conflict and label_cluster(merged)[0] != "possible_conflict":
        return False
    return True


def _merge_facets(groups: dict[frozenset[str], list[Claim]]
                  ) -> list[tuple[frozenset[str], list[Claim]]]:
    """Fold narrower facets into the broader facet they are a detail of.

    Applied to a fixpoint and in a deterministic order - fewest terms first,
    then the sorted key - so the same corpus always produces the same facets.
    """
    items: list[list] = [[key, list(rows)] for key, rows in groups.items()]
    items.sort(key=lambda it: (len(subject_terms(it[0])), sorted(it[0])))
    changed = True
    while changed:
        changed = False
        for i, small in enumerate(items):
            target = None
            for j, big in enumerate(items):
                if i == j:
                    continue
                if j < i:
                    # Only ever fold EARLIER into LATER in the deterministic
                    # ordering. A narrower facet always sorts first, so this
                    # is "detail into subject" - and it makes the fold acyclic,
                    # which a symmetric rule (equal phrases) otherwise is not.
                    continue
                if _can_merge(small[0], small[1], big[0], big[1]):
                    target = j
                    break
            if target is not None:
                items[target][0] = items[target][0] | small[0]
                items[target][1] = items[target][1] + small[1]
                items.pop(i)
                changed = True
                break
    return [(key, rows) for key, rows in items]


def cluster(claims: list[Claim], question_terms: frozenset[str]) -> list[Cluster]:
    """Cluster iff same facet_key, then merge facets that are the same subject
    at two levels of detail (`_can_merge`). Never by text similarity. Claims
    whose facet_key is None are dropped: they cannot be compared to anything,
    and a facet with no claim on either side is not emitted at all - a question
    word appearing somewhere is not a finding.
    """
    groups: dict[frozenset[str], list[Claim]] = {}
    for c in claims:
        key = facet_key(c, question_terms)
        if key is None:
            continue
        groups.setdefault(key, []).append(c)
    out: list[Cluster] = []
    for key, rows in _merge_facets(groups):
        if not rows:
            continue
        label, note = label_cluster(rows)
        out.append(Cluster(facet=_facet_string(key, rows), label=label,
                           rows=tuple(rows), note=note, key=key))
    out.sort(key=lambda c: c.facet)
    return out


# ------------------------------------------------------------------ API shape
def _row(claim: Claim, key: frozenset[str]) -> dict:
    dims = {k.split(":", 1)[1] for k in key if k.startswith("dim:")}
    chosen = next((m for m in claim.measurements if m.dimension in dims), None)
    if chosen is None and claim.measurements:
        chosen = claim.measurements[0]
    return {
        "evidence_id": claim.evidence_id,
        "filename": claim.filename,
        "page_start": claim.page_start,
        "section": claim.section,
        "exact_span": claim.exact_span,
        "raw_value": chosen.raw_value if chosen else None,
        "raw_unit": chosen.raw_unit if chosen else None,
        "normalized_value": chosen.normalized_value if chosen else None,
        "normalized_unit": chosen.normalized_unit if chosen else None,
    }


def to_api(clusters: list[Cluster]) -> list[dict]:
    """The ClaimCluster shape in frontend/src/types/analysis.ts. `note` is an
    extra key the type does not declare; the UI is free to ignore it."""
    return [
        {
            "facet": c.facet,
            "label": c.label,
            "rows": [_row(r, c.key) for r in c.rows],
            "note": c.note,
        }
        for c in clusters
    ]
