# ruff: noqa: F811
"""N9: a review parked behind its paper's reading says why ("waiting: its paper is still being read"), never a bare "queued". Invented values."""

from __future__ import annotations

from app import aim_review_runs, aim_review_store, db, review_jobs, states
from tests.test_aim_sheet_rule import PAPER, RUN, world  # noqa: F401 - fixture
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture


def _queue_the_run(
    paper_status: str, embedded: int = 0, chunks: int = 0, indexed: bool = False
):
    with db.connect() as conn:
        conn.execute(
            f"UPDATE {aim_review_store.RUNS} SET status = 'queued' WHERE run_id = ?",
            (RUN,),
        )
        conn.execute(
            "UPDATE documents SET status = ?, embedded_count = ?, chunk_count = ?, indexed_at = ? WHERE id = ?",
            (
                paper_status,
                embedded,
                chunks,
                "2026-11-26T00:00:00Z" if indexed else None,
                PAPER,
            ),
        )


def _row():
    (row,) = aim_review_runs.entries(db.connect(), frozenset({PAPER}))
    return row


def test_a_queued_review_whose_paper_is_still_being_read_says_so(world):
    _queue_the_run(states.EXTRACTING)
    row = _row()
    assert (
        row["status"] == "queued"
        and row["waiting_reason"] == "waiting: its paper is still being read"
    )
    assert row["waiting_reason"] == review_jobs.WAITING_FOR_PAPER_WORDS


def test_a_paper_answerable_with_vectors_outstanding_is_still_being_read(world):
    _queue_the_run(states.PARTIALLY_SEARCHABLE, embedded=3, chunks=10, indexed=True)
    assert _row()["waiting_reason"] == review_jobs.WAITING_FOR_PAPER_WORDS


def test_a_queued_review_of_a_read_paper_is_not_parked_and_says_nothing(world):
    _queue_the_run(states.READY, embedded=10, chunks=10, indexed=True)
    assert _row()["waiting_reason"] is None


def test_a_review_that_is_running_or_ended_carries_no_waiting_reason(world):
    _queue_the_run(states.EXTRACTING)
    with db.connect() as conn:
        conn.execute(
            f"UPDATE {aim_review_store.RUNS} SET status = 'running' WHERE run_id = ?",
            (RUN,),
        )
    assert _row()["waiting_reason"] is None


def test_the_claim_and_the_words_use_the_same_test_of_being_read(world):
    """One home for "still being read": the SQL the claim uses is the one `paper_still_being_read` asks."""
    for status, embedded, chunks, indexed in (
        (states.EXTRACTING, 0, 0, False),
        (states.READY, 10, 10, True),
        (states.PARTIALLY_SEARCHABLE, 1, 10, True),
    ):
        _queue_the_run(status, embedded, chunks, indexed)
        with db.connect() as conn:
            parked = review_jobs.paper_still_being_read(conn, PAPER)
            claimable = (
                conn.execute(
                    f"SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM documents d WHERE d.id = ? AND {review_jobs._reading_predicate('d')})",
                    (PAPER,),
                ).fetchone()
                is not None
            )
        assert parked != claimable
