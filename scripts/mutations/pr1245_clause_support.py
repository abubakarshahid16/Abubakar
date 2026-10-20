"""Orders 180 items 1 and 7: a sentence that states no requirement, or names a
service the sheet does not state, never supports a CRS row. `comparison.py` is in
the danger zone (rule 6). PR #1245: ids M1245-01 onwards, phase 1245."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_180_clause_support.py"
_TAGS = ("honesty", "180")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1245-01",
        phase=1245,
        description="the held sentences of the service gate never reach the run's held list",
        path=APP / "comparison.py",
        anchor='    held_items.extend(serviced["held"])\n',
        replacement="    pass\n",
        target=_T,
        keyword="sets_a_list_aside_and_holds",
        tags=_TAGS,
    ),
    Mutation(
        id="M1245-02",
        phase=1245,
        description="a list of items is kept as a requirement",
        path=APP / "clause_support.py",
        anchor="    return len(re.findall(r\"[,;]\", text)) >= 2\n",
        replacement="    return False\n",
        target=_T,
        keyword="states_no_requirement",
        tags=_TAGS,
    ),
    Mutation(
        id="M1245-03",
        phase=1245,
        description="a sentence naming a service the sheet does not state is kept",
        path=APP / "clause_support.py",
        anchor="        if not (missing and sheet):\n",
        replacement="        if True:\n",
        target=_T,
        keyword="held_not_listed",
        tags=_TAGS,
    ),
)
