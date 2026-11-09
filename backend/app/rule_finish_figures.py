"""Reading the figures of a quote for the rule finishing line (step a): numbers with a unit of the unit table.

Numbers are `numparse`'s (whole fractions, mixed numbers, grouped thousands, vulgar-fraction characters through their
compatibility form), units are `claims`'. No second number reader. A quote whose figure cannot be read with certainty
(a slash figure numparse does not read whole, a unit followed by a second unit word, an unreadable digit group) gives
`Reading.incomplete`, never a guessed figure. Each figure carries the comparator its OWN governing phrase gives.
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
    r"\s*(?:/\s*[a-z]|per\s+[a-z]|(?:hg|h\s?2\s?o|w\.?\s?[cg]\.?|wc|wg)(?![a-z]))"
)
_RANGE_GAP = re.compile(r"\s*(?:to|and|[-–—])\s*")
_RANGE_JOIN = re.compile(r"\s*(?:to|[-–—])\s*")
_RANGE_OPEN = re.compile(r"(?:between|from)\s*$")
_BREAK = re.compile(r"[.;:]\s")

#: Polarity phrases, longest first, so "not less than" is one phrase and never "less than".
_POLARITY = (
    ("greater than or equal to", ">="),
    ("less than or equal to", "<="),
    ("not to exceed", "<="),
    ("shall not exceed", "<="),
    ("not less than", ">="),
    ("no less than", ">="),
    ("not more than", "<="),
    ("no more than", "<="),
    ("not greater than", "<="),
    ("at least", ">="),
    ("at most", "<="),
    ("minimum", ">="),
    ("maximum", "<="),
    ("exactly", "="),
    ("equal to", "="),
    ("equals", "="),
    ("more than", ">"),
    ("greater than", ">"),
    ("exceeding", ">"),
    ("less than", "<"),
    ("smaller than", "<"),
    ("up to", "<="),
    (">=", ">="),
    ("<=", "<="),
    ("≥", ">="),
    ("≤", "<="),
    ("min.", ">="),
    ("max.", "<="),
    ("min", ">="),
    ("max", "<="),
)
_POLARITY_RE = re.compile(
    "|".join(
        r"(?<![a-z])" + re.escape(p) + (r"(?![a-z])" if p[-1].isalpha() else "")
        for p, _ in _POLARITY
    ),
    re.IGNORECASE,
)
_SYMBOL = dict(_POLARITY)


@dataclasses.dataclass(frozen=True)
class Figure:
    value: float
    unit: str
    start: int
    end: int
    unit_end: int
    raw: str
    comparator: str | None = None
    comparator_source: str | None = None


@dataclasses.dataclass(frozen=True)
class Reading:
    text: str
    figures: tuple[Figure, ...]
    incomplete: str | None = None


def _is_unit_word(word: str) -> bool:
    return claims.is_unit(word) and word != "a"


def normalise(quote: str) -> tuple[str, str | None]:
    """The quote with vulgar-fraction characters spelled as numparse reads a fraction ("1 1 half") and digit groups
    ("1 000") as the number numparse.parse_value reads; and the reason when one cannot be read."""
    out, problem, vulgar = [], None, 0
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
            and len(numbers[j + 1].raw) == 3
            and _DIGITS.fullmatch(numbers[j + 1].raw)
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


def _governing(text: str, figure: Figure, before: int) -> tuple[str | None, str | None]:
    """The comparator the phrase just before this figure gives: nearest polarity words after the previous figure and the
    last sentence break; two different polarities in that stretch, or none, is no comparator."""
    window = text[before : figure.start]
    cut = list(_BREAK.finditer(window))
    window = window[cut[-1].end() :] if cut else window
    symbols = [_SYMBOL[m.group(0).lower()] for m in _POLARITY_RE.finditer(window)]
    if len(set(symbols)) == 1:
        return symbols[0], "governing_phrase"
    return None, ("conflicting_phrases" if symbols else None)


def _with_ranges(text: str, figures: list[Figure]) -> list[Figure]:
    """ "between 10 and 40 C", "from 10 to 40 C", "10-40 C": two figures, >= the low end and <= the high end."""
    out: list[Figure] = []
    numbers = numparse.find_numbers(text)
    for fig in figures:
        before = out[-1].unit_end if out else 0
        low = None
        prev = out[-1] if out else None
        if (
            prev is not None
            and prev.unit == fig.unit
            and _RANGE_JOIN.fullmatch(text[prev.unit_end : fig.start])
        ):
            low = prev
        else:
            lead = [
                n
                for n in numbers
                if n.value is not None and n.end <= fig.start and n.start >= before
            ]
            if (
                lead
                and _RANGE_GAP.fullmatch(text[lead[-1].end : fig.start])
                and _RANGE_OPEN.search(text[before : lead[-1].start])
            ):
                n = lead[-1]
                low = Figure(n.value, fig.unit, n.digits_at, n.end, n.end, n.raw)
        if low is not None:
            if out and out[-1] is low:
                out.pop()
            out += [
                dataclasses.replace(
                    low, comparator=">=", comparator_source="range_low"
                ),
                dataclasses.replace(
                    fig, comparator="<=", comparator_source="range_high"
                ),
            ]
            continue
        comparator, source = _governing(text, fig, before)
        out.append(
            dataclasses.replace(fig, comparator=comparator, comparator_source=source)
        )
    return out


def read(quote: str) -> Reading:
    """The figures of the quote, each with its own comparator, or the reason it cannot be read with certainty."""
    text, problem = normalise(quote)
    if fraction_ambiguous(text):
        return Reading(text, (), "figure_ambiguous")
    figures = _raw_figures(text)
    if any(
        _COMPOUND.match(text[f.unit_end :].lower()) and "/" not in f.unit
        for f in figures
    ):
        return Reading(text, tuple(figures), "compound_unit")
    return Reading(text, tuple(_with_ranges(text, figures)), problem)


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
    if not rule_unit or not figure.unit:
        return False
    return claims.same_unit(
        claims.Measurement("", rule_unit, None, None, None),
        claims.Measurement("", figure.unit, None, None, None),
    )


def implied_comparator(quote: str, value: float, unit: str | None) -> str | None:
    """The comparator this quote gives the figure `value unit` by its own governing phrase, or None (unreadable, absent,
    conflicting between two printings of the same figure)."""
    found = {
        f.comparator
        for f in figures(quote)
        if f.value == float(value) and (unit is None or unit_matches(unit, f))
    }
    return found.pop() if len(found) == 1 else None
