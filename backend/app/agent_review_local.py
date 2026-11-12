"""The AI reviewer on the LOCAL model (owner orders, 12 Nov 2026: "both engines for every kind of paper"; "fix local review and
local model as well"). Behind `AGENT_REVIEW_LOCAL_ENGINE_ENABLED` (default off).

ONE SEAM, NOT A SECOND REVIEWER. The reviewer's prompts, batches, parsers, quote checks, guards, classes and CRS code are the Claude
path's own. `agent_review_run.Runner._metered_call` is the single place a request leaves the runner; with a `LocalEngine` it comes here
instead of `agent_claude._call`. This module turns the Claude-shaped request (`system` blocks and `messages`) into one Ollama chat call
and the reply back into the Claude-shaped answer (`{"content": [{"type": "text", "text": ...}], "model", "stop_reason"}`), so every
parser and guard downstream reads exactly what it reads on the Claude path. It differs in four things only: transport (the one local
socket module, `model_transport`), model names, the context budget, and cost (always USD 0.0).

NO NEW OUTBOUND PATH. Every call is `model_transport.post_json_retrying("/api/chat", ...)`: the loopback-validated Ollama address
(`config.check_model_url`), the shared runner options. This module opens no socket, imports no http library, never touches
`reader_transport` or `claude_spend` (so a local call can never write a spend row or count as money) and never reads `backend/.env`.

ONE BIG MODEL AT A TIME, STAGED. Reader A (`agent_review_local_model_a`, default the app's `answer_model`) reads ALL items first (phase
"first"). `to_second()` then unloads A (#666, `model_memory.unload`) and the second reader B (`agent_review_local_model_b`, another
family) reads the candidate lines (phase "second"). A call for the other phase is refused here (`LocalStageRefused`), so a Claude-shaped
step that would interleave the two models (the context check of a Fail, a second opinion, a re-read) is held, never run: its line stays
as the first reader left it. `session()` takes the one heavy lock (`heavy_lock`, kind "agent_review_local") for the whole run and unloads
both models in `finally`.

TWO READERS MEANS TWO FAMILIES. `second_ready()` is False when B is empty, of the same family as A (`agent_run_second.models_differ`)
or not installed; every call to B is then refused (`LocalSecondUnavailable`), so no second answer can exist and no line can be the class
"AI verdict, two readers agree". The class rule (`agent_review_two_reader.agrees`) checks the two stored model names again.

CONTEXT. The window is the shared local window (`model_transport.shared_window`, 8192 by default). A request whose estimated prompt plus
its output limit does not fit is NOT sent (`LOCAL_TOO_LONG`, an `AgentBadReply` that the runner splits by items and, for one item,
reports on the line: "not asked: too long for the local model"). Nothing is cut. Errors and logs carry codes and type names, never text.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
import threading
from collections.abc import Callable
from typing import Any

from . import agent_claude, agent_run_second, heavy_lock, model_memory, model_transport

log = logging.getLogger(__name__)

LOCK_KIND = "agent_review_local"
FIRST, SECOND = "first", "second"
#: What a line says when its request would not fit the local window (never "checked").
LOCAL_TOO_LONG = "not asked: too long for the local model"
#: The one code of the second-reader step when it was switched off because model B could not be a second reader.
OFF_SECOND_UNAVAILABLE = "second_reader_not_available_on_this_computer"
SECOND_UNAVAILABLE_WORDS = "a second reader was not available on this computer (no second local model of another family): lines stay 'AI thinks'"
GENERAL_REFUSED = (
    "the general review (a procedure or a contract with no rule book) does not run on the local model yet; "
    "nothing was asked"
)
CHARS_PER_TOKEN = 3  # conservative, as the repo's other local budget (numbers and JSON tokenise densely)
WINDOW_MARGIN_TOKENS = 256
TIMEOUT_S = 600.0
#: Smaller than the Claude path (it measured 1,000 + 1,100 x items with the reader's own thinking): thinking is off here, and the window
#: is 8k. A reply cut off at its limit is split and retried by the runner exactly as on the Claude path.
FIRST_BATCH_MAX = 3
FIRST_TOKENS_BASE, FIRST_TOKENS_PER_ITEM, FIRST_TOKENS_CAP = 300, 380, 2400
SECOND_BATCH_MAX = 3
SECOND_TOKENS_BASE, SECOND_TOKENS_PER_ITEM, SECOND_TOKENS_CAP = 300, 330, 2000


class LocalError(agent_claude.AgentClaudeError):
    code = "local_error"


class LocalStageRefused(LocalError):
    """A call for the model that is not this stage's: refused so two big models are never loaded together."""

    code = "local_wrong_stage"


class LocalSecondUnavailable(LocalError):
    code = "second_reader_not_available"


class LocalGateClosed(agent_claude.AgentGateClosed):
    """The local engine address was refused (not loopback) or the engine is barred: the run stops, nothing was sent."""

    code = "local_engine_refused"


def models_from_settings() -> tuple[str, str]:
    """(model A, model B) from the settings: A is `agent_review_local_model_a` else the app's `answer_model`; B may be ''."""
    from .config import settings

    a = str(getattr(settings, "agent_review_local_model_a", "") or "").strip()
    b = str(getattr(settings, "agent_review_local_model_b", "") or "").strip()
    return a or str(settings.answer_model).strip(), b


def switch_on() -> bool:
    """True when the local AI reviewer is switched on (`agent_review_local_engine_enabled`) and the AI reviewer itself is."""
    from . import agent_review_gate
    from .config import settings

    return (
        bool(settings.agent_review_local_engine_enabled) and agent_review_gate.enabled()
    )


def local_run(run_id: str) -> bool:
    """True when this run's stored plan puts the AI review on the LOCAL model and the switch is on. A run with no stored plan (the
    older routes), a plan on Claude, or the switch off is a Claude-path run, exactly as before."""
    from . import review_engine
    from .db import connect

    if not switch_on():
        return False
    return review_engine.ai_review_engine(connect(), run_id) == review_engine.ON_LOCAL


def engine_for(run_id: str) -> LocalEngine | None:
    """The local engine of this run (models from the settings), or None for a Claude-path run."""
    return LocalEngine(*models_from_settings()) if local_run(run_id) else None


def second_ready_for(a: str, b: str, installed: bool | None = None) -> tuple[bool, str]:
    """(ready, why not): model B must be named, of another family than A, and not known to be missing."""
    if not b:
        return False, "no second model is set"
    if not agent_run_second.models_differ([a], b):
        return False, "the second model is the same family as the first, or unnamed"
    if installed is False:
        return False, "the second model is not installed"
    return True, ""


def _installed(model: str) -> bool | None:
    """Is `model` listed by the local engine (`/api/tags`)? None when that cannot be read (the call itself will then say)."""
    try:
        got = model_transport.get_json("/api/tags", timeout=10.0, required=False)
    except Exception as exc:  # noqa: BLE001 - a stopped engine is a state, not an error here
        log.warning("local models could not be listed (%s)", type(exc).__name__)
        return None
    if not isinstance(got, dict):
        return None
    names = {
        str(m.get("name") or m.get("model") or "")
        for m in got.get("models") or []
        if isinstance(m, dict)
    }
    wanted = model if ":" in model else model + ":latest"
    return model in names or wanted in names


def _text_of_blocks(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "\n\n".join(
        str(b.get("text") or "")
        for b in content or []
        if isinstance(b, dict) and b.get("type") == "text"
    )


def chat_messages(parts: dict) -> list[dict]:
    """The Claude-shaped request (`system` blocks, `messages` of text blocks) as Ollama chat messages. Text blocks only (the AI
    reviewer's requests hold nothing else); a block of any other type is left out and its absence is the caller's `fits` check's
    concern, never hidden: it cannot occur in this reviewer's request builders."""
    out: list[dict] = []
    system = _text_of_blocks(parts.get("system"))
    if system:
        out.append({"role": "system", "content": system})
    for m in parts.get("messages") or []:
        out.append(
            {
                "role": str(m.get("role") or "user"),
                "content": _text_of_blocks(m.get("content")),
            }
        )
    return out


class LocalEngine:
    """The local transport of one run. `post`, `unload` and `installed` are the test seams (defaults: `model_transport`,
    `model_memory`, the engine's own list)."""

    def __init__(
        self,
        model_a: str,
        model_b: str = "",
        *,
        post: Callable[..., Any] | None = None,
        unload: Callable[[str], Any] | None = None,
        installed: Callable[[str], bool | None] | None = None,
        window: int | None = None,
    ) -> None:
        self.model_a, self.model_b = model_a.strip(), (model_b or "").strip()
        self._post = post
        self._unload = unload or model_memory.unload
        self._window = window
        self._lock = threading.Lock()
        self.phase = FIRST
        self.loaded: str | None = None
        self.calls = {FIRST: 0, SECOND: 0}
        self.not_asked = 0
        self.unloads: list[str] = []
        self._ready: tuple[bool, str] | None = None
        self._installed_of = installed or _installed

    # ---- readiness of the second reader
    def second_ready(self) -> tuple[bool, str]:
        if self._ready is None:
            known = self._installed_of(self.model_b) if self.model_b else None
            self._ready = second_ready_for(self.model_a, self.model_b, known)
        return self._ready

    # ---- budget
    def window(self) -> int:
        return int(self._window or model_transport.shared_window())

    def fits(self, parts: dict, max_tokens: int) -> bool:
        chars = sum(len(m["content"]) for m in chat_messages(parts))
        return (
            chars // CHARS_PER_TOKEN + 1 + int(max_tokens) + WINDOW_MARGIN_TOKENS
            <= self.window()
        )

    def first_tokens(self, n_items: int) -> int:
        return min(
            FIRST_TOKENS_CAP, FIRST_TOKENS_BASE + FIRST_TOKENS_PER_ITEM * n_items
        )

    def second_tokens(self, n_items: int) -> int:
        return min(
            SECOND_TOKENS_CAP, SECOND_TOKENS_BASE + SECOND_TOKENS_PER_ITEM * n_items
        )

    # ---- stages
    def to_second(self) -> None:
        """First reader finished: unload A, so B is the only big model loaded."""
        with self._lock:
            self._drop_loaded()
            self.phase = SECOND

    def _drop_loaded(self) -> None:
        if self.loaded:
            name, self.loaded = self.loaded, None
            self.unloads.append(name)
            try:
                self._unload(name)
            except Exception as exc:  # noqa: BLE001 - never replaces the run's own result; the type name only
                log.warning("local model unload failed (%s)", type(exc).__name__)

    @contextlib.contextmanager
    def session(self, wait_seconds: float | None = None):
        """The one heavy lock around the run; both models are unloaded in `finally`, even when the run raises."""
        wait = (
            heavy_lock.wait_seconds_from_env() if wait_seconds is None else wait_seconds
        )
        with heavy_lock.held(LOCK_KIND, wait_seconds=wait):
            try:
                yield self
            finally:
                with self._lock:
                    self._drop_loaded()
                    for name in (self.model_a, self.model_b):
                        if name and name not in self.unloads:
                            with contextlib.suppress(Exception):
                                self._unload(name)

    # ---- the one call
    def call(self, model: str, parts: dict, max_tokens: int) -> tuple[dict, float]:
        """One local request. `model` is the name the runner asked for: the first reader's own name is model A; any other name (the
        Claude second/final constants of the shared code) is model B. Returns (Claude-shaped answer, 0.0)."""
        role = FIRST if model == self.model_a else SECOND
        if role != self.phase:
            raise LocalStageRefused
        if role == SECOND:
            ready, _why = self.second_ready()
            if not ready:
                raise LocalSecondUnavailable
            name = self.model_b
        else:
            name = self.model_a
        if not self.fits(parts, max_tokens):
            with self._lock:
                self.not_asked += 1
            exc = agent_claude.AgentBadReply(LOCAL_TOO_LONG)
            exc.usd = 0.0
            raise exc
        body = {
            "model": name,
            "messages": chat_messages(parts),
            "stream": False,
            "think": False,
            "format": "json",
            "options": {"temperature": 0, "num_predict": int(max_tokens)},
        }
        with self._lock:  # one request at a time: one big model, one runner
            if self.loaded and self.loaded != name:
                self._drop_loaded()
            self.loaded = name
            self.calls[role] += 1
            answer = self._send(body)
        message = answer.get("message") if isinstance(answer, dict) else None
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str) or not text.strip():
            exc = agent_claude.AgentBadReply("bad_shape")
            exc.usd = 0.0
            raise exc
        if answer.get("done_reason") == "length":
            exc = agent_claude.AgentBadReply("stop_max_tokens")
            exc.usd = 0.0
            raise exc
        answered = answer.get("model")
        return {
            "content": [{"type": "text", "text": text}],
            "model": answered.strip()
            if isinstance(answered, str) and answered.strip()
            else "unknown",
            "stop_reason": "end_turn",
            "usage": {},
        }, 0.0

    def _send(self, body: dict) -> Any:
        post = self._post or model_transport.post_json_retrying
        try:
            return post("/api/chat", body, timeout=TIMEOUT_S)
        except (model_transport.ModelHostRefused, model_transport.LocalEngineNotLoaded):
            raise LocalGateClosed from None
        except Exception as exc:  # noqa: BLE001 - the type name only; the text may carry a host or a status
            raise agent_claude.AgentTransportError(
                "transport_" + type(exc).__name__
            ) from None


#: Honest time words: nothing has been measured on this install, so the number is a labelled guess (rule 4).
SECONDS_GUESS_PER_REQUEST = 60


def local_time(conn, document_id: str) -> dict:
    """The time of the AI review on the local model, in honest words: the number of requests from the rules the paper's last AI review
    asked (None when there is none), and a labelled GUESS of the minutes (nothing is measured on this install yet; CLAUDE.md rule 4)."""
    try:
        row = conn.execute(
            "SELECT a.items_total FROM agent_review_run a JOIN review_runs r ON r.id = a.run_id"
            " WHERE r.submittal_document_id = ? AND a.items_total IS NOT NULL ORDER BY r.started_at DESC LIMIT 1",
            (document_id,),
        ).fetchone()
    except sqlite3.Error:
        row = None
    if row is None or not row["items_total"]:
        return {
            "requests": None,
            "minutes_guess": None,
            "basis": "the rules to ask are chosen when the review starts, so the time is not known yet; each request to the local model is one"
            " at a time and the review needs a few minutes for every ten rules or more (a guess, not measured on this install)",
        }
    n = int(row["items_total"])
    first = -(-n // FIRST_BATCH_MAX)
    second = -(
        -n // (2 * SECOND_BATCH_MAX)
    )  # at most about half the lines are asked a second time
    requests = first + second
    return {
        "requests": requests,
        "minutes_guess": round(requests * SECONDS_GUESS_PER_REQUEST / 60),
        "basis": f"up to about {requests} requests to the local model, one at a time, if the same {n} rules are asked again; the minutes are a"
        f" guess of {SECONDS_GUESS_PER_REQUEST} seconds a request, not measured on this install",
    }
