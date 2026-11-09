"""Reading the figures of a quote for the rule finishing line (step a): numbers with a unit of the unit table.

Numbers are `numparse`'s (whole fractions included), units are `claims`'. No second number reader. Pure functions.
"""

from __future__ import annotations

import dataclasses
import re

from . import claims, numparse

_LONE_UNIT = re.compile(r"\s+([A-Za-z])(?![A-Za-z0-9])")


_UNIT_AFTER = re.compile(r"\s*-?\s*([A-Za-z]+)")
_SLASH_FIGURE = re.compile(r"\d\s*[/\u2044]\s*\d+\s*-?\s*([A-Za-z]+)")


def fraction_spans(quote: str) -> list:
    """The whole fractions and mixed numbers of the quote (numparse reads them: "3/4", "1 1/2", "2-3/8")."""
    return numparse.find_fractions(quote)


def mask_fractions(quote: str) -> str:
    out = quote
    for f in sorted(fraction_spans(quote), key=lambda n: -n.start):
        out = out[: f.start] + " " * (f.end - f.start) + out[f.end :]
    return out


def fraction_figures(quote: str) -> list[claims.Measurement]:
    """A fraction followed by a unit of the table is a figure, read whole: "3/4 inch" is 0.75 inch, never 4 inch."""
    out = []
    for f in fraction_spans(quote):
        hit = _UNIT_AFTER.match(quote, f.end)
        if hit and claims.is_unit(hit.group(1)) and hit.group(1) != "a":
            m = claims.normalise(repr(f.value), hit.group(1))
            out.append(dataclasses.replace(m, raw_value=f.raw))
    return out


def fraction_ambiguous(quote: str) -> bool:
    """A d/d printed next to a unit that numparse does not read as one whole fraction (a date, a list, "12/25 mm"): the
    figure cannot be read with certainty, so nothing is proposed or passed."""
    return any(
        claims.is_unit(m.group(1))
        for m in _SLASH_FIGURE.finditer(mask_fractions(quote))
    )


def stands(value: float, quote: str) -> bool:
    """The number stands in the quote: as a number outside any fraction, or as the value of a whole fraction."""
    return numparse.value_in_text(value, mask_fractions(quote)) or any(
        f.value == float(value) for f in fraction_spans(quote)
    )


def figures(quote: str) -> tuple[claims.Measurement, ...]:
    """Numbers with a unit in the unit table: a bare number, a date or a part-number-like token is not a figure.

    A whole fraction ("3/4", "1 1/2") is read by `numparse.find_fractions` and masked before the rest is read, so its
    denominator is never taken for a figure. `claims.extract_measurements` reads the unit written after a number; it sets
    aside a lone letter that follows a space ("15 m"), because "3 a coat" is a word. Here such a letter is read as a unit
    when `claims.is_unit` knows it and it is not the word "a". The numbers are numparse's; the unit table is claims'."""
    fractions = fraction_figures(quote)
    quote = mask_fractions(quote)
    found = list(claims.extract_measurements(quote))
    have = {(numparse.as_limit(m.raw_value), m.raw_unit) for m in found}
    taken = {numparse.as_limit(m.raw_value) for m in found}
    for number in numparse.find_numbers(quote):
        if number.value is None or number.joined or number.value in taken:
            continue
        hit = _LONE_UNIT.match(quote, number.end)
        if (
            hit
            and hit.group(1) != "a"
            and claims.is_unit(hit.group(1))
            and (number.value, hit.group(1)) not in have
        ):
            found.append(
                claims.normalise(quote[number.start : number.end], hit.group(1))
            )
    return tuple(found + fractions)


def number_of(m: claims.Measurement) -> float | None:
    return numparse.as_limit(m.raw_value) if m.raw_value is not None else None


def unit_matches(rule_unit: str | None, m: claims.Measurement) -> bool:
    if not rule_unit or not m.raw_unit:
        return False
    return claims.same_unit(claims.Measurement("", rule_unit, None, None, None), m)
