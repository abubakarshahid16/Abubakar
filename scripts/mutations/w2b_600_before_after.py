"""#600: the before/after acceptance tool. M5901 onward."""
from __future__ import annotations

from ._base import REPO, Mutation

_T = "tests/test_w2b_600_before_after.py"
_F = REPO / "scripts" / "accept_review_before_after.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M5901", phase=5901, description="the needs-engineer share loses its denominator",
             path=_F, anchor='        "needs_engineer": {"count": status.get(NEEDS_ENGINEER, 0), "of": total},\n',
             replacement='        "needs_engineer": {"count": status.get(NEEDS_ENGINEER, 0)},\n',
             target=_T, keyword="denominator", tags=("honesty",)),
    Mutation(id="M5902", phase=5902, description="a CRS row on a requirement that does not apply is not counted",
             path=_F, anchor='        if decisions.get(finding.get("requirement_id")) == "does_not_apply":\n',
             replacement='        if False:\n',
             target=_T, keyword="does_not_apply_is_counted", tags=("honesty", "critical")),
    Mutation(id="M5903", phase=5903, description="the tool runs on a live-shaped database path",
             path=_F, anchor="    if live_guard.is_live_shaped(path):\n", replacement="    if False:\n",
             target=_T, keyword="live_shaped", tags=("safety", "critical")),
)
