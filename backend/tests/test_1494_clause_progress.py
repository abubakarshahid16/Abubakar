"""#1494: "checking clause N of M" while the AI clause review works.

The provider is a FAKE (no socket, no model); all documents are invented. Each
test fails without the code it names."""

from __future__ import annotations

import time

import pytest

from app import db, job_progress, review_jobs
from app.config import settings
from tests.test_1477_clause_review import (  # noqa: F401 - fixtures
    REQ_ACTIONS,
    REQ_CHAIR,
    Fake,
    _go,
    _world,
    on,
)
from tests.test_1494_progress_detail import _job
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture

ANSWERS = {
    "HAZOP chair": {"answer": "no_evidence", "page": None, "quote": None},
    "recommend": {"answer": "no_evidence", "page": None, "quote": None},
}


@pytest.fixture(autouse=True)
def _clean():
    yield
    job_progress.CLAUSE_STARTED.clear()


def test_the_clause_review_reports_each_clause_before_it_works_on_it(on):
    _sub, run, scope = _world((REQ_CHAIR, REQ_ACTIONS))
    seen = []
    fake = Fake(ANSWERS)
    with job_progress.reporting_clauses(lambda n, t: seen.append((n, t, len(fake.packets)))):
        _go(run, scope, fake)
    # (clause, of, model calls made so far): reported BEFORE its own call
    assert seen == [(1, 2, 0), (2, 2, 1)]


def test_the_total_is_the_number_that_will_be_reviewed_not_the_cap_overflow(on, monkeypatch):
    monkeypatch.setattr(settings, "clause_review_max_requirements", 1)
    _sub, run, scope = _world((REQ_CHAIR, REQ_ACTIONS))
    seen = []
    with job_progress.reporting_clauses(lambda n, t: seen.append((n, t))):
        _go(run, scope, Fake(ANSWERS))
    assert seen == [(1, 1)]


def test_a_failing_progress_callback_changes_nothing_about_the_decision(on):
    _sub, run, scope = _world((REQ_CHAIR,))

    def boom(n, t):
        raise RuntimeError("progress down")

    with job_progress.reporting_clauses(boom):
        with_boom = _go(run, scope, Fake(ANSWERS))
    plain = _go(run, scope, Fake(ANSWERS))
    keys = ("verified", "no_evidence", "unverified", "unreadable", "failed")
    assert {k: with_boom[k] for k in keys} == {k: plain[k] for k in keys}


def test_no_callback_means_nothing_happens(on):
    _sub, run, scope = _world()
    assert _go(run, scope, Fake(ANSWERS))["ran"] is not False


def test_the_job_label_is_numbers_only_and_the_clause_clock_starts_at_clause_one():
    _job("comparing requirements with the datasheet")
    conn = db.connect()
    review_jobs._clause(conn, "j1", 1, 60)
    label = conn.execute("SELECT progress_label FROM jobs WHERE id='j1'").fetchone()[0]
    assert label == "checking clause 1 of 60"
    started = job_progress.CLAUSE_STARTED["j1"]
    review_jobs._clause(conn, "j1", 2, 60)
    assert job_progress.CLAUSE_STARTED["j1"] == started  # only clause 1 starts the clock


def test_clauses_done_are_finished_clauses_and_pages_are_null(monkeypatch):
    monkeypatch.setattr(settings, "review_progress_bar_enabled", True)
    run_id = _job("checking clause 12 of 60")
    d = review_jobs.job_for_run(run_id)["progress_detail"]
    assert (d["clauses_done"], d["clauses_total"]) == (11, 60)
    assert d["pages_done"] is None and d["pages_total"] is None
    assert d["clauses_elapsed_seconds"] is None  # no clause clock held: no estimate basis


def test_in_the_reading_step_clauses_are_null_never_zero(monkeypatch):
    monkeypatch.setattr(settings, "review_progress_bar_enabled", True)
    run_id = _job("reading the datasheet, page 7 of 69")
    d = review_jobs.job_for_run(run_id)["progress_detail"]
    assert d["clauses_done"] is None and d["clauses_total"] is None


def test_the_clause_clock_is_the_servers_seconds_since_clause_one(monkeypatch):
    monkeypatch.setattr(settings, "review_progress_bar_enabled", True)
    run_id = _job("checking clause 5 of 9")
    job_progress.CLAUSE_STARTED["j1"] = time.time() - 120
    d = review_jobs.job_for_run(run_id)["progress_detail"]
    assert 118 <= d["clauses_elapsed_seconds"] <= 125 and d["clauses_done"] == 4


def test_a_label_with_other_words_is_not_a_clause_label(monkeypatch):
    monkeypatch.setattr(settings, "review_progress_bar_enabled", True)
    run_id = _job("note: checking clause 5 of 9")
    assert review_jobs.job_for_run(run_id)["progress_detail"]["clauses_done"] is None
