"""#821 (S5): the weekly log check reports what a person must look at, and
reads without writing.

Invented ledger and invented audit rows only. Each test names the line the
check must print; a check that printed nothing, or "none found", for the
same input fails here.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app import claude_spend, db
from app.config import settings

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "weekly_log_check.py"
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def _load():
    spec = importlib.util.spec_from_file_location("weekly_log_check", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def env(tmp_path, monkeypatch):
    ledger = tmp_path / "claude_spend.jsonl"
    monkeypatch.setattr(settings, "claude_spend_log", ledger)
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "weekly.sqlite")
    db.reset_connection()
    db.init_db()
    yield ledger, tmp_path / "weekly.sqlite"
    db.reset_connection()


def _at(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat(timespec="seconds")


def _write(ledger: Path, *entries: dict) -> None:
    ledger.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")


def _call(step, usd, days_ago, model="claude-sonnet-4-6", **extra):
    return {"at": _at(days_ago), "step": step, "model": model, "cost_usd": usd,
            "prompt_sha256": "SENTINEL-PROMPT-HASH", "finish_reason": "end_turn", **extra}


def _report(db_path: Path) -> str:
    return _load().report(days=7, now=NOW, db_path=db_path)


def test_spend_is_stated_against_both_caps_with_the_window_split(env):
    ledger, path = env
    _write(ledger, _call("chat", 1.0, 20), _call("chat", 0.5, 2), _call("claude-recheck", 0.25, 1))
    out = _report(path)
    assert "All time: USD 1.7500 of the USD 20.00 total cap (3 calls in the ledger)." in out
    assert "This window: USD 0.7500 over 2 calls." in out
    assert "| chat | 1 | 0.5000 | 1.5000 | 5.00 |" in out
    assert "| claude-recheck | 1 | 0.2500 | 0.2500 | 5.00 |" in out


def test_unusual_calls_are_each_named(env):
    ledger, path = env
    _write(ledger,
           _call("chat", 4.2, 30),                                   # 84 % of the step cap
           _call("chat", 0.1, 1, model="claude-mystery-9"),          # unknown model
           _call("new-step", 0.1, 1),                                # first seen this window
           _call("chat", 0.0, 1, refused="not_approved", documents=["SENTINEL-DOC-ID"]),
           _call("chat", 0.3, 1, estimated=True),
           _call("b4-vision", 0.2, 1, reserved=True, reservation="r1"),
           "torn line {")
    out = _report(path)
    assert "model not in the price table: claude-mystery-9 (1 calls)" in out
    assert "step first seen this window: new-step (1 calls)" in out
    assert "step first seen this window: chat" not in out, "chat ran before the window"
    assert "refused, document not approved (not_approved): 1" in out
    assert "calls settled at an estimate, usage not reported: 1" in out
    assert "reservations never settled (charged at their worst case): 1" in out
    assert "step at 92% of its cap: chat" in out
    # the torn line counts at the total cap, as the caps count it
    assert "total at 1" in out
    assert "none found in this window" not in out


def test_a_dated_model_id_is_known(env):
    ledger, path = env
    _write(ledger, _call("chat", 0.1, 30), _call("chat", 0.1, 1, model="claude-haiku-4-5-20251001"))
    out = _report(path)
    assert "model not in the price table" not in out
    assert "- none found in this window" in out


def test_failed_logins_in_the_window_are_counted_by_outcome_and_account(env):
    _, path = env
    with db.connect() as conn:
        for days, outcome, user in ((1, "denied", "engineer1"), (2, "denied", "engineer1"),
                                    (3, "rate_limited", "ghost"), (9, "denied", "old")):
            conn.execute("INSERT INTO audit_events(at, actor_username, action, resource_type,"
                         " outcome) VALUES (?, ?, 'login_failed', 'session', ?)",
                         (_at(days), user, outcome))
        conn.execute("INSERT INTO audit_events(at, actor_username, action, resource_type,"
                     " outcome) VALUES (?, 'engineer1', 'login', 'session', 'ok')", (_at(1),))
    out = _report(path)
    assert "- 3 in this window: denied 2, rate_limited 1" in out
    assert "- engineer1: 2" in out and "- ghost: 1" in out
    assert "old" not in out.split("## Failed logins")[1]


def test_a_missing_database_is_could_not_check_and_is_not_created(env, tmp_path):
    missing = tmp_path / "typo.sqlite"
    out = _report(missing)
    assert "could not check: the database did not open" in out
    assert not missing.exists(), "the check created a database at a wrong path"


def test_the_check_writes_neither_file_and_prints_no_prompt_or_document(env):
    ledger, path = env
    _write(ledger, _call("chat", 0.1, 1, refused="not_approved", documents=["SENTINEL-DOC-ID"]))
    db.reset_connection()
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=DELETE")
    before = (ledger.read_bytes(), path.read_bytes())
    out = _report(path)
    assert (ledger.read_bytes(), path.read_bytes()) == before
    assert "SENTINEL" not in out


def test_an_empty_ledger_says_so(env):
    _, path = env
    out = _report(path)
    assert "The ledger has no calls (file missing or empty)." in out


def test_main_reads_the_ledger_named_on_the_command_line(env, tmp_path, capsys):
    _, path = env
    other = tmp_path / "other.jsonl"
    _write(other, _call("chat", 2.0, 1))
    assert _load().main(["--ledger", str(other), "--db", str(path)]) == 0
    assert "All time: USD 2.0000" in capsys.readouterr().out


def test_a_converter_step_is_reported_against_its_own_25_dollar_cap(env, monkeypatch):
    """Order 271.3: `standards_convert:<standard>` steps have a USD 25 cap, so the table must not say 5.00 and
    a step at USD 24 is at 96 % of its cap, not 480 %."""
    ledger, path = env
    monkeypatch.setattr(settings, "claude_budget_usd_total", 500.0)
    monkeypatch.setattr(claude_spend, "_today", lambda: datetime(2026, 11, 15).date())
    _write(
        ledger, _call("standards_convert:SAES-G-005", 24.0, 1), _call("chat", 4.9, 1)
    )
    out = _report(path)
    assert "| standards_convert:SAES-G-005 | 1 | 24.0000 | 24.0000 | 25.00 |" in out
    assert "| chat | 1 | 4.9000 | 4.9000 | 5.00 |" in out
    assert "step at 96% of its cap: standards_convert:SAES-G-005" in out
    assert "480%" not in out
