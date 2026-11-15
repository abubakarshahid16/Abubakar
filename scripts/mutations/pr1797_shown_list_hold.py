"""PR #1797 (owner, 12 Nov 2026, #1584): a specification a review cites goes to Claude only if the list shown before the start
names it. Entries for `claude_approved.py`: the hold in `refusal()` and the run context a review route declares."""
from __future__ import annotations

from ._base import APP, Mutation

_P = APP / "claude_approved.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1797-01", phase=1797, description="the gate no longer holds a cited specification the shown list does not name",
             path=_P, anchor="    if held:\n        return NOT_APPROVED, (\n",
             replacement="    if False:\n        return NOT_APPROVED, (\n",
             target="tests/test_d1_shown_list_hold.py", keyword="refused_when_no_list_was_shown",
             tags=("egress", "critical")),
    Mutation(id="M1797-02", phase=1797, description="a review route declares its documents but not its run, so the hold does not apply",
             path=_P, anchor="    with carrying(review_documents(review_run_id)), reviewing(review_run_id):\n        yield",
             replacement="    with carrying(review_documents(review_run_id)):\n        yield",
             target="tests/test_d1_route_hold.py", keyword="comparison_declares_the_run", tags=("egress", "critical")),
)
