"""Reading the figures of a quote for the rule finishing line (step a): numbers with a unit of the unit table.

Numbers are `numparse`'s (whole fractions, mixed numbers, grouped thousands, vulgar-fraction characters through their
compatibility form), units are `claims`'. No second number reader. CODE READS ONLY WHAT IT CAN READ ROBUSTLY: a quote
whose figure or unit cannot be read with certainty (an unknown unit, a compound unit, a unit printed in a case that
changes its meaning, a slash figure numparse does not read whole, an unreadable digit group) gives `Reading.incomplete`.
The comparator is decided here in ONE shape only (`shape == "simple"`: one unit figure, one table phrase directly
governing it, nothing else polar or numeric in the quote) or for the closed range forms; in every other shape the
meaning is the engineer's (`shape == "complex"`). No inheritance of a phrase from one figure to another.
Pure functions; no database, no model.
"""

# ruff: noqa: RUF001  (the fraction slash, no-break and thin spaces and en dashes are the point of this module)
from __future__ import annotations

import dataclasses
import re
import unicodedata

from . import claims, numparse

_LONE_UNIT = re.compile(r"\s+([A-Za-z])(?![A-Za-z0-9])")
_UNIT_AFTER = re.compile(r"\s*-?\s*([A-Za-z]+)")
_SLASH_FIGURE = re.compile(r"\d\s*[/⁄]\s*\d+\s*-?\s*([A-Za-z]+)")
_GROUP_SEPARATORS = "    "
_DIGITS = re.compile(r"\d+")
#: a unit followed by a second unit word or a "per"/"/" part that the unit table does not read as one unit
_COMPOUND = re.compile(
    r"\s*\.?\s*(?:/\s*[a-z]|per\s+[a-z]|(?:hg|h\s?2\s?o|w\.?\s?[cg]\.?|wc|wg|water|mercury)(?![a-z]))"
)

#: The CLOSED polarity table: every phrase that may give a figure a comparator, negated forms included. Anything else
#: that carries a negation word is not read (no comparator, so step a is incomplete and a proposal is refused).
POLARITY_TABLE: dict[str, tuple[str, ...]] = {
    ">=": (
        "at least",
        "minimum",
        "min.",
        "min",
        "not less than",
        "no less than",
        "not smaller than",
        "not lower than",
        "not fewer than",
        "shall not be less than",
        "shall not be smaller than",
        "shall not be lower than",
        "greater than or equal to",
        ">=",
        "≥",
    ),
    "<=": (
        "at most",
        "maximum",
        "max.",
        "max",
        "not more than",
        "no more than",
        "not greater than",
        "no greater than",
        "not higher than",
        "no higher than",
        "not exceeding",
        "shall not exceed",
        "not to exceed",
        "shall not be more than",
        "shall not be greater than",
        "shall not be higher than",
        "nor more than",
        "nor greater than",
        "nor exceeding",
        "up to",
        "less than or equal to",
        "<=",
        "≤",
    ),
    "=": ("exactly", "equal to", "equals"),
    ">": ("more than", "greater than", "exceeding", "higher than"),
    "<": ("less than", "smaller than", "lower than", "fewer than"),
}
_SYMBOL = {phrase: sym for sym, phrases in POLARITY_TABLE.items() for phrase in phrases}
_POLARITY_RE = re.compile(
    "|".join(
        r"(?<![a-z])" + re.escape(p) + (r"(?![a-z])" if p[-1].isalpha() else "")
        for p in sorted(_SYMBOL, key=len, reverse=True)
    ),
    re.IGNORECASE,
)
_NEGATION = re.compile(
    r"(?<![a-z])(?:not|no|nor|neither|never|without|cannot|n't)(?![a-z])", re.IGNORECASE
)
#: What may follow a figure's unit directly and give it its comparator.
_TRAILING_PHRASES = {
    "minimum": ">=",
    "or more": ">=",
    "maximum": "<=",
    "or less": "<=",
    "or below": "<=",
    "or lower": "<=",
    "or fewer": "<=",
    "at the most": "<=",
}
_TRAILING = re.compile(
    r"\s+("
    + "|".join(sorted(map(re.escape, _TRAILING_PHRASES), key=len, reverse=True))
    + r")(?![a-z])",
    re.IGNORECASE,
)
_RANGE_FORM = re.compile(r"(?:(between)\s+)?$", re.IGNORECASE)
_FROM_FORM = re.compile(r"(?:from\s+)?$", re.IGNORECASE)
_UNIT_SHAPED = re.compile(r"\s?([A-Za-z°º\"'%µ][A-Za-z0-9°º/%.\-\"']{0,11})")
#: Words of up to four letters that follow a number without being a unit.
_FUNCTION_WORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "to",
        "or",
        "and",
        "in",
        "is",
        "as",
        "at",
        "on",
        "by",
        "for",
        "if",
        "it",
        "be",
        "no",
        "not",
        "we",
        "are",
        "per",
        "than",
        "with",
        "from",
        "that",
        "this",
        "each",
        "any",
        "all",
        "but",
        "may",
        "can",
        "has",
        "was",
        "will",
        "must",
        "off",
        "out",
        "via",
        "its",
        "into",
        "then",
        "when",
        "also",
        "only",
        "both",
        "such",
        "same",
    ]
)
#: Units printed with a capital that mean what they say; any other capital in a unit is ambiguous (MM, Mm, M, S, G).
SAFE_CASE_UNITS = frozenset(
    [
        "C",
        "F",
        "K",
        "°C",
        "°F",
        "Pa",
        "kPa",
        "MPa",
        "GPa",
        "N",
        "kN",
        "MN",
        "W",
        "kW",
        "MW",
        "V",
        "kV",
        "A",
        "kA",
        "Hz",
        "kHz",
        "MHz",
        "GHz",
        "L",
        "kPag",
        "MPag",
        "kPaa",
        "MPaa",
        "J",
        "kJ",
        "MJ",
        "Wh",
        "kWh",
        "MWh",
        "dB",
        "dBA",
        "dB(A)",
        "Btu",
        "BTU",
        "Nm",
        "kNm",
    ]
)
#: Units whose letter case changes the meaning (milli/mega, siemens/second, ...): a case that is not exactly the rule's
#: is not the same unit, and a figure printed so is not read.
CASE_AMBIGUOUS = frozenset(numparse.CASE_KEPT_UNITS) | frozenset("MSGHTP")


@dataclasses.dataclass(frozen=True)
class Figure:
    value: float
    unit: str
    start: int
    end: int
    unit_end: int
    raw: str


@dataclasses.dataclass(frozen=True)
class Reading:
    text: str
    figures: tuple[Figure, ...]
    incomplete: str | None = None
    #: "none" (no figure), "simple" (comparator decided: `comparator`), "range" (closed form: low and high end) or "complex"
    shape: str = "none"
    comparator: str | None = None


def _is_unit_word(word: str) -> bool:
    return claims.is_unit(word) and word != "a"


def normalise(quote: str) -> tuple[str, str | None]:
    """The quote with vulgar-fraction characters spelled as numparse reads a fraction ("1 1 half") and digit groups
    ("1 000") as the number numparse.parse_value reads; and the reason when one cannot be read."""
    out, problem, vulgar = [], None, 0
    quote = re.sub(
        r"(?<![a-z])(?:minus|negative)\s+(?=\d)", "-", quote, flags=re.IGNORECASE
    )
    quote = re.sub(
        r"(?<=\d)\s*(?:per\s?cent|percent)(?![a-z])", "%", quote, flags=re.IGNORECASE
    )
    for ch in quote:
        if unicodedata.name(ch, "").startswith("VULGAR FRACTION"):
            vulgar += 1
            out.append(
                (" " if out and out[-1].isdigit() else "")
                + unicodedata.normalize("NFKD", ch)
            )
        else:
            out.append(ch)
    text = "".join(out)
    if vulgar and len(numparse.find_fractions(text)) < vulgar:
        problem = "fraction_character_unreadable"
    numbers = numparse.find_numbers(text)
    spans, i = [], 0
    while i < len(numbers):
        j = i
        while (
            j + 1 < len(numbers)
            and _DIGITS.fullmatch(numbers[j].raw)
            and re.fullmatch(r"\d{3}(?:[.,]\d+)*", numbers[j + 1].raw)
            and text[numbers[j].end : numbers[j + 1].start] in tuple(_GROUP_SEPARATORS)
            and (j > i or len(numbers[j].raw) <= 3)
        ):
            j += 1
        if j > i:
            spans.append((numbers[i].start, numbers[j].end))
        i = j + 1
    for start, end in reversed(spans):
        value = numparse.parse_value(text[start:end])
        if value is None:
            problem = problem or "grouped_number_unreadable"
            continue
        text = (
            text[:start]
            + (str(int(value)) if value == int(value) else repr(value))
            + text[end:]
        )
    return text, problem


def fraction_spans(text: str) -> list:
    """The whole fractions and mixed numbers of the text (numparse reads them: "3/4", "1 1/2", "2-3/8")."""
    return numparse.find_fractions(text)


def mask_fractions(text: str) -> str:
    out = text
    for f in sorted(fraction_spans(text), key=lambda n: -n.start):
        out = out[: f.start] + " " * (f.end - f.start) + out[f.end :]
    return out


def _unit_end(text: str, end: int, unit: str) -> int:
    hit = re.compile(r"[\s-]*" + re.escape(unit), re.IGNORECASE).match(text, end)
    return hit.end() if hit else end


def _locate(text: str, raw: str, cursor: int) -> int:
    hit = re.compile(r"(?<![\d.,])" + re.escape(raw) + r"(?!\d)").search(text, cursor)
    return hit.start() if hit else text.find(raw, cursor)


def _raw_figures(text: str) -> list[Figure]:
    out = []
    for f in fraction_spans(text):
        hit = _UNIT_AFTER.match(text, f.end)
        if hit and _is_unit_word(hit.group(1)):
            out.append(Figure(f.value, hit.group(1), f.start, f.end, hit.end(), f.raw))
    masked = mask_fractions(text)
    found = list(claims.extract_measurements(masked))
    cursor = 0
    for m in found:
        at = _locate(masked, m.raw_value.lstrip("-+"), cursor)
        if at < 0:
            continue
        cursor = at + len(m.raw_value.lstrip("-+"))
        value = numparse.as_limit(m.raw_value)
        if value is not None:
            out.append(
                Figure(
                    value,
                    m.raw_unit,
                    at,
                    cursor,
                    _unit_end(masked, cursor, m.raw_unit),
                    m.raw_value,
                )
            )
    taken = {f.value for f in out}
    have = {(f.value, f.unit) for f in out}
    for n in numparse.find_numbers(masked):
        if n.value is None or n.joined or n.value in taken:
            continue
        hit = _LONE_UNIT.match(masked, n.end)
        if hit and _is_unit_word(hit.group(1)) and (n.value, hit.group(1)) not in have:
            out.append(
                Figure(n.value, hit.group(1), n.digits_at, n.end, hit.end(), n.raw)
            )
    return sorted(out, key=lambda f: f.start)


def fraction_ambiguous(text: str) -> bool:
    """A d/d printed next to a unit that numparse does not read as one whole fraction (a date, a list, "1/2/3 mm")."""
    return any(
        _is_unit_word(m.group(1)) for m in _SLASH_FIGURE.finditer(mask_fractions(text))
    )


def _covered(n, figures: list[Figure]) -> bool:
    return any(
        f.start <= n.start < f.end or f.start <= n.digits_at < f.end for f in figures
    )


_IN_COMPOUND = re.compile(
    r"\d\s*in\.?\s+(?:wc|w\.\s?c\.|h\s?2\s?o|hg|wg)(?![a-z])", re.IGNORECASE
)


def _unknown_unit(text: str, figures: list[Figure]) -> bool:
    """A number that is no figure but is followed by a token shaped like a unit (a symbol, a slash, a short word that is no
    function word): an unknown, compound or oddly printed unit, never "no figure"."""
    masked = mask_fractions(text)
    if _IN_COMPOUND.search(masked):
        return True
    for n in numparse.find_numbers(masked):
        if n.value is None or n.joined or _covered(n, figures):
            continue
        hit = _UNIT_SHAPED.match(masked, n.end)
        if not hit:
            continue
        token = hit.group(1).rstrip(".,;:)").lower()
        if token in _FUNCTION_WORDS or not token:
            continue
        if len(token) <= 4 or "/" in token or not token[0].isalpha():
            return True
    return False


def _phrases_of(
    text: str, start: int, unit_end: int
) -> tuple[list[tuple[int, int, str]], str]:
    """The table phrases that sit directly before the figure and directly after its unit, and the text without them."""
    found = []
    lead = text[:start]
    hit = None
    for m in _POLARITY_RE.finditer(lead):
        if not lead[m.end() :].strip():
            hit = m
    if hit:
        found.append((hit.start(), hit.end(), _SYMBOL[hit.group(0).lower()]))
    trail = _TRAILING.match(text, unit_end)
    if trail:
        found.append(
            (trail.start(1), trail.end(1), _TRAILING_PHRASES[trail.group(1).lower()])
        )
    rest = text
    for a, b, _ in sorted(found, reverse=True):
        rest = rest[:a] + " " + rest[b:]
    return found, rest


def _closed_range(text: str, figures: list[Figure]):
    """ "between X and Y UNIT", "from X to Y UNIT", "X to Y UNIT": the unit once, at the end, and nothing else numeric.
    Returns the (low, high) figures or None."""
    high = figures[0]
    numbers = [
        n for n in numparse.find_numbers(text) if n.value is not None and not n.joined
    ]
    if (
        len(numbers) != 2
        or numbers[1].start > high.start
        or numbers[1].end <= high.start
    ):
        return None
    low, end = numbers
    gap = text[low.end : end.start].strip().lower()
    before = text[: low.start].lower()
    if (gap == "and" and re.search(r"between\s*$", before)) or (
        gap == "to" and not re.search(r"(?:between|and|to)\s*$", before)
    ):
        return Figure(low.value, high.unit, low.start, low.end, low.end, low.raw), high
    return None


def read(quote: str) -> Reading:
    """The figures of the quote and how far code can read their comparator, or why it cannot read them at all."""
    text, problem = normalise(quote)
    if fraction_ambiguous(text):
        return Reading(text, (), "figure_ambiguous")
    figures = _raw_figures(text)
    if any(
        n.value is None
        and (hit := _UNIT_AFTER.match(text, n.end))
        and _is_unit_word(hit.group(1))
        for n in numparse.find_numbers(mask_fractions(text))
    ):
        return Reading(text, tuple(figures), "number_unreadable")
    if any(f.unit != f.unit.lower() and f.unit not in SAFE_CASE_UNITS for f in figures):
        return Reading(text, tuple(figures), "unit_case_ambiguous")
    if any(
        _COMPOUND.match(text[f.unit_end :].lower()) and "/" not in f.unit
        for f in figures
    ):
        return Reading(text, tuple(figures), "compound_unit")
    if _unknown_unit(text, figures):
        return Reading(text, tuple(figures), "unit_not_in_table")
    if problem:
        return Reading(text, tuple(figures), problem)
    if not figures:
        return Reading(text, (), None, "none")
    ends = _closed_range(text, figures)
    if ends:
        return Reading(text, ends, None, "range")
    others = [
        n
        for n in numparse.find_numbers(mask_fractions(text))
        if n.value is not None and not _covered(n, figures)
    ]
    if len(figures) == 1 and not others:
        found, rest = _phrases_of(text, figures[0].start, figures[0].unit_end)
        if len(found) == 1 and not (
            _POLARITY_RE.search(rest)
            or _NEGATION.search(rest)
            or _TRAILING.search(rest)
        ):
            return Reading(text, tuple(figures), None, "simple", found[0][2])
    return Reading(text, tuple(figures), None, "complex")


def figures(quote: str) -> tuple[Figure, ...]:
    return read(quote).figures


def stands(value: float, text: str) -> bool:
    """The number stands in the (normalised) text: as a number outside any fraction, or as the value of a whole fraction.
    A value of zero stands only where the text prints a zero."""
    if float(value) == 0.0:
        return any(
            n.value == 0.0 and re.fullmatch(r"0(?:[.,]0+)?", n.raw)
            for n in numparse.find_numbers(mask_fractions(text))
        )
    return numparse.value_in_text(value, mask_fractions(text)) or any(
        f.value == float(value) for f in fraction_spans(text)
    )


def unit_matches(rule_unit: str | None, figure: Figure) -> bool:
    """The rule's unit is the figure's, by the repo's unit comparison; a difference of case only is no match."""
    if (
        not rule_unit
        or not figure.unit
        or (rule_unit != figure.unit and rule_unit.lower() == figure.unit.lower())
    ):
        return False
    return claims.same_unit(
        claims.Measurement("", rule_unit, None, None, None),
        claims.Measurement("", figure.unit, None, None, None),
    )
