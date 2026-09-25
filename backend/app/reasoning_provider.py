"""One interface for "give this bounded packet to a model and tell me exactly
what answered".

WHY THIS EXISTS. Today nothing in the system can say WHICH model produced an
answer. `review_runs.model_name` is NULL on every row and nothing writes it;
there is no `provider`, no `model_tag` and no digest column anywhere; and on
the local path the information was available and thrown away, because Ollama
reports the tag it loaded in every response and `synthesis.Generation` kept
only the text. That is B54, and it is symmetric - neither engine recorded
itself, so provenance is not a cost of adding a second provider. It is a debt
the first one already had.

So provenance is not an optional field here. A `Response` cannot be built
without a provider name, and the model tag is whatever the ENGINE reported,
never what configuration asked for: a floating tag can move under a running
system, and that is precisely the case where the recorded value earns its keep.

WHAT THIS IS NOT. It is not a refactor of the `claude_*` modules. Those take
an injected `model_call(prompt) -> str` and each one owns a prompt builder, a
`Reason` enum and gates that encode measured defects; flattening them into a
generic interface would spend risk in the wrong place for no gain. When cloud
processing is authorised in writing, `ClaudeProvider` becomes a thin adapter
over the existing `reader_api` / `reader_transport` client - one request
builder, one socket, one audit line - and those modules are left alone.

EGRESS. `OllamaProvider` is local and carries no egress question: it talks to
the URL `model_transport` validates, which is loopback unless an explicit
allow-list says otherwise. A future `ClaudeProvider` inherits the two existing
flags (`STANDARDS_READER_ENABLED`, `STANDARDS_READER_ALLOW_PUBLIC_EGRESS`) and
any new switch is ANDed with them, never ORed - a second switch that can turn
egress ON is not a guard, it is a bypass.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Protocol

from . import model_transport
from .config import settings

log = logging.getLogger(__name__)

#: Every provider name that may appear in a stored answer. A closed set,
#: because "which engine produced this" is a question with a finite list of
#: answers and an open string invites a typo to become a new provider.
OLLAMA = "ollama"
CLAUDE = "claude"
PROVIDERS = (OLLAMA, CLAUDE)


class ProviderRefused(RuntimeError):
    """The provider would not make the call, and says why.

    A refusal is not an empty answer. The distinction is the same one B44 draws
    for an unreadable file and B50 for an unparseable response: "it did not
    happen, here is the reason" and "it happened and produced nothing" are
    different facts, and only one of them is about the model.
    """


@dataclass(frozen=True)
class Packet:
    """What is sent. Built by Python, never by a model.

    `num_ctx` and `num_predict` are REQUIRED and explicit. The Phase A matrix
    was run with them pinned for exactly this reason: a defaulted context
    window silently changes what the model saw between two runs that are then
    compared as if they were the same test.
    """

    prompt: str
    num_ctx: int
    num_predict: int
    temperature: float = 0.0
    #: A JSON schema the answer must satisfy. Ollama enforces it in the
    #: engine (`format`); for Claude it is stated in the prompt AND checked in
    #: code here (`schema_errors`) - the gate never depends on the model.
    json_schema: dict | None = None
    #: Stable text sent as a CACHED system block (Claude prompt caching), e.g.
    #: instructions and a standard's text reused across calls. Ollama gets it
    #: prepended to the prompt.
    system: str = ""
    #: The budget step this call is charged to (claude_spend).
    step: str = "unassigned"
    #: Part of the Claude response-cache key: a changed prompt must say so.
    prompt_version: str = "unversioned"
    #: Off by default. Measured on the frozen packet: thinking on cost roughly
    #: seven times the wall time for the same answer, and twice ran out of
    #: budget inside the thinking channel and returned nothing at all.
    think: bool = False
    seed: int | None = None
    options: dict[str, object] = field(default_factory=dict)

    @property
    def sha256(self) -> str:
        """What was actually sent, so a result can be tied to its input."""
        text = self.prompt if not self.system else self.system + "\x00" + self.prompt
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Response:
    """What came back, and what produced it.

    `provider` and `model_tag` are not optional and not defaulted: a stored
    answer that cannot name its engine is a claim without provenance.
    `finish_reason` carries Ollama's `done_reason` verbatim, because "stop" and
    "length" are different outcomes and a truncated answer that reads as
    complete is the failure mode the Phase A runs hit twice.
    """

    text: str
    provider: str
    #: As the ENGINE reported it, never as configuration asked for it.
    model_tag: str
    #: sha256 of the response text. There is no content-addressed digest from
    #: either engine, so this is ours: it identifies the answer, not the model.
    digest: str
    finish_reason: str
    prompt_sha256: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    wall_time_s: float = 0.0
    thinking: str = ""
    #: Empty when the packet had no schema or the answer satisfied it; else
    #: why not. A caller treats a non-empty tuple exactly like invalid JSON.
    schema_errors: tuple = ()
    cost_usd: float | None = None

    def __post_init__(self) -> None:
        if self.provider not in PROVIDERS:
            raise ValueError(f"unknown provider {self.provider!r}; expected one of {PROVIDERS}")
        if not self.model_tag:
            raise ValueError(
                "a response with no model tag cannot be stored: provenance is "
                "the one thing this interface exists to guarantee")

    @property
    def truncated(self) -> bool:
        """The cap ended it, not the model - `synthesis.Generation`'s rule."""
        return self.finish_reason == "length"


class ReasoningProvider(Protocol):
    """One method. A third provider must require no change to any caller."""

    name: str

    def reason(self, packet: Packet) -> Response: ...


class OllamaProvider:
    """The local engine, through the one transport allowed to reach it.

    Never calls httpx itself: `model_transport` is on the socket allow-list
    that `test_socket_containment` enforces across the whole package, and it
    re-validates the URL immediately before the socket. A module that opened
    its own connection would fail that test by construction, which is the
    point of it.
    """

    name = OLLAMA

    def __init__(self, model: str | None = None) -> None:
        #: Configuration's ANSWER, not the engine's. Recorded separately from
        #: the tag the response reports, so the two can disagree visibly.
        self.requested_model = model or settings.answer_model

    def reason(self, packet: Packet) -> Response:
        options: dict[str, object] = {
            "temperature": packet.temperature,
            "num_ctx": packet.num_ctx,
            "num_predict": packet.num_predict,
            **packet.options,
        }
        if packet.seed is not None:
            options["seed"] = packet.seed
        body = {
            "model": self.requested_model,
            "prompt": (packet.system + "\n\n" + packet.prompt) if packet.system else packet.prompt,
            "stream": False,
            "think": packet.think,
            "options": options,
        }
        if packet.json_schema is not None:
            body["format"] = packet.json_schema
        started = time.time()
        try:
            raw = model_transport.post_json("/api/generate", body)
        # Broad on purpose, and it RE-RAISES: every transport failure becomes a
        # named refusal rather than an empty answer. No `noqa` is needed -
        # ruff's blind-except rule is about swallowing, which this does not do.
        except Exception as exc:
            raise ProviderRefused(f"{self.name}: {type(exc).__name__}: {exc}") from exc
        wall = time.time() - started

        text = str(raw.get("response") or "").strip()
        # THE ENGINE'S OWN ANSWER about what ran. Falling back to the requested
        # tag would quietly paper over precisely the case worth recording - a
        # floating tag that resolved to something else - so the fallback is
        # marked rather than silent.
        reported = str(raw.get("model") or "")
        model_tag = reported or f"{self.requested_model} (unreported)"
        return Response(
            text=text,
            provider=self.name,
            model_tag=model_tag,
            digest=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            finish_reason=str(raw.get("done_reason") or ""),
            prompt_sha256=packet.sha256,
            tokens_in=raw.get("prompt_eval_count"),
            tokens_out=raw.get("eval_count"),
            wall_time_s=round(wall, 3),
            thinking=str(raw.get("thinking") or ""),
            schema_errors=schema_errors(text, packet.json_schema),
        )


# ------------------------------------------------------------ JSON schema gate

def _check(value, schema: dict, path: str, errors: list[str]) -> None:
    """The subset of JSON Schema this project uses: type (incl. lists of
    types), enum, properties, required, items. Unknown keywords are ignored."""
    kinds = schema.get("type")
    kinds = [kinds] if isinstance(kinds, str) else (kinds or [])
    ok_type = {
        "object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list),
        "string": lambda v: isinstance(v, str), "boolean": lambda v: isinstance(v, bool),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "null": lambda v: v is None,
    }
    if kinds and not any(ok_type.get(k, lambda v: False)(value) for k in kinds):
        errors.append(f"{path or '$'}: expected {'/'.join(kinds)}")
        return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path or '$'}: not one of the allowed values")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: required")
        for key, sub in (schema.get("properties") or {}).items():
            if key in value:
                _check(value[key], sub, f"{path}.{key}", errors)
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(value):
            _check(item, schema["items"], f"{path}[{i}]", errors)


def schema_errors(text: str, schema: dict | None) -> tuple:
    """() when `schema` is None or `text` is JSON satisfying it."""
    if schema is None:
        return ()
    body = text.strip()
    fence = re.match(r"^```[a-zA-Z]*\s*\n(.*)\n```$", body, re.DOTALL)
    if fence:
        body = fence.group(1)
    try:
        value = json.loads(body)
    except json.JSONDecodeError:
        return ("not valid JSON",)
    errors: list[str] = []
    _check(value, schema, "", errors)
    return tuple(errors)


# -------------------------------------------------------------- Claude provider

#: Anthropic `stop_reason` -> the `finish_reason` vocabulary Ollama uses, so
#: `Response.truncated` means the same thing for both engines.
_STOP = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length"}


class ClaudeProvider:
    """The Claude API through the ONE approved transport (`reader_transport`).

    The request is built by `reader_api.build_request` - both egress flags,
    https, allowed host and key are checked there - and this class only adds
    the model (from configuration), max_tokens, a CACHED system block and the
    schema instruction. Before the call leaves, `claude_spend.ensure_affordable`
    refuses it if its worst case could cross a USD cap; after it returns, the
    ledger records tokens and cost (never text, never the key).
    """

    name = CLAUDE

    def __init__(self, model: str | None = None, *, transport=None, step: str | None = None) -> None:
        self.requested_model = model or settings.claude_reasoning_model
        self._transport = transport
        self._step = step

    def _send(self):
        if self._transport is None:
            from . import reader_transport
            self._transport = reader_transport.transport()
            if self._transport is None:
                raise ProviderRefused("claude: egress is disabled (STANDARDS_READER_ENABLED / "
                                      "STANDARDS_READER_ALLOW_PUBLIC_EGRESS)")
        return self._transport

    def reason(self, packet: Packet) -> Response:
        from dataclasses import replace

        from . import claude_spend, reader_api

        step = self._step or packet.step
        prompt = packet.prompt
        if packet.json_schema is not None:
            prompt += ("\n\nReturn ONLY one JSON value that satisfies this JSON schema, with no "
                       "other text:\n" + json.dumps(packet.json_schema, separators=(",", ":")))
        cfg = replace(reader_api.ReaderSettings.from_env(), model=self.requested_model,
                      max_tokens=packet.num_predict, timeout_seconds=120.0)
        try:
            request = reader_api.build_request(prompt, cfg=cfg)
        except reader_api.ReaderRefused as exc:
            raise ProviderRefused(f"{self.name}: {exc}") from exc
        body = dict(request["body"])
        body["temperature"] = packet.temperature
        if packet.system:
            body["system"] = [{"type": "text", "text": packet.system,
                               "cache_control": {"type": "ephemeral"}}]
        # RESPONSE CACHE (owner rule 2026-09-25): the same (model, prompt
        # version, input) is answered from disk at USD 0, never re-bought.
        key = cache_key(self.requested_model, packet)
        cached = _cache_read(key)
        if cached is not None:
            claude_spend.record(step=step, model=cached["model_tag"], usage={},
                                prompt_sha256=packet.sha256, wall_time_s=0.0,
                                finish_reason="cache_hit")
            return Response(
                text=cached["text"], provider=self.name, model_tag=cached["model_tag"],
                digest=hashlib.sha256(cached["text"].encode("utf-8")).hexdigest(),
                finish_reason=cached["finish_reason"], prompt_sha256=packet.sha256,
                tokens_in=cached.get("tokens_in"), tokens_out=cached.get("tokens_out"),
                wall_time_s=0.0, schema_errors=schema_errors(cached["text"], packet.json_schema),
                cost_usd=0.0)
        claude_spend.ensure_affordable(
            step, claude_spend.worst_case_usd(self.requested_model, len(packet.system) + len(prompt),
                                              packet.num_predict))
        started = time.time()
        try:
            payload = self._send()(request["url"], headers=request["headers"], body=body,
                                   timeout=request["timeout"])
        except ProviderRefused:
            raise
        except Exception as exc:
            # The type and the transport's own message (status + host + error
            # TYPE only - reader_transport never puts headers in it).
            raise ProviderRefused(f"{self.name}: {type(exc).__name__}: {exc}") from exc
        wall = time.time() - started
        text = reader_api.response_text(payload).strip()
        usage = payload.get("usage") if isinstance(payload, dict) else None
        reported = str((payload or {}).get("model") or "")
        finish = _STOP.get(str((payload or {}).get("stop_reason") or ""), str((payload or {}).get("stop_reason") or ""))
        entry = claude_spend.record(step=step, model=reported or self.requested_model, usage=usage,
                                    prompt_sha256=packet.sha256, wall_time_s=wall, finish_reason=finish)
        if finish == "stop":   # a truncated answer is not worth keeping
            _cache_write(key, {"text": text, "model_tag": reported or self.requested_model,
                               "finish_reason": finish, "tokens_in": (usage or {}).get("input_tokens"),
                               "tokens_out": (usage or {}).get("output_tokens")})
        return Response(
            text=text, provider=self.name,
            model_tag=reported or f"{self.requested_model} (unreported)",
            digest=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            finish_reason=finish, prompt_sha256=packet.sha256,
            tokens_in=(usage or {}).get("input_tokens"), tokens_out=(usage or {}).get("output_tokens"),
            wall_time_s=round(wall, 3), schema_errors=schema_errors(text, packet.json_schema),
            cost_usd=entry["cost_usd"],
        )


# ----------------------------------------------------------- response cache

def cache_key(model: str, packet: Packet) -> str:
    """Everything that changes the answer: model id, prompt version, the input
    (system + prompt) hash, schema, temperature, seed, max tokens."""
    parts = [model, packet.prompt_version, packet.sha256,
             json.dumps(packet.json_schema, sort_keys=True), str(packet.temperature),
             str(packet.seed), str(packet.num_predict)]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _cache_path(key: str):
    from pathlib import Path
    return Path(settings.claude_cache_dir) / key[:2] / f"{key}.json"


def _cache_read(key: str) -> dict | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _cache_write(key: str, value: dict) -> None:
    path = _cache_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------- selection

def claude_available() -> tuple[bool, str]:
    """Whether Claude may be used, and if not, why (never the key itself)."""
    from . import reader_api

    if (settings.reasoning_provider or "").strip().lower() != CLAUDE:
        return False, f"REASONING_PROVIDER={settings.reasoning_provider!r}"
    cfg = reader_api.ReaderSettings.from_env()
    if not (cfg.enabled and cfg.allow_public_egress):
        return False, "standards-reader egress flags are off"
    import os
    if not (str(os.environ.get(reader_api.API_KEY_ENV) or "").strip()
            or str(settings.anthropic_api_key or "").strip()):
        return False, "no ANTHROPIC_API_KEY"
    return True, "claude"


def get_provider(role: str = "reasoning", *, step: str | None = None) -> ReasoningProvider:
    """The configured provider. `role` = "reasoning" (Sonnet class) or
    "labelling" (Haiku class). Claude only when `claude_available()`;
    otherwise the local engine, and the reason is logged - a fallback is never
    silent."""
    ok, why = claude_available()
    if ok:
        model = settings.claude_labelling_model if role == "labelling" else settings.claude_reasoning_model
        return ClaudeProvider(model, step=step)
    if (settings.reasoning_provider or "").strip().lower() == CLAUDE:
        log.warning("reasoning provider: claude requested but not available (%s); using ollama", why)
    return OllamaProvider()
