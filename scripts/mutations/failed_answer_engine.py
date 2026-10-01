"""Mutations for the engine named on a failed chat answer (2026-10-01, M1830-M1831).
Files: backend/app/chat_claude_first.py, backend/app/chat_answers.py.
Target: backend/tests/test_failed_answer_names_engine.py.
"""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_failed_answer_names_engine.py"
_TAG = ("failed_answer_engine",)

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1830", phase=1830,
             description="a failed Claude tool loop no longer records that Claude failed",
             path=APP / "chat_claude_first.py",
             anchor='"reason": _failure_reason(exc), "provider": rp.CLAUDE,',
             replacement='"reason": _failure_reason(exc),',
             target=_T, keyword="claude_loop_failure_names_claude", tags=_TAG),
    Mutation(id="M1831", phase=1831,
             description="a failed general or rewrite answer always blames the local engine",
             path=APP / "chat_answers.py",
             anchor="engine = rp.CLAUDE if isinstance(exc, claude_spend.BudgetExceeded) else chat_model.engine_name(preference)",
             replacement="engine = rp.OLLAMA",
             target=_T, keyword="general_failure_names_claude", tags=_TAG),
)
