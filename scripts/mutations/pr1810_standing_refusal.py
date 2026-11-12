"""PR #1810 (U5): the Claude lane's standing refusal. `claude_spend.failure_word` tells a reached usage limit from any other 4xx, so the
review page never promises Claude while every call is refused. `claude_spend.py` is in the danger zone (rule 6)."""
from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1810-01", phase=1810,
             description="a reached usage limit is not told apart from any other 400 or 429 (the plan still promises Claude)",
             path=APP / "claude_spend.py",
             anchor='            limit = status in (400, 429) and sr.mentions_limit(err)\n',
             replacement="            limit = False\n",
             target="tests/test_u5_claude_standing_refusal.py", keyword="usage_limit_answer",
             tags=("honesty", "critical")),
)
