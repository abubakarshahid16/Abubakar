"""A paper's review history, general and earlier (order 14, piece D): ONE newest-first list of every review of the paper the caller may read.

An earlier review (the rule check, the old AI review) keeps its own download routes: this module LINKS them and changes none. A
general review's file is piece C's sheet route. Ids, counts, status words and times only: no document text, no rule text.

The scope rule is an intersection, never a union (CLAUDE.md rule 5): a paper the caller may not read has no history (the route answers
404, like a paper that does not exist), and the earlier runs are read through `submittal_review.list_review_runs`, which narrows to
the caller's grants. A general run is the paper's own run, so it is listed with the paper.
"""

from __future__ import annotations

from . import aim_review_store, crs_copy_words, submittal_review

BOUNDARY = "reviews of this paper you may read"
GENERAL = "general"
EARLIER = "earlier version"
PART_GENERAL = "general review"
PART_RULE_CHECK = "rule check"
PART_AI = "AI review"


def _ai_run_ids(conn) -> frozenset[str]:
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'agent_review_run'"
    ).fetchone():
        return frozenset()
    return frozenset(r[0] for r in conn.execute("SELECT run_id FROM agent_review_run"))


def _ai_lines(conn, run_id: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM agent_review_line WHERE run_id = ?", (run_id,)
    ).fetchone()[0]


def _earlier_files(run_id: str, part: str, status: str) -> list[dict]:
    """The older run's own download routes (unchanged), only while the app offers the older per-review files."""
    if status not in ("complete", "completed") or not crs_copy_words.old_file_offered():
        return []
    if part == PART_AI:
        base = f"/api/reviews/runs/{run_id}/agent/crs"
        return [
            {"label": "AI review, internal copy", "url": f"{base}?copy=internal"},
            {
                "label": "AI review, contractor working copy (older file, not the issued one)",
                "url": f"{base}?copy=contractor",
            },
        ]
    return [
        {
            "label": "Rule check, internal copy",
            "url": f"/api/reviews/runs/{run_id}/crs?copy=internal",
        }
    ]


def _earlier_entries(conn, paper_id: str, allowed: frozenset[str]) -> list[dict]:
    ai = _ai_run_ids(conn)
    out = []
    for r in submittal_review.list_review_runs(
        allowed_document_ids=allowed, submittal_document_id=paper_id
    ):
        run_id = str(r["id"])
        part = PART_AI if run_id in ai else PART_RULE_CHECK
        status = str(r.get("status") or "")
        out.append(
            {
                "run_id": run_id,
                "version": EARLIER,
                "part": part,
                "status": status,
                "started_at": r.get("started_at") or r.get("created_at"),
                "finished_at": r.get("completed_at"),
                # a count only where the run stores one: null renders as nothing, never 0
                "points": (_ai_lines(conn, run_id) if part == PART_AI else None),
                "files": _earlier_files(run_id, part, status),
                "_order": str(r.get("created_at") or r.get("started_at") or ""),
            }
        )
    return out


def _general_entries(conn, paper_id: str) -> list[dict]:
    if not aim_review_store.has_tables(conn):
        return []
    out = []
    for r in conn.execute(
        f"SELECT * FROM {aim_review_store.RUNS} WHERE paper_document_id = ?",
        (paper_id,),
    ).fetchall():
        run_id = str(r["run_id"])
        done = r["status"] == "done"
        out.append(
            {
                "run_id": run_id,
                "version": GENERAL,
                "part": PART_GENERAL,
                "status": str(r["status"]),
                "started_at": r["created_at"],
                "finished_at": r["finished_at"],
                "points": conn.execute(
                    f"SELECT COUNT(*) FROM {aim_review_store.LINES} WHERE run_id = ?",
                    (run_id,),
                ).fetchone()[0]
                if r["status"] in ("done", "stopped")
                else None,
                "files": [
                    {
                        "label": "General review, team copy",
                        "url": f"/api/reviews/papers/{paper_id}/general/sheet?run_id={run_id}&copy=team",
                    }
                ]
                if done
                else [],
                "_order": str(r["created_at"] or ""),
            }
        )
    return out


def history(conn, paper_id: str, allowed: frozenset[str]) -> dict | None:
    """The paper's history, newest first; None when the caller may not read the paper (the route answers 404)."""
    if paper_id not in allowed:
        return None
    runs = _general_entries(conn, paper_id) + _earlier_entries(conn, paper_id, allowed)
    runs.sort(key=lambda e: (e["_order"], e["run_id"]), reverse=True)
    for e in runs:
        del e["_order"]
    return {"paper_document_id": paper_id, "boundary": BOUNDARY, "runs": runs}
