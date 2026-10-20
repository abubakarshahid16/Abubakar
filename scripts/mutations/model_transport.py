"""Mutations of the local-call retry (order 163.3, item F): a timed-out local
model call is tried once more, then fails as before. The ids are placeholders
named after the order; the lead renames them to the PR number."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_163f_retry_and_answer_cache.py"
_PATH = APP / "model_transport.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1221-01", phase=1221,
             description="a timed-out local call is not retried, so one slow answer voids the sheet",
             path=_PATH,
             anchor="        if not is_timeout_error(exc):\n            raise\n",
             replacement="        if True:\n            raise\n",
             target=_T, keyword="forced_timeout_retries_once or timed_out_page_read_is_retried",
             tags=("model", "honesty")),
    Mutation(id="M1221-02", phase=1221,
             description="the retry retries again without end on a persistent timeout",
             path=_PATH,
             anchor="    time.sleep(TIMEOUT_RETRY_BACKOFF_S)\n    return post_json(path, body, timeout=timeout)\n",
             replacement="    time.sleep(TIMEOUT_RETRY_BACKOFF_S)\n    return post_json_retrying(path, body, timeout=timeout)\n",
             target=_T, keyword="second_timeout_still_fails",
             tags=("model", "budget")),
    Mutation(id="M1221-03", phase=1221,
             description="every failure is retried, not only a timeout (a refusal or an HTTP error is called twice)",
             path=_PATH,
             anchor="        if not is_timeout_error(exc):\n            raise\n",
             replacement="        if False:\n            raise\n",
             target=_T, keyword="only_a_timeout_is_retried",
             tags=("model",)),
    Mutation(id="M1221-04", phase=1221,
             description="a retry is made but not counted, so the run cannot report it",
             path=_PATH,
             anchor="        _TIMEOUT_RETRIES += 1\n",
             replacement="        pass\n",
             target=_T, keyword="forced_timeout_retries_once",
             tags=("model", "honesty")),
    Mutation(id="M1221-05", phase=1221,
             description="the Ollama provider ignores its retry switch, so the readers never retry",
             path=APP / "reasoning_provider.py",
             anchor="model_transport.post_json_retrying if self.retry_timeouts else",
             replacement="model_transport.post_json if False else",
             target=_T, keyword="timed_out_page_read_is_retried",
             tags=("model",)),
    Mutation(id="M1221-06", phase=1221,
             description="the AI matcher's pair-choice call calls the plain transport, with no retry",
             path=APP / "comparison.py",
             anchor='        raw = model_transport.post_json_retrying(\n            "/api/generate", body, timeout=settings.match_timeout_seconds)',
             replacement='        raw = model_transport.post_json(\n            "/api/generate", body, timeout=settings.match_timeout_seconds)',
             target=_T, keyword="pair_choice_call_retries",
             tags=("model",)),
)
