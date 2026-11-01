"""PR 1401: a checklist item held for the engineer is a CRS row, and a draft says so."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_265_checklist_crs_rows.py"
_TAGS = ("honesty", "critical")
_P = APP / "crs_checklist.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1401-01",
        phase=1401,
        description="a checklist item held for the engineer is no CRS row again",
        path=_P,
        anchor='    held = status == "NEEDS_ENGINEER_REVIEW" and bool(finding.get("standard_clause"))\n',
        replacement="    held = False\n",
        target=_T,
        keyword="held_checklist_item_is_a_crs_row",
        tags=_TAGS,
    ),
    Mutation(
        id="M1401-02",
        phase=1401,
        description="any held datasheet check becomes a CRS row, not only a checklist item",
        path=_P,
        anchor='    held = status == "NEEDS_ENGINEER_REVIEW" and bool(finding.get("standard_clause"))\n',
        replacement='    held = status == "NEEDS_ENGINEER_REVIEW"\n',
        target=_T,
        keyword="not_a_checklist_item_is_still_no_row",
        tags=_TAGS,
    ),
    Mutation(
        id="M1401-03",
        phase=1401,
        description="a draft checklist row no longer says it is a draft",
        path=_P,
        anchor='    return [DRAFT_WORDS] if is_draft_checklist(finding.get("requirement")) else []\n',
        replacement="    return []\n",
        target=_T,
        keyword="held_checklist_item_is_a_crs_row",
        tags=_TAGS,
    ),
    Mutation(
        id="M1401-04",
        phase=1401,
        description="a signed-off checklist is called a draft",
        path=_P,
        anchor='    return [DRAFT_WORDS] if is_draft_checklist(finding.get("requirement")) else []\n',
        replacement="    return [DRAFT_WORDS]\n",
        target=_T,
        keyword="signed_off_checklist_does_not_say_draft",
        tags=_TAGS,
    ),
)
