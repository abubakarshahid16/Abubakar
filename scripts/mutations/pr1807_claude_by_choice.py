"""PR #1807 (owner, 12 Nov 2026, #1584: "button is enough"): a review started with the explicit choice of Claude sends exactly the
documents listed on the screen, of any kind, and records that start; the register stays blocked. Entries for `claude_approved.py`."""
from __future__ import annotations

from ._base import APP, Mutation

_P = APP / "claude_approved.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1807-01", phase=1807, description="the consent record of the run is not read: a listed contract is refused again",
             path=_P, anchor="        return review_shown.consented_ids(connect(), run, ids)\n",
             replacement="        return frozenset()\n",
             target="tests/test_d1_claude_by_choice.py", keyword="listed_contract_with_the_explicit_choice",
             tags=("egress", "critical")),
    Mutation(id="M1807-02", phase=1807, description="the block list is not asked before the consent: a listed register would go",
             path=_P, anchor="    if ids:  # before the guard and the consent below: a block wins over both\n        stopped = _block_stop(ids)",
             replacement="    if ids and not _consented(ids):  # MUTANT\n        stopped = _block_stop(ids)",
             target="tests/test_d1_claude_by_choice.py", keyword="register_is_refused_even_when_listed",
             tags=("egress", "critical")),
)
