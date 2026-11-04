"""The Claude provider for the agent proof test (#1690, part of #805). Behind `AGENT_REVIEW_ENABLED`.

`ClaudeProvider` implements `agent_loop.Provider`: `complete(messages, tool_specs)` returns one dict,
{"tool", "args", "reason", "usd"} or {"final": {...}, "usd"}. EVERY call goes through `reader_transport`
(the one Claude socket) wrapped by `claude_spend.metered(step="agent_review")`, so the caps, the approved-document
gate and the ledger apply as on every other Claude lane. This module opens no socket, adds no flag and never reads
`backend/.env`: the gate is the process environment only (REASONING_PROVIDER, both STANDARDS_READER_* flags, the key).

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

STEP = "agent_review"
LEAD_MODEL = "claude-sonnet-5-5"
SECOND_MODEL = "claude-opus-5-5"
MAX_TOKENS = 2048
SECOND_MAX_TOKENS = 400
_OPEN_PROVIDERS = ("claude", "per_task")
_CACHE = {"type": "ephemeral"}

SYSTEM_RULES = (
    "You are a senior engineer reviewing one item of a submittal. Use one tool per turn. "
    "Finish with ONE JSON object (no other text) with keys: item, doc, color (GREEN, YELLOW or RED), page, "
    "doc_quote, clause_quote, standard, clause, action, priority (must, should, nice), reason (at most 20 words). "
    "Quote the document exactly. Not mentioned is never GREEN. Never state confidence. "
    "Numbers are decided by the compare_number tool, not by you. When unsure, ask the engineer."
)


class AgentClaudeError(RuntimeError):
    """Base: the message is a code, never text from a document."""

    code = "agent_claude_error"

    def __init__(self, code: str | None = None) -> None:
        self.code = code or self.code
        super().__init__(self.code)


class AgentGateClosed(AgentClaudeError):
    code = "gate_closed"


class AgentBudgetStop(AgentClaudeError):
    code = "budget_stop"


class AgentBadReply(AgentClaudeError):
    code = "bad_reply"


class AgentTransportError(AgentClaudeError):
    code = "transport_error"


# ------------------------------------------------------------------ request


def gate_open(env: dict | None = None) -> bool:
    """True only when the process environment opens the lane. `backend/.env` is never read here."""
    env = os.environ if env is None else env
    return str(env.get("REASONING_PROVIDER") or "").strip().lower() in _OPEN_PROVIDERS


def _request(model: str, max_tokens: int, env: dict | None) -> dict:
    """url, headers, timeout and a body shell from `reader_api.build_request` (both flags, https, host, key)."""
    from app import reader_api

    env = dict(os.environ) if env is None else env
    if not gate_open(env):
        raise AgentGateClosed
    try:
        cfg = replace(
            reader_api.ReaderSettings.from_env(env),
            model=model,
            max_tokens=int(max_tokens),
            timeout_seconds=120.0,
        )
        return reader_api.build_request("x", cfg=cfg, env=env)
    except reader_api.ReaderRefused:
        raise AgentGateClosed from None


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
    chars = len(json.dumps(body.get("messages"), default=str)) + len(
        json.dumps(body.get("system"), default=str)
    )
    return float(
        claude_spend.worst_case_usd(model, chars, int(body.get("max_tokens") or 0))
    )


def _call(
    model: str,
    body_parts: dict,
    max_tokens: int,
    send: Callable | None,
    env: dict | None,
) -> tuple[dict, float]:
    request = _request(model, max_tokens, env)
    raw = _transport(send)
    body = dict(request["body"])
    body.update(body_parts)
    body["model"], body["max_tokens"] = model, int(max_tokens)
    try:
        answer = _metered(raw)(
            request["url"],
            headers=request["headers"],
            body=body,
            timeout=request["timeout"],
        )
    except claude_spend.StopRun as exc:
        raise AgentBudgetStop(
            getattr(exc, "code", None) or getattr(type(exc), "count_key", "budget_stop")
        ) from None
    except Exception as exc:  # noqa: BLE001 - type only; the text may carry a host or a status
        raise AgentTransportError("transport_" + type(exc).__name__) from None
    if not isinstance(answer, dict) or not isinstance(answer.get("content"), list):
        raise AgentBadReply("bad_shape")
    if answer.get("stop_reason") in ("refusal", "max_tokens"):
        raise AgentBadReply("stop_" + str(answer.get("stop_reason")))
    return answer, _usd(model, answer, body)


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
    ) -> None:
        self.model, self.system, self.max_tokens = model, system, int(max_tokens)
        self.send, self.env = send, env
        self.total_usd = 0.0

    def complete(self, messages: list[dict], tool_specs: list[dict]) -> dict:
        api_messages, extra_system = to_api_messages(messages)
        tools = anthropic_tools(tool_specs)
        system_text = "\n\n".join([SYSTEM_RULES, self.system, *extra_system]).strip()
        parts: dict = {
            "system": [
                {"type": "text", "text": system_text, "cache_control": dict(_CACHE)}
            ],
            "messages": api_messages,
            "temperature": 0,
        }
        if tools:
            parts["tools"] = tools
            parts["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": True}
        answer, usd = _call(self.model, parts, self.max_tokens, self.send, self.env)
        reply = parse_reply(answer, {t["name"] for t in tools})
        self.total_usd += usd
        return {**reply, "usd": usd}


# ------------------------------------------------------------------ second opinion


def second_opinion(
    finding: dict,
    evidence: dict,
    *,
    model: str = SECOND_MODEL,
    lead_model: str = LEAD_MODEL,
    send: Callable | None = None,
    env: dict | None = None,
    max_tokens: int = SECOND_MAX_TOKENS,
) -> dict:
    """A DIFFERENT model confirms or rejects a GREEN or RED finding from the verified quotes only.

    Returns {"agree": True | False | None, "reason": <= 20 words, "usd": float}. None (an unparsable reply, a closed
    gate, the cap, the same model as the lead) counts as disagree upstream, so the finding becomes YELLOW.
    """
    if model == lead_model:
        return {"agree": None, "reason": "same model as lead", "usd": 0.0}
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
        "temperature": 0,
    }
    try:
        answer, usd = _call(model, parts, max_tokens, send, env)
    except AgentClaudeError as exc:
        return {"agree": None, "reason": words(exc.code, 20), "usd": 0.0}
    text = "".join(
        str(b.get("text") or "")
        for b in answer.get("content") or []
        if isinstance(b, dict) and b.get("type") == "text"
    )
    obj = parse_json_object(text) or {}
    agree = obj.get("agree")
    if not isinstance(agree, bool):
        return {"agree": None, "reason": "unparsable reply", "usd": usd}
    return {"agree": agree, "reason": words(obj.get("reason"), 20), "usd": usd}


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
