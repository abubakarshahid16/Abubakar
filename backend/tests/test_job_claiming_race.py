"""Issue #177 gap 1: two workers must never run the same job.

HISTORY. This file used to be a MEASUREMENT of the bug (issue #168, commit
46bd1f7): `standards.next_extraction_job` was a plain SELECT and
`run_extraction_job` claimed with `UPDATE ... WHERE state = 'queued'` without
reading the rowcount, so two workers that both read the queued row both ran
the extraction. The old assertion was `len(requirement_calls) == 2`, with a
note that it must be rewritten the day the gap closed. This is that rewrite:
every test here FAILS on the pre-#177 code (verified by running it against
origin/main 49b093f) and passes on the atomic claim.

The same gap existed on the document side: `IngestionWorker._next_document`
was a plain SELECT ordered by `uploaded_at`, so two worker instances polling
one database both received the same document id.

THE DETERMINISTIC TESTS INTERLEAVE BY HAND. A thread race only reproduces a
window when the scheduler cooperates; "A polls, B polls, then either works"
is the exact interleaving that broke, written down so it happens every run.
The threaded test is kept as well, because the real deployment shape is
threads/processes against one SQLite file, not a hand-written schedule.
"""

from __future__ import annotations

import threading

import pytest

from app import db, standards, submittal_review
from app.config import settings
from app.ingest import IngestionWorker


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "race.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    yield
    db.reset_connection()


def _doc(doc_id: str, status: str = "ready") -> None:
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO documents
               (id, filename, sha256, size_bytes, stored_path, status,
                page_count, uploaded_at)
               VALUES (?,?,?,?,?,?,1,?)""",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", 1, f"{doc_id}.pdf",
             status, "2026-09-24T00:00:00Z"),
        )
        conn.execute(
            """INSERT INTO document_classification
               (document_id, suggested_by, document_role, discipline,
                document_number)
               VALUES (?, 'test', ?, 'Mechanical', ?)""",
            (doc_id, standards.COMPANY_STANDARD, f"NUM-{doc_id}"),
        )


@pytest.fixture
def counted_extraction(monkeypatch):
    calls: list[tuple[str, str]] = []
    lock = threading.Lock()

    def fake_extract_requirements(document_id, *, allowed_document_ids):
        with lock:
            calls.append(("requirements", document_id))
        return {"requirements": 0}

    def fake_extract_table_values(document_id, *, allowed_document_ids):
        with lock:
            calls.append(("table_values", document_id))
        return {"values": 0}

    monkeypatch.setattr(standards, "extract_requirements", fake_extract_requirements)
    monkeypatch.setattr(standards, "extract_table_values", fake_extract_table_values)
    return calls


def test_a_second_poller_does_not_receive_a_job_the_first_already_holds(
        counted_extraction):
    """A polls, B polls, both run: the interleaving that duplicated work."""
    _doc("doc_race_target")
    standards.enqueue_extraction("doc_race_target")

    got_a = standards.next_extraction_job(worker_id="worker-a")
    got_b = standards.next_extraction_job(worker_id="worker-b")

    assert got_a == "doc_race_target"
    assert got_b is None, (
        "the second worker was handed a job the first had already taken - "
        "the claim is not atomic")

    for worker, got in (("worker-a", got_a), ("worker-b", got_b)):
        if got is not None:
            standards.run_extraction_job(got, worker_id=worker)
    requirement_calls = [c for c in counted_extraction if c[0] == "requirements"]
    assert len(requirement_calls) == 1


def test_running_a_job_someone_else_holds_does_no_work(counted_extraction):
    """`run_extraction_job` checks the claim; it does not trust its caller.

    The pre-#177 code issued the claiming UPDATE and went on to extract
    whether or not that UPDATE touched a row. A caller that arrives with a
    stale id - it polled before the other worker claimed - must stop here.
    """
    _doc("doc_held")
    standards.enqueue_extraction("doc_held")
    assert standards.next_extraction_job(worker_id="worker-a") == "doc_held"

    result = standards.run_extraction_job("doc_held", worker_id="worker-b")

    assert result["state"] == "not_claimed"
    assert counted_extraction == []
    row = db.connect().execute(
        "SELECT state, claimed_by, claimed_at FROM jobs WHERE document_id = ?",
        ("doc_held",)).fetchone()
    assert (row["state"], row["claimed_by"]) == ("running", "worker-a")
    assert row["claimed_at"]


def test_two_threads_polling_together_run_the_job_exactly_once(counted_extraction):
    """The deployment shape: two threads, one queued job, released together.

    Each thread uses the DEFAULT worker identity, which is per thread - so
    this also proves that a caller who never heard of `worker_id` (the
    ingestion worker's own call, any older call site) is still protected.
    """
    _doc("doc_race_threads")
    standards.enqueue_extraction("doc_race_threads")

    barrier = threading.Barrier(2)

    def worker():
        barrier.wait(timeout=5)
        job_doc_id = standards.next_extraction_job()
        if job_doc_id is not None:
            standards.run_extraction_job(job_doc_id)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    requirement_calls = [c for c in counted_extraction if c[0] == "requirements"]
    assert len(requirement_calls) == 1, (
        f"one queued job ran {len(requirement_calls)} time(s)")
    state = db.connect().execute(
        "SELECT state FROM jobs WHERE document_id = ?",
        ("doc_race_threads",)).fetchone()["state"]
    assert state == "done"


def test_two_ingestion_workers_never_take_the_same_document():
    """The document side of the same gap: `_next_document` was a SELECT."""
    _doc("doc_ingest_race", status="queued")
    first = IngestionWorker()
    second = IngestionWorker()

    assert first._next_document() == "doc_ingest_race"
    assert second._next_document() is None, (
        "a second ingestion worker was handed a document the first holds")
    # The holder polling again keeps its own document - a claim is not lost
    # to its owner between passes of the loop.
    assert first._next_document() == "doc_ingest_race"

    row = db.connect().execute(
        "SELECT claimed_by, claimed_at FROM documents WHERE id = ?",
        ("doc_ingest_race",)).fetchone()
    assert row["claimed_by"] == first.worker_id
    assert row["claimed_at"]

    # Released when the holder is done with it, and then available again.
    first._release("doc_ingest_race")
    assert second._next_document() == "doc_ingest_race"
