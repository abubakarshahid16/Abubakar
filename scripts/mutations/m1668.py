"""#1668 (lane 6): the AI review sheet is on the INTERNAL copy only."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_ai_review_view.py"
_TAGS = ("honesty", "critical")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1668-01",
        phase=1668,
        description="draw the AI review sheet on the issue copy too, so the contractor sees the AI's reasons",
        path=APP / "crs_export.py",
        anchor='    if internal and meta.get("ai_review"):',
        replacement='    if meta.get("ai_review"):',
        target=_T,
        keyword="the_internal_workbook_has_the_sheet_and_the_issue_workbook_does_not",
        tags=_TAGS,
    ),
    Mutation(
        id="M1668-02",
        phase=1668,
        description="the internal CRS meta carries the AI review data on the issue copy as well",
        path=APP / "run_record.py",
        anchor='    if copy != "internal":\n        return {}\n    out = {}',
        replacement="    out = {}",
        target=_T,
        keyword="the_internal_meta_carries_it_and_the_issue_meta_does_not",
        tags=_TAGS,
    ),
)
