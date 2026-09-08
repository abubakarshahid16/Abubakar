"""The one place in this codebase that may open a socket to the answer model.

WHY IT IS ITS OWN MODULE, and why it is a copy of `market_transport.py`'s
shape rather than a new idea. Four call sites used to format
`f"{settings.ollama_url}/api/..."` themselves and hand it to their own
`httpx.Client`: `answer._call_model`, `analysis.ollama_generate` and
`metrics` twice. Four places to audit, and a fifth arriving with the next
feature - a validator on the setting alone cannot stop a new call site
formatting the URL itself, and `settings` is a live object that can be
reassigned after startup. So the URL check moves to where the socket is: one
file, one function, and the check is the last thing that runs before the
request.

WHAT LEAVES THROUGH HERE IS DOCUMENT TEXT. That is the difference between
this module and the market transport, and the reason the rule is stricter:
the market lane may send only an approved phrase and its payload shape is
pinned by a test, while the body posted here is a prompt built from retrieved
passages, verbatim (`answer._build_prompt`, `synthesis.build_prompt`). There
is nothing to sanitise and no point pretending otherwise. The only control
that means anything is WHERE it goes, so that is the control: the host must be
loopback, checked by `config.check_model_url`.

TWO GATES, on the market lane's precedent:

  1. `Settings._refuse_a_non_local_answer_model` - at startup, so a machine
     with a wrong `OLLAMA_URL` does not boot. Bypassable by assigning
     `settings.ollama_url` afterwards, which is exactly why there is a second.
  2. `endpoint()` here - re-checks the CURRENT value immediately before every
     request. Not bypassable by anything short of editing this file, because
     it is the last thing between the value and the socket.
  3. The OS. Code-level checks are defence in depth and NOT the control. A
     firewall rule confining this process to loopback is what makes a
     deliberate exfiltration hard; this file is what makes an accident loud.

THIS MODULE MUST NOT BE ABLE TO REACH THE CORPUS - it imports no `db`,
`search`, `keyword`, `chunker`, `passages`, `claims` or `analysis`, and
tests/test_socket_containment.py checks that by parsing the source. The two
halves of a leak - reading document content and being able to send - stay in
different files. Its callers hand it a body they built; it never fetches one.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from .config import ModelHostRefused, check_model_url, settings

log = logging.getLogger(__name__)

#: Audit rows for requests sent to a deliberately permitted NON-loopback
#: model host, newest last, bounded. Built here and, as with
#: `market_providers.audit_record`, NOT PERSISTED BY THIS MODULE: writing to
#: `audit_events` needs `connect()` from `db`, and this is the module holding
#: the client - handing it a live database handle would put both halves of a
#: leak in one file. Persisting these belongs to `main.py`, which is not this
#: task's to edit, so the rows are also emitted at WARNING on every request.
#: Said plainly, because an audit trail nobody persists is not an audit trail.
remote_audit: list[dict] = []

#: Enough to show an operator what has been happening without becoming a
#: memory leak on a long-running process. Loopback requests add nothing here.
MAX_REMOTE_AUDIT_ROWS = 200


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z")


def _audit_remote(host: str, path: str) -> None:
    """Record one request to a permitted non-loopback model host.

    The HOST and the API path, never the URL and never the body: the body is
    document text and the URL could carry a credential. What this row exists
    to answer is "did document content go somewhere other than this machine,
    and where", and host plus path answers it.
    """
    row = {
        "at": _now_iso(),
        "action": "answer_model.remote_request",
        "resource_type": "answer_model_host",
        "resource_id": host,
        "detail": path,
        "outcome": "ok",
    }
    remote_audit.append(row)
    del remote_audit[:-MAX_REMOTE_AUDIT_ROWS]
    log.warning(
        "answer model request sent to non-loopback host %s (%s): document "
        "passages are leaving this machine by explicit configuration "
        "(answer_model_allow_remote_host)", host, path,
    )


def endpoint(path: str) -> str:
    """The validated absolute URL for an answer-model API path.

    GATE 2. Re-reads `settings.ollama_url` on every call rather than caching
    the value validated at startup, because caching would make this gate
    agree with the startup gate by construction and stop being a second
    check. Raises `ModelHostRefused` - never returns an unchecked URL, and
    never returns a fallback: there is no safe default destination for a
    prompt containing client documents.
    """
    if not path.startswith("/"):
        path = "/" + path
    base, remote_host = check_model_url(
        settings.ollama_url,
        allow_remote=settings.answer_model_allow_remote_host,
        allowed_hosts=settings.answer_model_allowed_hosts,
    )
    if remote_host is not None:
        _audit_remote(remote_host, path)
    return f"{base}{path}"


def post_json(path: str, body: dict, *, timeout: float) -> Any:
    """POST a JSON body to the answer model and return the decoded response.

    The one function that sends anything derived from a document. `body` is
    built by the caller and not inspected here - see the module docstring on
    why sanitising a prompt is not the control.
    """
    url = endpoint(path)
    with httpx.Client(
        timeout=timeout,
        # A 302 is a host no check ever saw; following one would move the
        # destination outside the check that just passed. Same reasoning as
        # market_transport, and it matters more here because the body is
        # document text.
        follow_redirects=False,
        # Ambient HTTP_PROXY/HTTPS_PROXY would route a "loopback" request
        # through somebody else's server. The check says the host is this
        # machine; trust_env=False is what keeps that true.
        trust_env=False,
    ) as client:
        response = client.post(url, json=body)
        response.raise_for_status()
        return response.json()


def get_json(path: str, *, timeout: float, required: bool = True) -> Any | None:
    """GET an answer-model API path.

    `required=True` raises on a non-2xx, which is what the `/api/tags` probe
    did before this module existed; `required=False` returns None instead,
    which is what the `/api/ps` probe did. Both behaviours preserved
    deliberately: `metrics` distinguishes "Ollama is not there" from "Ollama
    is there and no model is loaded", and collapsing them would change a
    dashboard field.

    Nothing derived from a document is sent by either probe, and both still
    go through the same gate: "this particular request carries no document
    content" is not a reason to skip the host check, it is how the second
    unchecked call site gets written.
    """
    url = endpoint(path)
    with httpx.Client(
        timeout=timeout, follow_redirects=False, trust_env=False,
    ) as client:
        response = client.get(url)
    if required:
        response.raise_for_status()
    elif response.status_code != 200:
        return None
    return response.json()


__all__ = [
    "ModelHostRefused", "endpoint", "get_json", "post_json", "remote_audit",
]
