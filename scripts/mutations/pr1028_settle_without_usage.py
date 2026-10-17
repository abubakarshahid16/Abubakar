"""PR #1028 (#459, audit B07): a Claude reply without usage settles at the
worst case it was reserved at, not USD 0. Entries for `claude_spend.py`
(danger zone: the budget); each undoes one part of the fix and a test in
tests/test_459_settle_without_usage.py must notice."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_459_settle_without_usage.py"
_S = APP / "claude_spend.py"
_TAG = ("budget", "critical")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1028-01", phase=1028, description="a reply without usage settles at USD 0 again",
             path=_S, anchor="    if estimated_usd is None and not _usage_reported(usage):\n",
             replacement="    if False:\n",
             target=_T, keyword="without_usage_settles_at_its_worst_case", tags=_TAG),
    Mutation(id="M1028-02", phase=1028, description="a missing usage block counts as reported",
             path=_S,
             anchor='    return isinstance(usage, dict) and ("input_tokens" in usage or "output_tokens" in usage)\n',
             replacement='    return True\n',
             target=_T, keyword="without_usage_settles_at_its_worst_case", tags=_TAG),
    Mutation(id="M1028-03", phase=1028, description="every reply is charged its worst case, used tokens or not",
             path=_S, anchor="    if estimated_usd is None and not _usage_reported(usage):\n",
             replacement="    if estimated_usd is None:\n",
             target=_T, keyword="still_charged_what_it_used", tags=("budget",)),
)
