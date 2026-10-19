"""Order 142 fix C: one field read twice is one field, never a tie between two
numbers. `comparison.py` is in the danger zone (rule 6). PRNUM is the pull
request number, to be filled in (ids `MPRNUM-NN`, `phase=PRNUM`) when it is
opened; a rename of these placeholders is the only edit this file needs."""

from __future__ import annotations

from ._base import APP, Mutation

PRNUM = "PRNUM"
_T = "tests/test_142c_same_field_twice.py"
_C = APP / "comparison.py"
_TAGS = ("honesty", "critical", "142c")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="MPRNUM-01",
        phase=PRNUM,
        description="copies of one field with different values are treated as one field",
        path=_C,
        anchor='    if filled and len({_value_signature(h["fact"]) for h in filled}) > 1:\n',
        replacement="    if False:\n",
        target=_T,
        keyword="different_values or never_picked",
        tags=_TAGS,
    ),
    Mutation(
        id="MPRNUM-02",
        phase=PRNUM,
        description="a field read twice, both blank, is a tie again",
        path=_C,
        anchor='    if filled and len({_value_signature(h["fact"]) for h in filled}) > 1:\n',
        replacement='    if not filled or len({_value_signature(h["fact"]) for h in filled}) > 1:\n',
        target=_T,
        keyword="both_blank",
        tags=_TAGS,
    ),
    Mutation(
        id="MPRNUM-03",
        phase=PRNUM,
        description="the same number in another unit counts as the same value",
        path=_C,
        anchor='        return ("number", float(fact["value"]), str(fact.get("unit") or unit).lower())\n',
        replacement='        return ("number", float(fact["value"]))\n',
        target=_T,
        keyword="different_unit",
        tags=_TAGS,
    ),
    Mutation(
        id="MPRNUM-04",
        phase=PRNUM,
        description="the other copies of a matched field are not named",
        path=_C,
        anchor="                                  for h in ordered if h is not chosen})}\n",
        replacement="                                  for h in ordered if False})}\n",
        target=_T,
        keyword="same_value",
        tags=_TAGS,
    ),
)
