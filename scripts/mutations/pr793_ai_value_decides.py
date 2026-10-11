"""PR #793 (planner decision 2026-10-11, 09:11 UTC): an AI-read value whose
quote the code proved on the page decides like a code-read one; any other
model-read value, and a conflicting one, still waits for an engineer."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_ai_reader_default.py"
_C = APP / "comparison.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M793-01", phase=793, description="every model-read value is trusted, proved quote or not",
             path=_C, anchor='        if ai_quote_proved(fact):\n            return None\n',
             replacement='        return None\n',
             target=_T, keyword="trusted_like_a_code_read_one", tags=("honesty", "critical")),
    Mutation(id="M793-02", phase=793, description="the proof flag is not checked (any datasheet_ai fact is trusted)",
             path=_C, anchor=' and box.get("quote_on_page") is True:\n',
             replacement=':\n',
             target=_T, keyword="trusted_like_a_code_read_one", tags=("honesty", "critical")),
    Mutation(id="M793-03", phase=793, description="a verdict an AI-read value decided does not say so",
             path=_C, anchor='    if box and verdict.get("status") in _VERDICTS_HELD_ON_LOW_TRUST:\n',
             replacement='    if False:\n',
             target=_T, keyword="says_so", tags=("honesty",)),
    Mutation(id="M793-04", phase=793, description="a proved AI value is still held for an engineer",
             path=_C, anchor='        if ai_quote_proved(fact):\n            return None\n',
             replacement='',
             target=_T, keyword="trusted_like_a_code_read_one or says_so", tags=("honesty",)),
)
