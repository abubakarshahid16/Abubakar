"""12 Nov defect: `AnswerStore.forget` left a write transaction open on a worker thread, so the run's other threads failed with
"database is locked" (planted valve). Two threads against the invented database; no network."""

# ruff: noqa: F811
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import threading
from pathlib import Path

from app import agent_review_reuse as reuse_mod
from app import db
from app.config import settings
from tests import agent_review_support as s
from tests.test_agent_review_guards import run_review, w  # noqa: F401

ANSWER = {
    "stop_reason": "end_turn",
    "content": [{"type": "text", "text": "{}"}],
    "model": "m",
}


def store_with_row(key="k1"):
    store = reuse_mod.AnswerStore("run-a", s.PAPER, "v1")
    reuse_mod.ensure_tables(db.connect())
    store.remember(key, "m", 10, ANSWER)
    assert store.commit() == 1
    return store


def other_thread(fn):
    out = {}

    def target():
        try:
            out["result"] = fn()
        except BaseException as exc:  # noqa: BLE001
            out["error"] = exc

    t = threading.Thread(target=target)
    t.start()
    t.join(10)
    return out


def test_a_forget_on_one_thread_leaves_no_write_lock_for_another_thread(w):
    store = store_with_row()
    released, forgotten = threading.Event(), threading.Event()

    def worker():  # a batch worker: it forgets a failed-quote answer, then waits for its next paid call
        store.forget("k1")
        forgotten.set()
        released.wait(10)

    t = threading.Thread(target=worker)
    t.start()
    assert forgotten.wait(10)
    try:

        def writer():  # another worker storing its own answer, with a short busy timeout (the app's is 30 s)
            db.connect().execute("PRAGMA busy_timeout = 300")
            mine = reuse_mod.AnswerStore("run-b", s.PAPER, "v1")
            mine.remember("k2", "m", 10, ANSWER)
            return mine.commit()

        out = other_thread(writer)
    finally:
        released.set()
        t.join(10)
    assert out.get("result") == 1, (
        out
    )  # fails with "database is locked" when forget leaves its DELETE uncommitted
    keys = {
        r[0]
        for r in db.connect().execute("SELECT request_key FROM agent_review_answer")
    }
    assert keys == {"k2"}


def test_a_run_that_forgets_an_answer_leaves_no_open_write_transaction(w, monkeypatch):
    monkeypatch.setattr(settings, "agent_review_reuse_answers_enabled", True)
    w["fake"].answers["R-coat"] = {
        **s.ANSWERS["R-coat"],
        "paper_quote": "a quote the paper does not hold",
    }
    run_review()  # a failed-quote answer is dropped (forget) inside the run
    run_review()
    raw = sqlite3.connect(settings.db_path, timeout=0.3)
    raw.execute(
        "INSERT OR REPLACE INTO agent_review_answer_run (run_id, fresh) VALUES ('x', 0)"
    )  # would be "locked"
    raw.commit()
    raw.close()
    assert not db.connect().in_transaction


def test_fresh_replacing_a_stored_answer_leaves_no_write_lock(w):
    store = store_with_row()
    fresh = reuse_mod.AnswerStore("run-c", s.PAPER, "v1", fresh=True)
    assert fresh.lookup("k1") is None  # a fresh run never reads
    fresh.remember("k1", "m", 10, ANSWER)
    assert fresh.commit() == 1
    out = other_thread(
        lambda: (
            sqlite3.connect(settings.db_path, timeout=0.3)
            .execute(
                "INSERT OR REPLACE INTO agent_review_answer_run (run_id, fresh) VALUES ('y', 0)"
            )
            .connection.commit()
        )
    )
    assert "error" not in out, out
    row = (
        db.connect()
        .execute("SELECT from_run_id FROM agent_review_answer WHERE request_key = 'k1'")
        .fetchone()
    )
    assert row[0] == "run-c" and store is not None


def trial_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "trial_on_copy.py"
    spec = importlib.util.spec_from_file_location("trial_on_copy_t", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["trial_on_copy_t"] = mod
    spec.loader.exec_module(mod)
    return mod


class QueuedHttp:
    def get_json(self, path):
        return 200, {"status": "queued"}


def test_the_trial_stops_waiting_when_the_job_failed_an_attempt_and_says_why(tmp_path):
    trial = trial_module()
    copy = tmp_path / "copy.sqlite"
    conn = sqlite3.connect(copy)
    conn.execute(
        "CREATE TABLE jobs (id TEXT, review_run_id TEXT, state TEXT, retries INTEGER, error_code TEXT)"
    )
    conn.execute(
        "INSERT INTO jobs VALUES ('j', 'r1', 'retrying', 1, 'OperationalError')"
    )
    conn.commit()
    conn.close()
    got = trial.wait_for(
        QueuedHttp(), "r1", 60.0, copy
    )  # returns at once, not after 60 s
    assert got.startswith("failed: job retrying after OperationalError (retries 1)")
    assert trial.wait_for(QueuedHttp(), "r1", 0.1, None).startswith(
        "timeout"
    )  # no copy to read: the old behaviour
    assert json.dumps(got)  # cause words only


def test_max_usd_bounds_this_run_not_the_whole_copy_ledger(tmp_path):
    """12 Nov: an in-place repeat run was refused 'usd_cap_reached: total' because the cap counted the first run's spend."""
    trial = trial_module()
    (tmp_path / "claude_spend.jsonl").write_text(
        json.dumps({"cost_usd": 0.55})
        + "\n"
        + json.dumps({"cost_usd": 0.0, "reserved": True})
        + "\nnot json\n"
    )
    assert trial.ledger_spent(tmp_path) == 0.55
    assert trial.ledger_spent(tmp_path / "none") == 0.0
    from app.config import settings

    cfg = trial.TrialConfig(data_dir=tmp_path, document="d", lane="open", max_usd=0.6)
    keep = (settings.claude_budget_usd_total, settings.claude_budget_usd_per_step)
    try:
        settings.claude_budget_usd_total, settings.claude_budget_usd_per_step = (
            500.0,
            5.0,
        )
        import os

        os.environ["ANTHROPIC_API_KEY"] = (
            "x"  # a placeholder: only its presence is read
        )
        try:
            trial.apply_settings(cfg)
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        assert (
            settings.claude_budget_usd_total == 0.55 + 0.6
        )  # the repeat run may spend its own 0.6
        assert settings.claude_budget_usd_per_step == 0.6
    finally:
        settings.claude_budget_usd_total, settings.claude_budget_usd_per_step = keep


def test_a_repeat_run_that_reviewed_nothing_fails_loudly_and_a_fully_reused_run_passes():
    trial = trial_module()
    cfg = trial.TrialConfig(data_dir=Path(), document="d", lane="open", max_usd=1.0)
    stopped = {
        "counts_by_class": {"Not reviewed": 53},
        "usd": None,
        "stop_reason": "usd_cap_reached: total: spent $0.5559",
    }
    check = trial.spend_check(cfg, stopped, Path(), 0)
    assert (
        not check.ok
        and "no spend recorded" in check.detail
        and "the run stopped: usd_cap_reached" in check.detail
    )
    assert (
        not trial.stop_check(cfg, stopped).ok
        and "usd_cap_reached" in trial.stop_check(cfg, stopped).detail
    )
    reused = {
        "counts_by_class": {"Proven by code": 3, "Query for the engineer": 50},
        "usd": 0.0,
        "answers_reused": 23,
    }
    assert trial.spend_check(
        cfg, reused, Path(), 0
    ).ok  # nothing was asked, nothing was spent, on purpose
    assert trial.stop_check(cfg, reused).ok
    nothing = {
        "counts_by_class": {"Query for the engineer": 53},
        "usd": 0.0,
        "answers_reused": 0,
    }
    assert not trial.spend_check(
        cfg, nothing, Path(), 0
    ).ok  # no reuse and no spend: still a failure
