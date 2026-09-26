"""A streamed chat turn: its events, its Stop, and the sentence gate.

OWNER ORDER 2026-09-26 (chat redesign, 2e). While an answer is being written
the reader sees real progress (the pipeline's own stages), the text as it
arrives, and a Stop that really stops the provider call. This module holds the
state one streamed turn needs and nothing else:

  * a TURN - id, owner, conversation, a `cancel` Event, and a queue of events
    the SSE route drains. Registered so the cancel route can find it; only its
    owner may stop it (the same identity rule as progress, P5).
  * the CURRENT turn, as a context variable bound for the worker thread that
    answers it - so the model call picks it up (`chat_model.generate`) with no
    new parameter threaded through the pipeline.
  * the SENTENCE GATE. General text is streamed as it arrives. A DOCUMENT
    answer on the Claude lane is buffered per sentence and a sentence is sent
    only once its quote verifies on the page it cites - exactly the check the
    final answer gets (`answer.verify_claims`), so the reader never sees a
    claim the finished answer will not contain. On the local lane an invented
    source number is dropped as it streams.

The `done` event carries the complete answer, built by the same code as the
non-streaming route; the streamed text is a preview of it, never a second
version.
"""
from __future__ import annotations

import contextvars
import queue
import re
import threading
import time
import uuid
from dataclasses import dataclass, field

#: How long a finished turn stays findable (for a late cancel), seconds.
TTL_SECONDS = 300
MAX_TURNS = 256

#: A sentence ends at . ! ? followed by space, or at a newline - but never
#: inside an open citation bracket, whose quoted words may contain either.
_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n")


@dataclass
class Turn:
    id: str
    owner: str | None
    conversation_id: str
    cancel: threading.Event = field(default_factory=threading.Event)
    events: queue.Queue = field(default_factory=queue.Queue)
    created: float = field(default_factory=time.time)
    #: What the reader has been shown - the partial answer if they stop.
    shown: list[str] = field(default_factory=list)
    _buffer: str = ""
    #: Set by the pipeline just before the model is called.
    passages: list[dict] | None = None
    verify: bool = False
    general: bool = False

    def emit(self, event: str, data: dict) -> None:
        self.events.put((event, data))

    def close(self) -> None:
        self.events.put(None)

    # ------------------------------------------------------ the sentence gate
    def prepare(self, *, passages: list[dict] | None, verify: bool, general: bool) -> None:
        """What the next model text is: which passages it may cite, and
        whether its sentences must pass the quote check before they show."""
        self.passages, self.verify, self.general = passages, verify, general
        self._buffer = ""
        self.shown = []

    def text(self, delta: str) -> None:
        """A piece of model text. Complete sentences are passed on; the rest waits."""
        self._buffer += delta
        start = 0
        for match in _BOUNDARY.finditer(self._buffer):
            piece = self._buffer[start:match.start()]
            if piece.count("[") > piece.count("]"):
                continue          # inside [S1 "...": wait for the bracket to close
            self._release(piece)
            start = match.end()
        self._buffer = self._buffer[start:]

    def discard(self) -> None:
        self._buffer = ""

    def flush(self) -> None:
        if self._buffer.strip():
            self._release(self._buffer)
        self._buffer = ""

    def _release(self, sentence: str) -> None:
        from . import answer as answer_mod

        if not sentence.strip():
            return
        if self.general:
            clean = answer_mod.drop_citations(sentence)
        elif self.verify:
            clean, _verification, _claims, _removed = answer_mod.verify_claims(
                sentence, self.passages or [])
        else:
            n = len(self.passages or [])
            clean = answer_mod._CITATION.sub(
                lambda m: m.group(0) if 1 <= int(m.group(1)) <= n else "", sentence)
        if clean.strip():
            self.shown.append(clean.strip())
            self.emit("delta", {"text": clean.strip() + " "})


_lock = threading.Lock()
_turns: dict[str, Turn] = {}
_current: contextvars.ContextVar[Turn | None] = contextvars.ContextVar("chat_turn", default=None)


def open_turn(*, owner: str | None, conversation_id: str) -> Turn:
    turn = Turn(id=f"turn_{uuid.uuid4().hex[:12]}", owner=owner, conversation_id=conversation_id)
    now = time.time()
    with _lock:
        _turns[turn.id] = turn
        for key in [k for k, t in _turns.items() if now - t.created >= TTL_SECONDS]:
            _turns.pop(key, None)
        while len(_turns) > MAX_TURNS:
            _turns.pop(min(_turns, key=lambda k: _turns[k].created), None)
    return turn


def find(turn_id: str, *, owner: str | None, unrestricted: bool = False) -> Turn | None:
    """The turn, or None when it does not exist OR is someone else's - the
    same answer, so a turn id cannot be probed."""
    with _lock:
        turn = _turns.get(turn_id)
    if turn is None or (not unrestricted and turn.owner != owner):
        return None
    return turn


def bind(turn: Turn):
    return _current.set(turn)


def unbind(token) -> None:
    _current.reset(token)


def current() -> Turn | None:
    return _current.get()


def cancelled() -> bool:
    turn = _current.get()
    return bool(turn and turn.cancel.is_set())
