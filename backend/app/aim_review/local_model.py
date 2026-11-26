"""LocalModel: the LOCAL adapter of the general review's model socket (`model_socket`; owner via the planner, 25 Nov 2026 22:35,
22:40, 23:15 and 23:25: "if we do not have the Claude API, use the local model until then"; one 14B-class model, never the 35B).

THE SAME CONTRACT AS `engine.ClaudeModel.ask`: one step's system text, the paper block (`cached`), the step's prompt and its answer
size in; the step's JSON answer out, or `StepFailed` with a code. Same steps, same code checks, same labels. What differs:

  * EVERY CALL GOES THROUGH `model_transport.post_json` (the one path to the local engine, loopback only, behind the local model
    gate of the worker's lanes). Nothing here imports or calls `reader_transport`, `agent_claude` or `claude_spend`: nothing
    leaves this computer and nothing is paid (each call is recorded at USD 0). The run is also barred from Claude for its whole
    length (`review_engine.barring`), so a step that tried the Claude lane anyway would be refused there.
  * THE MODEL OF EACH STEP is the setting (`settings.answer_model`, the one local default, qwen3.5:9b-q4_K_M; a step may name its own
    in `general_review_local_step_models`, e.g. "judge=qwen3.5:9b"). ONE MODEL IN MEMORY AT A TIME: when the next step needs
    another model, the one loaded is unloaded first. Every call records the model the engine REPORTED, never the setting.
  * NO BLIND CHUNKING (owner's standing lesson, 25 Nov 2026 23:15): the window is sized per paper (`budget.for_paper`) so the
    judge sees the WHOLE paper; a prompt that would not fit is never sent (`local_too_long`), a cut prompt is never used
    (`local_cut`), and every judge call notes whether it saw the whole paper or a page window.
  * NO CACHE: the paper block is sent with every call.

`readiness` is asked BEFORE the run loads anything: no start while another model is loaded, while the heavy-job lock is held, for
a model too large for this Mac (the 35B: not loaded unless the owner asks), or with less free memory than the model's need (its
file plus the window's cache) plus 6 GB. During the run, swap growing more than 1 GB stops it (the owner's memory rule). Codes and
fixed words only; no document text is logged or kept here.
"""

from __future__ import annotations

import logging
import time

from .budget import LOCAL, Budget
from .prompts import ANSWER_KEYS, parse_json

log = logging.getLogger(__name__)

ENGINE = "local"
#: One call's own time limit (a judge batch on a long window takes minutes on this Mac).
CALL_TIMEOUT_SECONDS = 20 * 60
#: Another model loaded in the local engine at or above this size: the run does not start (one model in memory at a time).
LARGE_MODEL_BYTES = 5_000_000_000
#: A local model file above this is never loaded by a review (owner, 25 Nov 2026 23:25: the 35B crashes memory).
MAX_MODEL_BYTES = 15_000_000_000
#: Free memory needed besides the model's own need before it is loaded (owner, 25 Nov 2026 23:25).
MEMORY_MARGIN_BYTES = 6_000_000_000
#: The window's cache per token when the engine does not say (a 14B-class model with grouped attention: 40 x 8 x 128 x 2 x 2).
DEFAULT_KV_BYTES_PER_TOKEN = 163_840

#: Codes after which no later call can succeed: the run stops (`StepFailed.stops_run` reads the word "stop").
LOCAL_DOWN = "local_down"
LOCAL_BARRED = "local_barred"
LOCAL_BUSY = "local_busy"
LOCAL_SWAP = "local_swap"
#: The owner's memory rule (12 Nov 2026): a run whose swap grows more than this above its start stops (its lines are kept).
SWAP_STOP_BYTES = 1_000_000_000

#: The steps a person names in `general_review_local_step_models`, and the method's step names each covers.
STEP_GROUPS = {
    "name": ("aim_identify",),
    "choose": ("aim_select",),
    "checklist": ("aim_checklist", "aim_checklist_knowledge", "aim_checklist_retry"),
    "attack": ("aim_attack", "aim_attack_items"),
    "judge": ("aim_judge", "aim_reference", "aim_answered"),
    "second reader": ("aim_second_read",),
    "editor": ("aim_edit",),
}
#: Sent with every local review call (lead-4, 26 Nov 2026, after four 14B checklist answers ran on to their limit): the usual
#: engine default, set here so a model file with no or a lower penalty cannot run on repeating itself. Not higher: the forced JSON
#: answer repeats the same unit or clause on many items, and a stronger penalty would push the model off those values.
REPEAT_PENALTY = 1.1
#: What the judge's prompt says when it reads one page window of a longer paper (`prompts.WINDOW_LINE`).
WINDOW_MARK = "THIS IS PART OF A LONGER PAPER"


def model_name() -> str:
    """The local default: the administrator's saved Review model (`review_model_setting`), else `ANSWER_MODEL`; the run
    records what the engine answered."""
    from app import answer_model_choice, review_model_setting

    return (review_model_setting.default_choice() or answer_model_choice.name()).strip()


def step_models() -> dict[str, str]:
    """{method step: local model} for the steps the administrator saved (`review_model_setting`) and, for a step not saved, the
    env setting ("judge=qwen3.5:9b, editor=ministral-3:14b"); an unknown step name or an empty model is ignored (the step keeps
    the default)."""
    from app.config import settings

    out: dict[str, str] = {}
    for part in str(
        getattr(settings, "general_review_local_step_models", "") or ""
    ).split(","):
        key, _, value = part.partition("=")
        group, value = " ".join(key.strip().lower().split()), value.strip()
        for step in STEP_GROUPS.get(group, ()) if value else ():
            out[step] = value
    from app import review_model_setting

    # the saved choice wins over the env setting
    for group, value in review_model_setting.step_choices().items():
        for step in STEP_GROUPS.get(group, ()):
            out[step] = value
    return out


class LocalModel:
    """The local engine through `model_transport`. `meter` is bound by `engine.run` (every call costs USD 0)."""

    dry = False
    engine = ENGINE

    def __init__(
        self,
        name: str | None = None,
        *,
        budget: Budget = LOCAL,
        meter=None,
        steps: dict[str, str] | None = None,
    ) -> None:
        from .engine import Meter

        self.name = (name or model_name()).strip()
        self.steps = dict(step_models() if steps is None else steps)
        self.budget = budget
        self.meter = meter or Meter(cap=0.0)
        #: The model names the engine itself reported (the run record names these, never the setting).
        self.answered_by: set[str] = set()
        #: swap in use before the run's first call (the owner's memory rule is measured from there)
        self.swap_at_start: int | None = None
        self.loaded: str | None = None
        self._thinks: dict[str, bool] = {}

    def names(self) -> list[str]:
        """Every local model this run may load (the default and each step's own)."""
        return sorted({self.name, *self.steps.values()})

    def model_for(self, step: str) -> str:
        return self.steps.get(step, self.name)

    def ask(
        self,
        *,
        step: str,
        model: str,
        system: str,
        cached: str | None,
        prompt: str,
        carries: set[str],
        max_tokens: int,
        effort: str | None = None,
    ):
        del (
            model,
            carries,
            effort,
        )  # the step's local model is the setting's; nothing is carried out of this computer
        from app import context_budget

        from .engine import CallRecord, StepFailed

        name = self.model_for(step)
        system_text = "\n\n".join(t for t in (system, cached) if t)
        messages = (
            [{"role": "system", "content": system_text}] if system_text else []
        ) + [{"role": "user", "content": prompt}]
        num_predict = max(1, min(int(max_tokens), int(self.budget.max_tokens)))
        need = sum(context_budget.estimate_tokens(m["content"]) for m in messages)
        rec = CallRecord(
            step=step, model=name, prompt_chars=len(system_text) + len(prompt)
        )
        rec.engine, rec.note = ENGINE, _note(step, prompt, self.budget.num_ctx)
        if need + num_predict + WINDOW_MARGIN_TOKENS > self.budget.num_ctx:
            rec.ok, rec.code = False, "local_too_long"
            self.meter.charge(rec)
            raise StepFailed(
                f"{step}: local_too_long (the prompt does not fit the local model's window)"
            )
        body = self._body(name, messages, num_predict, step)
        self._memory_rule(step, rec)
        self._one_in_memory(name)
        answer = self._post(step, body, rec)
        rec.model = _answered_model(answer, name)
        self.answered_by.add(rec.model)
        rec.input_tokens = _count(answer.get("prompt_eval_count"))
        rec.output_tokens = _count(answer.get("eval_count"))
        text = _content(answer)
        whole = "\n".join(m["content"] for m in messages)
        if _prompt_cut(
            answer.get("prompt_eval_count"), self.budget.num_ctx, num_predict, whole
        ):
            rec.ok, rec.code = False, "local_cut"
            self.meter.charge(rec)
            raise StepFailed(
                f"{step}: local_cut (the local engine may have cut the prompt; the answer is not used)"
            )
        if answer.get("done_reason") == "length":
            rec.ok, rec.code = False, "stop_max_tokens"
            self.meter.charge(rec)
            raise StepFailed(f"{step}: stop_max_tokens")
        out = parse_json(text, ANSWER_KEYS.get(step))
        if out is None:
            rec.ok, rec.code = False, "no_json"
            self.meter.charge(rec)
            raise StepFailed(f"{step}: no_json")
        self.meter.charge(rec)
        return out

    def _body(
        self, name: str, messages: list[dict], num_predict: int, step: str = ""
    ) -> dict:
        """The chat request: the step's own answer shape when one is written (`answer_schema.for_step`: the engine then
        cannot return a broken shape), else plain JSON; no randomness; the run's window; a model that thinks is told not to
        (its thinking would spend the answer's room)."""
        body = {
            "model": name,
            "messages": messages,
            "stream": False,
            "format": _answer_shape(step),
            "options": {
                "temperature": 0,
                "num_ctx": int(self.budget.num_ctx),
                "num_predict": num_predict,
                "repeat_penalty": REPEAT_PENALTY,
            },
        }
        if self._thinking(name):
            body["think"] = False
        return body

    def _thinking(self, name: str) -> bool:
        if name not in self._thinks:
            self._thinks[name] = "thinking" in (_show(name).get("capabilities") or [])
        return self._thinks[name]

    def _one_in_memory(self, name: str) -> None:
        """Before a call on another model than the one loaded: the loaded one is unloaded first (one model in memory at a time)."""
        if self.loaded and self.loaded != name:
            _unload(self.loaded)
        self.loaded = name

    def unload(self) -> None:
        """After the run: the model leaves memory (the next heavy job finds the memory free)."""
        if self.loaded:
            _unload(self.loaded)
            self.loaded = None

    def _memory_rule(self, step: str, rec) -> None:
        """Before each call: swap more than `SWAP_STOP_BYTES` above the run's start stops the run (the lines judged stay)."""
        from .engine import StepFailed

        used = _swap_bytes()
        if used is None:
            return
        if self.swap_at_start is None:
            self.swap_at_start = used
        elif used - self.swap_at_start > SWAP_STOP_BYTES:
            rec.ok, rec.code = False, LOCAL_SWAP
            self.meter.charge(rec)
            raise StepFailed(
                f"{step}: stop {LOCAL_SWAP} (the computer began to swap; the run stopped to keep it usable)"
            )

    def _post(self, step: str, body: dict, rec) -> dict:
        from app import local_model_gate, model_transport, worker_review

        from .engine import StepFailed

        t0 = time.time()
        try:
            with worker_review.keep_beating():  # a long local call is activity
                raw = model_transport.post_json(
                    "/api/chat", body, timeout=CALL_TIMEOUT_SECONDS
                )
        except model_transport.LocalEngineNotLoaded:
            code, fatal = LOCAL_BARRED, True
        except local_model_gate.LocalModelBusy:
            code, fatal = LOCAL_BUSY, True
        except Exception as exc:  # noqa: BLE001 - every engine failure is a code, never its text (it could hold the prompt)
            if model_transport.is_timeout_error(exc):
                code, fatal = "local_timeout", False
            elif type(exc).__name__ in (
                "ConnectError",
                "ConnectTimeout",
                "RemoteProtocolError",
            ):
                code, fatal = LOCAL_DOWN, True
            else:
                code, fatal = f"local_{type(exc).__name__}", False
            log.info(
                "general review local call %s failed (%s)", step, type(exc).__name__
            )
        else:
            rec.seconds = round(time.time() - t0, 2)
            return raw if isinstance(raw, dict) else {}
        rec.seconds = round(time.time() - t0, 2)
        rec.ok, rec.code = False, code
        self.meter.charge(rec)
        raise StepFailed(f"{step}: stop {code}" if fatal else f"{step}: {code}")


#: Room kept free in the window besides the answer (the chat template's own tokens).
WINDOW_MARGIN_TOKENS = 512


def _answer_shape(step: str):
    """The step's JSON schema for the engine's `format` (`aim_review.answer_schema.for_step`, the method's own module), else
    "json". A method without that module, or a step it has no schema for, keeps plain JSON."""
    try:
        from . import answer_schema
    except ImportError:
        return "json"
    return answer_schema.for_step(step) or "json"


#: What the judge's prompt says when it reads a paper MAP with the full pages an item cites (`paper_map.MAP_LINE`).
MAP_MARK = "THIS IS A LONG PAPER"


def _note(step: str, prompt: str, num_ctx: int) -> str:
    """What the call read, for the run record: its window and, for a judge call, whether it saw the whole paper (a page window
    or a paper map is not the whole paper)."""
    if step != "aim_judge":
        return f"window {num_ctx} tokens"
    if MAP_MARK in prompt:
        seen = "a paper map with the pages it cites, not the whole paper"
    elif WINDOW_MARK in prompt:
        seen = "a page window, not the whole paper"
    else:
        seen = "the whole paper"
    return f"window {num_ctx} tokens; {seen}"


def _count(value) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
        else 0
    )


def _answered_model(answer: dict, asked: str) -> str:
    got = answer.get("model")
    return got.strip() if isinstance(got, str) and got.strip() else asked


def _content(answer: dict) -> str:
    message = answer.get("message")
    text = message.get("content") if isinstance(message, dict) else None
    return text if isinstance(text, str) else ""


def _prompt_cut(reported, window: int, num_predict: int, text: str) -> bool:
    """True when the engine's reported prompt size says it may not have read the whole request: not reported, reaching the room
    the window leaves it, or shorter than the request's text can be (the local AI reviewer's own limits,
    `agent_review_local`). A count LONGER than the app's estimate is no cut: another tokenizer counts more (the 14B does)."""
    from app import agent_review_local as A

    if isinstance(reported, bool) or not isinstance(reported, int) or reported <= 0:
        return True
    if reported >= window - int(num_predict) - A.CUT_MARGIN:
        return True
    return reported < A.lower_bound_tokens(text)


def _show(name: str) -> dict:
    """The engine's own description of a model (`/api/show`: capabilities, sizes; no document is sent); {} when it cannot say."""
    from app import model_transport

    try:
        got = model_transport.post_json("/api/show", {"model": name}, timeout=30)
    except Exception as exc:  # noqa: BLE001 - an unknown model description: the defaults apply
        log.info("local model: description not read (%s)", type(exc).__name__)
        return {}
    return got if isinstance(got, dict) else {}


def _unload(name: str) -> None:
    from app import model_transport

    try:
        with model_transport.keep_alive_override(0):
            model_transport.post_json(
                "/api/generate", {"model": name, "prompt": ""}, timeout=60
            )
    except Exception as exc:  # noqa: BLE001 - a model that did not unload: the engine's own keep-alive ends it
        log.info("local model: not unloaded (%s)", type(exc).__name__)


def kv_bytes_per_token(info: dict) -> int:
    """The window's cache per token from the engine's model description (layers x key-value heads x head size x 2 x 2 bytes), else
    `DEFAULT_KV_BYTES_PER_TOKEN`."""
    mi = info.get("model_info") if isinstance(info.get("model_info"), dict) else {}

    def find(suffix: str) -> int:
        return next(
            (_count(v) for k, v in mi.items() if str(k).endswith(suffix) and _count(v)),
            0,
        )

    layers, heads, size = (
        find(".block_count"),
        find(".attention.head_count_kv"),
        find(".attention.key_length"),
    )
    return (
        layers * heads * size * 4
        if layers and heads and size
        else DEFAULT_KV_BYTES_PER_TOKEN
    )


# ------------------------------------------------------------------ before the run loads anything


NOT_INSTALLED = "the local model {name} is not installed on this computer, so the review did not start"
TOO_LARGE = (
    "the local model {name} is too large for this computer (the owner, 25 Nov 2026: the 35B crashes memory) and is not loaded "
    "unless the owner asks; choose a 14B-class model"
)
OTHER_LOADED = "another local model ({name}) is loaded, and only one model is in memory at a time; the review did not start"
LOCK_HELD = "another heavy job holds this computer ({who}); the review did not start; start it again when it ends"
LOW_MEMORY = (
    "this computer has {free} GB of memory free and the local model {name} needs {need} GB with its {ctx}-token window, plus "
    "6 GB to spare, so the review did not start; close other work and start it again"
)
ENGINE_DOWN = "the local model engine is not answering on this computer, so the review did not start"
NOT_LOCAL = (
    "the model {name} is not a model file on this computer (the engine would pass the paper's text to another computer), "
    "so the review did not start"
)


def is_cloud_name(name: str) -> bool:
    """A name the engine uses for a model that runs elsewhere (":cloud", "-cloud")."""
    low = str(name or "").lower()
    return ":cloud" in low or "-cloud" in low


def is_local_file(name: str, entry: dict) -> bool:
    """True only when the engine's list entry is a model FILE on this computer (review of update 10, M3): not a cloud name, no
    remote host or remote model field, a size above zero and a digest. Anything else may pass text to another computer
    (rule 1), so it is never offered and never started."""
    if is_cloud_name(name) or not isinstance(entry, dict):
        return False
    if entry.get("remote_host") or entry.get("remote_model"):
        return False
    return _count(entry.get("size")) > 0 and bool(
        str(entry.get("digest") or "").strip()
    )


def need_bytes(name: str, file_bytes: int, num_ctx: int) -> int:
    """What the model needs in memory: its file plus the window's cache for `num_ctx` tokens."""
    return int(file_bytes) + kv_bytes_per_token(_show(name)) * int(num_ctx)


def readiness(names=None, num_ctx: int = LOCAL.num_ctx) -> str | None:
    """None when a local general review may start now; else one plain sentence why not. Reads the heavy-job lock, the engine's
    installed and loaded models (`/api/tags`, `/api/ps`, `/api/show`: no document is sent) and the free memory. Never loads a
    model."""
    from app import heavy_lock, model_transport

    names = sorted(
        {str(n).strip() for n in (names or [model_name()]) if str(n).strip()}
    )
    holder = heavy_lock.read()
    if holder is not None and not heavy_lock.is_stale(holder):
        return LOCK_HELD.format(who=str(holder.get("kind") or "a heavy job"))
    try:
        tags = model_transport.get_json("/api/tags", timeout=10) or {}
        loaded = model_transport.get_json("/api/ps", timeout=10, required=False) or {}
    except Exception as exc:  # noqa: BLE001 - an engine that cannot be asked is not ready
        log.info("local readiness: engine not asked (%s)", type(exc).__name__)
        return ENGINE_DOWN
    entries = {
        str(m.get("name") or m.get("model") or ""): m
        for m in tags.get("models") or []
        if isinstance(m, dict)
    }
    for name in names:
        if is_cloud_name(name):
            return NOT_LOCAL.format(name=name)
        if name not in entries:
            return NOT_INSTALLED.format(name=name)
        if not is_local_file(name, entries[name]):
            return NOT_LOCAL.format(name=name)
        if _count(entries[name].get("size")) > MAX_MODEL_BYTES:
            return TOO_LARGE.format(name=name)
    in_memory = set()
    for m in loaded.get("models") or []:
        if not isinstance(m, dict):
            continue
        loaded_name = str(m.get("name") or m.get("model") or "")
        if loaded_name in names:
            in_memory.add(loaded_name)
        elif _count(m.get("size")) >= LARGE_MODEL_BYTES:
            return OTHER_LOADED.format(name=loaded_name)
    free = _free_bytes()
    for name in names:
        if name in in_memory or free is None:
            continue  # already in memory, or free memory unknown (the swap rule still holds)
        need = need_bytes(name, _count(entries[name].get("size")), num_ctx)
        if free < need + MEMORY_MARGIN_BYTES:
            return LOW_MEMORY.format(
                free=round(free / 1e9, 1),
                name=name,
                need=round(need / 1e9, 1),
                ctx=int(num_ctx),
            )
    # last, with the memory known to hold it: each model must give a structured answer (F, 26 Nov 2026: one 9B build answers
    # HTTP 501 "structured output is unavailable", so every run on it died at its first call)
    return next((w for w in (_probe(n, num_ctx) for n in names) if w), None)


NO_SHAPE = "this model cannot give the answer shape the review needs: {name}"
#: The probe's request: no document, a one-word answer in the shape the review asks for.
PROBE_PROMPT = 'Answer with this JSON only: {"ok": true}'


def _probe(name: str, num_ctx: int) -> str | None:
    """One tiny structured-output call to `name` (no document is sent), in the shape the review's first step asks for and at the
    run's window (so the model the run then uses is already loaded). None when it answers; `NO_SHAPE` when the engine refuses
    the shape (an HTTP error from it); `ENGINE_DOWN` when it cannot be reached. Codes only are logged."""
    from app import model_transport

    body = {
        "model": name,
        "messages": [{"role": "user", "content": PROBE_PROMPT}],
        "stream": False,
        "format": _answer_shape("aim_identify"),
        "options": {"temperature": 0, "num_ctx": int(num_ctx), "num_predict": 16},
    }
    if "thinking" in (_show(name).get("capabilities") or []):
        body["think"] = False
    try:
        model_transport.post_json("/api/chat", body, timeout=CALL_TIMEOUT_SECONDS)
    except model_transport.httpx.HTTPStatusError as exc:
        log.info(
            "local readiness: %s refused the answer shape (HTTP %s)",
            name,
            exc.response.status_code,
        )
        return NO_SHAPE.format(name=name)
    except Exception as exc:  # noqa: BLE001 - an engine that cannot be asked is not ready
        log.info("local readiness: probe of %s failed (%s)", name, type(exc).__name__)
        return ENGINE_DOWN
    return None


def _swap_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.swap_memory().used)
    except Exception as exc:  # noqa: BLE001 - unknown swap: the engine's own limits apply
        log.info("local memory rule: swap not read (%s)", type(exc).__name__)
        return None


def _free_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.virtual_memory().available)
    except Exception as exc:  # noqa: BLE001 - unknown free memory: the engine's own limits apply
        log.info("local readiness: free memory not read (%s)", type(exc).__name__)
        return None
