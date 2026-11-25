"""Review of 7a, M3: with two lanes, a review never starts while the upload lane is still reading its OWN paper (main's one
thread read every upload first). The job stays queued, the next job is claimed instead, and it runs once its paper is read.
Invented ids only; no model, no network."""

from __future__ import annotations

import pytest

from app import (
    agent_review_jobs,
    aim_review_jobs,
    db,
    job_queue,
    review_jobs,
    states,
    submittal_review,
)
from app.config import settings
from tests.test_worker_health import temp_storage  # noqa: F401 - fixture


def _paper(
    conn,
    doc_id: str,
    status: str,
    chunks: int = 3,
    embedded: int = 3,
    indexed: str | None = "x",
) -> None:
    conn.execute(
        "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path, status, uploaded_at, chunk_count,"
        " embedded_count, indexed_at) VALUES (?, ?, ?, 1, ?, ?, '2026-11-25T00:00:00Z', ?, ?, ?)",
        (
            doc_id,
            f"{doc_id}.pdf",
            doc_id * 4,
            f"/nowhere/{doc_id}",
            status,
            chunks,
            embedded,
            indexed,
        ),
    )


def _job(conn, job_id: str, doc_id: str, stage: str, started: str) -> None:
    conn.execute(
        "INSERT INTO jobs (id, document_id, stage, state, started_at, updated_at, priority, review_run_id)"
        " VALUES (?, ?, ?, 'queued', ?, ?, ?, ?)",
        (
            job_id,
            doc_id,
            stage,
            started,
            started,
            job_queue.PRIORITY_INTERACTIVE,
            f"run_{job_id}",
        ),
    )


@pytest.fixture
def conn(temp_storage, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "review_old_engine_enabled", False)
    submittal_review.ensure_schema()
    return db.connect()


@pytest.mark.parametrize(
    "being_read",
    [
        {"status": states.QUEUED},
        {"status": states.EXTRACTING},
        {"status": states.CHUNKING},
        {"status": states.INDEXING_KEYWORD},
        {
            "status": states.PARTIALLY_SEARCHABLE,
            "embedded": 1,
        },  # vectors still outstanding
        {
            "status": states.PARTIALLY_SEARCHABLE,
            "indexed": None,
        },  # never stamped finished
    ],
)
def test_a_review_of_a_paper_still_being_read_waits_and_the_next_one_runs(
    conn, being_read
):
    with conn:
        _paper(
            conn,
            "doc_reading",
            being_read["status"],
            embedded=being_read.get("embedded", 3),
            indexed=being_read.get("indexed", "x"),
        )
        _paper(conn, "doc_read", states.READY)
        _job(
            conn,
            "job_x_first",
            "doc_reading",
            aim_review_jobs.STAGE,
            "2026-11-25T00:00:01Z",
        )  # older: would go first
        _job(
            conn,
            "job_x_second",
            "doc_read",
            aim_review_jobs.STAGE,
            "2026-11-25T00:00:02Z",
        )
    assert aim_review_jobs.claim_next("w-test") == "job_x_second"
    assert (
        aim_review_jobs.claim_next("w-test") is None
    )  # the first stays queued: its paper is being read
    state = conn.execute("SELECT state FROM jobs WHERE id = 'job_x_first'").fetchone()[
        0
    ]
    assert state == "queued"
    # the second review ends (one review runs at a time); the first paper is read
    with conn:
        conn.execute("UPDATE jobs SET state = 'done' WHERE id = 'job_x_second'")
        conn.execute(
            "UPDATE documents SET status = ?, embedded_count = 3, indexed_at = 'x' WHERE id = 'doc_reading'",
            (states.READY,),
        )
    assert aim_review_jobs.claim_next("w-test") == "job_x_first"  # read: it runs


@pytest.mark.parametrize("status", sorted(states.TERMINAL_STATES))
def test_a_paper_in_any_finished_state_is_claimed(conn, status):
    with conn:
        _paper(conn, "doc_done", status)
        _job(
            conn,
            "job_x_done",
            "doc_done",
            aim_review_jobs.STAGE,
            "2026-11-25T00:00:01Z",
        )
    assert aim_review_jobs.claim_next("w-test") == "job_x_done"


def test_every_review_stage_waits_for_its_paper(conn, monkeypatch):
    monkeypatch.setattr(agent_review_jobs.agent_review_gate, "enabled", lambda: True)
    with conn:
        _paper(conn, "doc_reading", states.EXTRACTING)
        _job(conn, "job_rule", "doc_reading", review_jobs.STAGE, "2026-11-25T00:00:01Z")
        _job(
            conn,
            "job_agent",
            "doc_reading",
            agent_review_jobs.STAGE,
            "2026-11-25T00:00:02Z",
        )
    assert review_jobs.claim_next("w-test") is None
    assert agent_review_jobs.claim_next("w-test") is None
