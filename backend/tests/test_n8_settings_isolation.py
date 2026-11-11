"""A test cannot leave the process settings changed for the tests after it.

Found on the Mac: 150 to 200 tests failed in a full run that passed alone, because
some test assigned `settings.<field>` and never put it back (the bench scripts'
`main()` did it through `use_settings_of`, with the main checkout's real `.env`).
The two tests below run in file order on one worker: the first changes a path, a
switch and a host list on purpose, the second must see the original values.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

from app.config import settings

REPO = Path(__file__).resolve().parents[2]
_FIELDS = ("db_path", "match_enabled", "startup_warmup", "allowed_hosts", "upload_dir")
#: filled by the first test, after the session fixtures set the test values
_ORIGINAL: dict = {}


def test_a_aaa_changes_settings_without_restoring_them():
    _ORIGINAL.update({n: getattr(settings, n) for n in _FIELDS})
    settings.db_path = Path("/nonexistent/live.sqlite")
    settings.match_enabled = not settings.match_enabled
    settings.startup_warmup = not settings.startup_warmup
    settings.upload_dir = Path("/nonexistent/uploads")
    settings.allowed_hosts = "elsewhere.invalid"
    assert settings.db_path != _ORIGINAL["db_path"]


def test_b_the_next_test_sees_the_original_values():
    for name in _FIELDS:
        assert getattr(settings, name) == _ORIGINAL[name], name


def test_bench_main_under_pytest_does_not_look_for_a_real_env_file(monkeypatch, tmp_path):
    """In a checkout with no backend/.env (a git worktree), `_settings_file` asked git for the
    MAIN checkout and returned its real `.env`. Under pytest it must answer None without asking."""
    spec = importlib.util.spec_from_file_location("bench_script_n8", REPO / "scripts" / "crs_bench.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setattr(script, "REPO", tmp_path)  # a checkout with no backend/.env

    def refuse(*a, **k):
        raise AssertionError("looked for the main checkout's .env: " + repr(a))

    monkeypatch.setattr(subprocess, "run", refuse)
    assert script._settings_file(None) is None
    given = tmp_path / "given.env"  # an explicit file is still honoured
    assert script._settings_file(str(given)) == given
