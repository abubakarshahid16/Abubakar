"""The test session's settings come from the code, never from the machine.

WHAT WAS WRONG. `conftest.py` had a session fixture called
`_the_suite_does_not_read_the_developers_env` whose docstring promised the
suite did not depend on `backend/.env`. It pinned ONE field, `auth_mode`.
Everything else in that file still reached the suite. On the owner's laptop
`backend/.env` holds `REASONING_PROVIDER=claude`, both `STANDARDS_READER_*`
egress flags and a real Anthropic key, so running the suite:

  - sent REAL, PAID requests to the Anthropic API (test_reports.py; one came
    back a real 400), with test fixture text in them;
  - read, and wrote, the REAL spend ledger and response cache under
    `backend/data/` (`claude_spend_log`, `claude_cache_dir` were never
    redirected), so test calls counted against the owner's USD 20 cap;
  - failed 83 tests that pass everywhere else.

The same name/claim mismatch the honesty audit keeps recording: a guard named
for the whole promise, implementing one line of it.

THE FIX IS NOT A LONGER LIST OF PINS. A list of pins is correct on the day it
is written and wrong the day somebody adds a setting. Instead, `isolate()`:

  1. stops the `Settings` class reading ANY env file (`env_file=None`), so a
     test that builds a fresh `Settings()` is also blind to `backend/.env`;
  2. removes from `os.environ` every variable that names a `Settings` field,
     plus the few the application reads from `os.environ` directly
     (`ANTHROPIC_API_KEY`, `STANDARDS_READER_*`, `RAG_LIVE_WRITER`);
  3. builds a fresh `Settings()` from that empty environment - which is the
     code's defaults - and copies EVERY field onto the live singleton.

`conftest.py` calls it at import time, before any test module imports the
application, so nothing is ever computed from the developer's values.

`EGRESS_SAFE` then states, field by field, what "safe" means for everything
that can open a socket, spend money, hold a secret, or read/write outside the
test's temp dirs, and `unsafe_fields()` checks the live settings against it.
`test_env_isolation.py` proves the list is COMPLETE (every field whose name
looks like a switch, key, host, URL, provider or path must be classified), so
a new egress flag added to config.py fails the suite until someone decides
what it is.

The network guard is defence in depth, not the control: the control is the
settings above. If a code path finds a way to a non-loopback address anyway,
the guard refuses the connection and the test that tried is failed by name.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from pathlib import Path

from app.config import BACKEND_DIR, Settings

#: Variables the application reads straight from `os.environ`, bypassing
#: `Settings` (reader_api._sources, reasoning_provider.claude_unavailable,
#: claude_budget.max_calls_per_run, live_guard). Prefixes end in "_".
DIRECT_ENV_NAMES = ("ANTHROPIC_API_KEY", "RAG_LIVE_WRITER")
DIRECT_ENV_PREFIXES = ("STANDARDS_READER_",)

class OneOf(tuple):
    """An EGRESS_SAFE entry with more than one safe value."""


#: The TestClient sends `Host: testserver`. Trusted in TEST configuration only
#: (here), never by a production default - see `config.trusted_host_names`.
TEST_ALLOWED_HOSTS = "testserver"

#: The only values these fields may hold when a test session starts. A test
#: that needs one of them on sets it itself, with a fake transport - that is
#: the established pattern (monkeypatch.setattr / setenv, undone per test).
EGRESS_SAFE: dict[str, object] = {
    # --- the Claude lane (reader_transport): money and document text leave
    "reasoning_provider": "ollama",
    "standards_reader_enabled": False,
    "standards_reader_allow_public_egress": False,
    "anthropic_api_key": "",
    "review_ai_check_enabled": False,
    "rule_parse_model_enabled": False,
    "geometry_reader_enabled": False,      # also gates the Claude vision reader
    "answer_judge_enabled": False,          # a model call per answer
    "applicability_reasoning_enabled": False,  # a model call per standard per review
    # --- the market lane (market_transport)
    "market_live_enabled": False,
    "market_allow_public_egress": False,
    "market_search_api_key": "",
    "market_search_provider": "",
    "market_search_endpoint": "",
    "market_openalex_contact_email": "",
    "market_allowed_hosts": ("api.openalex.org", "en.wikipedia.org"),
    "chat_web_enabled": False,
    "review_web_standards_enabled": False,
    "standard_lookup_enabled": False,
    # --- the model lane (model_transport): loopback Ollama only
    "ollama_url": "http://127.0.0.1:11434",
    "answer_model_allow_remote_host": False,
    "answer_model_allowed_hosts": (),
    "match_enabled": False,
    # #647: the review's AI applicability tier calls the local model once per
    # requirement - off, like the model matcher above.
    "ai_applicability_enabled": False,
    # --- notifications (SMTP)
    "smtp_enabled": False,
    "smtp_host": "",
    "smtp_username": "",
    "smtp_password": "",
    "smtp_from": "",
    "smtp_recipient": "",
    "smtp_port": 587,                       # inert while smtp_enabled is off
    "smtp_starttls": True,
    "smtp_timeout_seconds": 10.0,
    "summary_schedule": "disabled",
    # --- secrets and identity
    "auth_mode": "disabled",
    "auth_secret": "",
    "crs_company_name": "",
    # --- the process binds loopback only
    "host": "127.0.0.1",
    "allow_unauthenticated_network_bind": False,
    # Inbound, not egress, but it names hosts so it is classified here. The
    # code default is "" and `isolate()` sets the TestClient's name; both are
    # safe, and nothing else is.
    "allowed_hosts": OneOf(("", TEST_ALLOWED_HOSTS)),
    "api_docs_enabled": False,
    # --- reads outside the test's own dirs
    "watch_folder": "",
    "watch_owner_email": "",
    "applicability_taxonomy_path": None,
    # --- local only; listed so the completeness check has seen it
    "geometry_table_reader_enabled": True,
    # --- local only: reads an uploaded Word file with the standard library
    "docx_input_enabled": True,
}

#: Path fields the suite WRITES through. They must point inside a temp dir,
#: never at `backend/data` (the live DB, the real spend ledger, the real
#: Claude response cache). Model directories are read-only and stay put.
WRITE_PATHS = ("data_dir", "upload_dir", "db_path", "claude_spend_log", "claude_cache_dir")
READ_ONLY_PATHS = ("embed_model_dir", "ocr_model_dir")

#: Name shapes that mean "this field might open a socket, hold a secret or
#: touch a path". Every field matching one must appear in EGRESS_SAFE,
#: WRITE_PATHS or READ_ONLY_PATHS - see test_env_isolation.py.
RISKY_NAME_PARTS = (
    "enabled", "egress", "api_key", "secret", "password", "username",
    "provider", "endpoint", "url", "host", "email", "smtp", "schedule",
    "folder", "_dir", "_path", "_log", "auth_mode", "allow_remote",
)

LIVE_DATA_DIR = BACKEND_DIR / "data"


def _field_names() -> set[str]:
    return set(Settings.model_fields)


def scrub_environment(env=None) -> list[str]:
    """Remove every variable that could configure the app. Returns the NAMES
    removed (never values: one of them may be a key)."""
    env = os.environ if env is None else env
    fields = _field_names()
    removed = []
    for name in list(env):
        if (name.lower() in fields or name in DIRECT_ENV_NAMES
                or name.startswith(DIRECT_ENV_PREFIXES)):
            del env[name]
            removed.append(name)
    return sorted(removed)


def isolate(target: Settings, env=None) -> list[str]:
    """Make `target` hold the code's defaults and nothing from this machine.

    Idempotent. Returns the names of environment variables removed.
    """
    Settings.model_config["env_file"] = None
    removed = scrub_environment(env)
    clean = Settings()
    for name in Settings.model_fields:
        setattr(target, name, getattr(clean, name))
    target.allowed_hosts = TEST_ALLOWED_HOSTS
    return removed


def unsafe_fields(target: Settings) -> list[str]:
    """Fields of `target` not at their safe value. Names only, never values."""
    return sorted(n for n, safe in EGRESS_SAFE.items()
                  if (getattr(target, n) not in safe if isinstance(safe, OneOf)
                      else getattr(target, n) != safe))


def paths_outside(target: Settings, root: Path) -> list[str]:
    """WRITE_PATHS of `target` that do not lie under `root`."""
    root = Path(root).resolve()
    bad = []
    for name in WRITE_PATHS:
        p = Path(getattr(target, name)).resolve()
        if p != root and root not in p.parents:
            bad.append(name)
    return bad


# ------------------------------------------------------------ network guard


class EgressBlocked(ConnectionRefusedError):
    """A test tried to reach something other than this machine.

    An OSError, so the code under test sees exactly what an air-gapped
    machine would show it. It is ALSO recorded, because code that catches
    OSError and falls back quietly would otherwise hide the attempt - the
    autouse fixture in conftest fails the test by name.
    """


#: Attempts recorded since the last `take_attempts()`.
_attempts: list[str] = []
_installed = False


def _loopback_host(host) -> bool:
    if host is None or host == "":
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    host = str(host).strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def _ip_literal(host) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    try:
        ipaddress.ip_address(str(host).strip("[]").split("%")[0])
        return True
    except ValueError:
        return False


def _refuse(what: str):
    _attempts.append(what)
    raise EgressBlocked(f"test network guard: refused {what} (tests may reach loopback only)")


#: A proxy on loopback would carry a request anywhere while the socket this
#: guard sees goes only to 127.0.0.1 - measured: the sandbox that built this
#: guard exports HTTPS_PROXY=http://127.0.0.1:<port>, and corporate laptops
#: often run one too. httpx honours these (trust_env), so they are removed.
PROXY_ENV_NAMES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "WS_PROXY", "WSS_PROXY")


def install_network_guard(env=None) -> list[str]:
    """Refuse DNS lookups of real names and connections to non-loopback
    addresses for the rest of the process. AF_UNIX and loopback are allowed,
    so TestClient, socketpair and a local fake Ollama keep working.

    Also removes proxy variables (see PROXY_ENV_NAMES). Returns the names
    removed."""
    global _installed
    env = os.environ if env is None else env
    removed = sorted(n for n in list(env) if n.upper() in PROXY_ENV_NAMES)
    for name in removed:
        del env[name]
    if _installed:
        return removed
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def _check(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            host = address[0] if isinstance(address, tuple) else address
            if not _loopback_host(host):
                _refuse(f"connect to {host!r}")

    def connect(self, address):
        _check(self, address)
        return real_connect(self, address)

    def connect_ex(self, address):
        _check(self, address)
        return real_connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):
        if not (_loopback_host(host) or _ip_literal(host)):
            _refuse(f"DNS lookup of {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = getaddrinfo
    _installed = True
    return removed


def take_attempts() -> list[str]:
    """Blocked attempts since the last call, and reset."""
    out = list(_attempts)
    _attempts.clear()
    return out
