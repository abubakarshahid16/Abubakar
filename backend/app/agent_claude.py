"""The Claude provider for the agent proof test (#1690, part of #805). Behind `AGENT_REVIEW_ENABLED`.

`ClaudeProvider` implements `agent_loop.Provider`: `complete(messages, tool_specs)` returns one dict,
{"tool", "args", "reason", "usd"} or {"final": {...}, "usd"}. EVERY call goes through `reader_transport`
(the one Claude socket) wrapped by `claude_spend.metered(step="agent_review")`, so the caps, the approved-document
gate and the ledger apply as on every other Claude lane. This module opens no socket, adds no flag and never reads
`backend/.env`. KEY: the process environment first (ANTHROPIC_API_KEY), then the app's own settings fallback exactly as
`reader_api` does it (`settings.anthropic_api_key`, loaded from backend/.env by the settings model; this module reads no
file). SWITCHES (REASONING_PROVIDER and both STANDARDS_READER_* flags): an `env` a caller injects is obeyed exactly; otherwise the process
environment decides, and for any of those three names the environment does NOT say at all, the app settings (loaded from
`backend/.env` by the settings model, which the server does not copy into `os.environ`) stand in (`_env_with_settings`). The
environment wins whenever it says anything, including "0". This module reads no file.
The key lives only in a call-local env copy for `build_request` and in the request headers; it is never stored on
the provider, in a module global, the ledger, a trace or an error (codes only).

THE CALLER (the runner) must wrap the run in `claude_approved.per_request_consent(ids)` / `claude_approved.carrying(ids)`
with exactly the selected documents. Without a declaration every call fails closed with `DocumentNotApproved` (a
`BudgetExceeded`, so `AgentBudgetStop`) and nothing is sent.

RUN CAP. One process-wide `SpendMeter` (default USD 10, the owner's cap for the whole test) is shared by the provider and by every
`second_opinion` made with it: before each call `spent + worst case of that request > cap` raises `AgentBudgetStop`
without sending; after it, the real usd is added. `provider.spent` is the runner's read-out.

Errors carry a CODE only, never document or standard text. The loop turns any raised error into a YELLOW
"ask the engineer" finding; this module never returns a verdict it could not parse.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from app import claude_spend
from app.agent_trace import words
from app.claude_image_tokens import json_counts

STEP = "agent_review"
LEAD_MODEL = "claude-sonnet-5-5"
SECOND_MODEL = "claude-opus-5-5"
MAX_TOKENS = 2048
SECOND_MAX_TOKENS = 400
TOTAL_CAP_USD = 10.0
#: REASONING_PROVIDER=claude opens the lane for every reasoning step. Under `per_task` (owner, 12 Nov 2026) it opens ONLY
#: when the AI reviewer's OWN engine setting (AGENT_REVIEW_ENGINE, `settings.agent_review_engine`) says claude, as every
#: other step with an engine setting works (`reasoning_provider.claude_unavailable_for_task`). `ollama` refuses all.
ENGINE_ENV = "AGENT_REVIEW_ENGINE"
_CACHE = {"type": "ephemeral"}

SYSTEM_RULES = (
    "You are a senior engineer reviewing one item of a submittal. Use one tool per turn. "
    "Finish with ONE JSON object (no other text) with keys: item, doc, color (GREEN, YELLOW or RED), page, "
    "doc_quote, clause_quote, standard, clause, action, priority (must, should, nice), reason (at most 20 words). "
    "Quote the document exactly. Not mentioned is never GREEN. Never state confidence. "
    "Numbers are decided by the compare_number tool, not by you. When unsure, ask the engineer."
)


class SpendMeter:
    """Run-level USD meter shared by a provider and its second opinions."""

    def __init__(self, cap_usd: float = TOTAL_CAP_USD) -> None:
        self.cap, self.spent = float(cap_usd), 0.0

    def check(self, worst: float) -> None:
        if self.spent + worst > self.cap:
            raise AgentBudgetStop("test_cap")

    def add(self, usd: float) -> None:
        self.spent += float(usd)


_SHARED = SpendMeter()


def reset_shared_meter_for_tests() -> None:
    """Tests only: the process-wide meter back to zero and the default cap."""
    _SHARED.cap, _SHARED.spent = TOTAL_CAP_USD, 0.0


class AgentClaudeError(RuntimeError):
    """Base: the message is a code, never text from a document."""

    code = "agent_claude_error"
    fatal = False  # True: the run must STOP (agent_loop re-raises it instead of making a YELLOW finding)

    def __init__(self, code: str | None = None) -> None:
        self.code = code or self.code
        super().__init__(self.code)


class AgentGateClosed(AgentClaudeError):
    code = "gate_closed"
    fatal = True


class AgentBudgetStop(AgentClaudeError):
    code = "budget_stop"
    fatal = True


class AgentBadReply(AgentClaudeError):
    code = "bad_reply"
    usd: float | None = (
        None  # what the call cost (its own usage, else the worst case), when known
    )


class AgentTransportError(AgentClaudeError):
    code = "transport_error"


# ------------------------------------------------------------------ request


def _env_with_settings() -> dict:
    """The process environment, plus the app settings' value for each gate flag the environment does not say at all.

    The server does not copy `backend/.env` into `os.environ` (config.py), so a deployment that switches the lane on
    in `.env` was invisible here. The environment still WINS when it says anything, including "0" (the same rule as
    `reader_api._flag_or`): one shell line keeps every document on the machine. A key is read by `_resolve_key`."""
    from app.config import settings

    out = dict(os.environ)
    wanted = {
        "REASONING_PROVIDER": settings.reasoning_provider,
        ENGINE_ENV: settings.agent_review_engine,
        "STANDARDS_READER_ENABLED": "1" if settings.standards_reader_enabled else "",
        "STANDARDS_READER_ALLOW_PUBLIC_EGRESS": "1"
        if settings.standards_reader_allow_public_egress
        else "",
    }
    for name, value in wanted.items():
        if not str(out.get(name) or "").strip() and str(value or "").strip():
            out[name] = str(value).strip()
    return out


def gate_open(env: dict | None = None) -> bool:
    """True only when the lane's provider switch is open: in the given `env` (obeyed exactly), else in the process
    environment with the app settings behind it (`_env_with_settings`). The two egress flags and the key are checked again
    where the request is built and where it is sent."""
    env = _env_with_settings() if env is None else env
    provider = str(env.get("REASONING_PROVIDER") or "").strip().lower()
    if provider == "claude":
        return True
    # per_task: only when this reviewer's own engine says claude. Anything else (ollama, unknown, empty) is closed.
    return (
        provider == "per_task"
        and str(env.get(ENGINE_ENV) or "").strip().lower() == "claude"
    )


def _resolve_key(env: dict, reader_api) -> str:
    """The API key: `env` first, then the app's settings fallback (as `reader_api` does). Never logged or kept.

    A failing fallback or a missing key is a code that says where we looked, never what we found.
    """
    key = str(env.get(reader_api.API_KEY_ENV) or "").strip()
    if key:
        return key
    recorded_failure = False
    try:
        _env, fallback = reader_api._sources(None)
        key = str(getattr(fallback, "anthropic_api_key", "") or "").strip()
    except Exception:  # noqa: BLE001 - a bad .env or import failure: code only, raised OUTSIDE this block
        recorded_failure = True
    if recorded_failure:
        raise AgentGateClosed("settings_unreadable")
    if not key:
        raise AgentGateClosed("no_key_in_env_or_settings")
    return key


#: the wait for one answer: 120 s, and longer only for a limit above 4,800 tokens: limit / SLOW_TOKENS_PER_SECOND seconds
#: (40 tokens a second is a slow rate), so a 12,000-token retry waits 300 s and every other call keeps 120 s.
BASE_TIMEOUT_SECONDS = 120.0
SLOW_TOKENS_PER_SECOND = 40.0


def request_timeout(max_tokens: int) -> float:
    return max(BASE_TIMEOUT_SECONDS, int(max_tokens) / SLOW_TOKENS_PER_SECOND)


def _request(model: str, max_tokens: int, env: dict | None) -> dict:
    """url, headers, timeout and a body shell from `reader_api.build_request` (both flags, https, host, key)."""
    from app import reader_api

    env = _env_with_settings() if env is None else env
    if not gate_open(env):
        raise AgentGateClosed
    key = _resolve_key(env, reader_api)
    built, refused = None, False
    try:
        cfg = replace(
            reader_api.ReaderSettings.from_env(env),
            model=model,
            max_tokens=int(max_tokens),
            timeout_seconds=request_timeout(max_tokens),
        )
        # a call-local copy carries the key ONLY for this build; the flags above were read from `env` alone
        built = reader_api.build_request(
            "x", cfg=cfg, env={**env, reader_api.API_KEY_ENV: key}
        )
    except reader_api.ReaderRefused:
        refused = True
    key = ""  # no frame of a later error keeps it
    if refused:
        raise AgentGateClosed
    return built


def _transport(send: Callable | None) -> Callable:
    if send is not None:
        return send
    from app import reader_transport

    found = reader_transport.transport()
    if found is None:
        raise AgentGateClosed
    return found


def _metered(send: Callable):
    from app import reader_transport

    return claude_spend.metered(
        send,
        step=STEP,
        unbilled=reader_transport.unbilled,
        keep_if=lambda _answer: False,
    )  # a loop turn is never replayed from the cache


def anthropic_tools(tool_specs: list[dict]) -> list[dict]:
    """Loop specs (name, description, input_schema or params) as Anthropic tools; each gets a `reason` field."""
    tools = []
    for spec in tool_specs or []:
        schema = spec.get("input_schema")
        if not isinstance(schema, dict):
            params = spec.get("params") or {}
            names = params.keys() if isinstance(params, dict) else params
            props = {str(n): {"type": "string"} for n in names}
            if isinstance(params, dict):
                props = {
                    str(n): (
                        v
                        if isinstance(v, dict)
                        else {"type": "string", "description": str(v)}
                    )
                    for n, v in params.items()
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
                "name": str(spec.get("name")),
                "description": str(spec.get("description") or ""),
                "input_schema": schema,
            }
        )
    return tools


def _text(content: Any) -> str:
    return (
        content
        if isinstance(content, str)
        else json.dumps(content, ensure_ascii=False, default=str)
    )


def to_api_messages(messages: list[dict]) -> tuple[list[dict], list[str]]:
    """Loop messages -> (Anthropic messages, system texts). The first user block is cache-marked."""
    out: list[dict] = []
    system: list[str] = []
    pending_id: str | None = None
    n = 0
    for m in messages or []:
        role, content = m.get("role"), m.get("content")
        if role == "system":
            system.append(_text(content))
        elif role == "assistant" and isinstance(content, dict) and "tool" in content:
            n += 1
            pending_id = f"toolu_{n:04d}"
            block = {
                "type": "tool_use",
                "id": pending_id,
                "name": str(content.get("tool")),
                "input": {
                    **(content.get("args") or {}),
                    "reason": content.get("reason") or "",
                },
            }
            out.append({"role": "assistant", "content": [block]})
        elif role == "assistant":
            out.append(
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": _text(content) or "."}],
                }
            )
        elif role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": pending_id or "toolu_0000",
                "content": _text(content),
            }
            out.append({"role": "user", "content": [block]})
        else:
            out.append(
                {"role": "user", "content": [{"type": "text", "text": _text(content)}]}
            )
    for first in out:
        if first["role"] == "user":
            first["content"][-1] = {
                **first["content"][-1],
                "cache_control": dict(_CACHE),
            }
            break
    return out, system


def _usd(model: str, answer: dict, body: dict) -> float:
    usage = answer.get("usage")
    if isinstance(usage, dict) and usage:
        return float(claude_spend.cost_usd(model, usage))
    chars, images = json_counts([body.get("messages"), body.get("system")])
    return float(
        claude_spend.worst_case_usd(
            model, chars, int(body.get("max_tokens") or 0), image_tokens=images
        )
    )


def _answered_model(answer: Any) -> str:
    """The model that ANSWERED, from the API response (never from configuration); 'unknown' if absent."""
    name = answer.get("model") if isinstance(answer, dict) else None
    return name.strip() if isinstance(name, str) and name.strip() else "unknown"


def _send_once(raw: Callable, request: dict, body: dict) -> tuple[Any, tuple | None]:
    """One metered send. (answer, None) or (None, (kind, code, billed)); the original error is not carried out."""
    from app import reader_transport

    recorded_failure: tuple | None = None
    try:
        return _metered(raw)(
            request["url"],
            headers=request["headers"],
            body=body,
            timeout=request["timeout"],
        ), None
    except claude_spend.StopRun as exc:
        code = getattr(exc, "code", None) or getattr(
            type(exc), "count_key", "budget_stop"
        )
        recorded_failure = ("stop", str(code), False)
    except Exception as exc:  # noqa: BLE001 - type only; the text may carry a host or a status
        recorded_failure = (
            "transport",
            "transport_" + type(exc).__name__,
            not reader_transport.unbilled(exc),
        )
    return None, recorded_failure


def _bad_reply(code: str, usd: float) -> AgentBadReply:
    """A bad reply that carries what the call cost: the answer's own usage when it came back, else the worst case."""
    exc = AgentBadReply(code)
    exc.usd = float(usd)
    return exc


def _call(
    model: str,
    body_parts: dict,
    max_tokens: int,
    send: Callable | None,
    env: dict | None,
    meter: SpendMeter | None = None,
) -> tuple[dict, float]:
    from app import claude_approved

    declared = claude_approved.carried()
    if (
        not declared
    ):  # absent or empty: we cannot tell what a prompt carries, so nothing is sent
        raise AgentGateClosed("undeclared_documents")
    # An image block counts by the published image rule, not as its base64 text.
    chars, images = json_counts(
        body_parts.get(k) for k in ("messages", "system", "tools")
    )
    worst = claude_spend.worst_case_usd(
        model, chars, int(max_tokens), image_tokens=images
    )
    if meter is not None:
        meter.check(worst)
    raw = _transport(send)
    # the request (and so the key) exists only from here: every raise above holds no key in any frame
    request = _request(model, max_tokens, env)
    body = dict(request["body"])
    body.update(body_parts)
    body["model"], body["max_tokens"] = model, int(max_tokens)
    answer, failure = _send_once(raw, request, body)
    # the headers (the key) leave this frame before any error is raised from it
    del request
    if failure is not None:
        kind, code, billed = failure
        if meter is not None and billed:
            meter.add(worst)  # may have been billed: charged at the worst case
        if kind == "stop":
            raise AgentBudgetStop(code)
        raise AgentTransportError(code)
    usd = _usd(model, answer, body) if isinstance(answer, dict) else worst
    if meter is not None:
        meter.add(usd)  # a paid bad reply still counts toward the cap
    if not isinstance(answer, dict) or not isinstance(answer.get("content"), list):
        raise _bad_reply("bad_shape", usd)
    if answer.get("stop_reason") in ("refusal", "max_tokens"):
        raise _bad_reply("stop_" + str(answer.get("stop_reason")), usd)
    return answer, usd


# ------------------------------------------------------------------ parsing


def parse_json_object(text: str) -> dict | None:
    """The first JSON object in `text` (fenced or bare), or None."""
    s = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if fence:
        s = fence.group(1).strip()
    start = s.find("{")
    if start < 0:
        return None
    try:
        obj, _end = json.JSONDecoder().raw_decode(s[start:])
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def parse_reply(answer: dict, tool_names: set[str]) -> dict:
    """tool_use -> {"tool","args","reason"}; text -> {"final"}. One tool call per turn; anything else raises."""
    blocks = [b for b in answer.get("content") or [] if isinstance(b, dict)]
    uses = [b for b in blocks if b.get("type") == "tool_use"]
    if uses:
        use = uses[0]
        name, args = use.get("name"), use.get("input")
        if name not in tool_names or not isinstance(args, dict):
            raise AgentBadReply("bad_tool_call")
        args = dict(args)
        reason = words(args.pop("reason", ""), 20)
        return {"tool": name, "args": args, "reason": reason}
    text = "".join(str(b.get("text") or "") for b in blocks if b.get("type") == "text")
    final = parse_json_object(text)
    if final is None:
        raise AgentBadReply("no_final")
    if "reason" in final:
        final["reason"] = words(final["reason"], 20)
    return {"final": final}


# ------------------------------------------------------------------ provider


class ClaudeProvider:
    """`agent_loop.Provider` on Claude. `send` is a test's fake transport; None means `reader_transport`."""

    def __init__(
        self,
        model: str = LEAD_MODEL,
        *,
        system: str = "",
        max_tokens: int = MAX_TOKENS,
        send: Callable | None = None,
        env: dict | None = None,
        total_cap_usd: float | None = None,
        meter: SpendMeter | None = None,
    ) -> None:
        self.meter = meter or (
            _SHARED if total_cap_usd is None else SpendMeter(total_cap_usd)
        )
        self.model, self.system, self.max_tokens = model, system, int(max_tokens)
        self.send, self.env = send, env
        self.total_usd = 0.0

    @property
    def spent(self) -> float:
        return self.meter.spent

    def complete(self, messages: list[dict], tool_specs: list[dict]) -> dict:
        api_messages, extra_system = to_api_messages(messages)
        tools = anthropic_tools(tool_specs)
        system_text = "\n\n".join([SYSTEM_RULES, self.system, *extra_system]).strip()
        parts: dict = {
            "system": [
                {"type": "text", "text": system_text, "cache_control": dict(_CACHE)}
            ],
            "messages": api_messages,
        }
        if tools:
            parts["tools"] = tools
            parts["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": True}
        answer, usd = _call(
            self.model, parts, self.max_tokens, self.send, self.env, self.meter
        )
        reply = parse_reply(answer, {t["name"] for t in tools})
        self.total_usd += usd
        return {**reply, "usd": usd, "model": _answered_model(answer)}

    def second_opinion(self, finding: dict, evidence: dict, **kw) -> dict:
        """`second_opinion` through THIS provider's meter, send and env, so it counts toward the run cap."""
        kw.setdefault("send", self.send)
        kw.setdefault("env", self.env)
        kw.setdefault("lead_model", self.model)
        return _second_opinion(finding, evidence, meter=self.meter, **kw)


# ------------------------------------------------------------------ second opinion


def _second_opinion(
    finding: dict,
    evidence: dict,
    *,
    model: str = SECOND_MODEL,
    lead_model: str = LEAD_MODEL,
    send: Callable | None = None,
    env: dict | None = None,
    max_tokens: int = SECOND_MAX_TOKENS,
    meter: SpendMeter,
) -> dict:
    """A DIFFERENT model confirms or rejects a GREEN or RED finding from the verified quotes only.

    Returns {"agree": True | False | None, "reason": <= 20 words, "usd": float}. None (an unparsable reply, a closed
    gate, the cap, the same model as the lead) counts as disagree upstream, so the finding becomes YELLOW.
    """
    if model == lead_model:
        return {
            "agree": None,
            "reason": "same model as lead",
            "usd": 0.0,
            "model": "unknown",
        }
    prompt = json.dumps(
        {
            "colour": (finding or {}).get("color"),
            "document_quote": (evidence or {}).get("doc_quote"),
            "clause_quote": (evidence or {}).get("clause_quote"),
            "question": "Do these two quotes alone support this colour? GREEN means the document meets the clause; "
            "RED means it does not. Reply with ONE JSON object: "
            '{"agree": true or false, "reason": "at most 20 words"}',
        },
        ensure_ascii=False,
    )
    parts = {
        "system": [
            {"type": "text", "text": SECOND_SYSTEM, "cache_control": dict(_CACHE)}
        ],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt, "cache_control": dict(_CACHE)}
                ],
            }
        ],
    }
    try:
        answer, usd = _call(model, parts, max_tokens, send, env, meter)
    except AgentClaudeError as exc:
        return {
            "agree": None,
            "reason": words(exc.code, 20),
            "usd": 0.0,
            "model": "unknown",
        }
    text = "".join(
        str(b.get("text") or "")
        for b in answer.get("content") or []
        if isinstance(b, dict) and b.get("type") == "text"
    )
    obj = parse_json_object(text) or {}
    agree = obj.get("agree")
    if not isinstance(agree, bool):
        return {
            "agree": None,
            "reason": "unparsable reply",
            "usd": usd,
            "model": _answered_model(answer),
        }
    return {
        "agree": agree,
        "reason": words(obj.get("reason"), 20),
        "usd": usd,
        "model": _answered_model(answer),
    }


SECOND_SYSTEM = (
    "You are an independent senior engineer checking another reviewer's finding. Use only the two quotes given. "
    "If they do not clearly support the colour, answer false."
)


# ------------------------------------------------------------------ cost projector


def project_cost(
    n_items_done: int,
    n_items_total: int,
    usd_so_far: float,
    second_opinion_ratio: float,
) -> dict:
    """Projected run cost from the items done so far (the 5-item check).

    `usd_so_far` is everything spent on the items done (lead calls and any second opinions). Each REMAINING item is
    expected to cost the observed per-item average, plus `second_opinion_ratio` of it (the extra a second opinion adds,
    as a fraction, 0 when none is planned). With no item done there is nothing to project: `projected_total` is None.
    """
    done, total = int(n_items_done), int(n_items_total)
    ratio = max(0.0, float(second_opinion_ratio))
    so_far = float(usd_so_far)
    if done <= 0 or total < done or so_far < 0 or so_far != so_far:
        return {
            "per_item": None,
            "remaining": max(0, total - done),
            "projected_total": None,
        }
    per_item = so_far / done
    remaining = total - done
    return {
        "per_item": per_item,
        "remaining": remaining,
        "projected_total": so_far + remaining * per_item * (1.0 + ratio),
    }
