"""Mechanical claim extraction and comparison. No model, no database, no network.

Spec: docs/design-analysis-and-synthesis.md, "The claim algorithm" and
"Unmeasured becoming zero". The rules that matter most, restated:

  * A claim's subject is the EXACT SENTENCE, verbatim. Never a paraphrase.
  * Unit normalisation is a table lookup. An unknown unit gives
    normalized_value None - never a guess, never 0. `normalise_strict` raises
    UnknownUnit instead, the scores.ScaleMismatch discipline.
  * Clustering is by facet key: the question's distinctive terms present in
    the claim, plus the unit dimension. Never by wording similarity.
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
_DIMENSION_UNIT = {
    "length": "um", "pressure": "MPa", "temperature": "C", "percent": "%",
    "time": "h", "voltage": "V", "current": "A",
}

#: Units extraction recognises but the table does NOT convert, with the
#: dimension they belong to when it is certain. Extracted with
#: normalized_value None and a dimension, so "350 °F" lands in the temperature
#: facet and is labelled unresolved there rather than silently converted. An
#: arbitrary word after a number ("no. 9 has") is NOT a measurement.
_UNCONVERTED_UNITS: dict[str, str | None] = {
    "f": "temperature", "degf": "temperature", "k": "temperature",
    "mil": "length", "mils": "length", "cm": "length", "m": "length", "km": "length",
    "ft": "length", "inch": "length", "inches": "length", "nm": "length",
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
        prefix = sentence[:start].rstrip()
        cmp_match = re.search(r"(?:" + _COMPARATOR_RE + r")\s*$", prefix, re.IGNORECASE)
        comparator = parse_comparator(cmp_match.group(0)) if cmp_match else None
        found.append(normalise(m.group("value"), unit, comparator))
    return tuple(found)


def claim_terms(sentence: str) -> frozenset[str]:
    return frozenset(t.lower() for t in lexical.distinctive_terms(sentence))


def question_terms(question: str) -> frozenset[str]:
    """The question's distinctive terms, lowercased, as a facet_key input."""
    return frozenset(t.lower() for t in lexical.distinctive_terms(question))


def extract_claims(evidence: list[dict]) -> list[Claim]:
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
                    terms=claim_terms(sentence) - frozenset(dropped),
                )
            )
    return claims


# ------------------------------------------------------------------ facets
def _dimensions(claim: Claim) -> frozenset[str]:
    return frozenset(m.dimension for m in claim.measurements if m.dimension)


def facet_key(claim: Claim, question_terms: frozenset[str]) -> frozenset[str] | None:
    """(question_terms ∩ claim.terms) plus "dim:<dimension>" per measurement.
    None when the intersection is empty and the claim has no designator: such a
    claim cannot be compared with anything and must not be clustered by wording.
    With no shared term but a designator, the designator words stand in."""
    shared = frozenset(t.lower() for t in question_terms) & claim.terms
    dims = frozenset(f"dim:{d}" for d in _dimensions(claim))
    if shared:
        return shared | dims
    if claim.designators:
        return frozenset(f"designator:{d}" for d in claim.designators) | dims
    return None


#: How a unit is written for a person rather than for a parser. "um" is what
#: the corpus contains and "µm" is what a coatings engineer reads.
_UNIT_DISPLAY = {"um": "µm", "degC": "°C", "percent": "%"}


def _facet_string(key: frozenset[str]) -> str:
    """One dimension, named so a reader recognises it: "coating thickness (µm)".

    This used to join every term, designator and unit in the key with " · ",
    producing "coating · thickness · A · um" and "coating · % · A · MPa" - a
    facet that names four things names none of them, and a reader scanning a
    gap analysis cannot tell what is being compared.

    The subject and the unit are separated: subject words read as a phrase,
    and the unit goes in brackets where a unit belongs. Terms stay sorted so
    the string is deterministic - two runs over the same corpus must produce
    the same facet - which happens to read correctly here ("coating
    thickness") and is a compromise where it does not.
    """
    terms = sorted(k for k in key if not k.startswith(("dim:", "designator:")))
    designators = sorted(k.split(":", 1)[1] for k in key if k.startswith("designator:"))
    units = sorted(
        _UNIT_DISPLAY.get(u, u)
        for u in (_DIMENSION_UNIT[k.split(":", 1)[1]] for k in key if k.startswith("dim:"))
    )

    subject = " ".join(terms) or ", ".join(designators)
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


def _compatible(a: Measurement, b: Measurement) -> bool | None:
    """True when the values (as ranges) overlap, False when not, None if undecidable."""
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
def cluster(claims: list[Claim], question_terms: frozenset[str]) -> list[Cluster]:
    """Cluster iff same facet_key. Never by text similarity. Claims whose
    facet_key is None are dropped: they cannot be compared to anything."""
    groups: dict[frozenset[str], list[Claim]] = {}
    for c in claims:
        key = facet_key(c, question_terms)
        if key is None:
            continue
        groups.setdefault(key, []).append(c)
    out: list[Cluster] = []
    for key, rows in groups.items():
        label, note = label_cluster(rows)
        out.append(Cluster(facet=_facet_string(key), label=label, rows=tuple(rows), note=note, key=key))
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
