"""PR #1810 (U5): the points listing feeds the sign gate's counts (`undecided`) and the proposed code's inputs, so what it groups, counts and
names is guarded: a proven or two-reader point never joins a group, the decided count is of points (not groups), and a rule book the caller
may not read is never named (rule 5)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_u5_points_polish.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1810-01", phase=1810,
             description="a proven Fail or a two-reader verdict can fall into a group of alike points (Keep all decides it unseen)",
             path=APP / "review_points.py",
             anchor="    if rank not in (3, 4) or not _clean(book) or not (_clean(clause) or _clean(field)):\n",
             replacement="    if not _clean(book) or not (_clean(clause) or _clean(field)):\n",
             target=_T, keyword="different_clause_or_field_or_book", tags=("honesty", "critical")),
    Mutation(id="M1810-02", phase=1810,
             description="the decided count counts groups, not points (the sign gate would wait for fewer decisions than there are points)",
             path=APP / "review_points_service.py",
             anchor='    decided = sum(1 for p in points if p["decision"]["state"])\n',
             replacement='    decided = len({p.get("group_key") or p["id"] for p in points if p["decision"]["state"]})\n',
             target=_T, keyword="decided_counts_points_not_groups", tags=("honesty", "critical")),
    Mutation(id="M1810-03", phase=1810,
             description="a rule book the caller may not read is named on a point (rule 5)",
             path=APP / "review_points_service.py",
             anchor="            if d in readable and d in names\n",
             replacement="            if d in names\n",
             target=_T, keyword="unreadable_one_is_not_named", tags=("privacy", "critical")),
)
