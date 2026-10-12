"""Which clause applies: conditions in a question and in a passage.

THE DEFECT THIS EXISTS FOR (refusal calibration, 2026-09-29, counts only). Of
166 real questions, 66 were answered from a clause stating a DIFFERENT value
than the one asked about - "the minimum wall thickness" answered from the
2-inch-and-smaller clause when the larger-pipe clause was meant. A check of 20
of those found about two in three were questions that never said which size,
class or service applied: both clauses were right, for different conditions,
and picking one silently is a confident wrong answer half the time. Better
search cannot fix a question that does not say what it is about.

So, for the few passages that compete to answer a question:

  * when the question NAMES a condition ("for a 6 inch pipe") and exactly one
    competing passage holds under it, that passage answers - the condition
    outranks a slightly higher score;
  * when the question names none of the conditions the passages differ on,
    every competing passage is shown WITH its condition, and the reader is
    asked which applies. Values are never merged, and none is picked for them.

DETERMINISTIC PATTERNS ONLY - no model, nothing leaves the machine. A
condition this module cannot read is not a condition to it: it never guesses
one, so a missed pattern degrades to today's behaviour (the top passage),
never to a wrong choice. Separate from `conditions.py`, which decides whether
a requirement's condition is ESTABLISHED by a submittal's facts for the
review engine - a different question with different evidence rules.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import numparse

#: A number as specifications print it: 6, 0.5, -29, 1/2, 1 1/2, 1-1/2, 150.
#: Never preceded by a letter, digit or point, so "SAES-L-310" yields no -310.
#: A hyphen followed by a fraction is a mixed number ("1-1/2"), never a range.
_N = r"(?<![\w.])-?\d+/\d+|(?<![\w.])-?\d+(?:[.,]\d+)?(?:(?:\s+|-)\d+/\d+(?![\d/]))?"

_INCH = r"(?:inch(?:es)?\b|in\.(?=\s|$)|\"|”|″)"
_MM = r"(?:mm\b|millimet(?:er|re)s?\b)"
_DEG_C = r"(?:°\s*C\b|º\s*C\b|deg(?:rees?)?\.?\s*C\b|C\b)"
_DEG_F = r"(?:°\s*F\b|º\s*F\b|deg(?:rees?)?\.?\s*F\b)"
_PRESSURE = r"(?:psig?\b|barg?\b|kpa\b|mpa\b)"

_ABOVE = r"(?:larger|greater|bigger|more|higher|over|above|exceeding|in excess of)"
_BELOW = r"(?:smaller|less|lower|under|below|up to|not exceeding|not more than|maximum of|max\.?)"

#: One quantity of each kind, captured whole. Size also reads the prefix
#: forms NPS 6 and DN 150.
_Q = {
    "size": rf"(?:\bnps\s*(?:{_N})|\bdn\s*\d{{2,4}}\b|(?:{_N})\s*-?\s*(?:{_INCH}|{_MM}))",
    "temperature": rf"(?:(?:{_N})\s*(?:{_DEG_C}|{_DEG_F}))",
    "pressure": rf"(?:(?:{_N})\s*{_PRESSURE})",
}

#: DN (nominal millimetres) to NPS (nominal inches) as ASME B36.10 pairs them.
#: DN / 25 is only right from DN 350 up (NPS 14 and larger).
_DN_TO_NPS = {6: 0.125, 8: 0.25, 10: 0.375, 15: 0.5, 20: 0.75, 25: 1, 32: 1.25, 40: 1.5,
              50: 2, 65: 2.5, 80: 3, 90: 3.5, 100: 4, 125: 5, 150: 6, 200: 8, 250: 10,
              300: 12}

#: Around a size, the words that make it a NOMINAL size - the case a clause
#: applies to ("6 inch pipe", "pipes larger than 2 inch") - rather than a
#: measured value ("thickness of 1/4 inch", "a gap of 3 mm").
_NOMINAL = r"(?:pipes?|piping|lines?|nozzles?|valves?|flanges?|branch(?:es)?|fittings?|headers?|sizes?|diameters?|bore|nb|nps|dn|tubing|tubes?)"
_NOMINAL_AFTER = re.compile(rf"^\s*(?:nominal\s+)?{_NOMINAL}\b", re.I)
_NOMINAL_WORD = re.compile(rf"\b{_NOMINAL}\b", re.I)
_MEASURE_WORD = re.compile(
    r"\b(?:thick(?:ness)?|wall|gap|clearance|allowance|length|width|height|depth|distance"
    r"|spacing|radius|overlap|weld|reinforcement|penetration|dft|coating|film|tolerance)\b", re.I)
#: A bare "C" after a number is a temperature unless the number names a table,
#: figure or clause ("Table 3 C").
_NOT_A_TEMPERATURE = re.compile(
    r"\b(?:table|figure|fig\.?|clause|section|annex|appendix|note|item|grade|class|type|part)\s*$", re.I)

#: Named, closed vocabularies. A bare "wet"/"dry"/"steam"/"atmospheric" is not a
#: service or location ("dry film thickness", "atmospheric pressure").
_CATEGORIES: dict[str, list[tuple[str, str]]] = {
    "service": [
        (r"\bsour\b|\bh2s\b|\bhydrogen sulfide|\bhydrogen sulphide", "sour"),
        (r"\bsea ?water\b", "seawater"), (r"\bfresh ?water\b", "fresh water"),
        (r"\bpotable water\b", "potable water"),
        (r"\bsteam (?:service|piping|lines?|systems?)\b", "steam"),
        (r"\bcaustic\b", "caustic"), (r"\bcryogenic\b", "cryogenic"),
        (r"\bhydrogen service\b", "hydrogen"),
        (r"\bwet (?:service|gas|h2s|sour|environments?|conditions?)\b", "wet"),
        (r"\bdry (?:service|gas|air|environments?|conditions?)\b", "dry"),
    ],
    "material": [
        (r"\bcarbon steel\b", "carbon steel"), (r"\blow[- ]alloy steel\b", "low-alloy steel"),
        (r"\bstainless steel\b", "stainless steel"), (r"\bsuper ?duplex\b", "super duplex"),
        (r"\bduplex\b(?! stainless)", "duplex"), (r"\bgalvani[sz]ed\b", "galvanized"),
        (r"\bcopper[- ]nickel\b|\bcuni\b", "copper-nickel"), (r"\bcast iron\b", "cast iron"),
    ],
    "location": [
        (r"\bburied\b|\bunderground\b", "buried"), (r"\bsubmerged\b|\bimmersed\b", "submerged"),
        (r"\bsplash zone\b", "splash zone"),
        (r"\batmospheric (?:service|exposure|environments?|zones?|corrosion)\b", "atmospheric"),
        (r"\babove ?ground\b", "above ground"), (r"\bonshore\b", "onshore"),
        (r"\boffshore\b", "offshore"), (r"\bindoors?\b", "indoor"), (r"\boutdoors?\b", "outdoor"),
    ],
}

#: ASME pressure classes and PN ratings - a bare "1500 lb" is a weight.
_CLASS = re.compile(r"\bclass\s*(\d{3,4})\b|(?<![\w.])(\d{3,4})\s*#", re.I)
_PN = re.compile(r"\bpn\s*(\d{1,3})\b", re.I)

_EPS = 1e-6


@dataclass(frozen=True)
class Condition:
    """One condition, as written and as a comparable value.

    Numeric kinds (size, temperature, pressure) carry an interval in the
    kind's base unit (inch, °C, psi): `low`/`high` None mean unbounded, and
    `*_open` marks a strict bound ("larger than 2 inch" excludes 2).
    Categorical kinds carry `value`.
    """
    kind: str
    text: str
    low: float | None = None
    high: float | None = None
    low_open: bool = False
    high_open: bool = False
    value: str | None = None

    def holds_for(self, other: Condition) -> bool | None:
        """Does the question's condition `other` fall WHOLLY under this one?
        None when the two are different kinds - nothing is decided.

        Interval inside interval, with open ends respected: "larger than 2
        inch" (2, inf) is inside "larger than 2 inch" and "2 inch and larger"
        [2, inf), and NOT inside "2 inch and smaller" (-inf, 2] - it shares
        only the endpoint the question excludes."""
        if other.kind != self.kind:
            return None
        if self.value is not None or other.value is not None:
            return self.value == other.value
        if other.low is None and other.high is None:
            return None
        return self._lower_ok(other) and self._upper_ok(other)

    def _lower_ok(self, q: Condition) -> bool:
        if self.low is None:
            return True
        if q.low is None:
            return False
        if q.low > self.low + _EPS:
            return True
        if abs(q.low - self.low) <= _EPS:
            return q.low_open or not self.low_open
        return False

    def _upper_ok(self, q: Condition) -> bool:
        if self.high is None:
            return True
        if q.high is None:
            return False
        if q.high < self.high - _EPS:
            return True
        if abs(q.high - self.high) <= _EPS:
            return q.high_open or not self.high_open
        return False

    def same_as(self, other: Condition) -> bool:
        return (self.kind, self.value, self._r(self.low), self._r(self.high),
                self.low_open, self.high_open) == (
            other.kind, other.value, other._r(other.low), other._r(other.high),
            other.low_open, other.high_open)

    @staticmethod
    def _r(x: float | None) -> float | None:
        return None if x is None else round(x, 4)


def _number(raw: str) -> float | None:
    raw = raw.strip()
    negative = raw.startswith("-")
    raw = raw.lstrip("-")
    parts = re.split(r"\s+|-(?=\d+/\d)", raw)
    total = 0.0
    try:
        for part in parts:
            if "/" in part:
                num, den = part.split("/", 1)
                total += float(num) / float(den)
            elif part:
                # numparse reads "1,500" as 1500 and "9,0" as 9.0; the old
                # blanket comma-to-point made "1,500 mm" 1.5 (audit A16).
                value = numparse.as_number(part)
                if value is None:
                    return None
                total += value
    except (ValueError, ZeroDivisionError):
        return None
    return -total if negative else total


def _quantity(kind: str, text: str, unit_from: str | None = None) -> tuple[float, str] | None:
    """(value in the kind's base unit, unit family) for one quantity, or None.
    `unit_from` lends a unit to a bare number ("2 to 6 inch": the 2)."""
    t = " ".join(text.split())
    if kind == "size":
        m = re.fullmatch(rf"nps\s*({_N})", t, re.I)
        if m:
            v = _number(m.group(1))
            return (v, "in") if v is not None and v > 0 else None
        m = re.fullmatch(r"dn\s*(\d{2,4})", t, re.I)
        if m:
            dn = int(m.group(1))
            v = _DN_TO_NPS.get(dn, dn / 25 if dn >= 350 else None)
            return (float(v), "in") if v else None
    m = re.match(rf"({_N})\s*-?\s*(.*)$", t, re.I)
    if not m:
        return None
    v = _number(m.group(1))
    unit = m.group(2).strip() or (unit_from or "")
    if v is None or not unit:
        return None
    if kind == "size":
        if v <= 0:
            return None
        if re.fullmatch(_INCH, unit, re.I):
            return v, "in"
        if re.fullmatch(_MM, unit, re.I):
            return v / 25.4, "mm"
        return None
    if kind == "temperature":
        if re.fullmatch(_DEG_F, unit, re.I):
            return (v - 32) * 5 / 9, "F"
        return v, "C"
    factor = {"psi": 1.0, "psig": 1.0, "bar": 14.5038, "barg": 14.5038,
              "kpa": 0.145038, "mpa": 145.038}.get(unit.lower())
    return (v * factor, "p") if factor else None


def _unit_of(text: str) -> str:
    m = re.match(rf"({_N})\s*-?\s*(.*)$", " ".join(text.split()), re.I)
    return m.group(2) if m else ""


def _counts(kind: str, text: str, start: int, end: int, family: str, question: bool,
            comparative: bool) -> bool:
    """Is this quantity a CONDITION here, or a value? See module docstring.

    A passage's bare point is always a value ("shall be 5 mm"). A size is a
    condition only as a NOMINAL size: NPS/DN, or next to a pipe word and not
    after a measuring word ("thickness of 1/4 inch"). A bare "C" after a table
    or clause number is not a temperature."""
    before = text[max(0, start - 40):start]
    after = text[end:]
    if kind == "temperature":
        if re.search(r"\d\s*C\b$", text[start:end]) and not re.search(r"[°º]|deg", text[start:end], re.I):
            if _NOT_A_TEMPERATURE.search(before):
                return False
        return question or comparative
    if kind == "pressure":
        return question or comparative
    # size
    head = text[start:end].lower()
    if head.startswith(("nps", "dn")):
        return True
    nominal_after = bool(_NOMINAL_AFTER.match(after))
    nominal_before = [m.end() for m in _NOMINAL_WORD.finditer(before)]
    measure_before = [m.end() for m in _MEASURE_WORD.finditer(before)]
    if _MEASURE_WORD.match(after.strip()) and not nominal_after:
        return False
    if nominal_after:
        return True
    if nominal_before and (not measure_before or max(nominal_before) > max(measure_before)):
        return comparative or question
    if family == "in" and not measure_before and (question or comparative):
        return True       # "for a 6 inch?", "2 inch and smaller:" - nominal inch sizes
    if question and family == "in" and re.search(r"\b(?:for|on|in)\s+(?:an?\s+|the\s+)?$", before, re.I):
        return True       # "thickness for 6 inch" - the preposition names the case
    return False


def _numeric(kind: str, text: str, question: bool) -> list[Condition]:
    """Ranges first, then comparisons, then points not already inside one.

    A POINT IS A CONDITION ONLY IN A QUESTION, and a size only as a nominal
    size - see `_counts`. Reading "shall be 5 mm" as a condition made every
    two clauses with different values look like different cases.
    """
    q = _Q[kind]
    out: list[Condition] = []
    taken: list[tuple[int, int]] = []

    def free(m: re.Match) -> bool:
        return all(m.end() <= a or m.start() >= b for a, b in taken)

    shapes = [
        (rf"between\s+(?P<a>{q}|{_N})\s+and\s+(?P<b>{q})", "range"),
        (rf"(?P<a>{q}|{_N})\s*(?:–|to|through|-(?!\s*\d+/\d))\s*(?P<b>{q})", "range"),
        (rf"{_ABOVE}\s+(?:than\s+)?(?P<a>{q})", "above"),
        (rf"(?P<a>{q})\s+(?:and|or)\s+(?:larger|greater|bigger|above|over|more|higher)", "from"),
        (rf"(?P<a>{q})\s+(?:and|or)\s+(?:smaller|less|below|under|lower)", "upto"),
        (rf"{_BELOW}\s+(?:than\s+)?(?P<a>{q})", "below"),
        (rf"(?P<a>{q})", "point"),
    ]
    for pattern, shape in shapes:
        for m in re.finditer(pattern, text, re.I):
            if not free(m):
                continue
            if shape == "range":
                b = _quantity(kind, m.group("b"))
                a = _quantity(kind, m.group("a"), unit_from=_unit_of(m.group("b")))
                if a is None or b is None:
                    continue
                if not _counts(kind, text, m.start(), m.end(), b[1], question, True):
                    continue
                taken.append((m.start(), m.end()))
                out.append(Condition(kind, " ".join(m.group(0).split()),
                                     low=min(a[0], b[0]), high=max(a[0], b[0])))
                continue
            got = _quantity(kind, m.group("a"))
            if got is None:
                continue
            v, family = got
            if not _counts(kind, text, m.start(), m.end(), family, question, shape != "point"):
                continue
            taken.append((m.start(), m.end()))
            label = " ".join(m.group(0).split())
            if shape == "above":
                out.append(Condition(kind, label, low=v, low_open=True))
            elif shape == "from":
                out.append(Condition(kind, label, low=v))
            elif shape == "upto":
                out.append(Condition(kind, label, high=v))
            elif shape == "below":
                strict = bool(re.search(r"smaller|less|lower|under|below", m.group(0), re.I)) \
                    and not re.search(r"up to|not exceeding|not more than|maximum", m.group(0), re.I)
                out.append(Condition(kind, label, high=v, high_open=strict))
            else:
                out.append(Condition(kind, label, low=v, high=v))
    # `taken` grows in step with `out` (one span per condition), so each
    # condition comes back with where it is written.
    return list(zip(out, taken))


def extract(text: str, *, question: bool = False) -> list[Condition]:
    """Every condition this module can read in `text`, in no particular
    order. Duplicates (the same condition written twice) are kept once.
    `question=True` also reads bare points ("a 6 inch pipe", "at 90 °C") -
    see `_counts` for why a passage's bare points are values instead."""
    text = (text or "").replace("−", "-").replace("–", "–")
    found: list[Condition] = []
    for kind in ("size", "temperature", "pressure"):
        found.extend(c for c, _ in _numeric(kind, text, question))
    for m in _CLASS.finditer(text):
        n = next(g for g in m.groups() if g)
        found.append(Condition("class", " ".join(m.group(0).split()), value=f"class {n}"))
    for m in _PN.finditer(text):
        found.append(Condition("class", m.group(0), value=f"PN {m.group(1)}"))
    lowered = text.lower()
    for kind, vocab in _CATEGORIES.items():
        for pattern, value in vocab:
            m = re.search(pattern, lowered)
            if m:
                found.append(Condition(kind, m.group(0), value=value))
    unique: list[Condition] = []
    for c in found:
        if not any(c.same_as(u) for u in unique):
            unique.append(c)
    return unique


_VALUE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w.])")


def stated_values(text: str) -> set[str]:
    """The bare numbers a passage states - what 'a different value' means."""
    return set(_VALUE.findall(text or ""))


def differing_kinds(a: list[Condition], b: list[Condition]) -> set[str]:
    """Kinds both passages state, where what they state differs."""
    kinds = {c.kind for c in a} & {c.kind for c in b}
    out = set()
    for kind in kinds:
        ca = [c for c in a if c.kind == kind]
        cb = [c for c in b if c.kind == kind]
        if not any(x.same_as(y) for x in ca for y in cb):
            out.add(kind)
    return out


def verdict(question_conditions: list[Condition], passage_conditions: list[Condition],
            kinds: set[str]) -> bool | None:
    """Does the passage hold under the question's conditions, judged on
    `kinds` only? True / False, or None when the question states none of
    those kinds (nothing to judge)."""
    judged = [q for q in question_conditions if q.kind in kinds]
    if not judged:
        return None
    for q in judged:
        same_kind = [p for p in passage_conditions if p.kind == q.kind]
        if not same_kind:
            return False
        if not any(p.holds_for(q) for p in same_kind):
            return False
    return True


def describe(conditions: list[Condition], kinds: set[str] | None = None) -> list[str]:
    """The conditions as the passage writes them, for the reader."""
    return [c.text for c in conditions if kinds is None or c.kind in kinds]


# ----------------------------------------------------- one passage, several cases

def located(text: str) -> list[tuple[Condition, int, int]]:
    """Every condition a PASSAGE states, with where it is written (offsets
    into `text`). Read as `extract` reads a passage, but NOT de-duplicated
    (the same condition on two lines is two occurrences) and ONE LINE AT A
    TIME: a table header's "wall thickness" must not make the row below it
    read as a measured value."""
    text = (text or "").replace("\u2212", "-")        # same length: offsets hold
    found: list[tuple[Condition, int, int]] = []
    at = 0
    for line in text.split("\n"):
        found.extend((c, a + at, b + at) for c, a, b in _located_line(line))
        at += len(line) + 1
    return sorted(found, key=lambda t: t[1])


def _located_line(text: str) -> list[tuple[Condition, int, int]]:
    found: list[tuple[Condition, int, int]] = []
    for kind in ("size", "temperature", "pressure"):
        found.extend((c, a, b) for c, (a, b) in _numeric(kind, text, False))
    for m in _CLASS.finditer(text):
        n = next(g for g in m.groups() if g)
        found.append((Condition("class", " ".join(m.group(0).split()), value=f"class {n}"),
                      m.start(), m.end()))
    for m in _PN.finditer(text):
        found.append((Condition("class", m.group(0), value=f"PN {m.group(1)}"), m.start(), m.end()))
    lowered = text.lower()
    for kind, vocab in _CATEGORIES.items():
        for pattern, value in vocab:
            for m in re.finditer(pattern, lowered):
                found.append((Condition(kind, m.group(0), value=value), m.start(), m.end()))
    return found


@dataclass(frozen=True)
class Case:
    """One line of a passage that lists several cases: the condition it is
    written for, where the line is (offsets into the passage text), the line
    as written, and the values it states (the condition's own numbers aside)."""
    condition: Condition
    start: int
    end: int
    text: str
    values: frozenset[str]


#: A case line starts after one of these (a clause's lead-in colon, a list
#: separator, a table row break, a sentence end) ...
_CASE_OPEN = re.compile(r"[;:,\n]|(?<=[.!?])\s")
#: ... and ends at a list separator, a row break or a sentence end ("1.5" is
#: not one: the point must be followed by a space or the end).
_CASE_CLOSE = re.compile(r"[;\n]|[.!?](?=\s|$)")
_KIND_ORDER = ("size", "temperature", "pressure", "class", "service", "material", "location")


def _lines_for(text: str, occurrences: list[tuple[Condition, int, int]]) -> list[Case]:
    starts = []
    for i, (_, s, _) in enumerate(occurrences):
        floor = occurrences[i - 1][2] if i else 0
        opens = [m.end() for m in _CASE_OPEN.finditer(text, floor, s)]
        starts.append(opens[-1] if opens else floor)
    out: list[Case] = []
    for i, (c, s, e) in enumerate(occurrences):
        close = _CASE_CLOSE.search(text, e)
        end = min(close.start() if close else len(text),
                  starts[i + 1] if i + 1 < len(occurrences) else len(text))
        start = starts[i]
        raw = text[start:end]
        lead = len(raw) - len(raw.lstrip())
        body = raw.strip().rstrip(";:,").rstrip()
        if not body:
            continue
        # the values the line SETS: its numbers, the condition's own blanked
        # out ("over 2 inch to 6 inch | 6 mm" sets 6, not nothing)
        at = start + lead
        values = stated_values(text[at:s] + " " * (e - s) + text[e:at + len(body)])
        if values:
            out.append(Case(c, start + lead, start + lead + len(body), body, frozenset(values)))
    return out


def cases(text: str) -> list[Case]:
    """The cases ONE passage lists, when it sets a different value for each:
    "pipes 2 inch and smaller: 3 mm; pipes larger than 2 inch: 6 mm", or a
    table whose rows are size ranges. In reading order; [] when the passage
    is not such a list - fewer than two lines each stating a value under a
    condition, conditions all the same, or values all the same.

    One kind of condition is read: the one with the most distinct
    conditions (ties in `_KIND_ORDER`). The lines are located, never
    rewritten - the passage is still quoted whole."""
    by_kind: dict[str, list[tuple[Condition, int, int]]] = {}
    for c, s, e in located(text):
        by_kind.setdefault(c.kind, []).append((c, s, e))
    best: list[Case] = []
    best_distinct = 1
    for kind in _KIND_ORDER:
        occurrences = by_kind.get(kind) or []
        found = _lines_for(text or "", occurrences)
        distinct: list[Condition] = []
        for case in found:
            if not any(case.condition.same_as(d) for d in distinct):
                distinct.append(case.condition)
        if len(distinct) <= best_distinct or len({case.values for case in found}) < 2:
            continue
        best, best_distinct = found, len(distinct)
    return best
