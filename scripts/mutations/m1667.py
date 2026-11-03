"""#1667 (lane 6): the AI review pass never removes a Fail, read from the result and severity a row carries."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_ai_review_real_rows.py"
_TAGS = ("honesty", "critical")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1667-01",
        phase=1667,
        description="the CRS row no longer carries the result behind it, so a failed self-check looks like a question",
        path=APP / "crs_mapping.py",
        anchor='                    "compliance_status": worst_status(group),\n',
        replacement='                    "compliance_status": "",\n',
        target=_T,
        keyword="carries_its_result",
        tags=_TAGS,
    ),
    Mutation(
        id="M1667-02",
        phase=1667,
        description="the verifier trusts the row kind alone and ignores the carried result and severity",
        path=APP / "ai_review_proposals.py",
        anchor='        or is_fail_word(row.get("compliance_status"))\n',
        replacement="",
        target=_T,
        keyword="is_a_fail_whatever_its_label",
        tags=_TAGS,
    ),
)
