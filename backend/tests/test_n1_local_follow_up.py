# ruff: noqa: F811
"""The follow-up of a plan that puts the AI review on the LOCAL model starts a run barred from Claude (owner orders, 12 Nov 2026)."""

from __future__ import annotations

from app import db, review_engine, review_engine_start
from tests.test_p3_review_jobs import (  # noqa: F401 - fixtures
    _enqueue,
    temp_storage,
    world,
)


def test_the_follow_up_of_a_local_plan_starts_a_barred_local_ai_review(world, monkeypatch):
    run_id, _job = _enqueue(world)
    review_engine.record(
        db.connect(), run_id, {"choice": "local", "project_document_ids": [], "fresh": False}, "adm",
        then_ai=True, bar_claude=True, now="2026-11-12T00:00:00Z",
    )  # fmt: skip
    job_id = db.connect().execute("SELECT id FROM jobs WHERE review_run_id = ?", (run_id,)).fetchone()["id"]
    ai_plan = {"choice": "local", "refused": None, "kind": "datasheet",
               "parts": [{"name": "rule_check", "engine": "local", "why": "x"},
                         {"name": "ai_review", "engine": "local", "why": "y"}]}  # fmt: skip
    queued = []
    monkeypatch.setattr(review_engine, "plan_for", lambda *a, **k: ai_plan)
    monkeypatch.setattr(review_engine_start.agent_review_gate, "enabled", lambda: True)
    monkeypatch.setattr(
        review_engine_start.agent_review_jobs, "enqueue",
        lambda doc, **k: queued.append((doc, k)) or ("ai-run", "ai-job"),
    )  # fmt: skip
    assert review_engine_start.follow_up(job_id, "done") == "ai-run"
    conn = db.connect()
    queued[0][1]["in_transaction"](conn, "ai-run")
    got = review_engine.stored(conn, "ai-run")
    assert got["bar_claude"] == 1 and got["plan"]["parts"][1]["engine"] == "local"  # barred from Claude for its whole length
    ai_plan["parts"][1]["engine"] = "claude"  # a Claude follow-up is NOT barred (as before)
    with db.connect() as c:
        c.execute("UPDATE review_runs SET status='complete' WHERE id = ?", (run_id,))
    run_b, job_b = _enqueue(world)
    review_engine.record(db.connect(), run_b, {"choice": "automatic"}, "adm", then_ai=True, bar_claude=False, now="2026-11-12T00:00:00Z")  # fmt: skip
    job_b = db.connect().execute("SELECT id FROM jobs WHERE review_run_id = ?", (run_b,)).fetchone()["id"]
    assert review_engine_start.follow_up(job_b, "done") == "ai-run"
    queued[1][1]["in_transaction"](conn, "ai-run-2")
    assert review_engine.stored(conn, "ai-run-2")["bar_claude"] == 0
