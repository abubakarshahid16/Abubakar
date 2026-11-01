"""Order 210 fix 3 (PR 1283): a held requirement is an engineer-review finding
with its reason - never a pass, never a garbled sentence or a list."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_210_held_rows.py"
_H = APP / "held_findings.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1283-01",
        phase=1283,
        description="the review no longer adds the held requirements' rows (back to a count only)",
        path=APP / "comparison.py",
        anchor="    held_findings.add(held_items, pending, prepared_rows, findings, run)\n",
        replacement="",
        target=_T,
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1283-02",
        phase=1283,
        description="a held requirement's row reads COMPLIANT instead of the engineer's question",
        path=_H,
        anchor='        "status": NEEDS_ENGINEER_REVIEW,\n',
        replacement='        "status": "COMPLIANT",\n',
        target=_T,
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1283-03",
        phase=1283,
        description="an unconfirmed garbled sentence gets a row as if it were a clause",
        path=_H,
        anchor='NOT_ROWS = frozenset({"text_quality"})\n',
        replacement="NOT_ROWS = frozenset()\n",
        target=_T,
        tags=("honesty",),
    ),
    Mutation(
        id="M1283-04",
        phase=1283,
        description="a list that states no requirement gets a row",
        path=_H,
        anchor=' and not item.get("not_a_requirement")',
        replacement="",
        target=_T,
        tags=("honesty",),
    ),
    Mutation(
        id="M1283-05",
        phase=1283,
        description="a standard with many held requirements gets a row each again (a real sheet: 1,937 lines)",
        path=_H,
        anchor='        if len(group) > GROUP_ABOVE and kind != "recommendation":\n',
        replacement="        if False:\n",
        target=_T,
        tags=("honesty",),
    ),
    Mutation(
        id="M1283-06",
        phase=1283,
        description="a hold that is not the division gate's own is called a part-scope hold again",
        path=_H,
        anchor='    return "other"\n',
        replacement='    return "scope_unsure"\n',
        target=_T,
        tags=("honesty",),
    ),
)
