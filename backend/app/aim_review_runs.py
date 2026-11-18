"""General reviews in the Review page's run list and its counts (order 14, #1899 blocker).

The runs list and the batch counts read `review_runs`, and a general run is excluded from the old readers on purpose (it holds no
findings), so a general review never showed on the Review page and any review it did show said "0 findings". Here a general run
is listed beside the earlier ones, newest first, with ITS OWN numbers: the points it reviewed and the comments it sent (and the
confirmations held back, when the run has them), from the one place that counts them (`aim_review_view.build`).

Rule 5: a general run is its paper's run; a caller sees it only when the caller may read the paper (an intersection with the caller's
grants, never a union). Ids, counts, status words and times only. Read only: no model, no network, no write.
"""

from __future__ import annotations

import sqlite3

from . import aim_review_store, aim_review_view

GENERAL = "general"
#: The status words the runs list uses, for a general run's own states. A stopped run ended early but holds its lines: it opens.
STATUS_SHOWN = {
    "done": "completed",
    "stopped": "completed",
    "queued": "queued",
    "running": "running",
    "failed": "failed",
    "cancelled": "cancelled",
}
ENDED_WITH_LINES = ("done", "stopped")


def _rows(conn, allowed: frozenset[str], document_id: str | None = None) -> list:
    if not aim_review_store.has_tables(conn):
        return []
    where, args = ("", [])
    if document_id is not None:
        where, args = " WHERE paper_document_id = ?", [document_id]
    rows = conn.execute(
        f"SELECT * FROM {aim_review_store.RUNS}{where} ORDER BY created_at DESC, run_id DESC",
        args,
    ).fetchall()
    return [r for r in rows if r["paper_document_id"] in allowed]


def counts_of(conn, run_id: str) -> dict | None:
    """What a finished general run says of itself: {points, comments, confirmations (when the run has them), stopped}; None when it
    has not ended or cannot be read. A count is a count (0 only when it is 0)."""
    run = aim_review_store.run(conn, run_id)
    if run is None or run.get("status") not in ENDED_WITH_LINES:
        return None
    try:
        counts = aim_review_view.build(conn, run)["counts"]
    except (sqlite3.Error, aim_review_view.NotFinished):
        return None
    out = {
        "points": counts["points"],
        "comments": counts["comments"],
        "stopped": run.get("status") == "stopped",
    }
    if counts.get("confirmations") is not None:
        out["confirmations"] = counts["confirmations"]
    return out


def entries(
    conn, allowed: frozenset[str], document_id: str | None = None
) -> list[dict]:
    """The general runs the caller may read, as rows of the runs list (`ReviewRunSummary`), newest first."""
    from . import review_jobs

    out = []
    for r in _rows(conn, allowed, document_id):
        run_id, status = str(r["run_id"]), str(r["status"])
        doc = conn.execute(
            "SELECT filename FROM documents WHERE id = ?", (r["paper_document_id"],)
        ).fetchone()
        try:
            job = (
                review_jobs.job_for_run(run_id)
                if status in ("queued", "running")
                else None
            )
        except sqlite3.Error:
            job = None
        out.append(
            {
                "review_run_id": run_id,
                "submittal_document_id": r["paper_document_id"],
                "submittal_filename": doc["filename"] if doc else None,
                "status": STATUS_SHOWN.get(status, status),
                "created_at": r["created_at"],
                "completed_at": r["finished_at"],
                "method": GENERAL,
                "general_counts": counts_of(conn, run_id)
                if status in ENDED_WITH_LINES
                else None,
                "failure_reason": (r["stop_reason"] or None)
                if status == "failed"
                else None,
                "job": job,
            }
        )
    return out


def counts_for(conn, run_ids: list[str], allowed: frozenset[str]) -> dict[str, dict]:
    """{run id: counts_of} for the ids that are general runs of a paper the caller may read and that have ended."""
    out: dict[str, dict] = {}
    if not aim_review_store.has_tables(conn):
        return out
    for run_id in run_ids:
        row = conn.execute(
            f"SELECT paper_document_id FROM {aim_review_store.RUNS} WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is not None and row["paper_document_id"] in allowed:
            got = counts_of(conn, run_id)
            if got is not None:
                out[run_id] = got
    return out


def is_general(conn, run_id: str) -> bool:
    return aim_review_store.is_general(conn, run_id)
