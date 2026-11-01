"""Order 260.1 follow-up (PR 1400): the Manual-review banner names the real reasons."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_260_one_meaning_of_checked.py"
_TAGS = ("honesty",)

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1400-01",
        phase=1400,
        description="the banner ignores the real reasons and blames a missing field again",
        path=APP / "requirement_split.py",
        anchor='    reasons = counts.get("reasons")\n',
        replacement="    reasons = None\n",
        target=_T,
        keyword="banner_names_the_real_reasons",
        tags=_TAGS,
    ),
    Mutation(
        id="M1400-02",
        phase=1400,
        description="the reasons beyond the fourth are dropped from the banner",
        path=APP / "requirement_split.py",
        anchor='        more = sum(r["count"] for r in reasons[4:])\n',
        replacement="        more = 0\n",
        target=_T,
        keyword="banner_names_the_real_reasons",
        tags=_TAGS,
    ),
    Mutation(
        id="M1400-03",
        phase=1400,
        description="the run does not hand the split's reasons to the review code",
        path=APP / "comparison.py",
        anchor='        "reasons": split["applies_not_checked_reasons"]}',
        replacement='        "reasons": []}',
        target="tests/test_w3_678_three_way_split.py",
        keyword="puts_other_equipment_in_does_not_apply",
        tags=_TAGS,
    ),
)
