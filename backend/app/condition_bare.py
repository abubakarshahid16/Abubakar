"""A numeric condition whose threshold states NO unit ("specific gravity below 0.5").

Order 264b, row 340: a clause that applies only where the specific gravity is below 0.5, and a sheet
that states 0.974, was held as an unexplained unit mismatch. A quantity that is dimensionless BY
NATURE (a ratio, an efficiency, a count: `reference/dimensionless_quantities.json`) is compared with
a submitted number that has no unit and whose field NAMES the same quantity (the whole phrase, never
one shared word: cloud on #1405). Any other quantity without a unit, and a value WITH a unit against
a threshold without one, stay undecided: no unit is guessed for either side.
"""

from __future__ import annotations

from pathlib import Path

from . import claims

PATH = Path(__file__).parent / "reference" / "dimensionless_quantities.json"

#: The words of a bound that `claims.parse_comparator` does not read.
_BOUND_WORDS = {
    "above": ">",
    "over": ">",
    "exceeding": ">",
    "exceeds": ">",
    "exceed": ">",
    "below": "<",
    "under": "<",
    "up to": "<=",
}
_NOT_SUBJECT = frozenset(
    [
        "than",
        "less",
        "more",
        "over",
        "under",
        "with",
        "least",
        "most",
        "equal",
        "greater",
        "exceeding",
        "exceeds",
        "exceed",
        "above",
        "below",
    ]
)


def subject_words(condition: str) -> list[str]:
    """The words of a numeric condition that name its subject (a fact's field name must hold one)."""
    from . import conditions

    return [
        w
        for w in conditions._WORD.findall(conditions._fold(condition))
        if len(w) > 3 and not w.replace(".", "").isdigit() and w not in _NOT_SUBJECT
    ]


def phrases() -> list[str]:
    """The quantities that are dimensionless by nature (`reference/dimensionless_quantities.json`)."""
    import json

    return json.loads(PATH.read_text(encoding="utf-8"))["phrases"]


def evaluate(condition: str, match, facts: list[dict]) -> dict:
    """The condition's state against the submitted numbers that carry no unit, for a quantity that
    is dimensionless by nature and that the submitted field NAMES by the same whole phrase."""
    from . import conditions as c

    def unknown(reason: str) -> dict:
        return c._result(c.UNKNOWN, c.SHAPE_NUMERIC, condition, reason)

    word = match.group("cmp").strip().lower()
    operator = claims.parse_comparator(word) or _BOUND_WORDS.get(word)
    if not operator:
        return unknown(
            f"the comparator {match.group('cmp')!r} is not one this system parses"
        )
    named = [p for p in phrases() if c._contains_term(c._fold(condition), p)]
    if not named:
        return unknown(
            "the threshold carries no unit and its quantity is not one that is dimensionless "
            "by nature, so nothing can be compared without guessing a unit"
        )
    threshold = claims.parse_value(match.group("value"))
    with_a_unit = None
    for fact in facts:
        if c._is_empty(fact.get("field_value")):
            continue
        name = c._fold(fact.get("field_name"))
        if not any(c._contains_term(name, p) for p in named):
            continue
        fact_unit = str(fact.get("raw_unit") or fact.get("unit") or "").strip()
        value = claims.parse_value(str(fact.get("raw_value") or ""))
        if fact_unit:
            with_a_unit = fact_unit
            continue
        if value is None or threshold is None:
            continue
        if c._low_trust(fact):
            return unknown(
                f"{c._where(fact)}, and {c._low_trust(fact)}; the condition is not decided "
                "on a value not yet trusted"
            )
        limit = claims.Measurement(match.group("value"), "", threshold, "", operator)
        seen = claims.Measurement(str(fact.get("raw_value")), "", value, "", None)
        verdict = claims._compatible(seen, limit)
        if verdict is None:
            break
        return c._result(
            c.SATISFIED if verdict else c.NOT_SATISFIED,
            c.SHAPE_NUMERIC,
            condition,
            f"{fact.get('field_name')!r} = {fact.get('field_value')!r} against {operator} "
            f"{match.group('value')} (neither states a unit; a quantity with none)",
            c._evidence_of(fact),
        )
    if with_a_unit:
        return unknown(
            f"the threshold carries no unit and the submitted value is in {with_a_unit!r}, "
            "so nothing can be compared without guessing one"
        )
    return unknown(
        "the threshold carries no unit, and no submitted number without a unit speaks to it"
    )
