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

#: A number as specifications print it: 6, 0.5, 1/2, 1 1/2, 1-1/2, 150.
_NUM = r"(\d+(?:[.,]\d+)?(?:[\s-]+\d+/\d+)?|\d+/\d+)"

_INCH = r"(?:inch(?:es)?\b|in\.(?=\s|$)|\"|”|″)"
_MM = r"(?:mm\b|millimet(?:er|re)s?\b)"
_DEG_C = r"(?:°\s*C\b|deg(?:rees?)?\.?\s*C\b|ºC\b|(?<=\d)\s*C\b)"
_DEG_F = r"(?:°\s*F\b|deg(?:rees?)?\.?\s*F\b|ºF\b)"
_PSI = r"(?:psig?\b)"
_BAR = r"(?:barg?\b)"
_KPA = r"(?:kpa\b)"
_MPA = r"(?:mpa\b)"

_ABOVE = r"(?:larger|greater|bigger|more|higher|over|above|exceeding|in excess of)"
_BELOW = r"(?:smaller|less|lower|under|below|up to|not exceeding|not more than|maximum of|max\.?)"

#: kind -> [(unit pattern, factor to the kind's base unit)]
_UNITS: dict[str, list[tuple[str, float]]] = {
    "size": [(_INCH, 1.0), (_MM, 1 / 25.4)],
    "temperature": [(_DEG_C, 1.0), (_DEG_F, None)],   # F converted below
    "pressure": [(_PSI, 1.0), (_BAR, 14.5038), (_KPA, 0.145038), (_MPA, 145.038)],
}

_BASE_UNIT = {"size": "in", "temperature": "°C", "pressure": "psi"}

#: Named, closed vocabularies. Order matters only for display.
_CATEGORIES: dict[str, list[tuple[str, str]]] = {
    "service": [
        (r"\bsour\b|\bh2s\b|\bhydrogen sulfide|\bhydrogen sulphide", "sour"),
        (r"\bsea ?water\b", "seawater"), (r"\bfresh ?water\b", "fresh water"),
        (r"\bpotable water\b", "potable water"), (r"\bsteam\b", "steam"),
        (r"\bcaustic\b", "caustic"), (r"\bcryogenic\b", "cryogenic"),
        (r"\bhydrogen service\b", "hydrogen"), (r"\bwet\b", "wet"), (r"\bdry\b", "dry"),
    ],
    "material": [
        (r"\bcarbon steel\b", "carbon steel"), (r"\blow[- ]alloy steel\b", "low-alloy steel"),
        (r"\bstainless steel\b", "stainless steel"), (r"\bsuper ?duplex\b", "super duplex"),
        (r"\bduplex\b(?! stainless)", "duplex"), (r"\bgalvani[sz]ed\b", "galvanized"),
        (r"\bcopper[- ]nickel\b|\bcuni\b", "copper-nickel"), (r"\bcast iron\b", "cast iron"),
    ],
    "location": [
        (r"\bburied\b|\bunderground\b", "buried"), (r"\bsubmerged\b|\bimmersed\b", "submerged"),
        (r"\bsplash zone\b", "splash zone"), (r"\batmospheric\b", "atmospheric"),
        (r"\babove ?ground\b", "above ground"), (r"\bonshore\b", "onshore"),
        (r"\boffshore\b", "offshore"), (r"\bindoors?\b", "indoor"), (r"\boutdoors?\b", "outdoor"),
    ],
}

_CLASS = re.compile(r"\bclass\s*(\d{3,4})\b|\b(\d{3,4})\s*#|\b(\d{3,4})\s*lbs?\b", re.I)
_PN = re.compile(r"\bpn\s*(\d{1,3})\b", re.I)
_NPS = re.compile(r"\bnps\s*" + _NUM, re.I)
_DN = re.compile(r"\bdn\s*(\d{2,4})\b", re.I)


@dataclass(frozen=True)
class Condition:
    """One condition, as written and as a comparable value.

    Numeric kinds (size, temperature, pressure) carry a range in the kind's
    base unit: `low`/`high` None mean unbounded, and `*_open` marks a strict
    bound ("larger than 2 inch" excludes 2). Categorical kinds carry `value`.
    """
    kind: str
    text: str
    low: float | None = None
    high: float | None = None
    low_open: bool = False
    high_open: bool = False
    value: str | None = None

    def holds_for(self, other: Condition) -> bool | None:
        """Does `other` (from a question) fall under this condition? None
        when the two are different kinds - nothing is decided."""
        if other.kind != self.kind:
            return None
        if self.value is not None or other.value is not None:
            return self.value == other.value
        # a question states a point (or a range): every point it states must
        # lie inside this condition's range
        points = [p for p in (other.low, other.high) if p is not None]
        if not points:
            return None
        return all(self._contains(p) for p in points)

    def _contains(self, x: float) -> bool:
        eps = 1e-6
        if self.low is not None:
            if self.low_open and x <= self.low + eps:
                return False
            if not self.low_open and x < self.low - eps:
                return False
        if self.high is not None:
            if self.high_open and x >= self.high - eps:
                return False
            if not self.high_open and x > self.high + eps:
                return False
        return True

    def same_as(self, other: Condition) -> bool:
        return (self.kind, self.value, self._r(self.low), self._r(self.high),
                self.low_open, self.high_open) == (
            other.kind, other.value, other._r(other.low), other._r(other.high),
            other.low_open, other.high_open)

    @staticmethod
    def _r(x: float | None) -> float | None:
        return None if x is None else round(x, 4)


def _number(raw: str) -> float | None:
    raw = raw.strip().replace(",", ".")
    parts = re.split(r"[\s-]+", raw)
    total = 0.0
    try:
        for part in parts:
            if "/" in part:
                num, den = part.split("/", 1)
                total += float(num) / float(den)
            else:
                total += float(part)
    except (ValueError, ZeroDivisionError):
        return None
    return total


def _convert(kind: str, value: float, unit_text: str) -> float | None:
    if kind == "temperature":
        if re.fullmatch(_DEG_F, unit_text.strip(), re.I):
            return (value - 32) * 5 / 9
        return value
    for pattern, factor in _UNITS[kind]:
        if re.fullmatch(pattern, unit_text.strip(), re.I):
            return value * factor
    return None


#: After a bare size in a PASSAGE, the words that make it a nominal size (a
#: condition: "6 inch pipe") rather than a measured value ("a gap of 1/2 inch").
_NOMINAL_AFTER = re.compile(
    r"^\s*(?:nominal\s+)?(?:pipes?|piping|lines?|nozzles?|valves?|flanges?|branch(?:es)?"
    r"|fittings?|headers?|size|diameter|bore|nb)\b", re.I)


def _numeric(kind: str, text: str, question: bool) -> list[Condition]:
    """Ranges first, then points not already inside a range.

    A POINT IS A CONDITION ONLY IN A QUESTION. "5 mm" in a passage is the
    value the clause sets, not the case it applies to - reading it as a
    condition made every pair of clauses with different values look like
    different conditions. In a passage only a comparison or range ("larger
    than 2 inch", "above 60 °C") is a condition, plus a nominal pipe size
    ("6 inch pipe").
    """
    out: list[Condition] = []
    taken: list[tuple[int, int]] = []
    unit = "(" + "|".join(u for u, _ in _UNITS[kind]) + ")"

    def free(m: re.Match) -> bool:
        return all(m.end() <= a or m.start() >= b for a, b in taken)

    def add(m: re.Match, **kw) -> None:
        taken.append((m.start(), m.end()))
        out.append(Condition(kind, " ".join(m.group(0).split()), **kw))

    shapes = [
        # "between 2 and 6 inch"; "2 to 6 inch", "2 - 6 inch" ("and" only
        # after "between": "5 mm and 3 mm" is a list, not a range)
        (rf"between\s+{_NUM}\s*{unit}?\s*and\s*{_NUM}\s*{unit}", "range"),
        (rf"{_NUM}\s*{unit}?\s*(?:-|–|to|through)\s*{_NUM}\s*{unit}", "range"),
        # "larger than 2 inch", "above 60 °C"
        (rf"{_ABOVE}\s+(?:than\s+)?{_NUM}\s*{unit}", "above"),
        # "2 inch and larger"
        (rf"{_NUM}\s*{unit}\s+(?:and|or)\s+(?:larger|greater|bigger|above|over|more|higher)",
         "from"),
        # "2 inch and smaller"
        (rf"{_NUM}\s*{unit}\s+(?:and|or)\s+(?:smaller|less|below|under|lower)", "upto"),
        # "smaller than 2 inch", "up to 80 °C"
        (rf"{_BELOW}\s+(?:than\s+)?{_NUM}\s*{unit}", "below"),
        (rf"{_NUM}\s*{unit}", "point"),
    ]
    for pattern, shape in shapes:
        for m in re.finditer(pattern, text, re.I):
            if not free(m):
                continue
            g = [x for x in m.groups() if x is not None]
            if shape == "range":
                a, b = _number(m.group(1)), _number(m.group(3))
                u = m.group(4)
                lo, hi = _convert(kind, a, u) if a is not None else None, \
                    _convert(kind, b, u) if b is not None else None
                if lo is None or hi is None:
                    continue
                add(m, low=min(lo, hi), high=max(lo, hi))
                continue
            value, u = _number(g[0]), g[1]
            if value is None:
                continue
            v = _convert(kind, value, u)
            if v is None:
                continue
            if shape == "above":
                add(m, low=v, low_open=True)
            elif shape == "from":
                add(m, low=v)
            elif shape == "upto":
                add(m, high=v)
            elif shape == "below":
                strict = bool(re.search(r"smaller|less|lower|under|below", m.group(0), re.I)) \
                    and not re.search(r"up to|not exceeding|not more than|maximum", m.group(0), re.I)
                add(m, high=v, high_open=strict)
            elif question or (kind == "size" and _NOMINAL_AFTER.match(text[m.end():])
                              and re.fullmatch(_INCH, u.strip(), re.I)):
                add(m, low=v, high=v)
    return out


def extract(text: str, *, question: bool = False) -> list[Condition]:
    """Every condition this module can read in `text`, in no particular
    order. Duplicates (the same condition written twice) are kept once.
    `question=True` also reads bare points ("a 6 inch pipe", "at 90 °C") -
    see `_numeric` for why a passage's bare points are values instead."""
    text = text or ""
    found: list[Condition] = []
    for kind in ("size", "temperature", "pressure"):
        found.extend(_numeric(kind, text, question))
    for m in _NPS.finditer(text):
        v = _number(m.group(1))
        if v is not None:
            found.append(Condition("size", " ".join(m.group(0).split()), low=v, high=v))
    for m in _DN.finditer(text):
        # DN is nominal millimetres; NPS = DN / 25 by the standard pairing
        v = float(m.group(1)) / 25
        found.append(Condition("size", m.group(0), low=v, high=v))
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
