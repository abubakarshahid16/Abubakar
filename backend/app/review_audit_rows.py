"""#1525: what a CRS file prints against the rows composed for it, for the audit
report (`review_audit`). "Audit rows N; exported rows M; removed K: ...", each
removal counted on its own, so a difference nobody named shows as `adds_up` False.
It reads the one builder the file and the preview read and changes nothing.
"""

from __future__ import annotations

import logging

from . import claude_answer_cache, claude_spend, local_engine_bar

#: What "audit rows" and "exported rows" are over, printed with them.
ROWS_BOUNDARY = (
    "Audit rows: the CRS rows composed for this run, before the export removes any, over "
    "the documents the requester may read. Exported rows: the rows that copy's file prints, "
    "with CRS_EXPORT_QUALITY as set when this report was written. Rules compared (section "
    "4) counts findings, not rows: one row can stand on many findings, so it is not in this sum."
)
#: A duplicate is merged into the row before it: its comment is kept there.
_REMOVED_WORDS = {
    "duplicates_merged": "duplicates merged",
    "empty_dropped": "empty dropped",
    "not_engineer_confirmed": "not engineer-confirmed",
    "safety_ticks": "safety ticks",
    "withheld_no_text": "no text",
}


def crs_reconciliation(rows: list[dict], meta: dict) -> dict:
    """What the file of `meta["copy"]` prints against the rows composed for it,
    from the one builder both the file and the preview read. Each removal is
    counted on its own, so a difference nobody named shows as `adds_up` False."""
    from . import crs_export as ce

    view = ce.build_crs_view(rows, meta)
    removed = {
        "duplicates_merged": view.get("rows_merged", 0),
        "empty_dropped": view.get("rows_dropped_no_comment", 0),
    }
    if view["crs_copy"] == ce.COPY_ISSUE:
        confirmed = [r for r in rows if r.get("engineer_confirmed") is True]
        removed |= {
            "not_engineer_confirmed": len(rows) - len(confirmed),
            "safety_ticks": sum(
                1 for r in confirmed if r.get("row_kind") == ce.ROW_KIND_SAFETY_TICK
            ),
            "withheld_no_text": view["rows_withheld_no_text"],
        }
    composed, exported, total = len(rows), len(view["rows"]), sum(removed.values())
    adds_up = composed == exported + total
    words = ", ".join(f"{_REMOVED_WORDS[k]} {v}" for k, v in removed.items())
    return {
        "copy": view["crs_copy"],
        "audit_rows": composed,
        "exported_rows": exported,
        "removed": removed,
        "removed_total": total,
        "adds_up": adds_up,
        "missed_standard_rows": sum(
            1 for r in view["rows"] if r.get("row_kind") == "standard_not_cited"
        ),
        "line": f"audit rows {composed}; exported rows {exported}; removed {total}: {words}"
        + (
            ""
            if adds_up
            else f" - DOES NOT ADD UP: {composed - exported - total} unexplained"
        ),
    }


def for_copy(review_run_id: str, scope, copy: str) -> dict | None:
    from .main import _crs_content

    try:
        rows, meta, _name, _stamp = _crs_content(review_run_id, scope, copy)
        return crs_reconciliation(rows, meta)
    except Exception:
        logging.getLogger(__name__).warning(
            "review audit: the %s CRS copy could not be composed", copy, exc_info=True
        )
        return None


def not_sent(row: dict) -> dict:
    """A step's Claude calls that were answered from the stored answers."""
    hits = row.get("cache_hits")
    return (
        {"not_sent": f"{claude_answer_cache.NOT_SENT} ({hits} of them)"} if hits else {}
    )


def skipped_steps(outcome: dict) -> list[dict]:
    """The steps a Claude-lane run did not run: a true 0 calls, and said so."""
    return [
        {
            "name": row["step"],
            "state": row["note"],
            "model": None,
            "calls": 0,
            "fresh": 0,
            "failed": 0,
            "reused": 0,
        }
        for row in outcome.get(local_engine_bar.OUTCOME_KEY) or []
    ]


def cache_figures(run: dict) -> dict:
    """The stored Claude answers since this run began; nothing on a run with no Claude call."""
    since = run.get("started_at") or run.get("created_at")
    if not since:
        return {}
    try:
        report = claude_spend.cache_report(since=since)
    except (OSError, ValueError):
        return {}
    return {"claude_answer_cache": report} if report["hits"] or report["misses"] else {}


def cache_lines(ai_use: dict) -> list[str]:
    cache = ai_use.get("claude_answer_cache")
    if not cache:
        return []
    return [
        f"- stored Claude answers: {cache['hits']} hits, {cache['misses']} misses, "
        f"USD {cache['saved_usd']} saved",
        f"  - {cache['boundary']}",
    ]
