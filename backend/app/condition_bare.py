"""A numeric condition whose threshold states NO unit ("specific gravity below 0.5").

Order 264b, row 340: a clause that applies only where the specific gravity is below 0.5, and a sheet
that states 0.974, was held as an unexplained unit mismatch. Two numbers that both carry no unit are
plain numbers, the same kind, and are compared. A value WITH a unit against a threshold without one is
still undecidable: no unit is guessed for either side.
"""

from __future__ import annotations

from . import claims

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


def evaluate(condition: str, match, facts: list[dict]) -> dict:
    """The condition's state against the submitted numbers that carry no unit."""
    from . import conditions as c

    def unknown(reason: str) -> dict:
        return c._result(c.UNKNOWN, c.SHAPE_NUMERIC, condition, reason)

    word = match.group("cmp").strip().lower()
    operator = claims.parse_comparator(word) or _BOUND_WORDS.get(word)
    if not operator:
        return unknown(
            f"the comparator {match.group('cmp')!r} is not one this system parses"
        )
    threshold = claims.parse_value(match.group("value"))
    with_a_unit = None
    for fact in facts:
        if c._is_empty(fact.get("field_value")):
            continue
        name = c._fold(fact.get("field_name"))
        if not any(c._contains_term(name, w) for w in subject_words(condition)):
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
            f"{match.group('value')} (neither states a unit; plain numbers)",
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
