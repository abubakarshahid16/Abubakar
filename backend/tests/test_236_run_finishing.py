"""Order 236 (owner report, M-03): a run is "completed" only when its job is done.

`comparison._store_run_outcome` stores status "completed" before the review job
has written the AI engineering-check drafts, the CRS numbers, the CRS wording
and the trace. The owner exported 17 seconds after "Review ready" and got a
sheet without the 14 AI rows and the wording written 25 to 45 seconds later.
Now the run reads "running" until the job is done; an export taken meanwhile
carries the incomplete-review note. Invented runs; no model.
"""

from __future__ import annotations

from app import access, db, main, review_jobs, submittal_review
from tests import test_p3_review_jobs as p3

world, temp_storage = p3.world, p3.temp_storage  # the review-job fixtures


def _status(run_id, scope):
    return submittal_review.get_review_run(run_id, allowed_document_ids=scope)["status"]


def test_a_completed_run_whose_job_is_still_running_reads_running(temp_storage):
    doc = "doc-fin"
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,"
            "uploaded_at) VALUES (?,?,?,1,?,'ready',1,'2026-10-27')",
            (doc, "d.pdf", "sha", "d.pdf"),
        )
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at)"
            " VALUES ('run-fin',?,'completed','2026-10-27','2026-10-27')",
            (doc,),
        )
    scope = frozenset({doc})
    assert _status("run-fin", scope) == "completed"  # no job at all: as before
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO jobs (id,document_id,stage,state,review_run_id,started_at,updated_at)"
            " VALUES ('job-fin',?,'review_run','running','run-fin','2026-10-27','2026-10-27')",
            (doc,),
        )
    assert _status("run-fin", scope) == "running"
    runs = submittal_review.list_review_runs(allowed_document_ids=scope)
    assert [r["status"] for r in runs] == ["running"] and "finishing" not in runs[0]
    with db.connect() as conn:
        conn.execute("UPDATE jobs SET state = 'done' WHERE id = 'job-fin'")
    assert _status("run-fin", scope) == "completed"


def test_the_review_job_leaves_the_run_running_until_its_post_steps_are_written(
    world, monkeypatch
):
    run_id, job_id = p3._enqueue(world)
    scope = world["scope"]
    seen = {}

    def slow_ai_check(run, allowed, missing):
        seen["during_ai_check"] = _status(run_id, scope)
        seen["label"] = (
            db.connect()
            .execute("SELECT progress_label FROM jobs WHERE id = ?", (job_id,))
            .fetchone()["progress_label"]
        )
        # the outcome is already stored: the raw row says completed
        seen["raw"] = (
            db.connect()
            .execute("SELECT status FROM review_runs WHERE id = ?", (run_id,))
            .fetchone()["status"]
        )

    monkeypatch.setattr(review_jobs, "_ai_check", slow_ai_check)
    review_jobs.claim_next(p3.W)
    assert review_jobs.run(job_id, p3.W) == "done"
    assert seen["raw"] == "completed"
    assert seen["during_ai_check"] == "running"
    assert seen["label"] == review_jobs.FINISHING
    assert _status(run_id, scope) == "completed"


def test_an_export_taken_meanwhile_says_the_review_is_not_finished(world, monkeypatch):
    run_id, job_id = p3._enqueue(world)
    scope = access.AccessScope(user_id="adm", allowed_document_ids=world["scope"])
    seen = {}

    def during(run, allowed, missing):
        _rows, meta, _n, _s = main._crs_content(run_id, scope, "internal")
        seen["note"] = meta.get(
            "run_status_note"
        ) or main.crs_export_mod.build_crs_view(_rows, meta).get("run_status_note")

    monkeypatch.setattr(review_jobs, "_ai_check", during)
    review_jobs.claim_next(p3.W)
    assert review_jobs.run(job_id, p3.W) == "done"
    assert seen["note"], (
        "an export while the job finishes must say the review is not finished"
    )
    _rows, meta, _n, _s = main._crs_content(run_id, scope, "internal")
    assert not main.crs_export_mod.build_crs_view(_rows, meta).get("run_status_note")
