"""The suite never runs on the developer's egress switches, keys or paths.

WHAT WAS WRONG (honesty audit entry 77). conftest's
`_the_suite_does_not_read_the_developers_env` pinned `auth_mode` only. On the
owner's laptop `backend/.env` turned the Claude lane on with a real key, and
the suite made real, paid Anthropic calls, used the real spend ledger and
cache under `backend/data/`, and failed 83 tests nobody else could reproduce.

These tests build that laptop - a hostile `.env` and hostile environment
variables with every egress switch on and a fake key - check the hostile
values really are honoured (so the rest is not vacuous), then check that the
isolation conftest uses turns every lane off. One test runs the real conftest
import in a fresh interpreter, which is the only way to prove conftest calls
it: in this process it has already run.

Nothing here opens a non-loopback socket; the guard tests aim at TEST-NET
addresses and names that the guard refuses before any packet exists.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from app import market_transport, notifications, reader_transport, reasoning_provider
from app.config import BACKEND_DIR, NotificationConfigError, Settings, check_model_url, settings
from tests import env_isolation

FAKE_KEY = "sk-ant-test-not-a-real-key-000"

#: Every egress switch on, a fake key, remote Ollama allowed, the spend ledger
#: pointed somewhere else. What the owner's `.env` looks like, and worse.
HOSTILE = {
    "REASONING_PROVIDER": "claude",
    "STANDARDS_READER_ENABLED": "true",
    "STANDARDS_READER_ALLOW_PUBLIC_EGRESS": "true",
    "ANTHROPIC_API_KEY": FAKE_KEY,
    "REVIEW_AI_CHECK_ENABLED": "true",
    "RULE_PARSE_MODEL_ENABLED": "true",
    "GEOMETRY_READER_ENABLED": "true",
    "ANSWER_JUDGE_ENABLED": "true",
    "MARKET_LIVE_ENABLED": "true",
    "MARKET_ALLOW_PUBLIC_EGRESS": "true",
    "MARKET_SEARCH_API_KEY": "fake-market-key",
    "CHAT_WEB_ENABLED": "true",
    "REVIEW_WEB_STANDARDS_ENABLED": "true",
    "OLLAMA_URL": "http://ollama.example.test:11434",
    "ANSWER_MODEL_ALLOW_REMOTE_HOST": "true",
    "ANSWER_MODEL_ALLOWED_HOSTS": '["ollama.example.test"]',
    "MATCH_ENABLED": "true",
    "SMTP_ENABLED": "true",
    "SMTP_HOST": "smtp.example.test",
    "SMTP_FROM": "a@example.test",
    "SMTP_RECIPIENT": "b@example.test",
    "SMTP_USERNAME": "u",
    "SMTP_PASSWORD": "p",
    "SUMMARY_SCHEDULE": "daily",
    "AUTH_MODE": "demo_required",
    "AUTH_SECRET": "x" * 64,
    "WATCH_FOLDER": "/somewhere/else",
    "CLAUDE_SPEND_LOG": "/somewhere/else/claude_spend.jsonl",
}

#: Split between the file and the process environment, as on a real machine.
FILE_HALF = {k: v for i, (k, v) in enumerate(HOSTILE.items()) if i % 2 == 0}
ENV_HALF = {k: v for k, v in HOSTILE.items() if k not in FILE_HALF}


def _lanes_open() -> dict:
    """Which egress gates the live `settings` + environment would open."""
    try:
        notifications._validate_runtime()
        smtp = True
    except NotificationConfigError:
        smtp = False
    _, remote = check_model_url(
        settings.ollama_url,
        allow_remote=settings.answer_model_allow_remote_host,
        allowed_hosts=settings.answer_model_allowed_hosts,
    )
    return {
        "claude": reasoning_provider.claude_available()[0],
        "reader": reader_transport.available(),
        "reader_transport": reader_transport.transport() is not None,
        "market": market_transport.available(),
        "market_transport": market_transport.transport() is not None,
        "smtp": smtp,
        "remote_model": remote is not None,
    }


@pytest.fixture
def hostile_machine(tmp_path, monkeypatch):
    """The owner's laptop: a `.env` and an environment with every lane on.

    Every field of the live singleton is monkeypatched (so all are restored),
    and so is the class-level `env_file`.
    """
    env_file = tmp_path / ".env"
    env_file.write_text("".join(f"{k}={v}\n" for k, v in FILE_HALF.items()), encoding="utf-8")
    monkeypatch.setitem(Settings.model_config, "env_file", env_file)
    for k, v in ENV_HALF.items():
        monkeypatch.setenv(k, v)
    hostile = Settings()
    for name in Settings.model_fields:
        monkeypatch.setattr(settings, name, getattr(hostile, name))
    # Nothing in this test writes, but a reset must not leave the singleton
    # pointing at backend/data even for a moment longer than needed.
    return hostile


def _back_to_tmp(tmp_path):
    for name in env_isolation.WRITE_PATHS:
        setattr(settings, name, tmp_path / name)


def test_the_hostile_machine_really_opens_every_lane(hostile_machine):
    """THE PRECONDITION. If the hostile file and environment did not open the
    lanes, the isolation test below would pass by default."""
    assert hostile_machine.reasoning_provider == "claude"          # from the file
    assert hostile_machine.standards_reader_enabled is True         # from the env
    assert hostile_machine.anthropic_api_key == FAKE_KEY            # from the env
    assert set(env_isolation.unsafe_fields(settings)) >= {
        "reasoning_provider", "standards_reader_enabled", "anthropic_api_key",
        "market_live_enabled", "smtp_enabled", "ollama_url", "auth_mode",
    }
    assert all(_lanes_open().values()), _lanes_open()


def test_isolate_closes_every_lane_a_hostile_machine_opened(hostile_machine, tmp_path):
    removed = env_isolation.isolate(settings)
    _back_to_tmp(tmp_path)

    assert env_isolation.unsafe_fields(settings) == []
    assert not any(_lanes_open().values()), _lanes_open()
    # The variables are gone from the process, so the direct os.environ reads
    # (reader_api, claude_unavailable) cannot see them either ...
    assert set(ENV_HALF) <= set(removed)
    assert not [k for k in ENV_HALF if k in os.environ]
    # ... and a fresh Settings() - what several tests build - reads no file.
    assert Settings.model_config["env_file"] is None
    assert env_isolation.unsafe_fields(Settings()) == []
    # The model lane dials loopback.
    from app import model_transport
    assert model_transport.endpoint("/api/tags").startswith("http://127.0.0.1:")
    # The key appears nowhere a report could print it.
    assert FAKE_KEY not in " ".join(removed)


def test_the_real_conftest_isolates_a_hostile_environment_at_import():
    """End to end, in a fresh interpreter: import the real conftest with every
    egress variable set, as a shell with `.env` exported would, and read back
    what the application would do. In THIS process isolation has already run,
    so only a new one can prove conftest runs it."""
    probe = (
        "import json, os, tests.conftest\n"
        "from app.config import settings\n"
        "from app import reasoning_provider, reader_transport, market_transport\n"
        "from tests import env_isolation\n"
        "print(json.dumps({\n"
        "  'unsafe': env_isolation.unsafe_fields(settings),\n"
        "  'claude': reasoning_provider.claude_available()[0],\n"
        "  'reader': reader_transport.available(),\n"
        "  'market': market_transport.available(),\n"
        "  'guard': env_isolation._installed,\n"
        "  'proxy': sorted(k for k in os.environ if k.upper() in env_isolation.PROXY_ENV_NAMES),\n"
        "}))\n"
    )
    env = {**os.environ, **HOSTILE, "HTTPS_PROXY": "http://127.0.0.1:9"}
    out = subprocess.run(
        [sys.executable, "-c", probe], cwd=BACKEND_DIR, env=env,
        capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0, out.stderr[-2000:]
    assert FAKE_KEY not in out.stdout + out.stderr
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got == {"unsafe": [], "claude": False, "reader": False,
                   "market": False, "guard": True, "proxy": []}, got


def test_the_live_session_is_isolated():
    """What every other test in this run is sitting on."""
    assert env_isolation.unsafe_fields(settings) == []
    assert Settings.model_config["env_file"] is None
    leaked = [k for k in os.environ
              if k.lower() in Settings.model_fields
              or k in env_isolation.DIRECT_ENV_NAMES
              or k.startswith(env_isolation.DIRECT_ENV_PREFIXES)
              or k.upper() in env_isolation.PROXY_ENV_NAMES]
    assert leaked == []
    live = env_isolation.LIVE_DATA_DIR.resolve()
    for name in env_isolation.WRITE_PATHS:
        p = Path(getattr(settings, name)).resolve()
        assert p != live and live not in p.parents, (
            f"{name} points into backend/data - the real ledger, cache or DB")


def test_every_risky_setting_is_classified():
    """A NEW egress switch in config.py fails here until someone decides what
    it is. The mechanism resets everything; this list is how the check knows
    what 'safe' means, so it must not silently fall behind the settings."""
    fields = set(Settings.model_fields)
    classified = (set(env_isolation.EGRESS_SAFE) | set(env_isolation.WRITE_PATHS)
                  | set(env_isolation.READ_ONLY_PATHS))
    assert classified <= fields, f"stale names: {sorted(classified - fields)}"
    pattern = re.compile("|".join(map(re.escape, env_isolation.RISKY_NAME_PARTS)))
    unclassified = sorted(f for f in fields if pattern.search(f) and f not in classified)
    assert unclassified == [], f"classify these in env_isolation: {unclassified}"
    # The safe value IS the code default: a default flipped on is caught here.
    for name, safe in env_isolation.EGRESS_SAFE.items():
        assert Settings.model_fields[name].default == safe, name


# ------------------------------------------------------------ network guard


def test_the_guard_refuses_a_non_loopback_connect_and_records_it():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)  # were the guard ever broken, fail fast rather than hang
    try:
        with pytest.raises(env_isolation.EgressBlocked):
            s.connect(("203.0.113.9", 443))           # TEST-NET-3, never routed
        with pytest.raises(env_isolation.EgressBlocked):
            s.connect_ex(("203.0.113.9", 443))
    finally:
        s.close()
    assert len(env_isolation.take_attempts()) == 2


def test_the_guard_refuses_a_dns_lookup_and_httpx_cannot_reach_the_api():
    with pytest.raises(env_isolation.EgressBlocked):
        socket.getaddrinfo("egress-probe.invalid", 443)
    assert env_isolation.take_attempts() == ["DNS lookup of 'egress-probe.invalid'"]
    with pytest.raises(httpx.ConnectError):
        httpx.get("https://api.anthropic.com/v1/models", timeout=2)
    attempts = env_isolation.take_attempts()
    assert attempts and all("api.anthropic.com" in a for a in attempts), attempts


def test_the_guard_lets_loopback_through():
    """TestClient, socketpair and a local fake Ollama must keep working, or the
    guard gets removed by the first person it inconveniences."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.connect(server.getsockname())
        assert socket.getaddrinfo("localhost", 80)
    finally:
        client.close()
        server.close()
    assert env_isolation.take_attempts() == []


PROBE = """
import socket

def test_swallows_the_refusal():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        s.connect(("203.0.113.9", 443))
    except OSError:
        pass  # a caller that falls back quietly, as the model lane does
    finally:
        s.close()
"""


def test_a_test_that_swallows_the_refusal_is_still_failed_by_name(tmp_path):
    """The guard raises an OSError, as an offline machine would, and code that
    catches OSError and falls back would hide the attempt. conftest's autouse
    fixture must fail that test anyway. Run as its own pytest session with the
    real conftest loaded as a plugin."""
    probe = tmp_path / "test_probe.py"
    probe.write_text(PROBE, encoding="utf-8")
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "-p", "tests.conftest", "-c", str(BACKEND_DIR / "pytest.ini"),
         "--rootdir", str(BACKEND_DIR), str(probe)],
        cwd=BACKEND_DIR, capture_output=True, text=True, timeout=300,
    )
    assert out.returncode == 1, out.stdout[-3000:]
    assert "tried to leave the machine" in out.stdout
    assert "203.0.113.9" in out.stdout
