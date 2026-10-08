"""What the machine is doing right now, recorded when it actually happens.

A Tier 2 answer takes 20-75 s on this hardware and the screen showed one
spinner for all of it, which a reader interprets as broken. The fix is to say
what is happening - and the only honest way to do that is to have the work
ITSELF report each transition, rather than have the screen guess from a clock.

WHY NOT INFER IT FROM ELAPSED TIME. Retrieval typically finishes in about
2.5 s and generation takes the rest, so a client could show "reranking" at
t=3 s and be right most of the time. Most of the time is the problem: on the
run where retrieval is slow, the screen would claim the model was generating
while the search was still going, and a reader who later sees a 40 s retrieval
in the timings has been told something false. Progress that is inferred is
progress that is invented, and this file exists so it does not have to be.

IN MEMORY, BOUNDED, AND NOT DURABLE. A stage record is worth nothing a second
after the answer arrives, so nothing is written to the database - the SQLite
file is what ingestion is writing to, and a row per stage per question would
put an unauthenticated writer in front of it. Entries expire, and the map is
capped so a client that starts requests and never collects them cannot grow it
without bound.

IT IS NOT A PERCENTAGE. There is no total to divide by: the generation length
is unknown until it ends. The reader gets the stage, the passage count and a
counter, all of which are true, instead of a bar that is a guess.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

#: How long a finished or abandoned entry survives. Long enough for a client
#: polling once a second to collect the final stage, short enough that an
#: abandoned request is forgotten.
TTL_SECONDS = 120

#: A hard cap. Reached only by a caller that starts work and never finishes it;
#: the oldest are dropped first.
MAX_ENTRIES = 256

#: The stages this pipeline actually has. A stage not in here cannot be
#: reported, so a typo becomes an error rather than a label nobody notices.
STAGES = (
    "retrieving",      # keyword + dense, before fusion
    "reranking",       # the cross-encoder, one batch
    "reading",         # passages selected; evidence being prepared
    "generating",      # the local model is producing tokens
    "done",
)


@dataclass
class _Entry:
    started: float
    #: P5: who started it. Only the same identity may read it back.
    owner: str | None = None
    stage: str = "retrieving"
    detail: str | None = None
    #: (stage, seconds since start) for every transition that HAPPENED.
    history: list[tuple[str, float]] = field(default_factory=list)
    updated: float = 0.0


_lock = threading.Lock()
_entries: dict[str, _Entry] = {}
#: A streamed chat turn listens to its own request's stages (chat_stream).
_listeners: dict[str, object] = {}


def listen(request_id: str, fn) -> None:
    """Call `fn(stage, detail)` on every stage this request reaches."""
    with _lock:
        _listeners[request_id] = fn


def unlisten(request_id: str) -> None:
    with _lock:
        _listeners.pop(request_id, None)


def _evict(now: float) -> None:
    """Called under the lock."""
    # `>=`, not `>`. time.time() on Windows is coarse enough that an entry
    # written microseconds ago reports an age of exactly 0.0, so a TTL of zero
    # would never expire anything under `>`. At the real TTL of 120 s the two
    # are indistinguishable.
    for key in [k for k, e in _entries.items() if now - e.updated >= TTL_SECONDS]:
        _entries.pop(key, None)
    while len(_entries) > MAX_ENTRIES:
        oldest = min(_entries, key=lambda k: _entries[k].updated)
        _entries.pop(oldest, None)


def start(request_id: str | None, owner: str | None = None) -> None:
    if not request_id:
        return
    now = time.time()
    with _lock:
        _entries[request_id] = _Entry(started=now, updated=now, owner=owner,
                                      history=[("retrieving", 0.0)])
        # AFTER the insert. Evicting first leaves MAX_ENTRIES + 1 in the map,
        # which is not a cap.
        _evict(now)


def stage(request_id: str | None, name: str, detail: str | None = None) -> None:
    """Record a transition that has just happened.

    Never raises into the request path: a progress bookkeeping error must not
    fail the answer it is describing.
    """
    if not request_id:
        return
    if name not in STAGES:
        raise ValueError(f"unknown stage {name!r}; add it to STAGES first")
    now = time.time()
    with _lock:
        entry = _entries.get(request_id)
        if entry is None:
            return
        entry.stage = name
        entry.detail = detail
        entry.updated = now
        entry.history.append((name, round(now - entry.started, 3)))
        listener = _listeners.get(request_id)
    if listener is not None:
        try:
            listener(name, detail)
        except Exception:  # noqa: BLE001 - a listener never fails the answer it describes
            pass


def finish(request_id: str | None) -> None:
    stage(request_id, "done")


def read(request_id: str, *, reader: str | None = None,
         unrestricted: bool = False) -> dict | None:
    """The entry, or None when it does not exist OR belongs to someone else -
    the same answer, so an id cannot be probed for another user's activity."""
    now = time.time()
    with _lock:
        entry = _entries.get(request_id)
        if entry is None:
            return None
        if not unrestricted and entry.owner != reader:
            return None
        return {
            "stage": entry.stage,
            "detail": entry.detail,
            "seconds": round(now - entry.started, 1),
            "history": [{"stage": s, "at_seconds": t} for s, t in entry.history],
        }


def clear() -> None:
    """For tests."""
    with _lock:
        _entries.clear()
