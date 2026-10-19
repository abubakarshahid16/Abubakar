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
        anchor='    if mixed or len({_value_signature(h["fact"]) for h in filled}) > 1:\n',
        replacement="    if mixed:\n",
        target=_T,
        keyword="different_values or never_picked",
        tags=_TAGS,
    ),
    Mutation(
        id="M1185-02",
        phase=1185,
        description="a field read twice, both blank, is a tie again",
        path=_C,
        anchor='    if mixed or len({_value_signature(h["fact"]) for h in filled}) > 1:\n',
        replacement='    if not filled or mixed or len({_value_signature(h["fact"]) for h in filled}) > 1:\n',
        target=_T,
        keyword="both_blank",
        tags=_TAGS,
    ),
    Mutation(
        id="M1185-03",
        phase=1185,
        description="the same number in another unit counts as the same value",
        path=_C,
        anchor='            str(fact.get("normalized_unit") or unit).lower(),\n',
        replacement='            "",\n',
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
    Mutation(
        id="M1185-05",
        phase=1185,
        description="a value on one copy and a blank on another is taken as one field (the blank is hidden)",
        path=_C,
        anchor="    mixed = bool(filled) and len(filled) < len(ordered)\n",
        replacement="    mixed = False\n",
        target=_T,
        keyword="value_beside_a_blank",
        tags=_TAGS,
    ),
    Mutation(
        id="M1185-06",
        phase=1185,
        description="two table columns with the same printed number are merged as one copy",
        path=_C,
        anchor='        str(fact.get("value_column") or "").lower(),\n',
        replacement='        "",\n',
        target=_T,
        keyword="table_columns",
        tags=_TAGS,
    ),
    Mutation(
        id="M1185-07",
        phase=1185,
        description="a minimum and a maximum of the same number are merged as one copy",
        path=_C,
        anchor="        comparator,\n",
        replacement='        "",\n',
        target=_T,
        keyword="minimum_and_a_maximum",
        tags=_TAGS,
    ),
)
