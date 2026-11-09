"""The LOCAL lead provider for the agent proof test (#1690, part of #805). Behind `AGENT_REVIEW_ENABLED`.

`LocalProvider` implements `agent_loop.Provider` on a local Ollama model (default the Qwen 35B), so the loop can run with
no Claude spend. Same contract as `agent_claude.ClaudeProvider.complete`: one dict, {"tool", "args", "reason", "usd",
"model"} or {"final": {...}, "usd", "model"}. `usd` is always 0.0; `model` is the name in the Ollama RESPONSE ("unknown"
if absent). One tool call per turn; a reply that is neither a call to a listed tool nor ONE JSON finding raises
`LocalBadReply` (a code; the loop turns any raised error into a YELLOW "ask the engineer" finding).

THE ONE SOCKET. Every call goes through `model_transport.post_json_retrying("/api/chat", ...)`; `engine_info` uses
`model_transport.get_json`. This module opens no socket. `model_transport` takes no per-call URL, so the `url`
argument is only a CHECK (as in `agent_local`): if given and different from the current setting, nothing is sent. To
point a run at the TEST Ollama the caller sets the Ollama URL in the PROCESS environment, never in `backend/.env`.
Think is off, temperature 0, `num_predict` is set; the context window and keep_alive come from
`model_transport.runner_options` / `keep_alive_override`.

ONE BIG MODEL. `session()` takes the heavy lock (kind "agent_local_lead") around a batch and always unloads the model in
`finally` through `model_memory.unload` (#666); an unload error is logged as its TYPE NAME only.

Messages come in the loop's layout (user dict, assistant {tool,args,reason}, tool results) or the Anthropic block layout
(system, text, tool_use, tool_result blocks). Errors and logs carry codes and type names, never document or standard text.
`stats` and `models_seen` are numbers and model names only, for the speed test.
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from typing import Any

from app import heavy_lock, model_memory, model_transport
from app.agent_trace import words

log = logging.getLogger(__name__)

DEFAULT_MODEL = "hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_XL"
LOCK_KIND = "agent_local_lead"
TIMEOUT_S = 300.0
NUM_PREDICT = 2048
PROBE_TIMEOUT_S = 10.0
DEFAULT_NUM_CTX = (
    8192  # settings.local_num_ctx default: the window when the caller sets none
)
CHARS_PER_TOKEN = 3  # conservative: numbers and JSON tokenise densely
WINDOW_MARGIN_TOKENS = 256
KEEP_TOOL_RESULTS = 2  # the newest tool results are shown whole while they fit
DROPPED = "[an earlier tool result was removed to fit the context window; call the tool again if you need it]"
CUT = " [cut to fit the context window]"

SYSTEM_RULES = (
    "You are a senior engineer reviewing one item of a submittal. Use one tool per turn. "
    "Finish with ONE JSON object and nothing else (no prose, no code fence) with keys: item, doc, color (GREEN, YELLOW "
    "or RED), page, doc_quote, clause_quote, standard, clause, action, priority (must, should, nice), reason (at most "
    "20 words). Quote the document exactly. Not mentioned is never GREEN. Never state confidence. "
    "Numbers are decided by the compare_number tool, not by you. When unsure, ask the engineer."
)

#: Fixed generic wording: never document text.
NUDGE = "Reply with exactly one tool call, or one JSON object (the final finding) and nothing else."

_STATS_KEYS = (
    "prompt_eval_count",
    "eval_count",
    "prompt_eval_duration",
    "eval_duration",
    "load_duration",
    "total_duration",
)


class AgentLocalLeadError(RuntimeError):
    """The message is a code, never text from a document."""

    code = "agent_local_lead_error"

    def __init__(self, code: str | None = None) -> None:
        self.code = code or self.code
        super().__init__(self.code)


class LocalBadReply(AgentLocalLeadError):
    code = "bad_reply"


class LocalTransportError(AgentLocalLeadError):
    code = "transport_error"


# ------------------------------------------------------------------ conversion


def _text(content: Any) -> str:
    return (
        content
        if isinstance(content, str)
        else json.dumps(content, ensure_ascii=False, default=str)
    )


def ollama_tools(tool_specs: list[dict]) -> list[dict]:
    """Loop specs (name, description, input_schema or params) as Ollama function tools; each gets a `reason` field."""
    tools = []
    for spec in tool_specs or []:
        schema = spec.get("input_schema")
        if not isinstance(schema, dict):
            params = spec.get("params") or {}
            props = {
                str(n): (
                    v
                    if isinstance(v, dict)
                    else {"type": "string", "description": str(v)}
                )
                for n, v in (
                    params.items()
                    if isinstance(params, dict)
                    else ((n, "") for n in params)
                )
            }
            schema = {"type": "object", "properties": props, "required": list(props)}
        schema = json.loads(json.dumps(schema))
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})["reason"] = {
            "type": "string",
            "description": "Why this tool, at most 20 words.",
        }
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": str(spec.get("name")),
                    "description": str(spec.get("description") or ""),
                    "parameters": schema,
                },
            }
        )
    return tools


def _call_message(name: Any, args: Any, reason: Any) -> dict:
    arguments = {**(args if isinstance(args, dict) else {}), "reason": reason or ""}
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": str(name), "arguments": arguments}}],
    }


def _block_messages(role: str, blocks: list) -> list[dict]:
    """Anthropic content blocks of one turn as Ollama messages."""
    out: list[dict] = []
    texts: list[str] = []
    for b in blocks:
        kind = b.get("type") if isinstance(b, dict) else None
        if kind == "tool_use":
            out.append(_call_message(b.get("name"), b.get("input"), None))
        elif kind == "tool_result":
            out.append({"role": "tool", "content": _text(b.get("content"))})
        elif kind == "text":
            texts.append(str(b.get("text") or ""))
    if texts:
        out.insert(0, {"role": role, "content": "\n".join(texts)})
    return out


def to_ollama_messages(messages: list[dict], extra_system: str = "") -> list[dict]:
    """Loop or Anthropic-layout messages -> Ollama /api/chat messages, system text first."""
    system = [SYSTEM_RULES]
    if extra_system:
        system.append(extra_system)
    out: list[dict] = []
    last_tool = None
    for m in messages or []:
        role, content = m.get("role"), m.get("content")
        if role == "system":
            system.append(_text(content))
        elif role == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_name": str(m.get("name") or last_tool or ""),
                    "content": _text(content),
                }
            )
        elif role == "assistant" and isinstance(content, dict) and "tool" in content:
            last_tool = content.get("tool")
            out.append(
                _call_message(last_tool, content.get("args"), content.get("reason"))
            )
        elif isinstance(content, list):
            out.extend(
                _block_messages("assistant" if role == "assistant" else "user", content)
            )
        else:
            out.append(
                {
                    "role": "assistant" if role == "assistant" else "user",
                    "content": _text(content),
                }
            )
    return [{"role": "system", "content": "\n\n".join(system)}, *out]


def _tokens(messages: list[dict]) -> int:
    return -(-len(json.dumps(messages, ensure_ascii=False)) // CHARS_PER_TOKEN)


def fit_to_window(
    messages: list[dict], tools: list[dict], num_ctx: int | None, num_predict: int
) -> tuple[list[dict], int]:
    """(messages that fit the context window, number of tool results shortened). Never touches the system message or the
    first user message. Oldest tool results go first (replaced by a fixed note), then the newest ones are cut. Without
    this a page read or two fills a small window and the server answers 500 (found 9 Nov: prompts reached 8175 of 8192)."""
    window = int(num_ctx or DEFAULT_NUM_CTX)
    budget = window - int(num_predict) - WINDOW_MARGIN_TOKENS - _tokens(tools)
    out = [dict(m) for m in messages]
    tool_at = [i for i, m in enumerate(out) if m.get("role") == "tool"]
    changed = 0
    for i in tool_at[:-KEEP_TOOL_RESULTS] if KEEP_TOOL_RESULTS else tool_at:
        if _tokens(out) <= budget:
            break
        if out[i].get("content") != DROPPED:
            out[i]["content"] = DROPPED
            changed += 1
    for i in reversed(tool_at[-KEEP_TOOL_RESULTS:] if KEEP_TOOL_RESULTS else []):
        over = _tokens(out) - budget
        if over <= 0:
            break
        text = str(out[i].get("content") or "")
        keep = max(len(text) - over * CHARS_PER_TOKEN - len(CUT), 0)
        if keep < len(text):
            out[i]["content"] = text[:keep] + CUT
            changed += 1
    return out, changed


# ------------------------------------------------------------------ parsing


def _no_dupes(pairs):
    keys = [k for k, _v in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate key")
    return dict(pairs)


def parse_strict(text: Any) -> dict | None:
    """The WHOLE text must be exactly one JSON object: no prose, fence, think tag or second object."""
    if not isinstance(text, str):
        return None
    try:
        obj = json.loads(text.strip(), object_pairs_hook=_no_dupes)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _arguments(raw: Any) -> dict:
    if isinstance(raw, str):
        raw = parse_strict(raw) if raw.strip() else {}
    if not isinstance(raw, dict):
        raise LocalBadReply("bad_tool_call")
    return dict(raw)


def parse_reply(answer: Any, tool_names: set[str]) -> dict:
    """tool call -> {"tool","args","reason"}; JSON content -> {"final"}. One tool call per turn; else LocalBadReply."""
    message = answer.get("message") if isinstance(answer, dict) else None
    if not isinstance(message, dict):
        raise LocalBadReply("no_message")
    calls = message.get("tool_calls")
    if isinstance(calls, list) and calls:
        fn = calls[0].get("function") if isinstance(calls[0], dict) else None
        name = fn.get("name") if isinstance(fn, dict) else None
        if name not in tool_names:
            raise LocalBadReply("bad_tool_call")
        args = _arguments(fn.get("arguments"))
        return {"tool": name, "args": args, "reason": words(args.pop("reason", ""), 20)}
    final = parse_strict(message.get("content"))
    if final is None:
        raise LocalBadReply("no_final")
    if "reason" in final:
        final["reason"] = words(final["reason"], 20)
    return {"final": final}


def _answered_model(answer: Any) -> str:
    name = answer.get("model") if isinstance(answer, dict) else None
    return name.strip() if isinstance(name, str) and name.strip() else "unknown"


# ------------------------------------------------------------------ provider


class LocalProvider:
    """`agent_loop.Provider` on a local Ollama model. Fake transports are patched in `model_transport` by tests."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        url: str | None = None,
        timeout: float = TIMEOUT_S,
        num_ctx: int | None = None,
        keep_alive: Any = None,
        think: bool = False,
        *,
        system: str = "",
        num_predict: int = NUM_PREDICT,
    ) -> None:
        self.model, self.url, self.timeout = model, url, float(timeout)
        self.num_ctx, self.keep_alive, self.think = num_ctx, keep_alive, bool(think)
        self.system, self.num_predict = system, int(num_predict)
        self.models_seen: list[str] = []
        self._totals: dict[str, float] = {
            "calls": 0,
            "retries": 0,
            "trimmed": 0,
            "seconds": 0.0,
            **dict.fromkeys(_STATS_KEYS, 0),
        }

    # -- request
    def build_body(self, messages: list[dict], tool_specs: list[dict]) -> dict:
        options: dict[str, Any] = {"temperature": 0, "num_predict": self.num_predict}
        if self.num_ctx:
            options["num_ctx"] = int(self.num_ctx)
        tools = ollama_tools(tool_specs)
        fitted, trimmed = fit_to_window(
            to_ollama_messages(messages, self.system),
            tools,
            self.num_ctx,
            self.num_predict,
        )
        self._totals["trimmed"] += trimmed
        body: dict[str, Any] = {
            "model": self.model,
            "messages": fitted,
            "stream": False,
            "think": self.think,
            "options": options,
        }
        if tools:
            body["tools"] = tools
        return body

    def _url_matches(self) -> bool:
        if self.url is None:
            return True
        try:
            current = model_transport.endpoint("/api/chat")
        except (model_transport.ModelHostRefused, model_transport.LocalEngineNotLoaded):
            return False
        return current == str(self.url).rstrip("/") + "/api/chat"

    def _post(self, body: dict) -> Any:
        if not self._url_matches():
            raise LocalTransportError("url_mismatch")
        try:
            if self.keep_alive is None:
                return model_transport.post_json_retrying(
                    "/api/chat", body, timeout=self.timeout
                )
            with model_transport.keep_alive_override(self.keep_alive):
                return model_transport.post_json_retrying(
                    "/api/chat", body, timeout=self.timeout
                )
        except Exception as exc:  # noqa: BLE001 - only the type name is kept and logged; raised below, chain dropped
            log.warning("local lead call failed (%s)", type(exc).__name__)
            code = "transport_" + type(exc).__name__
        raise LocalTransportError(code)

    # -- numbers for the speed test
    def _count(self, answer: Any, seconds: float) -> None:
        self._totals["calls"] += 1
        self._totals["seconds"] += seconds
        if isinstance(answer, dict):
            for k in _STATS_KEYS:
                v = answer.get(k)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    self._totals[k] += v
        name = _answered_model(answer)
        if name != "unknown" and name not in self.models_seen:
            self.models_seen.append(name)

    @property
    def stats(self) -> dict:
        """Numbers only. Durations are nanoseconds as Ollama reports them; tokens per second is None until measured."""
        t = dict(self._totals)

        def rate(count: str, dur: str):
            return t[count] / (t[dur] / 1e9) if t[dur] > 0 else None

        return {
            **t,
            "prompt_tokens_per_second": rate(
                "prompt_eval_count", "prompt_eval_duration"
            ),
            "generation_tokens_per_second": rate("eval_count", "eval_duration"),
        }

    # -- the Provider protocol
    def _ask(self, body: dict) -> Any:
        started = time.monotonic()
        answer = self._post(body)
        self._count(answer, time.monotonic() - started)
        return answer

    def complete(self, messages: list[dict], tool_specs: list[dict]) -> dict:
        """One call; a bad reply gets ONE internal retry with a fixed corrective message. Transport errors never retry."""
        body = self.build_body(messages, tool_specs)
        names = {t["function"]["name"] for t in body.get("tools", [])}
        answer = self._ask(body)
        retry = False
        try:
            reply = parse_reply(answer, names)
        except LocalBadReply:
            retry = True
        # outside the except block: no chained exception, one retry, never a loop
        if retry:
            self._totals["retries"] += 1
            answer = self._ask(
                {
                    **body,
                    "messages": [*body["messages"], {"role": "user", "content": NUDGE}],
                }
            )
            reply = parse_reply(answer, names)
        return {**reply, "usd": 0.0, "model": _answered_model(answer)}

    def unload(self) -> bool:
        """Ask Ollama to drop the model now (#666). False when it would not."""
        return bool(model_memory.unload(self.model))

    @contextmanager
    def session(self, wait_seconds: float | None = None):
        """Heavy lock around a batch of calls; the model is unloaded in `finally`, even when a call raises."""
        wait = (
            heavy_lock.wait_seconds_from_env() if wait_seconds is None else wait_seconds
        )
        with heavy_lock.held(LOCK_KIND, wait_seconds=wait):
            try:
                yield self
            finally:
                try:
                    self.unload()
                except Exception as exc:  # noqa: BLE001 - never replaces the original error; the type name only
                    log.warning(
                        "local lead model unload failed (%s)", type(exc).__name__
                    )

    def engine_info(self) -> dict:
        return engine_info()


# ------------------------------------------------------------------ what the server says it runs


def _probe(path: str) -> Any:
    try:
        return model_transport.get_json(path, timeout=PROBE_TIMEOUT_S, required=False)
    except Exception as exc:  # noqa: BLE001 - recorded as the type name, never raised
        log.warning("engine probe failed (%s)", type(exc).__name__)
        return {"error": type(exc).__name__}


def _model_row(m: Any) -> dict:
    m = m if isinstance(m, dict) else {}
    details = m.get("details") if isinstance(m.get("details"), dict) else {}
    size, vram = m.get("size"), m.get("size_vram")
    ok = (
        all(
            isinstance(x, (int, float)) and not isinstance(x, bool)
            for x in (size, vram)
        )
        and size
    )
    return {
        "name": m.get("name") or m.get("model"),
        "size": size,
        "size_vram": vram,
        "gpu_fraction": (vram / size) if ok else None,
        "context_length": m.get("context_length"),
        "family": details.get("family"),
        "parameter_size": details.get("parameter_size"),
        "quantization_level": details.get("quantization_level"),
    }


def engine_info() -> dict:
    """What the Ollama server says it runs: GET /api/version and /api/ps only (read-only), nothing assumed."""
    version, ps = _probe("/api/version"), _probe("/api/ps")
    models = ps.get("models") if isinstance(ps, dict) else None
    return {
        "version": version.get("version") if isinstance(version, dict) else None,
        "loaded": [_model_row(m) for m in models] if isinstance(models, list) else [],
        "errors": [
            x["error"] for x in (version, ps) if isinstance(x, dict) and "error" in x
        ],
    }
