"""#1584: a real review job writes the could-not-check count after its comparison,
when the outcome it adds to exists. Invented documents, no model."""

from __future__ import annotations

import json

from app import (
    applicability,
    claude_approved,
    claude_auto_approve,
    comparison,
    review_jobs,
)
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


def test_a_re_comparison_keeps_the_note(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "claude_auto_approve_reviews_enabled", True)
    claude_approved.block_file_path().write_text(
        json.dumps({"blocked_sha256": ["ee" * 32]}), encoding="utf-8"
    )
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    assert review_jobs.run(job_id, W) == "done"
    with connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES ('doc_eq','eq.pdf',?,1,'eq.pdf','ready',1,'2026-11-02T00:00:00Z')",
            ("dd" * 32,),
        )
    applicability.record_selection(
        review_run_id=run_id,
        standard_document_id="doc_eq",
        reason="invented reason",
        method=applicability.METHOD_EQUIPMENT,
    )
    comparison.run_comparison(run_id, allowed_document_ids=world["scope"] | {"doc_eq"})
    row = (
        connect()
        .execute("SELECT outcome_json FROM review_runs WHERE id = ?", (run_id,))
        .fetchone()
    )
    assert (
        json.loads(row["outcome_json"])[claude_auto_approve.RUN_KEY]["not_listed"] >= 1
    )
