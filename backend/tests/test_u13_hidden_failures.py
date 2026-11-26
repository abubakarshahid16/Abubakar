"""HIDDEN FAILURES (order 26 Nov 2026 03:35, D2): every failed AI or read step of the general review and of technical queries is
recorded in the run (or the query's history) and shown, never swallowed. One test per place that only logged before; the steps
recorded reach the page's and the file's "Steps that did not run" with their own words. Invented values only; no engine is
called."""

from __future__ import annotations

import pytest

from app import aim_review_jobs, aim_review_view
from app.aim_review import faults, library
from app.aim_review import local_model as lm


def _failed(calls: list, step: str) -> list:
    return [
        c
        for c in calls
        if getattr(c, "step", None) == step and not getattr(c, "ok", True)
    ]


def _boom(*_a, **_k):
    raise RuntimeError("invented")


def test_an_unreadable_kind_table_is_recorded_and_gives_no_floor(monkeypatch):
    from app import kind_review_table

    monkeypatch.setattr(kind_review_table, "no_main_equipment_kinds", _boom)
    with faults.recording([]) as calls:
        assert library.floor_for("procedure") == 0
    (rec,) = _failed(calls, "aim_kind_table")
    assert rec.code.endswith(
        "not applied: RuntimeError"
    )  # the class only, never the text


def test_an_unreadable_kind_reading_is_recorded(monkeypatch):
    from app import agent_review_kind

    monkeypatch.setattr(agent_review_kind, "read_kind", _boom)
    with faults.recording([]) as calls:
        assert library.stored_reading(None, "doc-invented", frozenset())[0] is None
    assert len(_failed(calls, "aim_kind_reading")) == 1


def test_an_unreadable_equipment_reading_is_recorded(monkeypatch):
    from app import agent_review_kind

    monkeypatch.setattr(
        agent_review_kind,
        "read_kind",
        lambda conn, pid: {
            "known": True,
            "kind": "datasheet",
            "method": "x",
            "page": 1,
        },
    )
    monkeypatch.setattr(agent_review_kind, "read_equipment", _boom)
    import app.aim_review.book_names as bn

    monkeypatch.setattr(bn, "last_run_type", lambda *a, **k: None)
    with faults.recording([]) as calls:
        library.stored_reading(None, "doc-invented", frozenset())
    assert len(_failed(calls, "aim_equipment_reading")) == 1


def test_a_failed_cross_document_check_is_in_the_runs_calls(monkeypatch):
    from app import tag_cross

    monkeypatch.setattr(tag_cross, "lines", _boom)
    calls: list = []
    assert aim_review_jobs._cross_document(None, "doc-invented", set(), 0, calls) == []
    assert len(_failed(calls, "aim_cross_document")) == 1


def test_an_unreadable_swap_is_recorded_once_per_run(monkeypatch):
    monkeypatch.setattr(lm, "_swap_bytes", lambda: None)
    model = lm.LocalModel("invented-model:9b")
    with faults.recording([]) as calls:
        for _ in range(3):
            model._memory_rule("aim_judge", object())
    assert len(_failed(calls, lm.SWAP_UNREAD_STEP)) == 1


def test_an_unreadable_model_description_is_recorded_once(monkeypatch):
    from app import model_transport

    monkeypatch.setattr(model_transport, "post_json", _boom)
    with faults.recording([]) as calls:
        assert lm._show("invented-model:9b") == {}
        assert lm._show("invented-model:9b") == {}
    assert len(_failed(calls, lm.SHOW_UNREAD_STEP)) == 1


def test_free_memory_that_cannot_be_read_stops_a_local_run_before_it_starts(
    monkeypatch,
):
    from app import heavy_lock, model_transport

    name = "invented-model:9b"
    tags = {"models": [{"name": name, "size": 6_000_000_000, "digest": "d"}]}
    monkeypatch.setattr(
        model_transport,
        "get_json",
        lambda path, *, timeout, required=True: (
            tags if path == "/api/tags" else {"models": []}
        ),
    )
    monkeypatch.setattr(heavy_lock, "read", lambda path=None: None)
    monkeypatch.setattr(lm, "_free_bytes", lambda: None)
    assert lm.readiness([name]) == lm.FREE_UNKNOWN


@pytest.mark.parametrize(
    "step",
    ["aim_kind_table", "aim_kind_reading", "aim_equipment_reading", "aim_cross_document", lm.SWAP_UNREAD_STEP,
     lm.SHOW_UNREAD_STEP],
)  # fmt: skip
def test_each_recorded_step_reaches_the_page_and_the_file_in_plain_words(step):
    calls = [
        {
            "step": step,
            "model": "code",
            "ok": False,
            "code": f"invented not applied: RuntimeError",
        }
    ]
    (shown,) = aim_review_view.steps_not_applied(calls)
    assert shown["step"] == step and "RuntimeError" in shown["sentence"]
    assert faults.NOT_APPLIED_WORDS[step].split(" (")[0] in shown["sentence"]


def test_a_query_whose_evidence_could_not_be_queued_says_so_in_its_history(
    monkeypatch, tmp_path
):
    from app import config, db, gmail_worker, technical_queries, technical_query_jobs

    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    monkeypatch.setattr(config.settings, "db_path", tmp_path / "tq.sqlite")
    db.reset_connection()
    db.init_db()
    try:
        technical_queries.ensure_schema()
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO technical_queries(id, subject, status, received_at, created_at, updated_at)"
                " VALUES ('q-invented', 'Invented subject', 'received', 'x', 'x', 'x')"
            )
        monkeypatch.setattr(technical_query_jobs, "latest", _boom)
        gmail_worker.auto_prepare("q-invented", None)
        with db.connect() as conn:
            events = conn.execute(
                "SELECT event, detail FROM query_events WHERE query_id = 'q-invented'"
            ).fetchall()
        assert [(e["event"], e["detail"]) for e in events] == [
            (gmail_worker.EVIDENCE_NOT_QUEUED, "RuntimeError")
        ]
    finally:
        db.reset_connection()
