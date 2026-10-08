"""#626 "background work must not make every request slow": each entry deletes
one fix; backend/tests/test_w7_626_background_load.py must notice."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w7_626_background_load.py"
_TAG = ("w7", "reliability")


def _m(i, desc, path, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=APP / path,
                    anchor=anchor, replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(3001, "the metrics probe builds a new HTTP client on every call again",
       "model_transport.py",
       "    response = _shared_client().get(url, timeout=timeout)\n",
       "    with httpx.Client(follow_redirects=False, trust_env=False) as _c:\n        response = _c.get(url, timeout=timeout)\n",
       "reuses_one_http_client"),
    _m(3002, "the shared client ignores the per-call timeout",
       "model_transport.py",
       "    response = _shared_client().get(url, timeout=timeout)\n",
       "    response = _shared_client().get(url)\n",
       "per_call_timeout"),
    _m(3003, "the Ollama probe answer is never cached",
       "metrics.py",
       "        if hit and hit[\"key\"] == key and now - hit[\"at\"] < OLLAMA_PROBE_TTL_SECONDS:\n",
       "        if False:\n",
       "cached_and_asked_again"),
    _m(3004, "the cached Ollama answer never expires",
       "metrics.py",
       "and now - hit[\"at\"] < OLLAMA_PROBE_TTL_SECONDS:\n",
       "and True:\n",
       "cached_and_asked_again"),
    _m(3005, "a changed host or model is not asked again",
       "metrics.py",
       "        if hit and hit[\"key\"] == key and now",
       "        if hit and now",
       "changed_host_or_model"),
    _m(3006, "the risk detection job no longer pauses between batches",
       "risks.py",
       "        if start:\n            _pause_between_batches()\n",
       "        if False:\n            _pause_between_batches()\n",
       "pauses_between_batches"),
    _m(3007, "the pause between batches is not a sleep",
       "risks.py",
       "    time.sleep(RISK_BATCH_PAUSE_SECONDS)\n",
       "    pass\n",
       "real_sleep"),
    _m(3008, "risk detection no longer logs its start and duration",
       "risks.py",
       '    log.info("risk detection started")\n',
       "",
       "risk_detection_logs"),
    _m(3009, "the acronym warm-up no longer logs its duration",
       "acronyms.py",
       '                log.info("acronym warm-up finished in %.1fs, %d document map(s) built",\n                         time.monotonic() - started, built)\n',
       "                pass\n",
       "acronym_warm_up_logs"),
    _m(3010, "the startup warm-up no longer logs each step",
       "warmup.py",
       '            log.info("startup warm-up step %r started", name)\n',
       "",
       "startup_warm_up_logs"),
)
