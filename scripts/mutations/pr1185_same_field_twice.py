"""Order 142 fix C: one field read twice is one field, never a tie between two
numbers. `comparison.py` is in the danger zone (rule 6). PR #1185: ids
M1185-01 onwards, phase 1185."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_142c_same_field_twice.py"
_C = APP / "field_copies.py"
_TAGS = ("honesty", "critical", "142c")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1185-01",
        phase=1185,
        description="copies of one field with different values are treated as one field",
        path=_C,
        anchor='    if filled and len({_value_signature(h["fact"]) for h in filled}) > 1:\n',
        replacement="    if False:\n",
        target=_T,
        keyword="different_values or never_picked",
        tags=_TAGS,
    ),
    Mutation(
        id="M1185-02",
        phase=1185,
        description="a field read twice, both blank, is a tie again",
        path=_C,
        anchor='    if filled and len({_value_signature(h["fact"]) for h in filled}) > 1:\n',
        replacement='    if not filled or len({_value_signature(h["fact"]) for h in filled}) > 1:\n',
        target=_T,
        keyword="both_blank",
        tags=_TAGS,
    ),
    Mutation(
        id="M1185-03",
        phase=1185,
        description="the same number in another unit counts as the same value",
        path=_C,
        anchor='        return ("number", float(fact["value"]), str(fact.get("unit") or unit).lower())\n',
        replacement='        return ("number", float(fact["value"]))\n',
        target=_T,
        keyword="different_unit",
        tags=_TAGS,
    ),
    Mutation(
        id="M1185-04",
        phase=1185,
        description="the other copies of a matched field are not named",
        path=_C,
        anchor='            {_copy_label(h["fact"], name) for h in ordered if h is not chosen}\n',
        replacement='            {_copy_label(h["fact"], name) for h in ordered if False}\n',
        target=_T,
        keyword="same_value",
        tags=_TAGS,
    ),
)
