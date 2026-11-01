"""PR 1533: a heat exchanger box reads a split abbreviation and a unit left off one copy (label_match.py,
datasheet_checks.py, datasheet_roles.py; danger zone). Ids M1533-01.. (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_c1_exchanger_box_match.py"
_TAG = ("checklist", "honesty")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1533-01",
        phase=1533,
        description="a unit left off one copy of the same number is two different values again",
        path=APP / "datasheet_checks.py",
        anchor="        found = drop_unit_less_twins(found)\n",
        replacement="        pass\n",
        target=_T,
        keyword="on_a_unit_left_off_one_copy_is_one_value",
        tags=_TAG,
    ),
    Mutation(
        id="M1533-02",
        phase=1533,
        description="a split abbreviation is never joined, so the tube outside diameter is not found",
        path=APP / "datasheet_roles.py",
        anchor="        found = _joined_roles(field_name, rules)\n",
        replacement="        pass\n",
        target=_T,
        keyword="on_a_split_abbreviation_is_the_tube_outside_diameter",
        tags=_TAG,
    ),
    Mutation(
        id="M1533-03",
        phase=1533,
        description="a unit-less reading with a DIFFERENT number is dropped as a twin (a conflict hidden)",
        path=APP / "label_match.py",
        anchor="    if any(_number(f) not in numbers for f in bare):\n        return found\n",
        replacement="",
        target=_T,
        keyword="different_numbers_or_units_stay_two_values",
        tags=_TAG,
    ),
    Mutation(
        id="M1533-04",
        phase=1533,
        description="united readings that disagree on the unit are merged with a unit-less one",
        path=APP / "label_match.py",
        anchor="    if len(units) != 1 or len(numbers) != 1:\n        return found\n",
        replacement="",
        target=_T,
        keyword="disagree_on_the_unit",
        tags=_TAG,
    ),
    Mutation(
        id="M1533-05",
        phase=1533,
        description="the label join runs with the switch off (live reviews change)",
        path=APP / "datasheet_roles.py",
        anchor="    if not settings.datasheet_label_match_enabled:\n        return []\n",
        replacement="",
        target=_T,
        keyword="off_a_split_abbreviation_is_not_found",
        tags=_TAG,
    ),
    Mutation(
        id="M1533-07",
        phase=1533,
        description='a unit-less "max 650" / "not 650" is dropped as a twin of "650 F" (a conflict hidden)',
        path=APP / "label_match.py",
        anchor="    if not all(_plain(f) for f in bare):",
        replacement="    if False:",
        target=_T,
        keyword="bound_or_negation_without_a_unit",
        tags=_TAG,
    ),
    Mutation(
        id="M1533-06",
        phase=1533,
        description="the unit-less twin merge runs with the switch off (live reviews change)",
        path=APP / "datasheet_checks.py",
        anchor="    if settings.datasheet_label_match_enabled:\n        found = drop_unit_less_twins(found)\n",
        replacement="    if True:\n        found = drop_unit_less_twins(found)\n",
        target=_T,
        keyword="off_a_unit_left_off_one_copy_is_two_values",
        tags=_TAG,
    ),
)
