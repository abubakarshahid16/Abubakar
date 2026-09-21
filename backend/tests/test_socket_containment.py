"""The answer model's socket, and every other socket in `backend/app`.

WHAT WAS WRONG. README:14 and ADR-0002 say client document content never
leaves this machine. The answer path POSTed a prompt built from retrieved
passages to `settings.ollama_url` - an ordinary `.env` string with a loopback
DEFAULT and no validation - from four separate call sites that each formatted
the URL themselves. No allowlist, no loopback check, no flag, no audit row.
The one socket-containment test in this suite
(`test_market_no_document_leak.py`) iterates a hand-written tuple of three
market filenames plus the transport, so it could not see the largest outbound
lane in the system. The promise had no enforcement point; this file is the
enforcement point's test, and the containment half is deliberately written
over the WHOLE package rather than a list of names, so the next module that
opens a socket turns it red without anybody remembering to add it.

Three groups:

  1. `check_model_url` - the parse and the refusals, including the shape that
     defeats the hand-rolled parser in `market_providers._host_of`.
  2. The three callers - refused even when `settings.ollama_url` is
     reassigned AFTER startup, which is what proves the gate is at the socket
     and not only at config load.
  3. The package-wide AST guard - who may hold a client, and who may format a
     model URL.

Everything here runs air-gapped: no test in this file makes a request, and
the ones that could are given an `httpx.Client` that raises if constructed,
so "refused" means the socket was never opened rather than opened and failed.
"""

from __future__ import annotations

import ast
from pathlib import Path

import httpx
import pytest

from app import analysis, answer, metrics, model_transport
from app.config import ModelHostRefused, Settings, check_model_url, model_host_of, settings

APP = Path(model_transport.__file__).resolve().parent


@pytest.fixture
def no_socket(monkeypatch):
    """An `httpx.Client` that cannot be constructed.

    A refusal test that merely asserts the exception could be satisfied by
    code that opened the socket, sent the prompt and then raised. This makes
    construction itself the failure, so the assertions below mean "no bytes
    left" and not "an error came back".
    """
    def explode(*a, **k):  # pragma: no cover - the point is that it is not hit
        raise AssertionError(
            "an httpx.Client was constructed for a refused model host - the "
            "check ran too late to prevent the request"
        )
    monkeypatch.setattr(httpx, "Client", explode)


# --------------------------------------------------- 1. the URL check itself


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:11434",
    "http://localhost:11434",
    "http://[::1]:11434",
    "http://127.0.0.1:11434/",     # a bare trailing slash is not a path
    "https://127.0.0.1:11434",
])
def test_a_loopback_model_url_is_accepted(url):
    """THE DEFAULT CONFIGURATION MUST BE UNCHANGED. `127.0.0.1` and
    `localhost` are the two values any real deployment uses, and a guard that
    inconvenienced them would be removed by the first operator who hit it."""
    base, remote = check_model_url(url)
    assert remote is None
    assert base.startswith(("http://", "https://"))


def test_the_default_setting_is_loopback_and_needs_no_flags():
    """Stated as an assertion because it is the compatibility promise: the
    shipped default passes with both new settings at their defaults."""
    fresh = Settings()
    assert fresh.answer_model_allow_remote_host is False
    assert fresh.answer_model_allowed_hosts == ()
    assert check_model_url(
        fresh.ollama_url,
        allow_remote=fresh.answer_model_allow_remote_host,
        allowed_hosts=fresh.answer_model_allowed_hosts,
    ) == ("http://127.0.0.1:11434", None)


def test_a_non_loopback_model_url_is_refused_by_default():
    """The finding, as one assertion. Matched on the specific words, not on
    `Exception`: a test that accepts any error passes when the refusal is
    replaced by a typo."""
    with pytest.raises(ModelHostRefused, match="not loopback") as caught:
        check_model_url("http://collector.example.net:11434")
    message = str(caught.value)
    assert "collector.example.net" in message      # names the offending host
    assert "ADR-0002" in message                   # and why it is refused


def test_the_refusal_names_the_host_and_never_the_whole_url():
    """A URL can carry a credential in a query string or a userinfo section
    and these strings reach logs. Same rule as `market_transport._fetch`."""
    url = "http://someone:hunter2@collector.example.net:11434"
    with pytest.raises(ModelHostRefused) as caught:
        check_model_url(url)
    message = str(caught.value)
    assert "hunter2" not in message
    assert url not in message
    assert "collector.example.net" in message


@pytest.mark.parametrize("url", [
    "http://user:pass@127.0.0.1:11434",
    "http://user@127.0.0.1:11434",
    "http://user:pass@collector.example.net:11434",
])
def test_embedded_credentials_are_refused_even_on_loopback(url):
    """Refused, not stripped. A value shaped like this is either an accident
    or an undocumented proxy, and a prompt built from client documents is not
    something to send through either on a silent guess."""
    with pytest.raises(ModelHostRefused, match="credentials"):
        check_model_url(url)


@pytest.mark.parametrize("url", [
    # THE MARKET BUG'S SHAPE. `market_providers._host_of` splits on "://",
    # "/", "@" and ":" and reads everything after the LAST "@", so it reports
    # `127.0.0.1` for this URL while httpx connects to `evil.test` - the "?"
    # starts the query, which puts the "@" inside it.
    "http://evil.test?@127.0.0.1:11434/",
    "https://evil.test?@127.0.0.1:11434/",
    "http://evil.test#@127.0.0.1:11434/",
    "http://evil.test:11434?@localhost",
])
def test_a_url_that_lies_to_a_string_splitting_parser_is_refused(url):
    """The bypass this check must not reproduce. Two independent reasons it
    fails - the parsed host is not loopback, and a base URL may not carry a
    query or fragment - so it stays refused even if one of them is edited."""
    assert model_host_of(url) == "evil.test", (
        "the parser under test agreed with the hand-rolled splitter, which "
        "is the bug"
    )
    with pytest.raises(ModelHostRefused):
        check_model_url(url)
    # And with the override fully open for the host the splitter would have
    # reported, it is STILL refused: the allowlist is consulted with the real
    # host, so `?@` cannot borrow a permitted name.
    with pytest.raises(ModelHostRefused):
        check_model_url(url, allow_remote=True,
                        allowed_hosts=("127.0.0.1", "localhost"))


@pytest.mark.parametrize("url,fragment", [
    ("", "scheme"),
    ("http://", "no host"),
    ("127.0.0.1:11434", "scheme"),            # no scheme: not a URL
    ("ftp://127.0.0.1:11434", "scheme"),
    ("file:///etc/passwd", "scheme"),
    ("http://127.0.0.1:11434/api/generate", "path"),
])
def test_a_value_that_is_not_a_base_url_is_refused(url, fragment):
    with pytest.raises(ModelHostRefused, match=fragment):
        check_model_url(url)


def test_a_name_that_merely_starts_like_loopback_is_not_loopback():
    """`127.0.0.1.evil.test` and `localhost.evil.test` resolve to whatever
    their owner wants. A prefix or suffix test would have passed both."""
    for host in ("127.0.0.1.evil.test", "localhost.evil.test",
                 "notlocalhost", "127.0.0.2.nip.io"):
        with pytest.raises(ModelHostRefused, match="not loopback"):
            check_model_url(f"http://{host}:11434")


def test_remote_inference_needs_both_the_flag_and_the_host():
    """THE TWO-SETTING PRECEDENT, asserted rather than described. Either one
    alone still refuses, so opening this lane cannot be one careless edit."""
    url = "http://gpu-box.internal:11434"
    with pytest.raises(ModelHostRefused, match="not loopback"):
        check_model_url(url, allowed_hosts=("gpu-box.internal",))
    with pytest.raises(ModelHostRefused, match="answer_model_allowed_hosts"):
        check_model_url(url, allow_remote=True)
    base, remote = check_model_url(
        url, allow_remote=True, allowed_hosts=("gpu-box.internal",))
    assert (base, remote) == ("http://gpu-box.internal:11434",
                              "gpu-box.internal")


def test_a_permitted_remote_host_is_audited_and_loopback_is_not(monkeypatch):
    """An override with no record would be an override nobody could find
    afterwards. The row names the host and the API path - never the body,
    which is document text."""
    monkeypatch.setattr(settings, "answer_model_allow_remote_host", True)
    monkeypatch.setattr(
        settings, "answer_model_allowed_hosts", ("gpu-box.internal",))
    monkeypatch.setattr(settings, "ollama_url", "http://gpu-box.internal:11434")
    monkeypatch.setattr(model_transport, "remote_audit", [])

    assert model_transport.endpoint("/api/generate") == (
        "http://gpu-box.internal:11434/api/generate")
    assert len(model_transport.remote_audit) == 1
    row = model_transport.remote_audit[0]
    assert row["action"] == "answer_model.remote_request"
    assert row["resource_id"] == "gpu-box.internal"
    assert row["detail"] == "/api/generate"
    assert set(row) == {"at", "action", "resource_type", "resource_id",
                        "detail", "outcome"}

    # The normal case writes NOTHING: an audit trail that records every
    # loopback request is one nobody reads.
    monkeypatch.setattr(settings, "ollama_url", "http://127.0.0.1:11434")
    model_transport.endpoint("/api/generate")
    assert len(model_transport.remote_audit) == 1


def test_the_process_refuses_to_start_on_a_misconfigured_model_host(monkeypatch):
    """GATE 1. A bad `OLLAMA_URL` stops the backend rather than logging
    something nobody reads and posting the passages anyway - audit entry 24,
    the hook that warned and exited 0."""
    monkeypatch.setenv("OLLAMA_URL", "http://collector.example.net:11434")
    with pytest.raises(Exception) as caught:
        Settings()
    assert "collector.example.net" in str(caught.value)


def test_startup_accepts_a_loopback_environment_value(monkeypatch):
    """The guard on the guard above: proves `Settings()` under this fixture
    can succeed, so the refusal test is not passing because the constructor
    raises for some unrelated reason."""
    monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434")
    assert Settings().ollama_url == "http://localhost:11434"


# ------------------------------- 2. the callers, AFTER startup has passed


@pytest.mark.parametrize("call", [
    pytest.param(lambda: answer._call_model("what is the coating thickness"),
                 id="answer._call_model"),
    pytest.param(lambda: analysis.ollama_generate("system", "passages"),
                 id="analysis.ollama_generate"),
    pytest.param(lambda: metrics.models(), id="metrics.models"),
])
def test_no_caller_can_reach_a_non_loopback_host_after_startup(
        call, monkeypatch, no_socket):
    """THE ONE THAT PROVES WHERE THE GATE IS.

    `settings` is a live object and pydantic does not revalidate on
    assignment, so the startup validator can be walked past in one line -
    which is what a plugin, a test helper or a `settings.ollama_url = ...` in
    a future feature would do. Each caller is exercised with the setting
    reassigned after import, and each must refuse. `no_socket` makes
    constructing a client an error, so this asserts the prompt never left.
    """
    monkeypatch.setattr(settings, "ollama_url", "http://collector.example.net:11434")
    with pytest.raises(ModelHostRefused, match="collector.example.net"):
        call()


def test_the_analysis_wrapper_does_not_downgrade_a_refusal(monkeypatch, no_socket):
    """`_generate_or_refuse` turns an httpx error into `ModelUnavailable`, a
    polite "the model is not there" the UI renders as a status. A refused host
    must NOT arrive that way: it is a misconfigured privacy boundary, not a
    stopped service."""
    monkeypatch.setattr(settings, "ollama_url", "http://collector.example.net:11434")
    with pytest.raises(ModelHostRefused):
        analysis._generate_or_refuse(analysis.ollama_generate, "s", "p")


def test_the_answer_route_does_not_downgrade_a_refusal(monkeypatch):
    """The same at the level above: `answer`'s generation step catches
    `Exception` broadly to report `model_unavailable`, and a refusal has an
    explicit clause in front of that handler."""
    monkeypatch.setattr(settings, "ollama_url", "http://collector.example.net:11434")

    def refuse(_prompt, timeout=180.0):
        raise ModelHostRefused("answer model host 'collector.example.net' is not loopback")

    monkeypatch.setattr(answer, "_call_model", refuse)
    source = ast.parse(Path(answer.__file__).read_text(encoding="utf-8"))
    handlers = [
        h.type.attr if isinstance(h.type, ast.Attribute) else None
        for node in ast.walk(source) if isinstance(node, ast.Try)
        for h in node.handlers
        if any(isinstance(n, ast.Name) and n.id == "_call_model"
               for n in ast.walk(node.body[0]) if isinstance(n, ast.Name))
    ]
    assert "ModelHostRefused" in handlers, (
        "the generation step must re-raise ModelHostRefused explicitly; "
        "without that clause its broad `except Exception` reports a "
        "misconfigured privacy boundary as `model_unavailable`"
    )


def test_a_loopback_caller_still_posts_exactly_what_it_used_to(monkeypatch):
    """NO BEHAVIOUR CHANGE FOR THE DEFAULT CONFIGURATION. The URL, the method
    and the body must be what the four old call sites sent, so a working
    Ollama keeps working."""
    seen: dict = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "text", "done_reason": "stop"}

    class FakeClient:
        def __init__(self, **kwargs):
            seen["client_kwargs"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None):
            seen["url"] = url
            seen["body"] = json
            return FakeResponse()

    monkeypatch.setattr(settings, "ollama_url", "http://127.0.0.1:11434")
    monkeypatch.setattr(httpx, "Client", FakeClient)
    answer._call_model("what is the coating thickness")

    assert seen["url"] == "http://127.0.0.1:11434/api/generate"
    assert seen["body"]["model"] == settings.answer_model
    assert seen["body"]["prompt"] == "what is the coating thickness"
    assert seen["body"]["stream"] is False
    assert seen["body"]["keep_alive"] == "30m"
    # A 302 is a host no check saw, and ambient proxy variables would route a
    # "loopback" request through somebody else's server.
    assert seen["client_kwargs"]["follow_redirects"] is False
    assert seen["client_kwargs"]["trust_env"] is False


# ------------------------------------- 3. the package-wide structural guard


#: THE FILES THAT MAY OPEN A SOCKET. Two, each with its reason, and each
#: forbidden the other half of a leak: neither may import `db`, `search`,
#: `keyword`, `chunker`, `passages`, `claims` or `analysis`.
SOCKET_ALLOWLIST = {
    # The public-information lane. Sends an approved phrase and nothing from
    # the corpus; host-checked against `market_allowed_hosts`, and inert
    # unless both egress flags are true.
    "market_transport.py",
    # The answer model. Sends prompts containing retrieved passages, and is
    # therefore restricted to a loopback host by `config.check_model_url`,
    # re-checked immediately before every request.
    "model_transport.py",
    # The standards reader. Sends ONE SENTENCE of a client's standard to
    # api.anthropic.com so a model can propose what it states; the proposal
    # is then verified by `reader_api.accept` without the model. Inert unless
    # BOTH STANDARDS_READER_* egress flags are true; host re-checked against
    # `ReaderSettings.allowed_hosts` immediately before every request; every
    # request logged at WARNING with counts and a digest, never the text.
    "reader_transport.py",
}

#: Modules that may NAME the model URL setting. Exactly one, so a new call
#: site cannot format its own URL and step around the check.
MODEL_URL_ALLOWLIST = {"config.py", "model_transport.py"}

#: The import roots that can put bytes on a wire.
NETWORK_ROOTS = frozenset({
    "httpx", "requests", "urllib", "urllib3", "aiohttp", "socket", "ftplib",
    "telnetlib", "websockets", "http",
})

#: Attributes of those roots that do NOT open anything: exception classes and
#: value types. Deliberately tiny and enumerated, so the scanner's default
#: answer for anything new is "this opens a socket" - it fails closed.
NON_OPENING = frozenset({
    "httpx.HTTPError", "httpx.HTTPStatusError", "httpx.ConnectError",
    "httpx.TimeoutException", "httpx.ReadTimeout", "httpx.RequestError",
    "httpx.Timeout", "httpx.Request", "httpx.Response", "httpx.Limits",
    "httpx.URL",
})


def _dotted(node: ast.AST) -> str | None:
    """`httpx.Client` for the AST of `httpx.Client`. None if not a dotted name."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def socket_calls(source: str) -> set[str]:
    """Every call in `source` that could open a socket, from the AST.

    Parsed rather than grepped so a commented-out line does not count and a
    real one cannot hide behind formatting. Any call on a network root counts
    unless it is in the enumerated `NON_OPENING` set: an unknown attribute is
    treated as opening, because a scanner that guessed the other way would go
    quiet the first time somebody used an API it had not heard of.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = _dotted(node.func)
        if name and name.split(".")[0] in NETWORK_ROOTS and name not in NON_OPENING:
            found.add(name)
        # `from urllib.request import urlopen; urlopen(...)` has no dotted
        # root to inspect, so the bare names are matched too.
        if isinstance(node.func, ast.Name) and node.func.id in (
                "urlopen", "urlretrieve", "create_connection", "socket"):
            found.add(node.func.id)
    return found


def app_modules() -> list[Path]:
    """Every module in the package, found by globbing.

    NOT A HAND-WRITTEN TUPLE. `test_market_no_document_leak.py` lists three
    filenames, which is why it could not see the answer path: a list of names
    only covers the modules somebody remembered. This walks the package, so a
    file added tomorrow is covered on the day it lands.
    """
    return sorted(p for p in APP.rglob("*.py") if p.name != "__init__.py")


def test_the_module_scan_finds_the_package():
    """A guard on the guard: a glob that matched nothing would make every
    assertion below pass vacuously - audit entry 10's failure mode."""
    modules = app_modules()
    names = {p.name for p in modules}
    assert len(modules) > 30, f"only found {len(modules)} modules in {APP}"
    assert {"answer.py", "analysis.py", "metrics.py", "config.py"} <= names
    assert SOCKET_ALLOWLIST <= names, "an allowlisted transport no longer exists"


def test_only_the_allowlisted_transports_open_a_socket():
    """THE WHOLE PACKAGE, not a list of market filenames. Any module that
    constructs an HTTP client or makes a request must be in
    `SOCKET_ALLOWLIST` with a comment saying why."""
    offenders = {}
    for path in app_modules():
        calls = socket_calls(path.read_text(encoding="utf-8"))
        if calls and path.name not in SOCKET_ALLOWLIST:
            offenders[str(path.relative_to(APP))] = sorted(calls)
    assert not offenders, (
        f"module(s) outside the socket allowlist open a socket: {offenders}.\n"
        f"Every outbound lane in this system is reviewed, host-checked and "
        f"audited in one file per lane - market_transport.py for public "
        f"information, model_transport.py for the answer model. If a new lane "
        f"is genuinely needed, it goes in its own module, gets its own host "
        f"check, and is added to SOCKET_ALLOWLIST with the reason. Formatting "
        f"a URL and calling httpx here is the defect this test exists for."
    )


def test_the_scanner_would_actually_catch_a_new_socket_call():
    """Proves `socket_calls` finds what it claims to, on the exact shapes the
    defect took: a formatted URL and a client, a module-level helper, and an
    import that hides the root name."""
    assert socket_calls(
        "import httpx\n"
        "def go(u):\n"
        "    with httpx.Client(timeout=1) as c:\n"
        "        return c.post(f'{u}/api/generate', json={}).json()\n"
    ) == {"httpx.Client"}
    assert socket_calls("import requests\nrequests.post('http://h', json={})\n")
    assert socket_calls(
        "from urllib.request import urlopen\nurlopen('http://h')\n")
    assert socket_calls("import socket\ns = socket.socket()\n")
    # and the two shapes that must NOT count, or every module catching an
    # httpx error would be reported as opening a socket
    assert not socket_calls(
        "import httpx\ntry:\n    pass\nexcept httpx.HTTPError:\n    pass\n")
    assert not socket_calls("import httpx\nt = httpx.Timeout(1.0)\n")


def test_the_two_transports_are_really_scanned_and_really_do_open_sockets():
    """The allowlist is not a list of files that happen to be quiet. Both
    named modules must actually contain the calls they are excused for, so a
    transport that stopped opening sockets - or was renamed - is noticed."""
    for name in sorted(SOCKET_ALLOWLIST):
        calls = socket_calls((APP / name).read_text(encoding="utf-8"))
        assert calls, f"{name} is allowlisted to open a socket and opens none"


def test_only_the_model_transport_names_the_model_url():
    """A VALIDATOR ON THE SETTING CANNOT STOP A NEW CALL SITE. The check lives
    at the socket, and this keeps it there: `settings.ollama_url` is read in
    exactly one place, so nothing else can format a URL from it and post."""
    offenders = []
    for path in app_modules():
        if path.name in MODEL_URL_ALLOWLIST:
            continue
        if "ollama_url" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(APP)))
    assert not offenders, (
        f"{offenders} name settings.ollama_url. Build the URL with "
        f"model_transport.endpoint() instead: a URL formatted elsewhere is a "
        f"request that skipped the loopback check."
    )


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.update(node.module.split("."))
            for alias in node.names:
                found.add(alias.name.split(".")[0])
    return found


def test_the_reader_transport_cannot_reach_the_corpus():
    """The lane that carries a client's clause text to a public host, held to
    the same split: `standards` reads the sentence and hands it over; this
    module can send it and cannot fetch one of its own."""
    forbidden = {"db", "search", "keyword", "chunker", "passages", "claims",
                 "analysis", "answer", "synthesis", "reports", "standards"}
    leaked = forbidden & _imports(APP / "reader_transport.py")
    assert not leaked, (
        f"reader_transport.py imports {sorted(leaked)}, which can reach the "
        f"corpus. It holds the client for the lane that carries standard text "
        f"off the machine; giving it corpus access puts both halves of a leak "
        f"in one file."
    )


def test_the_model_transport_cannot_reach_the_corpus():
    """The other half of the split, held to the same rule as
    `market_transport`: the module that can SEND must not be able to READ. It
    is handed a body its caller built."""
    forbidden = {"db", "search", "keyword", "chunker", "passages", "claims",
                 "analysis", "answer", "synthesis", "reports"}
    leaked = forbidden & _imports(APP / "model_transport.py")
    assert not leaked, (
        f"model_transport.py imports {sorted(leaked)}, which can reach the "
        f"corpus. This module holds the client for the lane that carries "
        f"document text; giving it corpus access of its own puts both halves "
        f"of a leak in one file."
    )
