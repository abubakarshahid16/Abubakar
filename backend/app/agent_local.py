"""The LOCAL second opinion for the agent proof test (#1690, part of #805). Behind `AGENT_REVIEW_ENABLED`.

Owner decision (4 Nov): the second opinion on a GREEN or RED finding comes from the local Qwen 35B, a different model
family from the Claude lead, never from Claude. `LocalSecondOpinion.second_opinion(finding, evidence)` has the same
contract as the Claude one in `agent_claude`: {"agree": True | False | None, "reason": <= 20 words, "usd": 0.0,
"model": <the model name in the Ollama RESPONSE, "unknown" if absent or on failure>}. None (garbage, empty, any failure)
counts as disagree upstream, so the finding becomes YELLOW.

WHAT IS SENT: the verified document quote, the verified clause quote and the colour claimed. Nothing else.

THE ONE SOCKET. Every call goes through `model_transport.post_json_retrying` (the repo's pattern for local calls: one
retry after a timeout only). This module opens no socket and imports no http library. The destination is
`settings.ollama_url`, re-validated as loopback by `model_transport.endpoint` before every request; `model_transport`
takes no per-call URL, so the `url` argument here is only a CHECK: if given and it differs from the current setting the
call is refused (agree None) and nothing is sent. To point a run at the TEST Ollama (port 11435) the caller sets
OLLAMA_URL=http://127.0.0.1:11435 in the PROCESS environment before the app starts, never in `backend/.env`.

`session()` takes the heavy lock (kind "agent_second_opinion") around a batch of calls and always unloads the model in
`finally` through `model_memory.unload` (#666).

Errors carry a CODE only, never document text; the quotes are never logged.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager

from app import heavy_lock, model_memory, model_transport
from app.agent_claude import parse_json_object
from app.agent_trace import words
from app.config import settings

log = logging.getLogger(__name__)

DEFAULT_MODEL = "hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_XL"
LOCK_KIND = "agent_second_opinion"
TIMEOUT_S = 180.0
NUM_PREDICT = 200

SYSTEM = (
    "You are an independent senior engineer checking another reviewer's finding. Use only the two quotes given. "
    "If they do not clearly support the colour, answer false."
)


class AgentLocalError(RuntimeError):
    """The message is a code, never text from a document."""

    code = "agent_local_error"

    def __init__(self, code: str | None = None) -> None:
        self.code = code or self.code
        super().__init__(self.code)


def _answered_model(answer) -> str:
    name = answer.get("model") if isinstance(answer, dict) else None
    return name.strip() if isinstance(name, str) and name.strip() else "unknown"


def _result(agree, reason: str, model: str = "unknown") -> dict:
    return {"agree": agree, "reason": words(reason, 20), "usd": 0.0, "model": model}


class LocalSecondOpinion:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        url: str | None = None,
        timeout: float = TIMEOUT_S,
    ) -> None:
        self.model, self.url, self.timeout = model, url, float(timeout)

    def build_body(self, finding: dict, evidence: dict) -> dict:
        prompt = json.dumps(
            {
                "colour": (finding or {}).get("color"),
                "document_quote": (evidence or {}).get("doc_quote"),
                "clause_quote": (evidence or {}).get("clause_quote"),
                "question": "Do these two quotes alone support this colour? GREEN means the document meets the "
                "clause; RED means it does not. Reply with ONE JSON object: "
                '{"agree": true or false, "reason": "at most 20 words"}',
            },
            ensure_ascii=False,
        )
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "think": False,
            "format": "json",
            "options": {"temperature": 0, "num_predict": NUM_PREDICT},
        }

    def _url_matches(self) -> bool:
        if self.url is None:
            return True
        return str(self.url).rstrip("/") == str(settings.ollama_url).rstrip("/")

    def second_opinion(self, finding: dict, evidence: dict, **_kw) -> dict:
        if not self._url_matches():
            return _result(None, "url_mismatch")
        try:
            answer = model_transport.post_json_retrying(
                "/api/chat", self.build_body(finding, evidence), timeout=self.timeout
            )
        except Exception as exc:  # noqa: BLE001 - any failure is agree None; only the type name is kept
            log.warning("local second opinion failed (%s)", type(exc).__name__)
            return _result(None, "transport_error")
        model = _answered_model(answer)
        message = answer.get("message") if isinstance(answer, dict) else None
        text = message.get("content") if isinstance(message, dict) else None
        obj = parse_json_object(text if isinstance(text, str) else "") or {}
        agree = obj.get("agree")
        if not isinstance(agree, bool):
            return _result(None, "unparsable reply", model)
        return _result(agree, str(obj.get("reason") or ""), model)

    def unload(self) -> bool:
        """Ask Ollama to drop the model now (#666: `model_memory.unload`). False when it would not."""
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
                self.unload()
