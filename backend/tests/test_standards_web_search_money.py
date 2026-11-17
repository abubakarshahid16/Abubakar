"""The online search's money holds are always closed, and the review's recorded cost includes its search fee (order 14, paid run
of 17 Nov 2026: two search holds were left open when the app was stopped on "completed" while the search was still running).
Fake senders and invented values only: no network, no real key, no paid call."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app import agent_review_jobs, claude_spend, crs_one, db
from app import standards_web_search as sws
from app import standards_web_search_money as money
from tests.test_b1_review_points import world_with_both
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture
from tests.test_k4_one_crs import scope_all
from tests.test_standards_web_search import (  # noqa: F401 - autouse fixtures
    ENV,
    EXPORTED,
    Sender,
    _invented_names_on_the_list,
    _on,
    cells,
    missing,
    open_reservations,
)


def _held_and_abandoned(
    run_id: str, usd: float, *, hours_ago: float, step: str = sws.STEP
) -> str:
    """A hold made under the run whose process ended before it settled or released it; its line dated `hours_ago`."""
    with claude_spend.for_run(run_id):
        held = claude_spend.reserve(
            step, usd, model=sws.MODEL, prompt_sha256="sh-digest"
        )
    _redate(held.id, hours_ago)
    return held.id


def _redate(reservation: str, hours_ago: float) -> None:
    path = claude_spend._ledger_path()
    when = (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat(
        timespec="seconds"
    )
    lines = [
        json.loads(x)
        for x in path.read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    for e in lines:
        if e.get("reservation") == reservation:
            e["at"] = when
    path.write_text("".join(json.dumps(e) + "\n" for e in lines), encoding="utf-8")


def _settlements(reservation: str) -> list[dict]:
    return [
        e
        for e in claude_spend._raw_lines()
        if e.get("settles") == reservation or e.get("releases") == reservation
    ]


# ------------------------------------------------------------------------------------------------ holds left open


def test_a_hold_left_by_an_ended_process_is_closed_once_at_its_worst_case_on_its_own_run():
    _doc, _rc, ai, _client = world_with_both()
    held = _held_and_abandoned("sh-run-ended", 0.236177, hours_ago=2)
    spent_before = claude_spend.spent(sws.STEP)
    missing(ai, "API 521")
    sws.search_run(ai, send=Sender(), env=ENV)
    closing = _settlements(held)
    assert len(closing) == 1
    line = closing[0]
    assert (
        line["finish_reason"] == "failed:" + money.STALE_REASON
        and line["estimated"] is True
    )
    assert line["cost_usd"] == pytest.approx(0.236177) and line["run"] == "sh-run-ended"
    assert open_reservations() == []
    # the caps see the same figure for it as while it was open: never released, never charged twice
    assert claude_spend.spent(sws.STEP) == pytest.approx(
        spent_before + money.run_cost(ai, sws.STEP)
    )
    sws.search_run(ai, send=Sender(), env=ENV)
    assert len(_settlements(held)) == 1


def test_a_hold_younger_than_any_request_can_run_is_left_to_its_own_caller():
    held = _held_and_abandoned("sh-run-in-flight", 0.2, hours_ago=0.1)
    assert money.close_stale(sws.STEP) == 0
    assert _settlements(held) == [] and [
        e["reservation"] for e in open_reservations()
    ] == [held]


def test_another_steps_hold_is_never_closed_by_the_search():
    held = _held_and_abandoned("sh-run-other", 0.3, hours_ago=5, step="agent_review")
    assert money.close_stale(sws.STEP) == 0
    assert _settlements(held) == []


def test_a_hold_whose_time_cannot_be_read_stays_open_and_counted():
    held = _held_and_abandoned("sh-run-undated", 0.4, hours_ago=5)
    path = claude_spend._ledger_path()
    lines = [
        json.loads(x)
        for x in path.read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    for e in lines:
        if e.get("reservation") == held:
            e["at"] = "not a time"
    path.write_text("".join(json.dumps(e) + "\n" for e in lines), encoding="utf-8")
    assert money.close_stale_holds(sws.STEP, older_than_s=0, reason="x") == []
    assert claude_spend.spent(sws.STEP) == pytest.approx(0.4)


def test_two_sweeps_close_a_hold_exactly_once():
    held = _held_and_abandoned("sh-run-twice", 0.25, hours_ago=3)
    first = money.close_stale_holds(sws.STEP, older_than_s=60, reason="process_ended")
    second = money.close_stale_holds(sws.STEP, older_than_s=60, reason="process_ended")
    assert [e["settles"] for e in first] == [held] and second == []
    assert claude_spend.spent(sws.STEP) == pytest.approx(0.25)


# ------------------------------------------------------------------------------------------------ the job's order


def test_the_search_runs_before_the_run_is_marked_completed(monkeypatch):
    _doc, _rc, ai, _client = world_with_both()
    seen = []

    def search(run_id, **kw):
        row = (
            db.connect()
            .execute("SELECT status FROM review_runs WHERE id = ?", (run_id,))
            .fetchone()
        )
        job = (
            db.connect()
            .execute("SELECT state FROM jobs WHERE id = 'job_sh1'")
            .fetchone()
        )
        seen.append((row["status"], job["state"], callable(kw.get("heartbeat"))))

    monkeypatch.setattr(sws, "search_run", search)
    monkeypatch.setattr(
        agent_review_jobs.crs_completeness, "record_after_run", lambda run_id: None
    )
    with db.connect() as conn:
        conn.execute("UPDATE review_runs SET status = 'running' WHERE id = ?", (ai,))
        conn.execute(
            "INSERT INTO jobs (id, review_run_id, document_id, state, started_at, updated_at) VALUES (?,?,?,?,?,?)",
            ("job_sh1", ai, "doc_sub", "running", "2026-11-17", "2026-11-17"),
        )
    result = {"partial": False, "stop_reason": None, "counts": {"lines": 3}}
    assert (
        agent_review_jobs._done(db.connect(), "job_sh1", ai, result, lambda: None)
        == "done"
    )
    assert seen == [("running", "running", True)]


def test_each_name_beats_the_jobs_heartbeat():
    _doc, _rc, ai, _client = world_with_both()
    missing(ai, "API 521", "ISO 9001")
    beats = []
    sws.search_run(ai, send=Sender(), env=ENV, heartbeat=lambda: beats.append(1))
    assert len(beats) == 2


# ------------------------------------------------------------------------------------------------ the review's cost


def _usd(run_id: str) -> tuple[float | None, dict]:
    row = (
        db.connect()
        .execute(
            "SELECT usd, counts_json FROM agent_review_run WHERE run_id = ?", (run_id,)
        )
        .fetchone()
    )
    return row["usd"], json.loads(row["counts_json"] or "{}")


def test_the_reviews_recorded_cost_includes_its_search_fee_once(monkeypatch):
    _doc, _rc, ai, _client = world_with_both()
    own, _ = _usd(ai)
    missing(ai, "API 521")
    send, real = Sender(), sws.search_run
    monkeypatch.setattr(
        sws, "search_run", lambda run_id, **kw: real(run_id, send=send, env=ENV, **kw)
    )
    sws.after_run(ai)
    search = money.run_cost(ai, sws.STEP)
    assert search > 0 and len(send.bodies) == 1
    usd, counts = _usd(ai)
    assert usd == pytest.approx(own + search) and counts[
        money.COST_KEY
    ] == pytest.approx(search)
    # the search fee itself (2 searches) is in it, not only the tokens
    assert search >= 2 * sws.USD_PER_SEARCH
    sws.after_run(ai)  # again: nothing new is searched and nothing is added twice
    assert _usd(ai)[0] == pytest.approx(own + search)


def test_a_run_that_searched_nothing_keeps_its_cost_and_its_counts():
    _doc, _rc, ai, _client = world_with_both()
    before = _usd(ai)
    assert money.add_to_run(ai, sws.STEP) is None
    assert _usd(ai) == before


def test_the_crs_says_the_search_is_included_only_when_it_is(monkeypatch):
    doc, _rc, ai, _client = world_with_both()
    missing(ai, "API 521")
    sws.search_run(ai, send=Sender(), env=ENV)
    how = cells(crs_one.build_team(doc, scope_all(), exported=EXPORTED))[
        crs_one.HOW_SHEET
    ]
    labels = [r[0] for r in how]
    assert (
        sws.COST_ROW in labels and money.COST_ROW_INCLUDED not in labels
    )  # recorded before: stated apart
    money.add_to_run(ai, sws.STEP)
    how = cells(crs_one.build_team(doc, scope_all(), exported=EXPORTED))[
        crs_one.HOW_SHEET
    ]
    labels = [r[0] for r in how]
    assert money.COST_ROW_INCLUDED in labels and sws.COST_ROW not in labels
