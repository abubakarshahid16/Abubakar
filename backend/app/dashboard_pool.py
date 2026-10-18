"""The dashboard's heavy reads get their own few threads (order 84-1, #626).

Every plain `def` route waits for one of the server's shared worker threads
(Starlette's default limiter: 40). Measured in the owner's app while a review
ran: /api/risks 53-86 s, /api/metrics 15-82 s, /api/reviews/runs 64 s - and
/api/health 52 s, although health itself does almost nothing. It was waiting
for a thread. The screens poll these routes, and in dev mode React StrictMode
fires every call twice, so slow dashboard reads pile up until the shared pool
is gone and everything else queues behind them.

`heavy_route` runs a route on THIS module's small limiter instead. When the
dashboard reads pile up, they queue behind each other, never in front of
health, sign-in or the page lists. The route's own code is unchanged.
"""
from __future__ import annotations

import asyncio
import functools
import weakref
from collections.abc import Callable
from typing import Any

import anyio.to_thread
from anyio import CapacityLimiter
from starlette.requests import Request

#: Threads the heavy dashboard reads may hold at once, all of them together.
DASHBOARD_THREADS = 8

# One limiter per event loop: an anyio limiter belongs to the loop it was
# made in, and the test client starts a new loop per client.
_limiters: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def limiter() -> CapacityLimiter:
    loop = asyncio.get_running_loop()
    found = _limiters.get(loop)
    if found is None:
        found = _limiters[loop] = CapacityLimiter(DASHBOARD_THREADS)
    return found


def _same_question(fn: Callable[..., Any], kwargs: dict) -> tuple | None:
    """The key under which identical calls share one answer, or None.

    The caller's whole `AccessScope` (frozen: user, grants, capabilities) is
    part of the key, so an answer is only ever shared with a caller whose
    scope is IDENTICAL - never across users or grants. A request counts by
    its full URL (path and query)."""
    parts = []
    for name, value in sorted(kwargs.items()):
        if isinstance(value, Request):
            value = str(value.url)
        try:
            hash(value)
        except TypeError:
            return None
        parts.append((name, value))
    return (fn.__module__, fn.__qualname__, tuple(parts))


def heavy_route(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Run the sync route `fn` on the dashboard limiter. FastAPI reads the
    parameters through `functools.wraps`, so the route's signature, its
    dependencies and its response model are unchanged.

    SINGLE-FLIGHT: a call identical to one still running waits for that one's
    answer instead of starting the same work again (doubled StrictMode calls,
    two tabs, a poll that fires while the last one is still running). Nothing
    is kept once the call ends - this is not a cache."""
    @functools.wraps(fn)
    async def on_dashboard_threads(*args: Any, **kwargs: Any) -> Any:
        key = None if args else _same_question(fn, kwargs)
        key = key and (id(asyncio.get_running_loop()), key)
        running = _in_flight.get(key) if key is not None else None
        if running is not None:
            return await asyncio.shield(running)
        task = asyncio.ensure_future(anyio.to_thread.run_sync(
            functools.partial(fn, *args, **kwargs), limiter=limiter()))
        if key is not None:
            _in_flight[key] = task
            task.add_done_callback(lambda _t: _in_flight.pop(key, None))
        return await asyncio.shield(task)
    return on_dashboard_threads


#: Calls still running, by `_same_question` key. Touched only on the event
#: loop's own thread, so it needs no lock.
_in_flight: dict[tuple, asyncio.Future] = {}
