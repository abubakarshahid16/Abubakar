"""Order 264b (PR 1405): a number with no unit against a quantity that is dimensionless by nature.
`comparison.py` is in the danger zone (rule 6); `condition_bare.py` decides "does not apply".
Ids M1405-01 onwards, phase 1405."""

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
        "two numbers with no unit are 'not the same quantity' again (the run's guard overwrites the verdict)",
        _CO,
        "                bare = not requirement_unit.raw_unit and not fact_unit.raw_unit\n",
        "                bare = False\n",
        "keep_the_compare_verdict",
    ),
    _m(
        "02",
        "ANY empty unit skips the run's unit guard (a number with a unit against one without is compared)",
        _CO,
        "                bare = not requirement_unit.raw_unit and not fact_unit.raw_unit\n",
        "                bare = not requirement_unit.raw_unit or not fact_unit.raw_unit\n",
        "still_a_unit_mismatch_in_the_run",
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
    _m(
        "07",
        "a field sharing ONE word with the quantity ('specific heat') speaks to 'specific gravity'",
        _CB,
        "        if not any(c._contains_term(name, p) for p in named):\n            continue\n",
        "",
        "dimensionless_quantity_named_by_the_same_phrase",
    ),
    _m(
        "08",
        "a quantity that is not dimensionless by nature (a pressure) is decided from bare numbers",
        _CB,
        "    named = [p for p in phrases() if c._contains_term(c._fold(condition), p)]\n",
        "    named = [p for p in phrases() if True] + [c._fold(condition).split()[0]]\n",
        "dimensionless_quantity_named_by_the_same_phrase",
    ),
)
