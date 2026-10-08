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
import threading
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


#: The Ollama paths that run - and therefore LOAD - the answer model.
RUNNER_PATHS = frozenset({"/api/generate", "/api/chat"})


def runner_options(num_ctx: int | None = None) -> dict[str, object]:
    """The options that decide WHICH RUNNER Ollama keeps loaded. One home.

    Ollama restarts the model runner whenever `num_ctx`, `num_batch` or
    `num_thread` differ from the loaded one, and each restart is a cold load
    (23.6 s on the laptop, docs/benchmarks.md). The call sites disagreed -
    comparison sent no `num_batch`, `OllamaProvider` sent neither thread nor
    batch, answerability asked for 4096 and field naming 16384 - so the
    features took turns evicting each other's runner (perf audit item 7).

    `num_ctx` is RAISED to `settings.num_ctx`, never lowered. A larger window
    changes nothing for a prompt that fits the smaller one - the output is the
    same - and it means every caller that needs no more than the default
    shares one runner. A caller that genuinely needs more (field naming at
    16384, vision at 32768) still gets it, and still pays a reload: that is a
    real trade, stated here rather than hidden by truncating its prompt.
    """
    return {
        "num_ctx": max(int(num_ctx or 0), int(settings.num_ctx)),
        "num_thread": settings.num_thread,
        "num_batch": settings.num_batch,
    }


def with_runner_options(body: dict) -> dict:
    """`body` with the shared runner options and `keep_alive`. A new dict.

    Applied by `post_json` and `stream_json` to every runner path, so no call
    site - present or future - can send different ones. Only these four keys
    are touched; the prompt is not inspected (see the module docstring).
    """
    options = dict(body.get("options") or {})
    options.update(runner_options(options.get("num_ctx")))
    return {**body, "options": options, "keep_alive": settings.ollama_keep_alive}


def _normalised(path: str, body: dict) -> dict:
    return with_runner_options(body) if _path_of(path) in RUNNER_PATHS else body


def _path_of(path: str) -> str:
    return path if path.startswith("/") else "/" + path


def post_json(path: str, body: dict, *, timeout: float) -> Any:
    """POST a JSON body to the answer model and return the decoded response.

    The one function that sends anything derived from a document. `body` is
    built by the caller and not inspected here - see the module docstring on
    why sanitising a prompt is not the control. Its runner OPTIONS are made
    uniform (`with_runner_options`), which is not an inspection of content.
    """
    url = endpoint(path)
    body = _normalised(path, body)
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


class _Abort:
    """Stop a request in flight - including one still waiting for its first byte.

    STOP MUST STOP WITHIN SECONDS, EVEN BEFORE THE FIRST TOKEN. A local model
    can spend tens of seconds evaluating the prompt before it sends a byte, a
    check between chunks never runs in that time, and closing the client from
    another thread does NOT interrupt a read that is already blocked (measured:
    the call ran on). What does is shutting the socket itself down, so the
    connection is captured as it opens (httpx's documented `trace` extension)
    and a watcher shuts it down when `cancel` is set. The engine sees the
    connection drop and stops.
    """

    def __init__(self, client: httpx.Client, cancel) -> None:
        import threading as _threading

        self.client, self.cancel = client, cancel
        self.stream = None
        self.finished = _threading.Event()
        if cancel is not None:
            _threading.Thread(target=self._watch, daemon=True).start()

    def trace(self, name: str, info: dict) -> None:
        if name == "connection.connect_tcp.complete":
            self.stream = info.get("return_value")

    def _watch(self) -> None:
        import socket as _socket

        while not self.finished.is_set():
            if self.cancel.wait(0.1):
                sock = self.stream.get_extra_info("socket") if self.stream is not None else None
                if sock is not None:
                    try:
                        sock.shutdown(_socket.SHUT_RDWR)
                    except OSError:
                        pass
                self.client.close()
                return


def stream_json(path: str, body: dict, *, timeout: float, cancel=None):
    """POST with `stream: true` and yield each decoded NDJSON line.

    The same gates as `post_json` - `endpoint()` re-validates the host - and
    the same client settings. `cancel` (a threading.Event) closes the
    connection mid-stream; the generator then simply ends.
    """
    import json as _json

    url = endpoint(path)
    body = _normalised(path, body)
    client = httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False)
    abort = _Abort(client, cancel)
    try:
        with client.stream("POST", url, json={**body, "stream": True},
                           extensions={"trace": abort.trace}) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if cancel is not None and cancel.is_set():
                    return
                if line.strip():
                    yield _json.loads(line)
    except (httpx.TransportError, RuntimeError):
        if cancel is not None and cancel.is_set():
            return        # the abort above, not a failure
        raise
    finally:
        abort.finished.set()
        client.close()


_client_lock = threading.Lock()
_client: httpx.Client | None = None


def _shared_client() -> httpx.Client:
    """The one `httpx.Client` the GET probes share (thread-safe by httpx)."""
    global _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(follow_redirects=False, trust_env=False)
        return _client


def close_shared_client() -> None:
    """Close and forget the shared client (shutdown, and tests)."""
    global _client
    with _client_lock:
        if _client is not None:
            _client.close()
            _client = None


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
    # ONE CLIENT FOR THE PROCESS (#626). Building an `httpx.Client` builds an
    # SSL context, and `/api/metrics` did that on every call (about 0.5 s of
    # CPU in 30 s of an idle app) for a plain-HTTP call to the local host. The
    # per-call timeout and the host check above are unchanged.
    response = _shared_client().get(url, timeout=timeout)
    if required:
        response.raise_for_status()
    elif response.status_code != 200:
        return None
    return response.json()


__all__ = [
    "ModelHostRefused", "close_shared_client", "endpoint", "get_json", "post_json", "remote_audit",
]
