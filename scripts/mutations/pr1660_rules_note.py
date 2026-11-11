"""Mutations of the CRS rules note (item 14, PR 1660)."""

from __future__ import annotations

from ._base import REPO, Mutation

_Q = REPO / "backend" / "app" / "crs_export_quality.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1660-01",
        phase=1660,
        description="the rules note is never added to row 1, whatever the switch says",
        path=_Q,
        anchor='    if not settings.crs_rules_note_enabled or (copy or "internal") != "internal":\n        return said\n',
        replacement="    if True:\n        return said\n",
        target="tests/test_crs_rules_note.py",
        keyword="one_sentence_on_row_1",
        tags=("crs", "honesty"),
    ),
    Mutation(
        id="M1660-02",
        phase=1660,
        description="the rules note is added even with the switch off",
        path=_Q,
        anchor='    if not settings.crs_rules_note_enabled or (copy or "internal") != "internal":\n        return said\n',
        replacement="    if False:\n        return said\n",
        target="tests/test_crs_rules_note.py",
        keyword="one_sentence_on_row_1",
        tags=("crs", "honesty"),
    ),
    Mutation(
        id="M1660-03",
        phase=1660,
        description="the contractor copy carries the engineer-must-confirm note",
        path=_Q,
        anchor=' or (copy or "internal") != "internal":\n',
        replacement=":\n",
        target="tests/test_crs_rules_note.py",
        keyword="contractor_copy",
        tags=("crs", "honesty"),
    ),
)
