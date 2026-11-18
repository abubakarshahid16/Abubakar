# ruff: noqa: F811
"""Piece H (order 14): the pre-start "last review cost" of the general review is the last GENERAL run's own cost, read from the spend
ledger for every step of that run, never the earlier engine's one-part figure; a run whose cost was not read says so. Invented values."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import aim_review_store as store
from app import db
from app.main import app
from tests.test_aim_store_runs import _line, _result
from tests.test_g2_review_list import papers, real_roles  # noqa: F401 - fixtures
from tests.test_p3_review_jobs import temp_storage  # noqa: F401 - fixture

NOW = "2026-11-18T10:00:00Z"


def _plan(ids, doc="submittal"):
    r = TestClient(app).get(
        "/api/reviews/plan",
        params={"submittal_document_id": ids[doc], "engine": "claude"},
        headers=ids["admin"],
    )
    assert r.status_code == 200, r.text
    return r.json()["cost"]


def _general_run(paper: str, run_id: str, usd, started=NOW, status="done"):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at, started_at) VALUES (?, ?, 'completed', ?, ?, ?)",
            (run_id, paper, started, started, started),
        )
        store.start_run(conn, run_id, paper, started)
        store.finish_run(
            conn, run_id, _result([_line()], usd=usd, status=status), started
        )


def _earlier_engine_cost(paper: str, usd: float, monkeypatch):
    """What the earlier engine stored for its one AI part: the figure the plan used to show."""
    from app import agent_review_schema
    from app.config import settings

    monkeypatch.setattr(settings, "agent_review_enabled", True)
    with db.connect() as conn:
        agent_review_schema.create_tables(conn)
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at, started_at) VALUES ('old_run', ?, 'completed', ?, ?, ?)",
            (paper, NOW, NOW, NOW),
        )
        conn.execute(
            "INSERT INTO agent_review_run (run_id, submittal_document_id, paper_kind, kind_source, usd, started_at) VALUES ('old_run', ?, 'datasheet', 'test', ?, ?)",
            (paper, usd, NOW),
        )


def test_the_plan_shows_the_last_general_runs_whole_cost_not_the_earlier_engines_part(
    real_roles, monkeypatch
):
    _earlier_engine_cost(real_roles["submittal"], 0.62, monkeypatch)
    _general_run(real_roles["submittal"], "gen_h_cost", 2.05)
    cost = _plan(real_roles)
    assert cost["last_review_usd"] == pytest.approx(2.05)
    assert "spend ledger" in cost["last_review_note"]


def test_a_general_review_whose_cost_was_not_read_says_so_never_a_number(
    real_roles, monkeypatch
):
    _earlier_engine_cost(real_roles["submittal"], 0.62, monkeypatch)
    _general_run(real_roles["submittal"], "gen_h_unread", None)
    cost = _plan(real_roles)
    assert cost["last_review_usd"] is None
    assert "not read" in cost["last_review_note"]


def test_a_paper_with_no_general_review_shows_no_last_cost_even_with_an_earlier_one(
    real_roles, monkeypatch
):
    _earlier_engine_cost(real_roles["submittal"], 0.62, monkeypatch)
    cost = _plan(real_roles)
    assert cost["last_review_usd"] is None and cost["last_review_note"] is None
