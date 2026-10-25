"""Order 205 (PR 1278): the engine's version is part of the answer-reuse key and
`AI_ANSWER_REUSE_ENABLED=false` turns reuse off (the final test before a client)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_163f_retry_and_answer_cache.py"
_P = APP / "ai_task_runner.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1278-01",
        phase=1278,
        description="the off switch is ignored: with reuse off, answers are still reused and kept",
        path=_P,
        anchor="    if not settings.ai_answer_reuse_enabled:\n",
        replacement="    if False:\n",
        target=_T,
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1278-02",
        phase=1278,
        description="the engine version is left out of the identity: a new Ollama reuses an old answer",
        path=_P,
        anchor='@{digest}|ollama/{version}"',
        replacement='@{digest}"',
        target=_T,
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1278-03",
        phase=1278,
        description="an engine that will not say its version still gets an identity (reuse allowed)",
        path=_P,
        anchor="                if digest and version:\n",
        replacement="                if digest:\n",
        target=_T,
        tags=("honesty",),
    ),
)
