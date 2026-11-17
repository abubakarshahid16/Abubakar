"""Review round 1 of PR #1897 (order 14): three of the four guards the fresh reviewer found untested (the fourth, the run meter's
worst case of a billed failure, is in `test_aim_review_round1.py`). Invented values only."""

from __future__ import annotations

from tests.test_p3_review_jobs import temp_storage  # noqa: F401 - fixture


def _paper(doc_id: str, text: str = "Invented field of the test item: 12 bar") -> None:
    """An invented paper as read in: its document, chunk and stored page (the general job reads stored text only)."""
    from app import db
    from tests.test_p3_review_jobs import _doc

    _doc(doc_id, "CONTRACTOR_SUBMITTAL", text)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES (?, 1, ?, 1, 0)",
            (doc_id, text),
        )


def test_follow_up_queues_no_old_ai_review_while_the_general_review_is_on(
    temp_storage,  # noqa: F811 - the fixture
    monkeypatch,
):
    """`review_engine_start.follow_up`: a rule check that finishes after the switch to the general review starts no old AI review."""
    from app import (
        agent_review_jobs,
        db,
        job_queue,
        review_engine,
        review_engine_start,
        review_jobs,
    )
    from app.config import settings
    from tests.test_b1_review_engine import open_facts
    from tests.test_p3_review_jobs import _doc, _user

    _doc("doc_fu_paper", "CONTRACTOR_SUBMITTAL", "invented paper text")
    _user("adm", ["doc_fu_paper"], admin=True)
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(
        review_engine, "read_facts", lambda *a, **k: (open_facts(), None)
    )

    def with_choice(conn, run_id):
        review_engine.record_in(conn, run_id, {"choice": "automatic", "text_leaves": True}, "adm", then_ai=True,
                                bar_claude=False, now=job_queue.now_iso())  # fmt: skip

    _run_id, job_id = review_jobs.enqueue("doc_fu_paper", allowed_document_ids=frozenset({"doc_fu_paper"}),
                                          requested_by="adm", in_transaction=with_choice)  # fmt: skip
    with db.connect() as conn:
        conn.execute("UPDATE jobs SET state = 'done' WHERE id = ?", (job_id,))
        conn.execute(
            "UPDATE review_runs SET status = 'completed' WHERE id = (SELECT review_run_id FROM jobs WHERE id = ?)",
            (job_id,),
        )
    queued = []
    monkeypatch.setattr(
        agent_review_jobs,
        "enqueue",
        lambda *a, **k: queued.append(1) or ("run_x", "job_x"),
    )
    monkeypatch.setattr(settings, "review_old_engine_enabled", False)
    assert review_engine_start.follow_up(job_id, job_queue.DONE) is None
    assert queued == []


def test_a_general_job_queued_before_the_way_back_is_not_claimed_after_it(
    temp_storage,  # noqa: F811 - the fixture
    monkeypatch,
):
    """`aim_review_jobs.claim_next`: with the old engine switched back on, a general job still queued is never claimed."""
    from app import aim_review_jobs, db, job_queue
    from app.config import settings
    from tests.test_p3_review_jobs import _doc

    _doc("doc_cl_paper", "CONTRACTOR_SUBMITTAL", "invented paper text")
    monkeypatch.setattr(settings, "review_old_engine_enabled", False)
    _run, job_id = aim_review_jobs.enqueue(
        "doc_cl_paper",
        allowed_document_ids=frozenset({"doc_cl_paper"}),
        requested_by=None,
    )
    monkeypatch.setattr(settings, "review_old_engine_enabled", True)
    assert aim_review_jobs.claim_next(job_queue.worker_id()) is None
    assert (
        db.connect()
        .execute("SELECT state FROM jobs WHERE id = ?", (job_id,))
        .fetchone()[0]
        == "queued"
    )


def test_a_failed_general_job_logs_the_fault_type_only(
    temp_storage,  # noqa: F811 - the fixture
    monkeypatch,
    caplog,
):
    """`aim_review_jobs.run`: the log line of a failed run names the fault's type, never its text (it may hold document words)."""
    import logging

    from app import aim_review, aim_review_jobs, job_queue
    from app.config import settings

    _paper("doc_lg_paper")
    monkeypatch.setattr(settings, "review_old_engine_enabled", False)
    _run, job_id = aim_review_jobs.enqueue(
        "doc_lg_paper",
        allowed_document_ids=frozenset({"doc_lg_paper"}),
        requested_by=None,
    )

    def boom(*a, **k):
        raise RuntimeError("invented words of a paper")

    monkeypatch.setattr(aim_review, "run", boom)
    monkeypatch.setattr(
        aim_review_jobs.review_jobs,
        "_scope_of",
        lambda user: frozenset({"doc_lg_paper"}),
    )
    worker = job_queue.worker_id()
    assert aim_review_jobs.claim_next(worker) == job_id
    with caplog.at_level(logging.DEBUG):
        assert aim_review_jobs.run(job_id, worker) == job_queue.POISONED
    mine = [
        r.getMessage() for r in caplog.records if r.name == "app.aim_review_jobs"
    ]  # this job's own log line
    assert mine and all("RuntimeError" in m for m in mine)
    assert not [m for m in mine if "invented words of a paper" in m]


def test_a_general_run_makes_no_old_field_reader_call_when_the_pages_hold_text(
    temp_storage,  # noqa: F811 - the fixture
    monkeypatch,
):
    """Rehearsal, 18 Nov: the general job reads the stored pages only; the older datasheet field reader (and its model calls) is
    never run for it. The method still gets the run (here a recorder)."""
    from app import aim_review, aim_review_jobs, datasheets, job_queue, submittal_review
    from app.config import settings
    from tests.test_aim_button_start import _Recorder

    _paper("doc_rd_paper")
    monkeypatch.setattr(settings, "review_old_engine_enabled", False)
    called = []
    monkeypatch.setattr(
        submittal_review,
        "ensure_facts_extracted",
        lambda *a, **k: called.append("facts"),
    )
    monkeypatch.setattr(
        datasheets, "extract_facts", lambda *a, **k: called.append("extract")
    )
    rec = _Recorder()
    monkeypatch.setattr(aim_review, "run", rec)
    monkeypatch.setattr(
        aim_review_jobs.review_jobs,
        "_scope_of",
        lambda user: frozenset({"doc_rd_paper"}),
    )
    _run, job_id = aim_review_jobs.enqueue(
        "doc_rd_paper",
        allowed_document_ids=frozenset({"doc_rd_paper"}),
        requested_by=None,
    )
    worker = job_queue.worker_id()
    assert aim_review_jobs.claim_next(worker) == job_id
    assert aim_review_jobs.run(job_id, worker) == job_queue.DONE
    assert called == [] and len(rec.calls) == 1


def test_a_paper_with_no_stored_text_stops_with_words_and_asks_nothing(
    temp_storage,  # noqa: F811 - the fixture
    monkeypatch,
):
    from app import aim_review, aim_review_jobs, aim_review_store, db, job_queue
    from app.config import settings
    from tests.test_aim_button_start import _Recorder
    from tests.test_p3_review_jobs import _doc

    _doc("doc_nt_paper", "CONTRACTOR_SUBMITTAL", "x")
    with db.connect() as conn:
        conn.execute("UPDATE pages SET text = '' WHERE document_id = 'doc_nt_paper'")
    monkeypatch.setattr(settings, "review_old_engine_enabled", False)
    rec = _Recorder()
    monkeypatch.setattr(aim_review, "run", rec)
    monkeypatch.setattr(
        aim_review_jobs.review_jobs,
        "_scope_of",
        lambda user: frozenset({"doc_nt_paper"}),
    )
    run_id, job_id = aim_review_jobs.enqueue(
        "doc_nt_paper",
        allowed_document_ids=frozenset({"doc_nt_paper"}),
        requested_by=None,
    )
    worker = job_queue.worker_id()
    assert aim_review_jobs.claim_next(worker) == job_id
    assert aim_review_jobs.run(job_id, worker) == job_queue.DONE
    stored = aim_review_store.run(db.connect(), run_id)
    assert stored["status"] == "stopped" and stored["stop_reason"] and rec.calls == []
    assert aim_review_store.lines(db.connect(), run_id) == []
