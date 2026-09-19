"""A review run left `running` by a process that died.

THE ROW THAT CLAIMS TO BE BUSY. `run_c9b16f71c398` sat at `running` in the
corpus with nothing running it, and `POST /api/reviews/run` refuses to start a
second review while one is going for the same submittal - so that one dead row
locked the drum sheet out of the product, permanently, with nothing on screen
explaining why.

IT IS MARKED FAILED, NOT DELETED. Somebody started it, findings may have been
written before it died, and removing the row would erase the only record that
it ever happened. A crashed run is history.

STARTUP IS WHERE THIS IS SAFE, the same fact `standards.recover_stale_
extraction_jobs` relies on: this process has just begun, so it owns no run,
and `run_comparison` is synchronous inside a request - there is no queue and
no worker that could be carrying one. A run still marked `running` therefore
belongs to a process that is gone.

Mutations: M208-M210, `python scripts/mutation_check.py --phase 17`.
"""

from __future__ import annotations

import json
import uuid

import pytest

from app import comparison, db, submittal_review
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "runs.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    yield
    db.reset_connection()


def _document(doc_id: str = "doc_sub") -> str:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf",
             "2026-09-19T00:00:00Z"))
    return doc_id


def _run(doc_id: str, status: str, run_id: str | None = None) -> str:
    run_id = run_id or str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,"
            "created_at,updated_at) VALUES (?,?,?,?,?)",
            (run_id, doc_id, status, "2026-09-19T06:00:00Z",
             "2026-09-19T06:00:00Z"))
    return run_id


def _status(run_id: str) -> str:
    return db.connect().execute(
        "SELECT status FROM review_runs WHERE id = ?", (run_id,)).fetchone()["status"]


def test_a_run_still_running_at_startup_is_marked_failed():
    doc = _document()
    orphan = _run(doc, "running")

    assert submittal_review.fail_orphaned_review_runs() == 1

    assert _status(orphan) == "failed"


def test_the_row_is_kept_because_a_crashed_run_is_history():
    """NOT DELETED. Findings may have been written before it died, and the row
    is the only record that anybody ever started it."""
    doc = _document()
    orphan = _run(doc, "running")

    submittal_review.fail_orphaned_review_runs()

    row = db.connect().execute(
        "SELECT id FROM review_runs WHERE id = ?", (orphan,)).fetchone()
    assert row is not None, "the run was deleted rather than marked failed"


def test_the_failure_says_why_in_words():
    """A status of `failed` with no reason sends the reader to the logs for
    something the row already knows."""
    doc = _document()
    orphan = _run(doc, "running")

    submittal_review.fail_orphaned_review_runs()

    stored = db.connect().execute(
        "SELECT refusal_reason FROM review_runs WHERE id = ?",
        (orphan,)).fetchone()["refusal_reason"]
    assert json.loads(stored)["error"] == submittal_review.ORPHANED_RUN_REASON
    assert "orphaned" in submittal_review.ORPHANED_RUN_REASON


@pytest.mark.parametrize("status", ["completed", "pending", "failed"])
def test_a_run_that_is_not_running_is_left_alone(status):
    """THE GUARD. A sweep that touched completed runs would rewrite the
    outcome of every review ever done, every time the server started."""
    doc = _document()
    other = _run(doc, status)

    assert submittal_review.fail_orphaned_review_runs() == 0

    assert _status(other) == status


def test_a_completed_runs_outcome_survives_the_sweep():
    """The stronger form of the guard above: the recommendation itself, not
    just the status word."""
    doc = _document()
    done = _run(doc, "completed")
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_runs SET refusal_reason = ? WHERE id = ?",
            (json.dumps({"recommended_code": "Manual Review Required",
                         "reason": "not enough of the submittal was read"}),
             done))

    submittal_review.fail_orphaned_review_runs()

    outcome = comparison.run_outcome(
        done, allowed_document_ids=frozenset({doc}))
    assert outcome["recommended_code"] == "Manual Review Required"


def test_the_submittal_can_be_reviewed_again_once_the_orphan_is_resolved():
    """THE POINT OF THE SWEEP, ASSERTED THROUGH THE RULE THAT BLOCKED IT.

    `POST /api/reviews/run` refuses while a run for the same document is
    `running`. Before the sweep that refusal is permanent; after it, the
    document is available again.
    """
    doc = _document()
    _run(doc, "running")

    def blocked() -> bool:
        return any(
            (run.get("status") or "") == "running"
            for run in submittal_review.list_review_runs(
                allowed_document_ids=frozenset({doc}),
                submittal_document_id=doc))

    assert blocked(), "the fixture does not reproduce the lock-out"

    submittal_review.fail_orphaned_review_runs()

    assert not blocked(), "the submittal is still locked out after the sweep"


def test_the_sweep_is_called_at_startup():
    """A sweep nothing runs resolves nothing.

    Asserted against `main.lifespan`'s source rather than by booting the app -
    the same idiom as `test_the_facts_migration_is_called_at_startup`, and for
    the same reason: the claim is structural (the call sits at startup, beside
    the extraction sweep), and actually booting would start the ingest worker
    and the folder watcher to prove one line.
    """
    import inspect

    from app import main
    assert "fail_orphaned_review_runs" in inspect.getsource(main.lifespan), \
        "the sweep exists but nothing calls it, so no orphan is ever resolved"


def test_several_orphans_across_documents_are_all_resolved():
    first, second = _document("doc_a"), _document("doc_b")
    _run(first, "running")
    _run(second, "running")
    kept = _run(first, "completed")

    assert submittal_review.fail_orphaned_review_runs() == 2
    assert _status(kept) == "completed"
