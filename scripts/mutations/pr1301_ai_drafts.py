"""PR #1301 (order 224 item 4): an AI check's draft never moves the suggested
review code, whatever its status. backend/tests/test_224_ai_draft_status.py
must notice."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_224_ai_draft_status.py"
_PATH = APP / "comparison.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1301-01",
        phase=1301,
        description="the guard is dropped: AI drafts are counted by the code policy again",
        path=_PATH,
        anchor='    kept = [f for f in findings if f.get("origin") not in AI_DRAFT_ORIGINS]\n',
        replacement="    kept = list(findings)\n",
        target=_T,
        keyword="never_moves_the_suggested_code",
        tags=("pr1301", "comparison"),
    ),
    Mutation(
        id="M1301-02",
        phase=1301,
        description="the web check's drafts are counted again (only the AI check is ignored)",
        path=_PATH,
        anchor='AI_DRAFT_ORIGINS = ("ai_engineering_check", "web_standard_check")\n',
        replacement='AI_DRAFT_ORIGINS = ("ai_engineering_check",)\n',
        target=_T,
        keyword="never_moves_the_suggested_code",
        tags=("pr1301", "comparison"),
    ),
)
