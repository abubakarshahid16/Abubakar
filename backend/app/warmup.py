"""Background warm-up at startup: models and acronym maps, off the request path.

WHY. Nothing was warm when the server started (perf audit item 4). The first
question paid the e5 session load (1.0-1.35 s), the reranker's, and a harvest
of every acronym in the corpus (1-10 s). The lifespan DID try the last one -
`acronyms_mod.harvest()` - but `harvest` requires `allowed_document_ids`, so
the call raised TypeError, `except Exception: pass` swallowed it, and the
comment above it ("done once at startup") stayed true on paper only.

THREE RULES, each held by a test:

1. NEVER BLOCKS THE SERVER START. It runs in a daemon thread started after the
   worker; `start()` returns at once, whatever the steps then do.
2. NEVER WRITES THE DATABASE. Every step only reads: the acronym maps are
   built from `SELECT`s, and the two models see a fixed, non-document string.
   Warm-up is where a write would be least expected and least noticed, so the
   test watches every statement it issues.
3. NEVER FAILS SILENTLY. A step that raises is logged with its traceback and
   recorded in `status()`; the other steps still run.
"""

from __future__ import annotations

import logging
import threading
import time

from .config import settings

log = logging.getLogger("uvicorn.error")

#: A fixed string, so no document text is ever what warms a model.
_PROBE = "warm-up probe"

_lock = threading.Lock()
_thread: threading.Thread | None = None
#: step name -> {"ok": bool, "seconds": float, "error": str | None}
_status: dict[str, dict] = {}


def _embedder() -> None:
    from .embedder import Embedder, EmbedderConfig

    Embedder.instance(EmbedderConfig()).embed_queries([_PROBE])


def _reranker() -> None:
    from . import reranker

    reranker.rerank(_PROBE, [("warm-up", _PROBE)])
    reason = reranker.unavailable_reason()
    if reason:
        raise RuntimeError(f"reranker unavailable: {reason}")


def _acronyms() -> None:
    from . import acronyms
    from .search import every_document_id

    # THE WHOLE CORPUS, BECAUSE THE CACHE IS PER DOCUMENT. Every caller's map
    # is a union of per-document maps, so harvesting every document once warms
    # every scope - including the narrowest - without serving anyone a map
    # built from documents they cannot read.
    acronyms.harvest(allowed_document_ids=every_document_id())


#: Order matters only for what the first question needs soonest.
STEPS: tuple[tuple[str, object], ...] = (
    ("embedder", _embedder),
    ("reranker", _reranker),
    ("acronyms", _acronyms),
)


def _run(steps) -> None:
    from . import db

    try:
        for name, step in steps:
            started = time.perf_counter()
            log.info("startup warm-up step %r started", name)
            try:
                step()
            except Exception as exc:  # noqa: BLE001 - logged and recorded, never swallowed
                log.exception("startup warm-up step %r failed", name)
                result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            else:
                result = {"ok": True, "error": None}
            result["seconds"] = round(time.perf_counter() - started, 3)
            log.info("startup warm-up step %r %s in %.1fs", name,
                     "finished" if result["ok"] else "FAILED", result["seconds"])
            with _lock:
                _status[name] = result
    finally:
        # This thread's connection is not needed again; closing it keeps the
        # database files free (Windows will not delete an open file).
        db.close_thread_connection()


def start(steps=None) -> threading.Thread | None:
    """Start the warm-up in a daemon thread and return at once.

    Returns None when `settings.startup_warmup` is off - which is itself
    recorded, so `status()` never reads as "warmed" when nothing ran.
    """
    global _thread
    with _lock:
        _status.clear()
        if not settings.startup_warmup:
            _status["disabled"] = {"ok": True, "seconds": 0.0,
                                   "error": "STARTUP_WARMUP is off"}
            return None
    thread = threading.Thread(
        target=_run, args=(steps if steps is not None else STEPS,),
        name="startup-warmup", daemon=True)
    thread.start()
    _thread = thread
    return thread


def status() -> dict[str, dict]:
    """What each step did, for a test or a health view. A copy."""
    with _lock:
        return {k: dict(v) for k, v in _status.items()}
