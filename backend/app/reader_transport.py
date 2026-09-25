"""The one place in this codebase that may open a socket to the standards reader.

THE THIRD OUTBOUND LANE, and the one that carries the most. The market lane
sends an approved phrase; the answer-model lane sends retrieved passages to a
loopback host. This lane sends ONE SENTENCE OF A CLIENT'S STANDARD to
`api.anthropic.com`, so that a model can propose what the sentence states and
`reader_api.accept` can try to throw the proposal away. Nothing about that
can be sanitised: the sentence IS the payload. The only controls that mean
anything are WHETHER it may leave and WHERE it goes, and both are here.

THE SHAPE IS `market_transport.py`'s, deliberately. One file, one function,
readable in full before deciding whether to trust it. `reader_api` builds the
request - destination, headers, body, timeout, and the two-flag check - and
hands it to a callable; this module is that callable. The split means the
module that can READ a standard (`standards`, via `db`) and the module that
can SEND are never the same file, and `tests/test_socket_containment.py`
parses the source to keep it that way.

THREE GATES BEFORE A BYTE LEAVES, redundant on purpose:

  1. `available()` - both flags, checked before a client is built. With them
     off, `transport()` returns None: no client, no connection pool, no code
     path that could construct one.
  2. The host, re-checked HERE against `ReaderSettings.allowed_hosts`
     immediately before the request. `reader_api.build_request` checked the
     URL it built; this checks the URL that is about to be requested, which
     is the last thing between the destination and the socket.
  3. The OS. A firewall rule confining this process is the real control;
     this file makes an accident loud.

WHAT IS NOT SENT. No cookies, no redirects followed (a 302 is a host the
allowlist never saw), no ambient proxy, a User-Agent naming the software and
nothing about the deployment. The API key travels only in the `x-api-key`
header that `reader_api` put there, and never appears in a log or an error
raised from here.

EVERY REQUEST IS LOGGED AT WARNING, because every request is client text
leaving the machine: host, model, status, token counts and a digest of what
was sent. Never the text. `usage` on the returned callable accumulates the
same counts, so a caller can say what one standard cost before anyone runs
the corpus through this.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping

import httpx

from .config import model_host_of
from .reader_api import ReaderRefused, ReaderSettings

log = logging.getLogger(__name__)

#: Names the software and nothing about who runs it or what corpus it holds.
USER_AGENT = "rag-intelligence/1.0 (standards reader; offline-first)"

#: Bytes. A Messages response for one sentence is a few KB; a megabyte is
#: something else and is refused rather than read.
MAX_RESPONSE_BYTES = 1 * 1024 * 1024


class TransportRefused(RuntimeError):
    """A request this module will not make. Distinct from an HTTP error: an
    HTTP error means the request happened and failed; this means it never
    happened."""


def available() -> bool:
    """Whether a transport can exist at all. Both flags, read the same way
    `reader_api.build_request` reads them - process environment first,
    `backend/.env` behind it - so the two never disagree."""
    cfg = ReaderSettings.from_env()
    return bool(cfg.enabled and cfg.allow_public_egress)


def _digest(body: Mapping) -> str:
    """A fingerprint of what left, for the audit line. Not the text."""
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:12]


def transport():
    """A callable `(url, headers=..., body=..., timeout=...) -> dict`, or None.

    None IS THE DEFAULT AND None IS SAFE: `reader_api.call_claude` is never
    handed a callable when the flags are off, so the off state is the absence
    of a transport rather than the presence of an unused one.

    The callable carries `.usage` - calls, input_tokens, output_tokens,
    bytes_sent - accumulated across every request it makes.
    """
    if not available():
        return None

    usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "bytes_sent": 0}

    def _send(url: str, *, headers: Mapping[str, str], body: Mapping, timeout: float) -> dict:
        if not available():
            # Somebody kept a reference across a settings change. Belt and
            # braces; `transport()` already refused to build this.
            raise TransportRefused(
                "standards reader egress is disabled; both "
                "STANDARDS_READER_ENABLED and STANDARDS_READER_ALLOW_PUBLIC_EGRESS "
                "must be true")

        # GATE 2. `build_request` checked the URL it built; this checks the
        # URL about to be requested, against the same one allowlist.
        allowed = ReaderSettings.from_env().allowed_hosts
        host = model_host_of(url)
        if not url.startswith("https://") or host not in allowed:
            raise ReaderRefused(
                f"reader transport refuses host {host!r}; allowed {allowed!r}")

        sent_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        sent_headers.update(dict(headers or {}))
        payload = json.dumps(dict(body), ensure_ascii=False).encode("utf-8")

        with httpx.Client(
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,   # a 302 is a host the allowlist never saw
            cookies=None,             # nothing about one request may shape the next
            trust_env=False,          # no ambient HTTP_PROXY routing this elsewhere
        ) as client:
            response = client.post(url, headers=sent_headers, content=payload)

        if response.status_code >= 400:
            # The status, the HOST, and the API's error TYPE. Never the URL,
            # never the headers - the key is in the headers and this string
            # reaches a log - and never the error MESSAGE, which is free text
            # the provider writes and could echo a request field. The type is
            # a fixed enum (`authentication_error`, `invalid_request_error`,
            # `rate_limit_error`...) and is what a reader of the log needs:
            # the first real call failed with a bare "400" that took a second
            # probe to read as "credit balance too low".
            kind = ""
            try:
                err = response.json().get("error", {})
                kind = str(err.get("type") or "") if isinstance(err, dict) else ""
            except ValueError:
                pass
            raise httpx.HTTPStatusError(
                f"{response.status_code} from {host}" + (f" ({kind})" if kind else ""),
                request=response.request, response=response)
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise TransportRefused(
                f"response from {host} is {len(response.content)} bytes, over "
                f"the {MAX_RESPONSE_BYTES} limit")

        decoded = response.json()
        counts = decoded.get("usage") if isinstance(decoded, dict) else None
        counts = counts if isinstance(counts, Mapping) else {}
        usage["calls"] += 1
        usage["input_tokens"] += int(counts.get("input_tokens") or 0)
        usage["output_tokens"] += int(counts.get("output_tokens") or 0)
        usage["bytes_sent"] += len(payload)
        log.warning(
            "standards reader: sent %d bytes to %s model=%s status=%d "
            "in=%s out=%s digest=%s",
            len(payload), host, body.get("model"), response.status_code,
            counts.get("input_tokens"), counts.get("output_tokens"), _digest(body))
        return decoded

    _send.usage = usage
    return _send


def list_models() -> list[str]:
    """The model ids this key may use (GET /v1/models), through the same gates
    as `transport()`: both flags, https, allowed host. Ids only - nothing else
    from the response is returned or logged."""
    from .reader_api import build_models_request  # the one request builder

    if not available():
        raise TransportRefused("standards reader egress is disabled")
    request = build_models_request()
    host = model_host_of(request["url"])
    if not request["url"].startswith("https://") or host not in ReaderSettings.from_env().allowed_hosts:
        raise ReaderRefused(f"reader transport refuses host {host!r}")
    sent_headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **request["headers"]}
    with httpx.Client(timeout=httpx.Timeout(request["timeout"]), follow_redirects=False,
                      cookies=None, trust_env=False) as client:
        response = client.get(request["url"], headers=sent_headers)
    if response.status_code >= 400:
        raise httpx.HTTPStatusError(f"{response.status_code} from {host}",
                                    request=response.request, response=response)
    log.warning("standards reader: listed models at %s status=%d", host, response.status_code)
    return [str(m.get("id")) for m in response.json().get("data", []) if isinstance(m, dict)]


# ------------------------------------------------------ Message Batches API
#
# The same lane, the same three gates, for many requests at once at half the
# price (owner order 2026-09-25: the one-time scope records of every held
# standard). Three calls - create, retrieve, results - each through `_gated`:
# both flags, https, allowed host, no redirects / cookies / proxy. The body of
# a create is the list of Messages bodies `reader_api.build_request` built;
# nothing here adds text. Logged: counts, bytes and a digest - never a prompt,
# never an answer, never the key.

#: Bytes. The results file of a few hundred scope records is a few MB.
MAX_BATCH_RESULTS_BYTES = 64 * 1024 * 1024
BATCHES_SUFFIX = "/batches"


def _gated(method: str, url: str, *, headers: Mapping[str, str], timeout: float,
           content: bytes | None = None, limit: int = MAX_RESPONSE_BYTES):
    """One request through the gates; returns the httpx response."""
    if not available():
        raise TransportRefused(
            "standards reader egress is disabled; both "
            "STANDARDS_READER_ENABLED and STANDARDS_READER_ALLOW_PUBLIC_EGRESS "
            "must be true")
    host = model_host_of(url)
    if not url.startswith("https://") or host not in ReaderSettings.from_env().allowed_hosts:
        raise ReaderRefused(f"reader transport refuses host {host!r}")
    sent = {"User-Agent": USER_AGENT, "Accept": "application/json", **dict(headers or {})}
    with httpx.Client(timeout=httpx.Timeout(timeout), follow_redirects=False,
                      cookies=None, trust_env=False) as client:
        response = (client.post(url, headers=sent, content=content) if method == "POST"
                    else client.get(url, headers=sent))
    if response.status_code >= 400:
        kind = ""
        try:
            err = response.json().get("error", {})
            kind = str(err.get("type") or "") if isinstance(err, dict) else ""
        except ValueError:
            pass
        raise httpx.HTTPStatusError(f"{response.status_code} from {host}" + (f" ({kind})" if kind else ""),
                                    request=response.request, response=response)
    if len(response.content) > limit:
        raise TransportRefused(f"response from {host} is {len(response.content)} bytes, over the {limit} limit")
    return response


def batch_create(messages_url: str, *, headers: Mapping[str, str], requests: list[dict],
                 timeout: float = 120.0) -> dict:
    """POST `{"requests": [{"custom_id", "params"}]}` to the Message Batches
    endpoint beside `messages_url` (the URL `reader_api.build_request` built).
    Returns the batch object (id, processing_status, ...)."""
    url = messages_url.rstrip("/") + BATCHES_SUFFIX
    body = {"requests": list(requests)}
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    response = _gated("POST", url, headers=headers, timeout=timeout, content=payload)
    decoded = response.json()
    log.warning("standards reader: batch create sent %d bytes (%d requests) to %s status=%d digest=%s",
                len(payload), len(body["requests"]), model_host_of(url), response.status_code, _digest(body))
    return decoded


def batch_retrieve(messages_url: str, batch_id: str, *, headers: Mapping[str, str],
                   timeout: float = 60.0) -> dict:
    """GET one batch's status object."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", batch_id or ""):
        raise TransportRefused("batch id is not a plain identifier")
    url = messages_url.rstrip("/") + BATCHES_SUFFIX + "/" + batch_id
    response = _gated("GET", url, headers=headers, timeout=timeout)
    decoded = response.json()
    counts = decoded.get("request_counts") if isinstance(decoded, dict) else None
    log.warning("standards reader: batch status %s at %s status=%d counts=%s",
                decoded.get("processing_status") if isinstance(decoded, dict) else None,
                model_host_of(url), response.status_code, json.dumps(counts, sort_keys=True))
    return decoded


def batch_results(results_url: str, *, headers: Mapping[str, str], timeout: float = 300.0) -> list[dict]:
    """GET the JSONL results file of an ended batch. `results_url` comes from
    the API's own answer, so it is held to the same https + allowed-host gate
    as every other URL here."""
    response = _gated("GET", results_url, headers=headers, timeout=timeout, limit=MAX_BATCH_RESULTS_BYTES)
    rows = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    kinds: dict[str, int] = {}
    tokens_in = tokens_out = 0
    for row in rows:
        result = row.get("result") or {}
        kinds[str(result.get("type"))] = kinds.get(str(result.get("type")), 0) + 1
        usage = (result.get("message") or {}).get("usage") or {}
        tokens_in += int(usage.get("input_tokens") or 0)
        tokens_out += int(usage.get("output_tokens") or 0)
    log.warning("standards reader: batch results %d rows from %s status=%d types=%s in=%d out=%d",
                len(rows), model_host_of(results_url), response.status_code, json.dumps(kinds, sort_keys=True),
                tokens_in, tokens_out)
    return rows
