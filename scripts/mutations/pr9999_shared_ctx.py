"""PR #9999 (placeholder, the owner renames): one shared context window for
every local Ollama call. backend/tests/test_9999_shared_ctx.py must notice."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_9999_shared_ctx.py"
_PATH = APP / "model_transport.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M9999-01",
        phase=9999,
        description="the shared window is dropped: a step's own num_ctx is sent, so steps reload the model again",
        path=_PATH,
        anchor='        "num_ctx": max(int(num_ctx or 0), shared),',
        replacement='        "num_ctx": int(num_ctx or 0) or shared,',
        target=_T,
        keyword="every_local_step_sends_the_same_num_ctx or exactly_one_distinct",
        tags=("pr9999", "model_transport"),
    ),
    Mutation(
        id="M9999-02",
        phase=9999,
        description="LOCAL_NUM_CTX is ignored: the window stays at the prompt size (4096), not the shared one",
        path=_PATH,
        anchor="    shared = max(int(settings.num_ctx), int(settings.local_num_ctx))\n",
        replacement="    shared = int(settings.num_ctx)\n",
        target=_T,
        keyword="every_local_step_sends_the_same_num_ctx or shared_normaliser",
        tags=("pr9999", "model_transport"),
    ),
    Mutation(
        id="M9999-03",
        phase=9999,
        description="a step asking for MORE than the shared size is cut down to it (max becomes shared only)",
        path=_PATH,
        anchor='        "num_ctx": max(int(num_ctx or 0), shared),',
        replacement='        "num_ctx": shared,',
        target=_T,
        keyword="larger_than_the_shared_size_keeps_its_own",
        tags=("pr9999", "model_transport"),
    ),
    Mutation(
        id="M9999-04",
        phase=9999,
        description="the runner-path guard is removed: embeddings and other non-runner bodies are rewritten too",
        path=_PATH,
        anchor="    return with_runner_options(body) if _path_of(path) in RUNNER_PATHS else body\n",
        replacement="    return with_runner_options(body)\n",
        target=_T,
        keyword="only_runner_paths_are_changed or claude_lane",
        tags=("pr9999", "model_transport"),
    ),
)
