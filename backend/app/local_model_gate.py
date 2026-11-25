"""THE LOCAL MODEL GATE between the worker's two lanes (planner 19 Nov 2026 01:02, GitHub #1913): one large local model at a time.

The worker runs two lanes on two threads: the UPLOAD lane (page reading, picture reading by the OCR engine, rule extraction of a
new standard: none of these loads the large model) and the REVIEW lane (a review can hold the large local model for minutes). A
local model call (`model_transport.post_json` / `stream_json`, the one path to the local engine) made inside a lane passes this gate:

  * calls of ONE lane share the model (a review's side-by-side calls are not slowed);
  * a call of the other lane waits until the holding lane has no call in flight (so the two lanes never run two large models);
  * a lane that waits goes next: the holding lane starts no new call while the other lane waits (no lane waits for ever).

A call made outside a lane (a chat request, a script, a test) is not gated, exactly as before. Nothing here reads, logs or sends
document content; the gate holds only lane names and counts.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from contextvars import ContextVar

REVIEW = "review"
UPLOAD = "upload"

#: The lane of the work running in this context (`lane`): None outside the worker. A thread started with a COPY of a review's
#: context (`aim_review.parallel`) is in the review lane too.
_LANE: ContextVar[str | None] = ContextVar("local_model_lane", default=None)


class _Gate:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self.holder: str | None = None
        self.in_flight = 0
        self.waiting: dict[str, int] = {}
        #: The lane whose turn it is when the model is free: the lane that waited while the other held it.
        self.turn: str | None = None

    def _others_wait(self, lane: str) -> bool:
        return any(n for name, n in self.waiting.items() if name != lane)

    def enter(self, lane: str) -> None:
        with self._cond:
            self.waiting[lane] = self.waiting.get(lane, 0) + 1
            try:
                while not (
                    (self.holder is None and self.turn in (None, lane))
                    or (self.holder == lane and not self._others_wait(lane))
                ):
                    self._cond.wait()
            finally:
                self.waiting[lane] -= 1
            self.holder = lane
            if self.turn == lane:
                self.turn = None
            self.in_flight += 1

    def leave(self) -> None:
        with self._cond:
            self.in_flight -= 1
            if self.in_flight <= 0:
                held = self.holder
                self.in_flight = 0
                self.holder = None
                # the model is free: a lane that waited while `held` had it goes next
                self.turn = next(
                    (
                        name
                        for name, n in sorted(self.waiting.items())
                        if n and name != held
                    ),
                    None,
                )
                self._cond.notify_all()

    def blocked(self, lane: str) -> bool:
        """A call of `lane` waits now while another lane holds the model."""
        with self._cond:
            return bool(self.waiting.get(lane)) and self.holder not in (None, lane)


_GATE = _Gate()


@contextmanager
def lane(name: str):
    """Run the block in lane `name` (the worker's lane threads)."""
    token = _LANE.set(name)
    try:
        yield
    finally:
        _LANE.reset(token)


def current() -> str | None:
    return _LANE.get()


@contextmanager
def holding():
    """Around ONE local model call: waits at the gate when this context is in a lane; passes at once outside the worker."""
    name = _LANE.get()
    if name is None:
        yield
        return
    _GATE.enter(name)
    try:
        yield
    finally:
        _GATE.leave()


def blocked(name: str) -> bool:
    """Is lane `name` waiting for the model while the other lane holds it (the Dashboard's "busy with a review: N uploads
    waiting")?"""
    return _GATE.blocked(name)
