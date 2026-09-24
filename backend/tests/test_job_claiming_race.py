"""Issue #168, criterion 1 (\"horizontally scalable\"): two workers racing on
the same `jobs` row.

THE CLAIM UNDER TEST. `standards.next_extraction_job` is a plain `SELECT ...
WHERE state = 'queued'` with no row lock, no `claimed_by`/`claimed_at`, and no
`SELECT ... FOR UPDATE`-equivalent (SQLite has none; the nearest available
tool would be a single atomic `UPDATE ... WHERE state = 'queued' RETURNING`,
which the code does not use). `run_extraction_job` issues an UPDATE guarded by
`WHERE state = 'queued'`, but never checks that UPDATE's rowcount before
proceeding to do the extraction work - so a second caller that read the same
`queued` row before the first caller's UPDATE committed will still run
`extract_requirements`/`extract_table_values` a second time, even though its
own claiming UPDATE affected zero rows.

That is the concrete, current gap behind "not proven horizontally scalable":
a second worker process pulling from the same `jobs` table can and does
duplicate work on the same document. `standards.py`'s own comment above
`enqueue_extraction` ("ONE WORKER, NOT A SECOND ONE... master plan section 24
says one ingestion/review worker") confirms this was never designed to be
run by two workers - this test proves it, rather than taking the comment's
word for it.

This test is a MEASUREMENT of the current gap, not a fix. Per issue #168's
scope discipline, no locking column is added here - that is a separately
sized fix (e.g. an atomic `UPDATE jobs SET state='running' WHERE state
='queued' RETURNING document_id`, or a `claimed_by` column) left to the
issue's owner to decide is worth building.

Mutation: if `run_extraction_job` were changed to check the claiming UPDATE's
rowcount and bail out when it is 0 (the actual fix), this test's assertion
that BOTH threads ran the extraction would start failing - which is exactly
the signal that the gap had been closed and this test should be rewritten to
assert the opposite.
"""

from __future__ import annotations

import threading

import pytest

from app import db, standards, submittal_review
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "race.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    yield
    db.reset_connection()


def _doc(doc_id: str) -> None:
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO documents
               (id, filename, sha256, size_bytes, stored_path, status,
                page_count, uploaded_at)
               VALUES (?,?,?,?,?,'ready',1,?)""",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", 1, f"{doc_id}.pdf",
             "2026-09-24T00:00:00Z"),
        )
        conn.execute(
            """INSERT INTO document_classification
               (document_id, suggested_by, document_role, discipline,
                document_number)
               VALUES (?, 'test', ?, 'Mechanical', ?)""",
            (doc_id, standards.COMPANY_STANDARD, f"NUM-{doc_id}"),
        )


def test_two_workers_polling_next_extraction_job_both_run_the_same_job(monkeypatch):
    """Reproduces the race directly: two threads, one `queued` job, no lock.

    Each thread independently calls `next_extraction_job()` (the read a second
    worker process would do) and then `run_extraction_job()` on whatever it
    got back - exactly what a second horizontally-scaled worker would do
    against the same database. Both are released together with a Barrier so
    they are inside the race window at the same instant, the same technique
    `test_migration_race.py` uses for the schema-migration race this project
    already found and fixed.
    """
    doc_id = "doc_race_target"
    _doc(doc_id)
    standards.enqueue_extraction(doc_id)

    calls = []
    call_lock = threading.Lock()

    def fake_extract_requirements(document_id, *, allowed_document_ids):
        with call_lock:
            calls.append(("requirements", document_id, threading.get_ident()))
        return {"requirements": 0}

    def fake_extract_table_values(document_id, *, allowed_document_ids):
        with call_lock:
            calls.append(("table_values", document_id, threading.get_ident()))
        return {"values": 0}

    monkeypatch.setattr(standards, "extract_requirements", fake_extract_requirements)
    monkeypatch.setattr(standards, "extract_table_values", fake_extract_table_values)

    barrier = threading.Barrier(2)
    results = []

    def worker():
        barrier.wait(timeout=5)
        job_doc_id = standards.next_extraction_job()
        if job_doc_id is None:
            results.append(None)
            return
        results.append(standards.run_extraction_job(job_doc_id))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    requirement_calls = [c for c in calls if c[0] == "requirements"]

    # THE GAP, MEASURED: with no claiming lock, both threads read the same
    # `queued` document_id from `next_extraction_job()` before either
    # `run_extraction_job()` UPDATE commits, so both proceed to do the
    # extraction work. If a proper claim existed (an atomic claim-and-check,
    # or a `claimed_by` column respected by both the read and the write
    # side), exactly one thread would have called the extractor.
    assert len(requirement_calls) == 2, (
        "expected the unlocked queue to let both workers run the same "
        f"extraction job - got {len(requirement_calls)} call(s); if this "
        "is now 1, the claiming gap this test documents has been fixed and "
        "this test should be rewritten to assert single execution instead"
    )

    # Both threads process the SAME document_id - confirming this is not
    # merely two different jobs each running once, but one job run twice.
    assert {c[1] for c in requirement_calls} == {doc_id}
