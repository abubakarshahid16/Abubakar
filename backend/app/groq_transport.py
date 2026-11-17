"""The one place in this codebase that may open a socket to Groq (the second AI, owner decision 17 Nov 2026, #1584).

THE FIFTH OUTBOUND LANE. It carries the two quotes of ONE reviewer line (the paper's words and the clause's words, both
verified by code on their pages) and the colour, so an AI of another company can say whether the quotes support the colour
(`agent_review_crosscheck`). Nothing else: no page, no whole document, no file name, no title.

GATES, ALL REQUIRED, IN THIS ORDER, BEFORE A CLIENT IS BUILT (`send`):

  1. the switch `groq_crosscheck_enabled` (default False);
  2. a key in the settings (`groq_api_key`, loaded from `backend/.env` as GROQ_API_KEY), checked by presence only;
  3. the URL: https, host exactly `api.groq.com`, path exactly the chat completions path; anything else is refused;
  4. the documents the body carries, declared by the caller and checked by `groq_approved.refusal`: every one on BOTH the
     Claude approved list and the Groq list, none blocked, none a contract, not a Local-only run. Nothing declared = refused.

WHAT IS NOT SENT. No cookies, no redirects followed, no ambient proxy, a User-Agent naming the software only. The key
travels only in the Authorization header built here, inside this function, and is never stored, logged or raised.

WHAT COMES BACK. JSON only, at most `MAX_RESPONSE_BYTES`. A 4xx or 5xx is OUR fixed sentence for its status (never the
API's own words, which could echo the request or a key); a 4xx did no billable work (`unbilled`). Errors raised from here
are this module's own types and carry no request, response or header: no frame of a caller can print the key.

ONE LOG LINE PER CALL, at WARNING: model id, status and a digest of the body. Never the text.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Collection, Mapping
from urllib.parse import urlsplit

import httpx

from . import groq_approved
from .config import settings

log = logging.getLogger(__name__)

HOST = "api.groq.com"
PATH = "/openai/v1/chat/completions"
URL = f"https://{HOST}{PATH}"
USER_AGENT = "rag-intelligence/1.0 (cross-check; offline-first)"
#: Bytes. One JSON verdict of at most 20 words is a few KB (a reasoning model adds its own text); more is refused.
MAX_RESPONSE_BYTES = 256 * 1024
TIMEOUT_SECONDS = 60.0

#: OUR sentence per status; the API's message is never read. Anything not listed: the status alone.
_SAID = {
    400: "Groq refused the request as malformed.",
    401: "Groq refused the key.",
    403: "Groq refused the key for this request.",
    404: "Groq does not know this model or path.",
    413: "the request was too large for Groq.",
    422: "Groq refused the request as malformed.",
    429: "Groq is limiting the request rate; try again later.",
    500: "Groq had an internal error.",
    502: "Groq could not be reached through its gateway.",
    503: "Groq is unavailable or overloaded.",
}


class GroqRefused(RuntimeError):
    """A request this module will not make (`sent` False), or an answer it will not read (`sent` True: Groq may have billed
    it). The message is a fixed code of ours."""

    def __init__(self, code: str, *, sent: bool = False) -> None:
        super().__init__(code)
        self.code, self.sent = code, sent


class GroqRejected(RuntimeError):
    """Groq answered with an error status. Carries the status and OUR sentence, nothing from the request or the answer."""

    def __init__(self, status: int) -> None:
        self.status = int(status)
        said = _SAID.get(self.status, "")
        super().__init__(f"{self.status} from {HOST}" + (f": {said}" if said else ""))


class GroqUnreachable(RuntimeError):
    """The connection failed (`sent` False: never made) or broke after the request left (`sent` True: may be billed)."""

    def __init__(self, kind: str, *, sent: bool) -> None:
        super().__init__(f"transport_{kind}")
        self.sent = sent


def unbilled(exc: BaseException) -> bool:
    """True only when `exc` proves Groq did no billable work: refused here before sending, a connection never made, or a
    4xx rejection. Anything else (a 5xx, a timeout after sending, an answer refused for its size or shape) may be billed."""
    if isinstance(exc, (GroqRefused, GroqUnreachable)):
        return not exc.sent
    if isinstance(exc, GroqRejected):
        return 400 <= exc.status < 500
    return False


def _key() -> str:
    """The key, from the settings, at call time. Never stored on a module or returned to a caller outside this file."""
    return str(getattr(settings, "groq_api_key", "") or "").strip()


def available() -> bool:
    """Gates 1 and 2: the switch is on and a key is present (by presence only)."""
    return bool(settings.groq_crosscheck_enabled) and bool(_key())


def url_allowed(url: str) -> bool:
    """Gate 3: https, the host exactly `api.groq.com` (parsed, never split), no user info, port or query, the one path."""
    parts = urlsplit(str(url or ""))
    return (
        parts.scheme == "https"
        and (parts.hostname or "").lower() == HOST
        and parts.netloc.lower() == HOST
        and parts.path == PATH
        and not parts.query
        and not parts.fragment
    )


def digest(body: Mapping) -> str:
    """A fingerprint of what left, for the log line. Not the text."""
    blob = json.dumps(body, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def _gate(url: str, document_ids: Collection[str]) -> None:
    if not settings.groq_crosscheck_enabled:
        raise GroqRefused("switch_off")
    if not _key():
        raise GroqRefused("no_key")
    if not url_allowed(url):
        raise GroqRefused("host_refused")
    refused = groq_approved.refusal(document_ids)
    if refused is not None:
        raise GroqRefused(refused)


def _post(url: str, payload: bytes, timeout: float) -> tuple[int, bytes, str]:
    """(status, body bytes, content type). The httpx response (whose request holds the key) never leaves this frame."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": "Bearer " + _key(),
    }
    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,  # a 302 is a host no gate saw
            cookies=None,
            trust_env=False,  # no ambient HTTP_PROXY routing this elsewhere
        ) as client:
            response = client.post(url, headers=headers, content=payload)
            return (
                response.status_code,
                response.content,
                str(response.headers.get("content-type") or ""),
            )
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        failed = (type(exc).__name__, False)
    except httpx.HTTPError as exc:  # any other failure: the request may have left
        failed = (type(exc).__name__, True)
    finally:
        headers.clear()  # the key leaves this frame before anything is raised from it
    # raised OUTSIDE the except block: no context exception (whose request holds the key) is chained to it
    raise GroqUnreachable(failed[0], sent=failed[1])


def send(
    body: Mapping,
    *,
    document_ids: Collection[str],
    url: str = URL,
    timeout: float = TIMEOUT_SECONDS,
) -> dict:
    """POST one chat completion and return the decoded JSON answer. Every gate first; see the module docstring."""
    _gate(url, document_ids)
    if (
        not isinstance(body, Mapping)
        or not body.get("model")
        or not body.get("messages")
    ):
        raise GroqRefused("bad_body")
    payload = json.dumps(dict(body), ensure_ascii=False).encode("utf-8")
    status, content, content_type = _post(url, payload, timeout)
    log.warning(
        "groq cross-check: sent %d bytes to %s model=%s status=%d digest=%s",
        len(payload),
        HOST,
        body.get("model"),
        status,
        digest(body),
    )
    if status >= 400:
        raise GroqRejected(status)
    if len(content) > MAX_RESPONSE_BYTES:
        raise GroqRefused("answer_too_large", sent=True)
    if "json" not in content_type.lower():
        raise GroqRefused("answer_not_json", sent=True)
    try:
        decoded = json.loads(content)
    except ValueError:
        raise GroqRefused("answer_not_json", sent=True) from None
    if not isinstance(decoded, dict):
        raise GroqRefused("answer_not_json", sent=True)
    return decoded
