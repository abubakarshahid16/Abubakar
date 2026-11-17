"""Order 14, piece B: the ONE Review button with the general review on: the plan, the start, the job, the worker, the way back.

Invented papers only (the p3 world: an invented rule book and an invented pump paper). The method itself (`aim_review.run`) is
replaced by a recorder in these tests: they check what the BUTTON hands it and what the job stores, never what the method judges
(piece A's tests do that). Nothing here opens a socket: the Claude lane is "open" only in the stored facts.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import (
    aim_review,
    aim_review_gate,
    aim_review_jobs,
    aim_review_store,
    claude_approved,
    db,
    job_queue,
    review_engine,
    review_engine_start,
    review_shown,
)
from app.config import settings
from app.main import app
from tests.test_b1_review_engine import open_facts
from tests.test_p3_review_jobs import temp_storage, world  # noqa: F401 - fixtures

OTHER_BOOK = "doc_inv_other_book"


@pytest.fixture
def general(world, monkeypatch):  # noqa: F811
    """The general review on, every door open for an invented datasheet; the method's book list is the world's rule book."""
    monkeypatch.setattr(settings, "review_old_engine_enabled", False)
    monkeypatch.setattr(settings, "claude_approved_list_enforced", False)
    monkeypatch.setattr(settings, "claude_auto_approve_reviews_enabled", False)
    monkeypatch.setattr(settings, "claude_spend_log", settings.data_dir / "spend.jsonl")
    monkeypatch.setattr(
        review_engine, "read_facts", lambda *a, **k: (open_facts(), None)
    )
    with (
        db.connect() as conn
    ):  # a read-in paper has its stored page (the general job reads stored text only)
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES (?, 1, ?, 1, 0)",
            (world["sub"], "Invented pump paper page 1: noise level 95 dB(A)"),
        )
    books = [{"id": world["std"], "why": aim_review.WHY_CITED}]
    monkeypatch.setattr(
        aim_review,
        "candidates",
        lambda conn, paper, allowed, store, earlier=frozenset(): aim_review.Candidates(
            kind="datasheet",
            equipment_type=None,
            kind_source="test",
            books=[b for b in books if b["id"] in allowed],
            not_held=[
                {"name": "Invented Public Standard 1", "why": aim_review.WHY_CITED}
            ],
            unreadable=0,
            checklist_key="datasheet__inv",
            checklist_saved=False,
        ),
    )
    return world


def _jobs() -> int:
    return db.connect().execute("SELECT COUNT(*) FROM jobs").fetchone()[0]


def _plan(w, engine="automatic"):
    r = TestClient(app).get(
        "/api/reviews/plan",
        params={"submittal_document_id": w["sub"], "engine": engine},
        headers=w["admin"],
    )
    assert r.status_code == 200, r.text
    return r.json()


def _start(w, engine="automatic", shown=None):
    body = {"submittal_document_id": w["sub"], "engine": engine}
    if shown is not None:
        body["shown_document_ids"] = shown
    return TestClient(app).post("/api/reviews/start", json=body, headers=w["admin"])


def _ledger_lines() -> int:
    path = settings.claude_spend_log
    return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0


# ---------------------------------------------------------------- the plan


def test_the_plan_says_general_and_lists_the_paper_and_the_chosen_books(general):
    plan = _plan(general)
    assert (
        plan["method"] == "general" and plan["refused"] is None and plan["text_leaves"]
    )
    leaving = {d["id"]: d for d in plan["documents"]["leaving"]}
    assert set(leaving) == {general["sub"], general["std"]}
    assert leaving[general["std"]]["why"] == aim_review.WHY_CITED
    assert {"name": "Invented Public Standard 1", "kind": "rule book", "why": aim_review.WHY_CITED,
            "reason": "not held in the library"} in plan["documents"]["not_sent"]  # fmt: skip
    assert plan["cost"]["at_most_usd"] == aim_review_gate.max_usd() == 5.0
    assert "at most USD 5.00 for this review" in plan["cost"]["basis"]
    assert aim_review_gate.AI_MARK in plan["sentence"]


def test_with_the_old_engine_on_the_plan_says_earlier(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(
        review_engine, "read_facts", lambda *a, **k: (open_facts(), None)
    )
    plan = _plan(world)
    assert plan["method"] == "earlier"
    assert [p["engine"] for p in plan["parts"]] != ["not_run", "claude"]


def test_a_book_the_caller_may_not_read_is_counted_never_named(general, monkeypatch):
    monkeypatch.setattr(
        aim_review,
        "candidates",
        lambda *a, **k: aim_review.Candidates(
            "datasheet", None, "test", [], [], 2, None, False
        ),
    )
    docs = _plan(general)["documents"]
    assert docs["not_readable"] == 2
    assert [d["id"] for d in docs["leaving"]] == [general["sub"]]


def test_a_blocked_book_on_the_list_is_not_sent_even_on_an_explicit_claude(
    general, monkeypatch
):
    sha = "ab" * 32
    with db.connect() as conn:
        conn.execute(
            "UPDATE documents SET sha256 = ? WHERE id = ?", (sha, general["std"])
        )
    claude_approved.block_file_path().write_text(
        json.dumps({"blocked_sha256": [sha]}), encoding="utf-8"
    )
    plan = _plan(general, "claude")
    assert general["std"] not in {d["id"] for d in plan["documents"]["leaving"]}
    assert any(
        d.get("id") == general["std"] and d["reason"] == "blocked by the owner"
        for d in plan["documents"]["not_sent"]
    )


# ---------------------------------------------------------------- the start


def test_local_only_is_refused_queues_nothing_and_writes_no_ledger_line(general):
    plan = _plan(general, "local")
    assert (
        plan["refused_code"] == review_engine.GENERAL_NOT_ON_LOCAL
        and not plan["text_leaves"]
    )
    assert plan["refused"] == aim_review_gate.LOCAL_NOT_AVAILABLE
    before, lines = _jobs(), _ledger_lines()
    r = _start(general, "local", shown=[])
    assert r.status_code == 409 and aim_review_gate.LOCAL_NOT_AVAILABLE in r.text
    assert r.json()["detail"]["code"] == review_engine.GENERAL_NOT_ON_LOCAL
    assert _jobs() == before and _ledger_lines() == lines


def test_a_start_without_the_shown_list_is_refused(general):
    before = _jobs()
    r = _start(general)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "LIST_NOT_SHOWN"
    assert _jobs() == before


def test_automatic_queues_one_general_job_with_its_list_and_no_old_job(general):
    shown = [general["sub"], general["std"]]
    r = _start(general, shown=shown)
    assert r.status_code == 200, r.text
    conn = db.connect()
    jobs = [dict(j) for j in conn.execute("SELECT stage, review_run_id FROM jobs")]
    assert [j["stage"] for j in jobs] == [aim_review_jobs.STAGE]
    run_id = jobs[0]["review_run_id"]
    assert aim_review_store.is_general(conn, run_id)
    assert review_shown.shown_ids(conn, run_id) == frozenset(shown)
    assert review_shown.consent_of(conn, run_id) is None  # Automatic records no consent
    assert not review_engine.stored(conn, run_id)["then_ai"]  # no old AI review follows


def test_automatic_never_sends_a_contract(general, monkeypatch):
    monkeypatch.setattr(
        review_engine,
        "read_facts",
        lambda *a, **k: (open_facts(kind="contract", is_contract=True), None),
    )
    before = _jobs()
    r = _start(general, shown=[general["sub"]])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NEEDS_YES"
    assert _jobs() == before


def test_an_explicit_claude_on_a_contract_writes_the_consent_record(
    general, monkeypatch
):
    monkeypatch.setattr(
        review_engine,
        "read_facts",
        lambda *a, **k: (open_facts(kind="contract", is_contract=True), None),
    )
    r = _start(general, "claude", shown=[general["sub"], general["std"]])
    assert r.status_code == 200, r.text
    conn = db.connect()
    run_id = conn.execute("SELECT review_run_id FROM jobs").fetchone()[0]
    consent = review_shown.consent_of(conn, run_id)
    assert consent is not None and set(consent["documents"]) == {
        general["sub"],
        general["std"],
    }


def test_the_old_one_click_starts_are_refused_while_the_general_review_is_on(
    general, monkeypatch
):
    monkeypatch.setattr(
        settings, "agent_review_enabled", True
    )  # the AI run route exists only with its switch on
    monkeypatch.setattr(
        review_engine, "read_facts", lambda *a, **k: (open_facts(lane_open=False), None)
    )  # even with nothing able to leave: only the Review button starts a review now
    before = _jobs()
    for route in ("/api/reviews/run", "/api/reviews/agent-run"):
        r = TestClient(app).post(
            route,
            json={"submittal_document_id": general["sub"]},
            headers=general["admin"],
        )
        assert (
            r.status_code == 409 and review_engine_start.LEGACY_START_WORDS in r.text
        ), route
    assert _jobs() == before


def test_with_the_old_engine_on_nothing_of_the_general_review_is_queued_or_claimed(
    world,  # noqa: F811 - the fixture
    monkeypatch,
):
    monkeypatch.setattr(
        review_engine, "read_facts", lambda *a, **k: (open_facts(lane_open=False), None)
    )
    with pytest.raises(aim_review_jobs.GeneralReviewOff):
        aim_review_jobs.enqueue(
            world["sub"], allowed_document_ids=world["scope"], requested_by="adm"
        )
    assert aim_review_jobs.claim_next(job_queue.worker_id()) is None
    assert aim_review_jobs.recover_stale() == 0


# ---------------------------------------------------------------- the job


class _Recorder:
    """Stands in for `aim_review.run`: records what the job hands the method and returns a fixed result."""

    def __init__(
        self, raises: Exception | None = None, cancel_job: str | None = None
    ) -> None:
        self.calls: list[dict] = []
        self.raises, self.cancel_job = raises, cancel_job

    def __call__(self, conn, **kw):
        self.calls.append(kw)
        if self.cancel_job:
            with db.connect() as c:
                c.execute(
                    "UPDATE jobs SET cancel_requested = 1 WHERE id = ?",
                    (self.cancel_job,),
                )
        if self.raises:
            raise self.raises
        return aim_review.Result(
            status="done", stop_reason="", identity={"kind": "datasheet"}, checklist_key="datasheet__inv",
            checklist_sha256="1" * 64, checklist_reused=True, books=sorted(kw["allowed_books"]), not_held=[],
            unlisted_books=[], unlisted_count=0,
            lines=[{"item_id": "C01", "label": "Question", "field": "invented field", "page": 1, "quote": "", "comment": "x"},
                   {"item_id": "C02", "label": "Met", "field": "invented field 2", "page": 1, "quote": "", "comment": ""}],
            calls=[], usd=0.0, seconds=0.1,
        )  # fmt: skip


def _queued(w, shown):
    r = _start(w, shown=shown)
    assert r.status_code == 200, r.text
    conn = db.connect()
    row = conn.execute(
        "SELECT id, review_run_id FROM jobs WHERE stage = ?", (aim_review_jobs.STAGE,)
    ).fetchone()
    return row["id"], row["review_run_id"]


def _run_claimed(job_id):
    worker = job_queue.worker_id()
    assert aim_review_jobs.claim_next(worker) == job_id
    return aim_review_jobs.run(job_id, worker)


def test_the_method_gets_only_the_shown_books_inside_the_scope_never_the_paper(
    general, monkeypatch
):
    rec = _Recorder()
    monkeypatch.setattr(aim_review, "run", rec)
    job_id, run_id = _queued(
        general, [general["sub"], general["std"], OTHER_BOOK]
    )  # OTHER_BOOK: outside the scope
    assert _run_claimed(job_id) == job_queue.DONE
    (call,) = rec.calls
    assert call["allowed_books"] == frozenset({general["std"]})
    assert call["run_id"] == run_id and call["paper_id"] == general["sub"]
    assert call["max_usd"] == aim_review_gate.max_usd()
    conn = db.connect()
    assert aim_review_store.run(conn, run_id)["status"] == "done"
    assert len(aim_review_store.lines(conn, run_id)) == 2
    assert (
        conn.execute(
            "SELECT status FROM review_runs WHERE id = ?", (run_id,)
        ).fetchone()[0]
        == "completed"
    )


def test_a_book_not_on_the_shown_list_never_reaches_the_method(general, monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(aim_review, "run", rec)
    job_id, _run = _queued(
        general, [general["sub"]]
    )  # the book was not on the list the screen showed
    _run_claimed(job_id)
    assert rec.calls[0]["allowed_books"] == frozenset()


def test_a_run_without_a_stored_list_gets_no_book(general):
    conn = db.connect()
    assert (
        aim_review_jobs.allowed_books(
            conn, "no-such-run", general["sub"], general["scope"]
        )
        == frozenset()
    )


def test_a_cancelled_run_leaves_a_truthful_row_and_keeps_what_was_judged(
    general, monkeypatch
):
    job_id, run_id = _queued(general, [general["sub"], general["std"]])
    monkeypatch.setattr(aim_review, "run", _Recorder(cancel_job=job_id))
    assert _run_claimed(job_id) == job_queue.CANCELLED
    conn = db.connect()
    assert (
        conn.execute(
            "SELECT status FROM review_runs WHERE id = ?", (run_id,)
        ).fetchone()[0]
        == "cancelled"
    )
    stored = aim_review_store.run(conn, run_id)
    assert (
        stored["status"] == "cancelled"
        and stored["stop_reason"] == aim_review_jobs.CANCELLED_WORDS
    )
    assert len(aim_review_store.lines(conn, run_id)) == 2


def test_a_failed_run_is_not_retried_and_says_so(general, monkeypatch):
    job_id, run_id = _queued(general, [general["sub"], general["std"]])
    rec = _Recorder(raises=RuntimeError("invented fault"))
    monkeypatch.setattr(aim_review, "run", rec)
    assert _run_claimed(job_id) == job_queue.POISONED
    conn = db.connect()
    assert (
        conn.execute("SELECT state FROM jobs WHERE id = ?", (job_id,)).fetchone()[0]
        == job_queue.POISONED
    )
    assert (
        conn.execute(
            "SELECT status FROM review_runs WHERE id = ?", (run_id,)
        ).fetchone()[0]
        == "failed"
    )
    stored = aim_review_store.run(conn, run_id)
    assert (
        stored["status"] == "failed"
        and stored["stop_reason"] == aim_review_jobs.FAILED_WORDS
    )
    assert "invented fault" not in json.dumps(stored)
    assert aim_review_jobs.claim_next(job_queue.worker_id()) is None  # nothing to retry
    assert len(rec.calls) == 1


def test_one_review_of_a_paper_at_a_time_across_the_stages(general):
    assert _start(general, shown=[general["sub"]]).status_code == 200
    r = _start(general, shown=[general["sub"]])
    assert r.status_code == 409 and "already queued or running" in r.text


def test_the_worker_claims_the_general_stage(general, monkeypatch):
    from app import ingest

    rec = _Recorder()
    monkeypatch.setattr(aim_review, "run", rec)
    job_id, _run = _queued(general, [general["sub"], general["std"]])
    worker = ingest.IngestionWorker()
    assert worker._drain_review_jobs() is True
    assert len(rec.calls) == 1
    assert (
        db.connect()
        .execute("SELECT state FROM jobs WHERE id = ?", (job_id,))
        .fetchone()[0]
        == job_queue.DONE
    )
