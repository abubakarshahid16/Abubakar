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


def _waiting(conn, status: str, paper_id: str) -> str | None:
    """ "waiting: its paper is still being read" for a queued run parked behind its paper's reading, else None."""
    from . import review_jobs

    try:
        return (
            review_jobs.WAITING_FOR_PAPER_WORDS
            if status == "queued" and review_jobs.paper_still_being_read(conn, paper_id)
            else None
        )
    except sqlite3.Error:
        return None


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


def _equipment(row) -> list[str]:
    """The equipment the AI named for the paper ("relief valve"), for the Equipment column: a general review has no valve tags of its own
    (planner 19 Nov, item 8: the column was empty on every recent review). [] when the run named none."""
    import json

    try:
        ident = json.loads(row["identity_json"] or "{}")
    except (TypeError, ValueError, KeyError, IndexError):
        return []
    word = (
        str((ident or {}).get("equipment_type") or "").replace("_", " ").strip()
        if isinstance(ident, dict)
        else ""
    )
    return [word] if word else []


def _account_stop(row) -> str | None:
    """The plain words when the run STOPPED because the Claude account cannot answer (no credit, usage limit): such a run is listed as
    failed with that reason, never as a finished review."""
    from . import aim_review_gate

    if str(row["status"]) != "stopped":
        return None
    return aim_review_gate.account_words(row["stop_reason"])


def total(conn, allowed: frozenset[str]) -> int:
    """How many general runs of papers the caller may read there are (every run, not only the newest of a paper)."""
    return len(_rows(conn, allowed))


def entries(
    conn,
    allowed: frozenset[str],
    document_id: str | None = None,
    *,
    newest_only: bool = False,
) -> list[dict]:
    """The general runs the caller may read, as rows of the runs list (`ReviewRunSummary`), newest first, each with its engine and
    whether it is its paper's FACE (`aim_review_face`: newest signed, else newest on Claude, else newest); `newest_only` keeps the
    face of each paper (the others are not even counted: reading a run's counts builds its whole page)."""
    from . import aim_review_face, review_jobs

    rows = _rows(conn, allowed, document_id)
    meta = _meta(conn, rows)
    faces = aim_review_face.face_ids(list(meta.values()))
    out = []
    for r in rows:
        if newest_only and str(r["run_id"]) not in faces:
            continue
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
                "status": "failed"
                if _account_stop(r)
                else STATUS_SHOWN.get(status, status),
                "created_at": r["created_at"],
                "completed_at": r["finished_at"],
                "waiting_reason": _waiting(conn, status, r["paper_document_id"]),
                "method": GENERAL,
                "equipment_tags": _equipment(r),
                "general_counts": counts_of(conn, run_id)
                if status in ENDED_WITH_LINES
                else None,
                "failure_reason": _account_stop(r)
                or ((r["stop_reason"] or None) if status == "failed" else None),
                "job": job,
                "engine": meta[run_id]["engine"],
                "engine_words": aim_review_face.engine_words(meta[run_id]["engine"]),
                "face": run_id in faces,
                "newer_note": aim_review_face.newer_words(list(meta.values()), run_id)
                if run_id in faces
                else None,
                "general_signoff": meta[run_id]["general_signoff"],
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


def _meta(conn, rows) -> dict[str, dict]:
    """{run id: its id, paper, start, status, engine and sign-off}: what THE RULE of the face reads (`aim_review_face`)."""
    from . import aim_review_face

    return {
        str(r["run_id"]): {
            "review_run_id": str(r["run_id"]),
            "submittal_document_id": r["paper_document_id"],
            "created_at": r["created_at"],
            "status": str(r["status"]),
            "engine": aim_review_face.engine_of(conn, r),
            "general_signoff": aim_review_face.signoff_state(conn, str(r["run_id"]))
            if str(r["status"]) == "done"
            else None,
        }
        for r in rows
    }


def face_fields(conn, allowed: frozenset[str], run_id: str) -> dict | None:
    """ONE general run's own fields as its row in the runs list carries them (method, engine and its words, sign-off, whether it is
    its paper's face, the note naming a newer review), without building any review's counts (lead-4, 26 Nov 2026: `GET
    /api/reviews/runs/{id}` left them out, so the review page could not tell it had opened the signed Claude review and drew the
    paper's newer local rough draft). None when it is not a general run of a paper the caller may read."""
    from . import aim_review_face

    row = conn.execute(f"SELECT paper_document_id FROM {aim_review_store.RUNS} WHERE run_id = ?", (run_id,)).fetchone() if (
        aim_review_store.has_tables(conn)) else None  # fmt: skip
    if row is None:
        return None
    meta = _meta(conn, _rows(conn, allowed, row["paper_document_id"]))
    if run_id not in meta:
        return None  # rule 5: a paper the caller may not read is not answered
    face = run_id in aim_review_face.face_ids(list(meta.values()))
    return {
        "method": GENERAL,
        "engine": meta[run_id]["engine"],
        "engine_words": aim_review_face.engine_words(meta[run_id]["engine"]),
        "general_signoff": meta[run_id]["general_signoff"],
        "face": face,
        "newer_note": aim_review_face.newer_words(list(meta.values()), run_id) if face else None,
    }


def is_general(conn, run_id: str) -> bool:
    return aim_review_store.is_general(conn, run_id)


def ai_line_counts(conn, run_ids: list[str]) -> dict[str, int]:
    """{run id: how many lines the earlier AI reviewer stored} for the runs that have any. Those lines live in `agent_review_line`,
    not in the findings table, so the earlier counter (findings only) said 0 for them. A run with no AI line is absent: nothing is
    said about it, never 0."""
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'agent_review_line'"
    ).fetchone():
        return {}
    out: dict[str, int] = {}
    for run_id in run_ids:
        n = conn.execute(
            "SELECT COUNT(*) FROM agent_review_line WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        if n:
            out[run_id] = int(n)
    return out
