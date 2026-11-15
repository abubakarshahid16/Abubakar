"""A reference that states its own value is a plain limit (order 214).

"The set pressure shall not exceed the vessel MAWP of 12 barg" names a
reference (the MAWP) but also gives its number. Read as a comparison with
another field of the sheet, the 12 barg was dropped and the clause went to an
engineer ("MAWP is not stated on the datasheet"). It is a limit of 12 barg on
the set pressure. General: any "<comparator> <noun phrase> of <number> <unit>".

Left alone on purpose (the clause stays with an engineer, never a wrong Meets):
- a phrase that picks one of several values ("the lesser of 10 mm or 6 mm");
- a number just before the comparator ("10 % above", "2 bar below"): the limit
  is the stated value moved by that number, not the stated value;
- anything after the unit except the end of the sentence or a plain trailing
  clause ("minus 1 bar", "multiplied by 1.5", "by at least 10 %", "per 100 m",
  "at 40 C"): an allow-list, so a new wording cannot slip through;
- a unit the system cannot convert, and a reference with no number.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from functools import cache

from . import numparse


@cache
def _patterns() -> tuple[re.Pattern, ...]:
    """Built on first use: this module is imported by `requirements_3b`, whose
    vocabulary the patterns are made of."""
    from . import requirements_3b as r3b

    own_value = re.compile(
        r"(?P<cmp>"
        + r3b._CMP_RE
        + r")\s*(?:the\s+)?(?P<ref>[A-Za-z][A-Za-z0-9 \-/]{1,60}?)"
        r"\s+of\s+(?P<value>[-+]?" + r3b._VALUE + r")\s*(?P<unit>" + r3b._UNIT + r")"
        r"(?![\w/])(?!\s*(?:or|and|to)\s+\d)",
        re.IGNORECASE,
    )
    picks_one = re.compile(
        r"\b(?:greater|lesser|higher|lower|larger|smaller|sum|total|difference|"
        r"average|ratio|half|twice|double|times|multiple|percent)\b",
        re.IGNORECASE,
    )
    number_before = re.compile(r"\d\s*(?:%|[A-Za-z]{1,6})?\s*$")
    # a trailing clause may follow a comma, but it holds no digit and no word
    # that moves, scales or chooses the number
    moves_number = re.compile(
        r"\d|%|\b(?:minus|plus|less|more|multiplied|divided|times|per|by|above|below|"
        r"over|under|whichever|greater|lesser|exceed|than)\b",
        re.IGNORECASE,
    )
    return own_value, picks_one, number_before, moves_number


def _stands_alone(sentence: str, match: re.Match) -> bool:
    """True when nothing before the comparator or after the unit changes the
    stated number."""
    _, _, number_before, moves_number = _patterns()
    if number_before.search(sentence[: match.start("cmp")]):
        return False
    tail = sentence[match.end() :]
    if re.match(r"\s*(?:[.;]|$)", tail):
        return True
    clause = re.match(r"\s*,([^.;]*)", tail)
    return clause is not None and not moves_number.search(clause.group(1))


def parse(sentence: str) -> dict | None:
    """The limit the sentence states through a reference, or None."""
    from . import requirements_3b as r3b

    own_value, picks_one, _, _ = _patterns()
    match = own_value.search(sentence or "")
    if match is None or picks_one.search(match.group("ref")):
        return None
    if not _stands_alone(sentence, match):
        return None
    operator = r3b._OPERATOR.get(r3b._canonical_comparator(match.group("cmp")))
    raw_unit = r3b.unit_token(match.group("unit"))
    measurement = (
        r3b.measure(match.group("value"), raw_unit) if operator and raw_unit else None
    )
    if measurement is None or measurement.normalized_unit is None:
        return None
    return {
        "operator": operator,
        "raw_value": match.group("value"),
        "raw_unit": raw_unit,
        "value": measurement.normalized_value,
        "unit": measurement.normalized_unit,
    }


@cache
def _subject_be_pattern() -> re.Pattern:
    from . import requirements_3b as r3b

    return re.compile(
        r"(?<![A-Za-z])(?P<cmp>maximum|minimum|max|min)\s+(?P<ref>[A-Za-z][A-Za-z0-9 .\-/]{1,60}?)"
        r"\s+(?:shall|must|should|will|is|are)\s+be\s+(?P<value>[-+]?"
        + r3b._VALUE
        + r")\s*(?P<unit>"
        + r3b._UNIT
        + r")"
        r"(?![\w/])(?!\s*(?:or|and|to)\s+\d)",
        re.IGNORECASE,
    )


@cache
def _role_rules() -> dict:
    from . import datasheet_checks

    return datasheet_checks.load_rules()


_ALT_UNITS = re.compile(
    r"\s*\(\s*(?P<value>[\d][\d/. ]*)\s*(?P<unit>[A-Za-z\"\u201d\u2033']{1,6})\s*\)"
)


def _alternative_agrees(tail: str, main) -> str | None:
    """The text after a stated value when it only repeats the value in another unit ("(1/8 in)") and the repeat converts to the same figure, the tail
    with it removed; the tail unchanged when there is none; None when a bracket states something else."""
    from . import requirements_3b as r3b

    found = _ALT_UNITS.match(tail)
    if found is None:
        return tail if not re.match(r"\s*\(", tail) else None
    unit = found.group("unit").replace("\u201d", '"').replace("\u2033", '"')
    unit = {'"': "in", "'": "ft"}.get(unit, unit)
    value = found.group("value").strip()
    if "/" in value:
        try:
            num, den = value.split("/")
            value = str(float(num) / float(den))
        except (ValueError, ZeroDivisionError):
            return None
    other = r3b.measure(value, r3b.unit_token(unit))
    if other.normalized_value is None or other.normalized_unit != main.normalized_unit:
        return None
    if abs(other.normalized_value - main.normalized_value) > 0.02 * abs(
        main.normalized_value
    ):
        return None  # 1/16 in is 1.59 mm: a repeat of 1.6 mm (rounded), a different figure is not
    return tail[found.end() :]


#: words that make a subject MORE than a field's name: a preposition (another component or scope follows), a conjunction (two subjects), a condition, a second comparator
SUBJECT_STOP = frozenset(
    "of for at per on in by to with without from under over during between within inside outside into through across as than after before while when where "
    "if unless except and or nor not each every all any both either neither only other maximum minimum max min".split()
)
ARTICLES = frozenset({"the", "a", "an"})
MAX_SUBJECT_WORDS = 4


def subject_tokens(ref: str) -> list[str] | None:
    """The words of the subject between the comparator word and "shall be", folded (a dotted abbreviation "C.A." is the words "c", "a"), articles dropped; None
    when the subject is not a plain name: it holds a word of `SUBJECT_STOP` (another component or scope, two subjects, a condition, a second comparator word),
    a figure, or more than four words. ONE function: the parser, the subject check and the exit all ask it, so the three cannot disagree."""
    tokens = [
        t
        for w in str(ref or "").lower().split()
        if w not in ARTICLES
        for t in re.findall(r"[a-z0-9]+", w)
    ]  # an article is a whole word ("c.a." keeps its "a")
    if (
        not tokens
        or len(tokens) > MAX_SUBJECT_WORDS
        or any(t in SUBJECT_STOP or t.isdigit() for t in tokens)
    ):
        return None
    return tokens


def subject_ref(sentence: str) -> tuple[str, str] | None:
    """(comparator word, subject text) of the shape in the sentence, whether or not the subject is a plain name; None when the sentence is not of the shape."""
    match = _subject_be_pattern().search(sentence or "")
    return None if match is None else (match.group("cmp"), match.group("ref"))


def subject_be(sentence: str) -> dict | None:
    """ "The maximum <subject> shall be <value> <unit>" is a limit of that value on the subject (`<=`; "minimum" gives `>=`), the comparator being the
    clause's own word in front of the subject and the value coming after "shall be".

    Left alone (the clause stays a statement for an engineer): "maximum <subject>" that is itself the name of a registered field ("the maximum allowable
    working pressure shall be 12 barg" states that field's value, it does not limit anything); "shall not be"; a choice of values ("3 mm or 5 mm"); a
    number before the comparator; a bracket that is not the same figure in another unit; a phrase that moves, scales or chooses the number; a unit the
    system cannot convert."""
    from . import datasheet_roles
    from . import requirements_3b as r3b

    match = _subject_be_pattern().search(sentence or "")
    if match is None:
        return None
    if subject_tokens(match.group("ref")) is None:
        return None  # a limit on another component or scope ("of the skirt", "for nozzles", "per side"), two subjects, a condition: a statement for an engineer
    _, picks_one, number_before, moves_number = _patterns()
    before = re.sub(
        r"^\s*\d{1,3}(?:\.\d{1,3})+\.?\s+", "", sentence[: match.start("cmp")]
    )  # a clause number in front is not a figure
    alternative = re.search(
        r"\d[\d./]*\s*[A-Za-z%\u00b0\"]{0,8}\s*\)?\s*,?\s*(?:or|and)\s+(?:the\s+)?$",
        before,
        re.IGNORECASE,
    )  # "(5 mm), or the minimum ... 0.154 in": two thresholds
    if re.search(
        r"\b(?:for|unless|where|if|when|except|provided|in\s+case)\b",
        before,
        re.IGNORECASE,
    ):
        return None  # a clause that opens with a condition ("For carbon steel, ...", "Where ...") holds its limit to that condition: a statement for an engineer
    if (
        picks_one.search(match.group("ref"))
        or number_before.search(before)
        or alternative
    ):
        return None
    if datasheet_roles.roles_of(
        f"{match.group('cmp')} {match.group('ref')}", _role_rules()
    ):
        return (
            None  # "maximum allowable working pressure" is a field, not a limit on one
        )
    operator = r3b._OPERATOR.get(r3b._canonical_comparator(match.group("cmp")))
    raw_unit = r3b.unit_token(match.group("unit"))
    measurement = (
        r3b.measure(match.group("value"), raw_unit) if operator and raw_unit else None
    )
    if measurement is None or measurement.normalized_unit is None:
        return None
    tail = _alternative_agrees(sentence[match.end() :], measurement)
    if tail is None:
        return None
    clause = re.match(r"\s*,([^.;]*)", tail)
    if not (
        re.match(r"\s*(?:[.;]|$)", tail)
        or (clause is not None and not moves_number.search(clause.group(1)))
    ):
        return None
    return {
        "operator": operator,
        "raw_value": match.group("value"),
        "raw_unit": raw_unit,
        "value": measurement.normalized_value,
        "unit": measurement.normalized_unit,
    }


@cache
def _trailing_pattern() -> re.Pattern:
    from . import requirements_3b as r3b

    return re.compile(
        r"(?P<value>[-+]?" + r3b._VALUE + r")\s*(?P<unit>" + r3b._UNIT + r")"
        r"\s+(?P<cmp>or\s+[A-Za-z]+)\b",
        re.IGNORECASE,
    )


def _trailing_candidates(sentence: str) -> Iterator[tuple[re.Match, str, str]]:
    """Every "<number> <unit> or <comparator>" in the sentence, with its direction and
    unit. The direction is the shared vocabulary's (`comparators`)."""
    from . import comparators
    from . import requirements_3b as r3b

    for match in _trailing_pattern().finditer(sentence or ""):
        direction = comparators.direction_of(match.group(0))
        raw_unit = r3b.unit_token(match.group("unit"))
        if direction is not None and raw_unit:
            yield match, direction, raw_unit


def trailing_refused(sentence: str) -> bool:
    """A trailing limit in the sentence starts where no value may ("A-5 mm or less", "3-5 C
    or lower"). The text cannot say what it is, so NO limit of this sentence can be trusted:
    not a later value, and not a general limit whose exception it is. It goes to an engineer
    (#1619).

    "10-12 mm or larger" is refused too. The hyphen is no minus, so main's -12 was wrong, but it
    could be a size range or a tag, and no general rule tells it from "Item 3-15 C or lower". As
    a range no single bound is stated: 11 mm passes from 10 and fails from 12.

    A dash kept apart from its digits, and a sign `_LIMIT` cannot read after a comparator, are
    refused the same way (#1640: `_dash_apart`, `_unclear_after_comparator`)."""
    starts = [found[0].start() for found in _trailing_candidates(sentence)]
    if any(not numparse.value_may_start(sentence, start) for start in starts):
        return True
    return (
        _dash_apart(sentence, starts)
        or _unclear_after_comparator().search(sentence or "") is not None
    )


def _dash_apart(sentence: str, starts: list[int]) -> bool:
    """A trailing limit's digits follow a dash that space, a bracket or a colon keeps apart from them
    ("Zone 2 - 29 C or lower", "A- 29", "A-(29", "A-:29"). The dash is no sign, so the regex reads
    29, but it may be a minus, a range or a tag: the text cannot say (#1640). A sign written on the
    digits ("-20 - -10 C or lower") is the value's own and stays."""
    for start in starts:
        before = sentence[:start].rstrip(" \t([{:")
        if sentence[start] not in "+-" and before and before[-1] in numparse.DASH_LIKE:
            return True
    return False


@cache
def _unclear_after_comparator() -> re.Pattern:
    """A comparator whose number `_LIMIT` cannot read: after a Unicode minus, a dash, a hyphen kept
    apart from its digits, a bracket or a colon ("shall not exceed - 29 C", "max \u221229 C",
    "shall not exceed (29 C"). `_LIMIT` then skips this comparator and can read a later one
    ("minimum 5 C"), so NO limit of the sentence is trusted (#1640)."""
    from . import requirements_3b as r3b

    dashes = re.escape(numparse.DASH_LIKE)
    return re.compile(
        r"(?<![A-Za-z])(?:" + r3b._CMP_RE + r")(?>\s*(?:of\s+)?)(?![-+]?\d)"
        r"[\s(\[{:]*(?:[" + dashes + r"][\s(\[{:]*)?\d",
        re.IGNORECASE,
    )


def trailing(sentence: str) -> dict | None:
    """A comparator that FOLLOWS the value: "3 m or less", "5 mm or more". `_LIMIT`
    reads only one in front of the number."""
    from . import requirements_3b as r3b

    found = next(_trailing_candidates(sentence), None)
    if found is None or trailing_refused(sentence):
        return None
    match, direction, raw_unit = found
    raw_value = match.group("value")
    measurement = r3b.measure(raw_value, raw_unit)
    return {
        "operator": direction,
        "raw_value": raw_value,
        "raw_unit": raw_unit,
        "value": measurement.normalized_value,
        "unit": measurement.normalized_unit,
    }
