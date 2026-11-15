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
import math
import re
import sqlite3
import threading
import uuid
from collections import Counter
from collections.abc import Callable
from typing import Any

from . import (
    agent_claude,
    agent_run_second,
    context_budget,
    heavy_lock,
    model_memory,
    model_transport,
)

log = logging.getLogger(__name__)

LOCK_KIND = "agent_review_local"
FIRST, SECOND = "first", "second"
#: What a line says when its request would not fit the local window (never "checked").
LOCAL_TOO_LONG = "not asked: too long for the local model"
#: What a reader of the sheet sees for such a line: nothing was called, so it is never "AI call failed".
NOT_ASKED_WORDS = "Not asked: too long for the local model. Not reviewed"
NOT_ASKED_CODE = "not_asked_too_long"


def failed_words(error: object) -> str:
    """Why a line has no answer. A request the local engine could not take was never called: it says so, never "AI call failed"."""
    return NOT_ASKED_WORDS if error == LOCAL_TOO_LONG else f"AI call failed: {error}"


#: The one code of the second-reader step when it was switched off because model B could not be a second reader.
OFF_SECOND_UNAVAILABLE = "second_reader_not_available_on_this_computer"
SECOND_UNAVAILABLE_WORDS = "a second reader was not available on this computer (no second local model of another family): lines stay 'AI thinks'"
#: TRUNCATION GUARD, three nets. (1) The SEND decision uses the repo's own fail-safe estimate (`context_budget.estimate_tokens`: a digit
#: costs a token each, letters 3.5 to a token; it may over-estimate and must never under-estimate) for the whole prompt plus the output
#: limit plus a margin; a request over the window is not sent. (2) After every call the engine's own `prompt_eval_count` is read from the
#: JSON `model_transport` returns. `context_budget` measured that on an overflow the engine reports a count BELOW the window (1,026 of
#: 1,536, 33% under), so a count at the window is not the test: an answer is thrown away when the count is missing, when it is at or over
#: CUT_FRACTION of the window (a prompt admitted by (1) is at most about 0.7 of its estimate for prose; one that reads that full of the
#: window is treated as cut, the safe side), or when it is below the lower bound of what the prompt must cost (a digit is at least a
#: third of a token, other text at least a sixteenth of a token a character). (3) A per-call nonce starts the system text so the engine's
#: prompt cache can never make a full prompt look short.
CUT_FRACTION = 0.6
#: The general review on the local engine: windows of pages, checklist batches and project-paper groups that fit the window under the
#: engine's output ceiling (units: `agent_general_review.tokens_of`, characters / 4). A paper longer than one window is read in windows;
#: the sheet says which pages were and were not read.
GENERAL_WINDOW_TOKENS = 2600
GENERAL_P2_BATCH = 3
GENERAL_GROUP_TOKENS = 1200
GENERAL_OUTPUT_CAP = 1400
MIN_CHARS_PER_DIGIT_TOKEN, MIN_CHARS_PER_WORD_TOKEN = 3, 16
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


def engine_for(run_id: str, general: bool = False) -> LocalEngine | None:
    """The local engine of this run (models from the settings), or None for a Claude-path run. `general`: the general review, whose
    windows fit under `GENERAL_OUTPUT_CAP`, the ceiling put on every request's output limit."""
    if not local_run(run_id):
        return None
    return LocalEngine(
        *models_from_settings(), output_cap=GENERAL_OUTPUT_CAP if general else None
    )


_ROOT = re.compile(r"[a-z]+")


def families_of(show: Any) -> set[str] | None:
    """The family words the local engine itself reports for a model (`/api/show`: `details.family`, `details.families`, the architecture),
    each reduced to its leading letters (`qwen35moe` and `qwen3` are `qwen`). None when the answer holds none (unknown: fails closed)."""
    if not isinstance(show, dict):
        return None
    details = show.get("details") if isinstance(show.get("details"), dict) else {}
    info = show.get("model_info") if isinstance(show.get("model_info"), dict) else {}
    raw = [
        details.get("family"),
        *(details.get("families") or []),
        info.get("general.architecture"),
    ]
    roots = {
        m.group(0)
        for x in raw
        if isinstance(x, str) and (m := _ROOT.match(x.strip().lower()))
    }
    return roots or None


def _show(model: str) -> dict | None:
    """The engine's own data for a model (`/api/show`, through `model_transport`: the one validated loopback socket). None when it cannot be
    read (not installed, engine down, host refused): the caller fails closed."""
    try:
        got = model_transport.post_json("/api/show", {"model": model}, timeout=15.0)
    except Exception as exc:  # noqa: BLE001 - a stopped engine or a missing model is a state, not an error here
        log.warning("local model details could not be read (%s)", type(exc).__name__)
        return None
    return got if isinstance(got, dict) else None


def busy_words(exc: heavy_lock.HeavyJobBusy) -> str:
    """The stop sentence of a run that never got the heavy lock: plain words, never a type name."""
    return f"another heavy job held the computer for {int(exc.waited / 60)} minutes; start again later"


def progress_writer(run_id: str) -> Callable[[str], None]:
    """A callback that writes the screen's progress label of this run's job (counts only), on the calling thread's own connection."""

    def write(label: str) -> None:
        from .db import connect

        with connect() as conn:
            conn.execute(
                "UPDATE jobs SET progress_label = ? WHERE review_run_id = ? AND state = 'running'",
                (label, run_id),
            )

    return write


LOCAL_REVIEW_NOTE = "A local review is running; answers may be slower."


def review_running() -> bool:
    """Is a local AI review holding the heavy lock right now? (the chat's model menu says so: it shares the local engine)"""
    rec = heavy_lock.read()
    return bool(rec and rec.get("kind") == LOCK_KIND and not heavy_lock.is_stale(rec))


def second_ready_for(
    a: str, b: str, show_a: Any = None, show_b: Any = None
) -> tuple[bool, str]:
    """(ready, why not). FAILS CLOSED: model B must be named and installed, and the local engine's own data for BOTH models must be
    readable and share no family word. The name rule (`agent_run_second.models_differ`) is checked too and can only make it stricter."""
    if not b:
        return False, "no second model is set"
    fa, fb = families_of(show_a), families_of(show_b)
    if show_b is None:
        return False, "the second model is not installed or its details cannot be read"
    if fa is None or fb is None:
        return False, "the family of a model is not known from the local engine"
    if fa & fb:
        return False, "the second model is the same family as the first"
    if not agent_run_second.models_differ([a], b):
        return False, "the second model is the same family as the first, or unnamed"
    return True, ""


def _text_of_blocks(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "\n\n".join(
        str(b.get("text") or "")
        for b in content or []
        if isinstance(b, dict) and b.get("type") == "text"
    )


def _too_long() -> agent_claude.AgentBadReply:
    exc = agent_claude.AgentBadReply(LOCAL_TOO_LONG)
    exc.usd = 0.0
    return exc


def lower_bound_tokens(text: str) -> int:
    """The fewest tokens `text` can cost any tokenizer of the models in use: a digit at least a third of a token, any other character at
    least a sixteenth. A reply that says the prompt was smaller than this was cut."""
    digits = sum(ch.isdigit() for ch in text)
    return (
        digits // MIN_CHARS_PER_DIGIT_TOKEN
        + (len(text) - digits) // MIN_CHARS_PER_WORD_TOKEN
    )


def _cut_prompt(reported: Any, window: int, text: str) -> str | None:
    """Why the prompt the engine reports cannot be trusted to be the whole request, or None when it can. Code only."""
    if isinstance(reported, bool) or not isinstance(reported, int) or reported <= 0:
        return "prompt size not reported"
    if reported >= int(window * CUT_FRACTION):
        return "prompt at or near the window"
    if reported < lower_bound_tokens(text):
        return "prompt shorter than the request needs"
    return None


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
        show: Callable[[str], dict | None] | None = None,
        window: int | None = None,
        output_cap: int | None = None,
    ) -> None:
        self.output_cap = output_cap  # a ceiling on every request's output limit (the general review's windows fit under it)
        self.discarded: Counter = (
            Counter()
        )  # reason -> n: answers thrown away because the prompt was cut or not reported
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
        self._show_of = show or _show
        self.used: set[str] = (
            set()
        )  # the models THIS run loaded (only these are ever unloaded)
        self.progress_cb: Callable[[str], None] | None = None

    # ---- readiness of the second reader
    def second_ready(self) -> tuple[bool, str]:
        if self._ready is None:
            sa = self._show_of(self.model_a) if self.model_b else None
            sb = self._show_of(self.model_b) if self.model_b else None
            self._ready = second_ready_for(self.model_a, self.model_b, sa, sb)
        return self._ready

    # ---- budget
    def window(self, role: str = FIRST) -> int:
        """The context window asked of the model of this role: the setting (0 = the shared local window), never below the shared window
        (the transport raises a smaller one to it)."""
        if self._window:
            return int(self._window)
        from .config import settings

        asked = int(
            getattr(
                settings,
                "agent_review_local_num_ctx_b"
                if role == SECOND
                else "agent_review_local_num_ctx",
                0,
            )
            or 0
        )
        if role == SECOND and not asked:
            asked = int(getattr(settings, "agent_review_local_num_ctx", 0) or 0)
        return max(asked, model_transport.shared_window())

    def stats(self) -> dict:
        """Counts only (no text): requests by stage, requests not sent for length, answers discarded for a cut or unreported prompt."""
        return {
            "local_requests_first": self.calls[FIRST],
            "local_requests_second": self.calls[SECOND],
            "local_not_asked_too_long": self.not_asked,
            "local_answers_discarded": sum(self.discarded.values()),
        }

    def fits(self, parts: dict, max_tokens: int, role: str = FIRST) -> bool:
        need = sum(
            context_budget.estimate_tokens(m["content"]) for m in chat_messages(parts)
        )
        return need + int(max_tokens) + WINDOW_MARGIN_TOKENS <= self.window(role)

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
                    # only models THIS run loaded: a model another job or the chat is using is never unloaded from here
                    for name in sorted(self.used - set(self.unloads)):
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
        if self.output_cap:
            max_tokens = min(int(max_tokens), int(self.output_cap))
        if not self.fits(parts, max_tokens, role):
            with self._lock:
                self.not_asked += 1
            raise _too_long()
        messages = chat_messages(parts)
        whole = "\n".join(m["content"] for m in messages)
        messages = [
            {
                **messages[0],
                "content": f"[request {uuid.uuid4().hex[:8]}]\n"
                + messages[0]["content"],
            },
            *messages[1:],
        ]
        window = self.window(role)
        body = {
            "model": name,
            "messages": messages,
            "stream": False,
            "think": False,
            "format": "json",
            "options": {
                "temperature": 0,
                "num_predict": int(max_tokens),
                "num_ctx": window,
            },
        }
        with self._lock:  # one request at a time: one big model, one runner
            if self.loaded and self.loaded != name:
                self._drop_loaded()
            self.loaded = name
            self.used.add(name)
            self.calls[role] += 1
            answer = self._send(body)
        message = answer.get("message") if isinstance(answer, dict) else None
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str) or not text.strip():
            exc = agent_claude.AgentBadReply("bad_shape")
            exc.usd = 0.0
            raise exc
        reported = answer.get("prompt_eval_count")
        why = _cut_prompt(reported, window, whole)
        if why:  # the engine may have cut the prompt: nothing it said is used (never a met / not met from a part of the paper)
            with self._lock:
                self.discarded[why] += 1
            raise _too_long()
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

    def note(self, label: str) -> None:
        """Progress: a beat of the running review's heartbeat (`worker_review.beat_now`) and the screen's label, before and after a request."""
        from . import worker_review

        worker_review.beat_now()
        if self.progress_cb is not None:
            try:
                self.progress_cb(label)
            except Exception as exc:  # noqa: BLE001 - a label is never worth a run
                log.warning("local progress label failed (%s)", type(exc).__name__)

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


ITEMS_PER_FIRST_REQUEST = 2.3  # the stable batches are halved on a hash until at most 3: about 2.3 items a request on average
SHARE_ASKED_SECOND = (
    0.5  # a guess: about half the lines are candidates for the second reader
)
GENERAL_ON_LOCAL = True  # the general review runs on the local model (staged; `agent_general_parts.run_all_local`)
WAIT_WORDS = "other reviews wait behind it (one review at a time), and chat answers may be slower while it runs"


def local_time(conn, document_id: str, two_readers: bool = False) -> dict:
    """The time of the AI review on the local model, in honest words: an ESTIMATE of the requests from the rules the paper's last AI review
    asked (None when there is none), counting only what will really be asked (no second reader unless that switch is on), and a labelled
    GUESS of the minutes (nothing is measured on this install yet; CLAUDE.md rule 4)."""
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
            "basis": "an estimate cannot be made yet: the rules to ask are chosen when the review starts. A local review takes a few minutes for every"
            f" ten rules or more (a guess, not measured on this install); {WAIT_WORDS}",
        }
    n = int(row["items_total"])
    first = math.ceil(n / ITEMS_PER_FIRST_REQUEST * 1.2)  # 20% for splits and re-asks
    second = (
        math.ceil(n * SHARE_ASKED_SECOND / ITEMS_PER_FIRST_REQUEST * 1.1)
        if two_readers
        else 0
    )  # 10% for context checks
    requests = first + second
    return {
        "requests": requests,
        "minutes_guess": round(requests * SECONDS_GUESS_PER_REQUEST / 60),
        "basis": f"an estimate of about {requests} requests ({first} first reader"
        + (
            f", {second} second reader"
            if two_readers
            else ", no second reader: that switch is off"
        )
        + f") if the same {n} rules are asked again, one at a time, at a guess of {SECONDS_GUESS_PER_REQUEST} seconds a request (not measured on this"
        f" install); a local review takes about {round(requests * SECONDS_GUESS_PER_REQUEST / 60)} minutes and {WAIT_WORDS}",
    }
