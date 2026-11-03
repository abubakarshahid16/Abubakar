"""#1668 (lane 6): the AI review sheet is on the INTERNAL copy only."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_ai_review_view.py"
_F = "tests/test_ai_review_followups.py"
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
    Mutation(
        id="M1668-03",
        phase=1668,
        description="the AI removal count prints in the top note of the issue copy too",
        path=APP / "crs_ai_review_view.py",
        anchor='if copy == "internal" else ""',
        replacement='if True else ""',
        target=_F,
        keyword="top_note_counts_removed_comments_on_the_internal_copy_only",
        tags=_TAGS,
    ),
    Mutation(
        id="M1668-04",
        phase=1668,
        description="the gate and the decide route no longer see rows the AI review removed",
        path=APP / "crs_ai_review_view.py",
        anchor="    if not _KEEP.get():",
        replacement="    if True:",
        target=_F,
        keyword="removed_row_stays_in_the_decision_paths_rows",
        tags=_TAGS,
    ),
    Mutation(
        id="M1668-05",
        phase=1668,
        description="a row an engineer confirmed (kept on the CRS) is still labelled removed",
        path=APP / "crs_ai_review_view.py",
        anchor='                else STATE_KEPT\n                if row.get("engineer_confirmed")',
        replacement='                else STATE_REMOVED\n                if row.get("engineer_confirmed")',
        target=_F,
        keyword="confirmed_or_absent_row_is_never_called_removed",
        tags=_TAGS,
    ),
)
