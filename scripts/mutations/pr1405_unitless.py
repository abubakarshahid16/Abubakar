"""Order 264b (PR 1405): two numbers with no unit are plain numbers. `comparison.py` is in the danger
zone (rule 6); `condition_bare.py` decides "does not apply". Ids M1405-01 onwards, phase 1405."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_264b_unitless.py"
_CO = APP / "comparison.py"
_CB = APP / "condition_bare.py"
_TAGS = ("honesty", "o264b")


def _m(n, description, path, anchor, replacement, keyword):
    return Mutation(
        id=f"M1405-{n}",
        phase=1405,
        description=description,
        path=path,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=_TAGS,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "two numbers with no unit are 'not the same quantity' again (the guard overwrites the verdict)",
        _CO,
        "        bare\n        or claims.same_unit(requirement_unit, fact_unit)\n",
        "        claims.same_unit(requirement_unit, fact_unit)\n",
        "unit_guard_lets_two_unitless",
    ),
    _m(
        "02",
        "ANY empty unit passes the guard (a number with a unit against one without is compared)",
        _CO,
        "    bare = not requirement_unit.raw_unit and not fact_unit.raw_unit\n",
        "    bare = not requirement_unit.raw_unit or not fact_unit.raw_unit\n",
        "unit_guard_lets_two_unitless",
    ),
    _m(
        "03",
        "a value WITH a unit is compared against a threshold without one (a unit is guessed)",
        _CB,
        "        if fact_unit:\n            with_a_unit = fact_unit\n            continue\n",
        "",
        "with_a_unit_against_a_threshold_without_one",
    ),
    _m(
        "04",
        "'below' is no longer a bound word: the clause stays undecided",
        _CB,
        '    "below": "<",\n',
        "",
        "decided_against_a_value_with_no_unit",
    ),
    _m(
        "05",
        "the threshold's operator is dropped (a bound is read as an equality)",
        _CB,
        '        limit = claims.Measurement(match.group("value"), "", threshold, "", operator)\n',
        '        limit = claims.Measurement(match.group("value"), "", threshold, "", None)\n',
        "decided_against_a_value_with_no_unit",
    ),
    _m(
        "06",
        "a value the model read and no engineer confirmed decides the condition",
        _CB,
        "        if c._low_trust(fact):\n",
        "        if False:\n",
        "not_confirmed_decides_no_condition",
    ),
)
