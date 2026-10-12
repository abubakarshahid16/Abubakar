"""#644 "the AI task runner": each entry deletes one part;
backend/tests/test_w4b_644_ai_task_runner.py must notice."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w4b_644_ai_task_runner.py"
_TAG = ("w4b_644", "ai_task_runner")


def _m(i, desc, path, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=APP / path,
                    anchor=anchor, replacement=repl, target=_T, keyword=kw, tags=_TAG)


R = "ai_task_runner.py"
MUTATIONS: tuple[Mutation, ...] = (
    _m(3801, "an invalid reply is kept", R, "        problems = _reply_problems(spec, response, text)\n",
       "        problems = []\n", "invalid_reply_twice"),
    _m(3802, "there is no retry", R, "MAX_ATTEMPTS = 2\n", "MAX_ATTEMPTS = 1\n", "one_retry"),
    _m(3803, "a cache hit still calls the model", R, "    if use_cache:\n        hit = _cache_get(key)\n",
       "    if False:\n        hit = _cache_get(key)\n", "cache_hit"),
    _m(3804, "the model is not part of the cache key", R,
       'material = "\\x00".join([spec.name, spec.version, model,', 'material = "\\x00".join([spec.name, spec.version,',
       "two_models"),
    _m(3805, "the word limit is gone", R, "    if words > settings.ai_task_max_words:\n",
       "    if False:\n", "word_limit"),
    _m(3806, "the batch does not pause", R, "                if reason:\n                    summary[\"paused\"] = reason\n",
       "                if False:\n                    summary[\"paused\"] = reason\n", "paused_batch"),
    _m(3807, "the gate ignores a chat in progress", R, "    if active:\n", "    if False:\n", "gate_yields"),
    _m(3808, "the gate ignores low memory", R, "    if free < floor:\n", "    if False:\n", "gate_yields"),
    _m(3809, "the gate ignores a test or P1 run", R, "    if heavy_name:\n", "    if False:\n", "gate_yields"),
    _m(3810, "the model is not unloaded after a batch", R, "        if called_model:\n", "        if False:\n",
       "stays_loaded"),
    _m(3811, "the batch keep-alive is not sent", R,
       "model_transport.keep_alive_override(settings.ai_task_batch_keep_alive)",
       "model_transport.keep_alive_override(None)", "stays_loaded"),
    _m(3812, "two batches can run at once", R, "    if not _batch_lock.acquire(blocking=False):\n",
       "    if False:\n", "second_concurrent_batch"),
    _m(3813, "a job left running by a dead process is never picked up", R,
       "STALE_RUNNING_S = 15 * 60\n", "STALE_RUNNING_S = 10 ** 9\n", "dead_process"),
    _m(3814, "an error's text (document text) reaches the stored reason", R,
       "    return type(exc.__cause__ or exc).__name__\n", "    return str(exc)\n", "late_or_unreachable"),
    _m(3815, "the default model is not qwen3.5:2b", "config.py",
       '    ai_task_model: str = "qwen3.5:2b"\n', '    ai_task_model: str = "qwen3.5:4b"\n', "default_model"),
    _m(3816, "the keep-alive override is ignored", "model_transport.py",
       '"keep_alive": _keep_alive()}', '"keep_alive": settings.ollama_keep_alive}', "stays_loaded"),
    _m(3817, "an active chat request is not counted", "progress.py",
       '        return sum(1 for e in _entries.values()\n                   if e.stage != "done" and now - e.updated < TTL_SECONDS)',
       '        return sum(1 for e in _entries.values()\n                   if False)', "chat_request_in_progress"),
    _m(3818, "a paused batch loses its jobs", R, "    ensure_schema()\n    pause = pause or pause_reason\n",
       "    ensure_schema()\n    pause = pause or pause_reason\n    _claim_next()\n", "paused_batch"),
)
