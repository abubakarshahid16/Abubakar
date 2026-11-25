"""LocalModel: the general review on the LOCAL model (owner via the planner, 25 Nov 2026 22:35: "if we do not have the Claude API,
use the local model until then").

THE SAME CONTRACT AS `engine.ClaudeModel.ask`: one step's system text, the paper block (`cached`), the step's prompt and its answer
size in; the step's JSON answer out, or `StepFailed` with a code. Same steps, same code checks, same labels: the method does not
know which model answered. What differs:

  * EVERY CALL GOES THROUGH `model_transport.post_json` (the one path to the local engine, loopback only, behind the local model
    gate of the worker's lanes). Nothing here imports or calls `reader_transport`, `agent_claude` or `claude_spend`: nothing
    leaves this computer and nothing is paid (each call is recorded at USD 0). A run on this model is also barred from Claude for
    its whole length (`review_engine.barring`, set by the run's stored Local only plan), so a step that tried the Claude lane
    anyway would be refused there.
  * ONE LOCAL MODEL FOR EVERY STEP (`settings.answer_model`, the installed Qwen 35B): the step's Claude model name is not used.
  * SMALLER SIZES (`budget.LOCAL`, set by the run): smaller paper windows, clause batches and judge batches, so the prompt and
    its answer fit the model's window. A prompt that would not fit is never sent (`local_too_long`), and an answer whose prompt
    the engine may have cut is never used (`local_cut`): a step never judges from part of what it was given.
  * NO CACHE: the paper block is sent with every call (the local engine keeps no prompt cache across steps here).

`readiness` is asked BEFORE the run loads anything: a run does not start while another large local model is loaded, while the
heavy-job lock is held, or while the machine has too little free memory to load the model. Codes and fixed words only; no
document text is logged or kept here.
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
#: A model loaded in the local engine at or above this size is a LARGE model: two never run at once.
LARGE_MODEL_BYTES = 10_000_000_000
#: Free memory needed for a model other than the answer model, besides its file size (its window's cache).
MEMORY_MARGIN_BYTES = 2_000_000_000

#: Codes after which no later call can succeed: the run stops (`StepFailed.stops_run` reads the word "stop").
LOCAL_DOWN = "local_down"
LOCAL_BARRED = "local_barred"
LOCAL_BUSY = "local_busy"


def model_name() -> str:
    """The local model every step of a local general review runs on (the setting; the run records what the engine answered)."""
    from app.config import settings

    return str(settings.answer_model).strip()


class LocalModel:
    """The local engine through `model_transport`. `meter` is bound by `engine.run` (every call costs USD 0)."""

    dry = False
    engine = ENGINE

    def __init__(
        self, name: str | None = None, *, budget: Budget = LOCAL, meter=None
    ) -> None:
        from .engine import Meter

        self.name = (name or model_name()).strip()
        self.budget = budget
        self.meter = meter or Meter(cap=0.0)
        #: The model names the engine itself reported (the run record names these, never the setting).
        self.answered_by: set[str] = set()

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
        )  # one local model for every step; nothing is carried out of this computer
        from app import context_budget

        from .engine import CallRecord, StepFailed

        system_text = "\n\n".join(t for t in (system, cached) if t)
        messages = (
            [{"role": "system", "content": system_text}] if system_text else []
        ) + [{"role": "user", "content": prompt}]
        num_predict = max(1, min(int(max_tokens), int(self.budget.max_tokens)))
        need = sum(context_budget.estimate_tokens(m["content"]) for m in messages)
        rec = CallRecord(
            step=step, model=self.name, prompt_chars=len(system_text) + len(prompt)
        )
        rec.engine = ENGINE
        if need + num_predict + WINDOW_MARGIN_TOKENS > self.budget.num_ctx:
            rec.ok, rec.code = False, "local_too_long"
            self.meter.charge(rec)
            raise StepFailed(
                f"{step}: local_too_long (the prompt does not fit the local model's window)"
            )
        body = {
            "model": self.name,
            "messages": messages,
            "stream": False,
            "think": False,
            "format": "json",
            "options": {
                "temperature": 0,
                "num_ctx": int(self.budget.num_ctx),
                "num_predict": num_predict,
            },
        }
        answer = self._post(step, body, rec)
        rec.model = _answered_model(answer, self.name)
        self.answered_by.add(rec.model)
        rec.input_tokens = _count(answer.get("prompt_eval_count"))
        rec.output_tokens = _count(answer.get("eval_count"))
        text = _content(answer)
        if _prompt_cut(
            answer.get("prompt_eval_count"), self.budget.num_ctx, num_predict, need
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

    def _post(self, step: str, body: dict, rec) -> dict:
        from app import local_model_gate, model_transport, worker_review

        from .engine import StepFailed

        t0 = time.time()
        try:
            with (
                worker_review.keep_beating()
            ):  # a long local call is activity, not silence
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


def _prompt_cut(reported, window: int, num_predict: int, estimate: int) -> bool:
    """True when the engine's reported prompt size says it may not have read the whole request (the local AI reviewer's own rule,
    `agent_review_local._cut_prompt`): not reported, reaching the room the window leaves, or longer than the estimate."""
    from app import agent_review_local

    return (
        agent_review_local._cut_prompt(reported, window, "", num_predict, estimate)
        is not None
    )


# ------------------------------------------------------------------ before the run loads anything


NOT_INSTALLED = "the local model {name} is not installed on this computer, so the review did not start"
OTHER_LARGE = "another large local model ({name}) is loaded, and only one large model runs at a time; the review did not start"
LOCK_HELD = "another heavy job holds this computer ({who}); the review did not start; start it again when it ends"
LOW_MEMORY = (
    "this computer has {free} GB of memory free and the local model needs about {need} GB, so the review did not start; "
    "close other work and start it again"
)
ENGINE_DOWN = "the local model engine is not answering on this computer, so the review did not start"


def readiness(name: str | None = None) -> str | None:
    """None when a local general review may start now; else one plain sentence why not. Reads the heavy-job lock, the engine's
    installed and loaded models (`/api/tags`, `/api/ps`: no document is sent) and the free memory. Never loads a model."""
    from app import heavy_lock, model_transport
    from app.config import settings

    name = (name or model_name()).strip()
    holder = heavy_lock.read()
    if holder is not None and not heavy_lock.is_stale(holder):
        return LOCK_HELD.format(who=str(holder.get("kind") or "a heavy job"))
    try:
        tags = model_transport.get_json("/api/tags", timeout=10) or {}
        loaded = model_transport.get_json("/api/ps", timeout=10, required=False) or {}
    except Exception as exc:  # noqa: BLE001 - an engine that cannot be asked is not ready
        log.info("local readiness: engine not asked (%s)", type(exc).__name__)
        return ENGINE_DOWN
    installed = {
        str(m.get("name") or m.get("model") or ""): _count(m.get("size"))
        for m in tags.get("models") or []
        if isinstance(m, dict)
    }
    if name not in installed:
        return NOT_INSTALLED.format(name=name)
    ours = False
    for m in loaded.get("models") or []:
        if not isinstance(m, dict):
            continue
        loaded_name = str(m.get("name") or m.get("model") or "")
        if loaded_name == name:
            ours = True
        elif _count(m.get("size")) >= LARGE_MODEL_BYTES:
            return OTHER_LARGE.format(name=loaded_name)
    if ours:
        return None  # already in memory: nothing new is loaded
    # the app's own rule for the answer model (`answer_model_ram_bytes`, the Explain warning); another model: its file + margin
    if name == str(settings.answer_model).strip() or not installed[name]:
        need = int(settings.answer_model_ram_bytes)
    else:
        need = installed[name] + MEMORY_MARGIN_BYTES
    free = _free_bytes()
    if free is not None and free < need:
        return LOW_MEMORY.format(free=round(free / 1e9, 1), need=round(need / 1e9, 1))
    return None


def _free_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.virtual_memory().available)
    except Exception as exc:  # noqa: BLE001 - unknown free memory: the engine's own limits apply
        log.info("local readiness: free memory not read (%s)", type(exc).__name__)
        return None
