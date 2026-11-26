"""Update 11 (lead-4, 26 Nov 2026): a running LOCAL review's progress page names its model and the minutes of the last measured run of
that model and kind on this Mac ("not yet measured" when there is none), from the stored runs, never from a table of its own.
Invented kinds, models and times; no model, no network."""

from __future__ import annotations

import json
import sqlite3

import pytest

from app import aim_review_local_view as LV
from app import aim_review_store as store


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    store._create(c)
    return c


def _run(
    c,
    run_id,
    *,
    status="done",
    kind="valve",
    model="m9",
    seconds=1980.0,
    stop=None,
    at="2026-11-20T10:00:00",
    engine="local",
):
    calls = [{"step": "aim_judge", "model": model, "engine": engine}]
    c.execute(
        "INSERT INTO aim_runs (run_id, paper_document_id, status, identity_json, calls_json, seconds, stop_reason, created_at, finished_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (
            run_id,
            "doc",
            status,
            json.dumps({"kind": kind}),
            json.dumps(calls),
            seconds,
            stop,
            at,
            at,
        ),
    )


def test_the_last_finished_run_of_this_model_and_kind_gives_the_minutes(conn):
    _run(conn, "old", seconds=3000, at="2026-11-19T10:00:00")
    _run(conn, "new", seconds=1980, at="2026-11-21T10:00:00")
    assert LV.measured_minutes(conn, "valve", "m9") == 33  # the newest, 1980 s


def test_another_kind_another_model_a_stopped_or_claude_run_is_not_a_measure(conn):
    _run(conn, "pump", kind="pump")
    _run(conn, "other-model", model="m14")
    _run(conn, "stopped", status="stopped")
    _run(conn, "stop-reason", stop="swap")
    _run(conn, "claude", engine="claude")
    assert LV.measured_minutes(conn, "valve", "m9") is None
    assert LV.measured_minutes(conn, None, "m9") is None


def _local(monkeypatch, models=("m9",), local=True):
    from app import aim_review_jobs
    from app.aim_review import local_model

    monkeypatch.setattr(aim_review_jobs, "on_local", lambda conn, run_id: local)
    monkeypatch.setattr(local_model, "model_name", lambda: models[0])
    monkeypatch.setattr(local_model, "step_models", lambda: {})


def test_the_note_names_the_model_and_the_measured_minutes(conn, monkeypatch):
    _local(monkeypatch)
    _run(conn, "past", seconds=1980)
    conn.execute(
        "INSERT INTO aim_runs (run_id, paper_document_id, status, identity_json, created_at) VALUES ('now','doc','running',?,?)",
        (json.dumps({"kind": "valve"}), "2026-11-26T09:00:00"),
    )
    note = LV.progress_note(conn, "now")
    assert "m9" in note and "about 33 min for this kind on this Mac" in note


def test_no_measured_run_or_no_kind_yet_says_not_yet_measured(conn, monkeypatch):
    _local(monkeypatch)
    conn.execute(
        "INSERT INTO aim_runs (run_id, paper_document_id, status, identity_json, created_at) VALUES ('now','doc','running',?,?)",
        (json.dumps({"kind": "valve"}), "2026-11-26T09:00:00"),
    )
    assert "m9" in LV.progress_note(
        conn, "now"
    ) and "not yet measured" in LV.progress_note(conn, "now")
    conn.execute(
        "INSERT INTO aim_runs (run_id, paper_document_id, status, created_at) VALUES ('early','doc','running','2026-11-26T09:00:00')"
    )
    assert "not yet measured" in LV.progress_note(
        conn, "early"
    )  # the kind is not named yet


def test_a_claude_run_has_no_note(conn, monkeypatch):
    _local(monkeypatch, local=False)
    conn.execute(
        "INSERT INTO aim_runs (run_id, paper_document_id, status, created_at) VALUES ('c','doc','running','2026-11-26T09:00:00')"
    )
    assert LV.progress_note(conn, "c") is None


def test_the_naming_step_stores_the_kind_on_the_running_run_but_never_over_an_ended_one(
    conn,
):
    conn.execute(
        "INSERT INTO aim_runs (run_id, paper_document_id, status, created_at) VALUES ('r','doc','running','2026-11-26T09:00:00')"
    )
    store.set_identity(conn, "r", {"kind": "valve"})
    assert json.loads(
        conn.execute("SELECT identity_json FROM aim_runs WHERE run_id='r'").fetchone()[
            0
        ]
    ) == {"kind": "valve"}
    _run(conn, "ended", kind="pump")
    store.set_identity(conn, "ended", {"kind": "valve"})
    assert json.loads(
        conn.execute(
            "SELECT identity_json FROM aim_runs WHERE run_id='ended'"
        ).fetchone()[0]
    ) == {"kind": "pump"}


def test_the_job_the_page_gets_carries_the_note(monkeypatch):
    from app import review_jobs

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(
        "CREATE TABLE jobs (id TEXT, state TEXT, progress_done INT, progress_total INT, progress_label TEXT, cancel_requested INT, review_run_id TEXT, started_at TEXT)"
    )
    db.execute(
        "INSERT INTO jobs VALUES ('j','running',2,5,'checklist',0,'r1','2026-11-26T09:00:00')"
    )
    monkeypatch.setattr(review_jobs, "connect", lambda: db)
    monkeypatch.setattr(
        LV,
        "progress_note",
        lambda conn, run_id: (
            "Local model m9: not yet measured for this kind on this Mac."
        ),
    )
    assert review_jobs.job_for_run("r1")["local_note"].startswith("Local model m9")
    monkeypatch.setattr(LV, "progress_note", lambda conn, run_id: None)
    assert "local_note" not in review_jobs.job_for_run("r1")
    monkeypatch.setattr(
        LV,
        "progress_note",
        lambda conn, run_id: (_ for _ in ()).throw(sqlite3.Error("x")),
    )
    assert "local_note" not in review_jobs.job_for_run(
        "r1"
    )  # a note that cannot be made is left out


def test_a_failure_storing_the_kind_early_never_stops_a_review():
    broken = sqlite3.connect(":memory:")  # no aim_runs table: the update fails
    store.keep_identity(broken, "r", {"kind": "valve"})  # does not raise
