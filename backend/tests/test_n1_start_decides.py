# ruff: noqa: F811
"""R66 on #1827: THE START DECIDES. A start whose screen said nothing leaves can never send anything for its whole life: its follow-up
AI review is planned as Local only (it stays local or does not start), never from the stored choice. A start that DID show a list still
sends exactly that list. And "N rule books not sent" is never said of a run that sent nothing."""

from __future__ import annotations

import json

import pytest

from app import (
    claude_spend,
    db,
    reader_transport,
    review_engine,
    review_engine_start,
    review_shown,
)
from tests.test_p3_review_jobs import (  # noqa: F401 - fixtures
    _enqueue,
    temp_storage,
    world,
)

PLAN = {
    "refused": None,
    "kind": "datasheet",
    "parts": [{"name": "rule_check", "engine": "local", "why": "x"}, {"name": "ai_review", "engine": "claude", "why": "y"}],
}  # fmt: skip


def _by_choice(local_on: bool):
    """plan_for as the world changes: Automatic now resolves to Claude (a cap, the lane or an approval changed since the start); Local only
    resolves to the local model when the local reviewer is on, else the AI review does not run."""

    def plan_for(_conn, _doc, _scope, choice, **_k):
        if choice == "local":
            engine = "local" if local_on else "not_run"
            return {
                **PLAN,
                "choice": "local",
                "parts": [
                    PLAN["parts"][0],
                    {
                        "name": "ai_review",
                        "engine": engine,
                        "why": "the local reviewer is off",
                    },
                ],
            }
        return {**PLAN, "choice": choice}

    return plan_for


def _started(world, *, text_leaves: bool, shown=None):
    run_id, _job = _enqueue(world)
    conn = db.connect()
    review_engine.record(
        conn, run_id, {"choice": "automatic", "text_leaves": text_leaves, "project_document_ids": [], "fresh": False}, "adm",
        then_ai=True, bar_claude=not text_leaves, now="2026-11-15T00:00:00Z",
    )  # fmt: skip
    if shown is not None:
        with conn:
            review_shown.record_in(conn, run_id, shown, "t")
    job_id = conn.execute(
        "SELECT id FROM jobs WHERE review_run_id = ?", (run_id,)
    ).fetchone()["id"]
    return run_id, job_id


def _wire(monkeypatch, local_on):
    queued = []
    monkeypatch.setattr(review_engine, "plan_for", _by_choice(local_on))
    monkeypatch.setattr(review_engine_start.agent_review_gate, "enabled", lambda: True)
    monkeypatch.setattr(
        review_engine_start.agent_review_jobs,
        "enqueue",
        lambda doc, **k: queued.append(k) or ("ai-run", "ai-job"),
    )

    def never(*_a, **_k):
        raise AssertionError("a request reached the Claude transport")

    monkeypatch.setattr(reader_transport, "transport", never)
    return queued


def test_an_automatic_start_that_fell_back_to_local_stays_local_when_the_world_changes_to_claude(
    world, monkeypatch
):
    run_id, job_id = _started(world, text_leaves=False)
    queued = _wire(monkeypatch, local_on=True)
    assert review_engine_start.follow_up(job_id, "done") == "ai-run"
    conn = db.connect()
    queued[0]["in_transaction"](conn, "ai-run")
    got = review_engine.stored(conn, "ai-run")
    assert (
        got["plan"]["parts"][1]["engine"] == "local" and got["bar_claude"] == 1
    )  # the engine was not re-resolved upward; the bar is kept
    assert (
        review_shown.shown_ids(conn, "ai-run") is None and claude_spend.entries() == []
    )  # nothing was shown, nothing was sent


def test_with_the_local_reviewer_off_that_follow_up_does_not_start_and_says_why_in_plain_words(
    world, monkeypatch
):
    run_id, job_id = _started(world, text_leaves=False)
    queued = _wire(monkeypatch, local_on=False)
    assert review_engine_start.follow_up(job_id, "done") is None and queued == []
    said = review_engine.stored(db.connect(), run_id)["followed_by"]
    assert (
        said
        == "AI review not started: this review was started with nothing leaving this computer; start again and choose Claude to send it"
        " (the local AI reviewer is switched off on this install)"
    )
    assert claude_spend.entries() == []


def test_a_stored_plan_with_no_text_leaves_key_is_read_as_nothing_leaves(
    world, monkeypatch
):
    run_id, _j = _enqueue(world)
    review_engine.record(
        db.connect(),
        run_id,
        {"choice": "automatic"},
        "adm",
        then_ai=True,
        bar_claude=False,
        now="2026-11-15T00:00:00Z",
    )
    job_id = (
        db.connect()
        .execute("SELECT id FROM jobs WHERE review_run_id = ?", (run_id,))
        .fetchone()["id"]
    )
    queued = _wire(monkeypatch, local_on=True)
    assert review_engine_start.follow_up(job_id, "done") == "ai-run"
    queued[0]["in_transaction"](db.connect(), "ai-run")
    assert (
        review_engine.stored(db.connect(), "ai-run")["plan"]["parts"][1]["engine"]
        == "local"
    )  # fail closed: never Claude from a plan that does not say it sends


def test_a_start_that_did_show_a_list_still_sends_exactly_that_list(world, monkeypatch):
    run_id, job_id = _started(world, text_leaves=True, shown=[world["std"]])
    queued = _wire(monkeypatch, local_on=True)
    assert review_engine_start.follow_up(job_id, "done") == "ai-run"
    conn = db.connect()
    queued[0]["in_transaction"](conn, "ai-run")
    got = review_engine.stored(conn, "ai-run")
    assert (
        got["plan"]["parts"][1]["engine"] == "claude" and got["bar_claude"] == 0
    )  # a start that sends may follow up on Claude
    assert review_shown.shown_ids(conn, "ai-run") == frozenset(
        {world["std"]}
    )  # exactly the list the screen showed


def test_no_not_sent_note_is_made_of_a_run_that_sent_nothing_even_when_an_old_start_stored_an_empty_list(
    world,
):
    run_id, _job = _started(
        world, text_leaves=False, shown=[]
    )  # the two old live runs: nothing leaves, list []
    conn = db.connect()
    with conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS agent_review_rule (run_id TEXT, standard_document_id TEXT, asked INTEGER, left_out_reason TEXT)"
        )
        conn.execute(
            "INSERT INTO agent_review_rule VALUES (?, ?, 1, NULL)",
            (run_id, world["std"]),
        )
    assert review_shown.sends_nothing(conn, run_id) is True
    assert (
        review_shown.held_applied(conn, run_id) == []
        and review_shown.held_rule_books(conn, run_id) == []
    )
    run_b, _j = _started_claude_with_empty_list(world)
    assert review_shown.sends_nothing(conn, run_b) is False
    assert review_shown.held_applied(conn, run_b, extra=[world["std"]]) == [
        world["std"]
    ]  # a run that sends keeps its note


def _started_claude_with_empty_list(world):
    with db.connect() as c:
        c.execute("UPDATE review_runs SET status = 'completed'")
    return _started(world, text_leaves=True, shown=[])


def test_with_the_local_reviewer_on_the_sentence_carries_the_plans_own_reason(
    world, monkeypatch
):
    from app.config import settings

    monkeypatch.setattr(settings, "agent_review_local_engine_enabled", True)
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    run_id, job_id = _started(world, text_leaves=False)
    _wire(
        monkeypatch, local_on=False
    )  # the plan itself says the AI review does not run: "the local reviewer is off" is its words
    assert review_engine_start.follow_up(job_id, "done") is None
    said = review_engine.stored(db.connect(), run_id)["followed_by"]
    assert (
        said.endswith("(the local reviewer is off)")
        and "switched off on this install" not in said
    )
