"""The page record and the requeue of an AI review job (moved unchanged out of `agent_review_jobs`, which decides what a review runs)."""

from __future__ import annotations

import json

from . import job_queue


def _now() -> str:
    return job_queue.now_iso()


def page_record(conn, run_id: str) -> dict | None:
    """The page reading to keep on an AI run's row (#1780). The AI review reads no page itself, so its row used to carry
    none, and a paper whose normal reviews held a good reading showed "no page record". Now: the paper's current page
    ledger when it holds pages; else the newest earlier run's stored reading that has pages, marked with the run and date it
    came from ("carried_from_run", "carried_from_at"); else None (the screen says so plainly). A skipped, failed or empty
    reading never replaces a stored one that has pages."""
    from . import comparison

    row = conn.execute(
        "SELECT submittal_document_id FROM review_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if row is None:
        return None
    try:
        now = comparison.pages_read_with_reading(row["submittal_document_id"])
    except Exception:  # noqa: BLE001 - a missing record must not fail the run
        now = None
    if isinstance(now, dict) and now.get("pages_total"):
        return now
    for old in conn.execute(
        "SELECT id, outcome_json, COALESCE(completed_at, updated_at) AS at FROM review_runs"
        " WHERE submittal_document_id = ? AND id <> ? AND outcome_json IS NOT NULL ORDER BY created_at DESC, id DESC",
        (row["submittal_document_id"], run_id),
    ):
        try:
            cov = (json.loads(old["outcome_json"]) or {}).get("page_coverage")
        except (ValueError, TypeError):
            continue
        if isinstance(cov, dict) and cov.get("pages_total"):
            return {**cov, "carried_from_run": old["id"], "carried_from_at": old["at"]}
    return None


def _with_page_record(conn, run_id: str, outcome: dict) -> dict:
    cov = page_record(conn, run_id)
    return {**outcome, "page_coverage": cov} if cov else outcome


def _requeue_switched_off(conn, job_id: str, run_id: str) -> str:
    """The switch went off while the job waited: nothing is sent, the job goes back to the queue."""
    with conn:
        conn.execute(
            "UPDATE jobs SET state = 'queued', claimed_by = NULL, claimed_at = NULL, updated_at = ? WHERE id = ?",
            (_now(), job_id),
        )
        conn.execute(
            "UPDATE review_runs SET status = 'queued', updated_at = ? WHERE id = ?",
            (_now(), run_id),
        )
    return "queued"
