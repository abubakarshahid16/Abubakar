"""#1584: a real review job writes the could-not-check count after its comparison,
when the outcome it adds to exists. Invented documents, no model."""

from __future__ import annotations

import json

from app import claude_approved, claude_auto_approve, review_jobs
from app.config import settings
from app.db import connect
from tests.test_p3_review_jobs import (  # noqa: F401 - fixtures
    W,
    _enqueue,
    temp_storage,
    world,
)


def test_the_review_job_records_the_note_on_the_stored_outcome(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "claude_auto_approve_reviews_enabled", True)
    claude_approved.block_file_path().write_text(
        json.dumps({"blocked_sha256": ["ee" * 32]}), encoding="utf-8"
    )
    seen = []

    def spy(run_id):
        row = (
            connect()
            .execute("SELECT outcome_json FROM review_runs WHERE id = ?", (run_id,))
            .fetchone()
        )
        seen.append((run_id, bool(row["outcome_json"])))

    monkeypatch.setattr(claude_auto_approve, "record_on_run", spy)
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    assert review_jobs.run(job_id, W) == "done"
    assert seen == [(run_id, True)]
