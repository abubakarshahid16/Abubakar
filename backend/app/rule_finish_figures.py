"""Reading the numbers of a quote for the rule finishing line (step a). CODE VERIFIES NUMBERS AND QUOTES, NEVER MEANING.

There is no English in this module that decides anything: no comparator, no negation, no range shape, no unit word list.
What the figures MEAN (a limit or a range, its comparator) comes only from the engineer check. Here:

  * `figures`       the numbers that stand directly before a unit of the repo's unit table (`claims`), with where they stand;
  * `number_tokens` EVERY number token of the quote, fail closed: digits of any script (fullwidth, Arabic-Indic, a
                    superscript, a vulgar fraction, a CJK numeral), a number written as a word, a whole fraction, a compound
                    ("5.3.2"), an "e" notation, after the references the repo already strips (cited standards, clause,
                    section, para, page, table, figure, note). A token no stored figure accounts for is never "no figure".

Numbers are `numparse`'s, units are `claims`'. No second number reader. Pure functions; no database, no model.
"""

from __future__ import annotations

import dataclasses
import re
import unicodedata

from . import claims, numparse, standard_ids
from .converter_gates import fold

_LONE_UNIT = re.compile(r"\s+([A-Za-z])(?![A-Za-z0-9])")
_UNIT_AFTER = re.compile(r"\s*-?\s*([A-Za-z]+)")
#: Numbers written as words: a long closed list, plurals and ordinals included. A word-number the list lacks is still
#: safe where it stands next to a digit or a unit; only the engineer's accounting can clear the ones it holds.
_WORD_NUMBERS = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
    "hundred",
    "thousand",
    "million",
    "billion",
    "half",
    "quarter",
    "dozen",
    "single",
    "double",
    "triple",
    "pair",
    "couple",
]
_WORD_RE = re.compile(
    r"(?<![a-z])(?:" + "|".join(_WORD_NUMBERS) + r")(?:s|th|ths)?(?![a-z])"
)
_REFERENCE = re.compile(
    r"(?:\bclause|\bcl\.|\bpara(?:graph)?\.?|\bsection|\bsec\.|\bpage|\bp\.|§|\btable|\bfigure|\bfig\.|\bnote)\s*\d+(?:\.\d+)*[a-z]?"
)


@dataclasses.dataclass(frozen=True)
class Figure:
    value: float
    unit: str
    start: int
    end: int
    unit_end: int
    raw: str


def _is_unit_word(word: str) -> bool:
    return claims.is_unit(word) and word != "a"


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


def figures(text: str) -> tuple[Figure, ...]:
    """The numbers that stand directly before a unit of the unit table (a whole fraction included), left to right."""
    out = []
    for f in fraction_spans(text):
        hit = _UNIT_AFTER.match(text, f.end)
        if hit and _is_unit_word(hit.group(1)):
            out.append(Figure(f.value, hit.group(1), f.start, f.end, hit.end(), f.raw))
    masked = mask_fractions(text)
    cursor = 0
    for m in claims.extract_measurements(masked):
        at = _locate(masked, m.raw_value.lstrip("-+"), cursor)
        value = numparse.as_limit(m.raw_value)
        if at < 0 or value is None:
            continue
        cursor = at + len(m.raw_value.lstrip("-+"))
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
    for n in numparse.find_numbers(masked):
        hit = _LONE_UNIT.match(masked, n.end)
        if (
            n.value is not None
            and not n.joined
            and n.value not in taken
            and hit
            and _is_unit_word(hit.group(1))
        ):
            out.append(
                Figure(n.value, hit.group(1), n.digits_at, n.end, hit.end(), n.raw)
            )
    return tuple(sorted(out, key=lambda f: f.start))


def strip_references(text: str) -> str:
    """The quote folded, without what the repo already strips before it counts numbers (`ai_review_proposals`): the
    standards it cites and its clause, section, paragraph, page, table, figure and note references."""
    folded = fold(text)
    for name in standard_ids.cited_standards(text):
        piece = fold(name)
        if piece:
            folded = folded.replace(piece, " ")
    return _REFERENCE.sub(" ", folded)


def number_tokens(text: str) -> list[tuple[str, float | None]]:
    """(raw token, value or None) of every number in the quote, fail closed. A token with no value (a word, a non-ASCII
    digit, a compound) can only be accounted for by the engineer."""
    stripped = strip_references(text)
    out: list[tuple[str, float | None]] = [
        (f.raw, f.value) for f in fraction_spans(stripped)
    ]
    masked = mask_fractions(stripped)
    out += [(n.raw, n.value) for n in numparse.find_numbers(masked)]
    run = ""
    for ch in masked + " ":
        if ord(ch) > 127 and unicodedata.numeric(ch, None) is not None:
            run += ch
        elif run:
            out.append((run, None))
            run = ""
    out += [(m.group(0), None) for m in _WORD_RE.finditer(masked)]
    return out


def stands(value: float, text: str) -> bool:
    """The number stands in the text: as a number outside any fraction, or as the value of a whole fraction. A value of
    zero stands only where the text prints a zero."""
    if float(value) == 0.0:
        return any(
            n.value == 0.0 and re.fullmatch(r"0(?:[.,]0+)?", n.raw)
            for n in numparse.find_numbers(mask_fractions(text))
        )
    return numparse.value_in_text(value, mask_fractions(text)) or any(
        f.value == float(value) for f in fraction_spans(text)
    )


def same_unit(a: str | None, b: str | None) -> bool:
    """One unit by the repo's unit comparison; a difference of case only is no match (m and M)."""
    if not a or not b or (a != b and a.lower() == b.lower()):
        return False
    return claims.same_unit(
        claims.Measurement("", a, None, None, None),
        claims.Measurement("", b, None, None, None),
    )


def unit_matches(rule_unit: str | None, figure: Figure) -> bool:
    return same_unit(rule_unit, figure.unit)
