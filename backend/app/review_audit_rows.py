"""#1525: what a CRS file prints against the rows composed for it, for the audit
report (`review_audit`). "Audit rows N; exported rows M; removed K: ...", each
removal counted on its own, so a difference nobody named shows as `adds_up` False.
It reads the one builder the file and the preview read and changes nothing.
"""

from __future__ import annotations

import logging

from . import claude_answer_cache, claude_spend, claude_spend_report, local_engine_bar

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
    "folded_by_contractor": "folded into the By Contractor row",
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
        # switch on only: one By Contractor query row stands for these rows
        if view.get(ce.crs_by_contractor.FOLDED):
            removed["folded_by_contractor"] = view[ce.crs_by_contractor.FOLDED]
    # the rows the copy itself adds to what was composed (`crs_export._copy_and_rows`)
    composed = len(ce._copy_and_rows(rows, meta)[1])
    exported, total = len(view["rows"]), sum(removed.values())
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


def clause_step(clause: dict, not_recorded: str, figures: dict) -> dict:
    """The clause review's step. A batch still out is pending, never completed or stopped; `figures` hold the counts
    with their denominators (`review_audit_detail.clause_figures`)."""
    step = {
        "name": "clause_review",
        "state": "completed" if clause.get("ran") else not_recorded,
        "model": clause.get("model"),
        "calls": clause.get("calls"),
        "fresh": clause.get("calls"),
        "reused": clause.get("cache_hits"),
        "results": clause.get("results"),
        "plain": clause.get("plain"),
        "usd": clause.get("usd"),
        **figures,
    }
    return {**step, "state": "pending"} if clause.get("pending") else step


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


#: The steps whose own stored status counts calls attempted, hits included.
_COUNT_THEIR_OWN = {
    "ai_engineering_check": "review_ai_check",
    "crs_wording": "crs_wording",
}


def cache_figures(run: dict) -> dict:
    """The stored Claude answers of this run, by the run's id on the ledger lines; nothing
    on a run with no Claude call."""
    if not run.get("id"):
        return {}
    try:
        report = claude_spend.cache_report(run_id=str(run["id"]))
    except (OSError, ValueError):
        return {}
    wanted = report["hits"] or report["misses"]
    return {"claude_answer_cache": report} if wanted else {}


def fold_stored_hits(
    steps: list[dict], ledger: list[dict] | None, figures: dict
) -> list[dict] | None:
    """A stored answer is never a fresh call. `steps` that keep their own count move their
    hits from fresh to reused; their ledger row, which says the same, is dropped so no hit
    is counted twice. Returns the ledger rows left."""
    hits = (figures.get("claude_answer_cache") or {}).get("hits_by_step") or {}
    for step in steps:
        got = hits.get(_COUNT_THEIR_OWN.get(step.get("name"), ""))
        if got and step.get("fresh") is not None:
            step["fresh"] = max(0, step["fresh"] - got)
            step["reused"] = (step.get("reused") or 0) + got
            step.update(not_sent({"cache_hits": got}))
    if ledger is None:
        return None
    return [row for row in ledger if row["step"] not in _COUNT_THEIR_OWN.values()]


def cache_lines(ai_use: dict) -> list[str]:
    cache = ai_use.get("claude_answer_cache")
    if not cache:
        return []
    off = (
        [f"  - the answer cache is off: {cache['cache_off']}"]
        if cache.get("cache_off")
        else []
    )
    return [
        f"- stored Claude answers, this review run: {cache['hits']} hits, {cache['misses']} "
        f"misses, USD {cache['saved_usd']} saved",
        f"  - {cache['boundary']}",
        *off,
    ]


def spend_figures(run: dict) -> dict:
    """This run's spend per step, read now from the ledger the run record is written from; switch off, or a run with
    no Claude call: nothing."""
    if not claude_spend_report.enabled() or not run.get("id"):
        return {}
    try:
        figures = claude_spend_report.for_review_run(str(run["id"]))
    except (OSError, ValueError):
        return {
            claude_spend_report.OUTCOME_KEY: {
                "not_recorded": claude_spend_report.LEDGER_UNREADABLE
            }
        }
    return {claude_spend_report.OUTCOME_KEY: figures} if figures["asked"] else {}


def spend_lines(ai_use: dict) -> list[str]:
    spend = ai_use.get(claude_spend_report.OUTCOME_KEY)
    if not spend:
        return []
    if spend.get("not_recorded"):
        return [f"- Claude spend, this review run: {spend['not_recorded']}"]
    out = [
        f"- Claude spend, this review run: USD {spend['usd']} over {spend['asked']} asked: "
        f"{spend['calls_charged']} charged ({spend['batch_calls']} at batch price, USD "
        f"{spend['usd_estimated']} at worst case because the usage is unknown), "
        f"{spend['stored_answers']} stored answers, {spend['refused']} refused"
    ]
    out += [
        f"  - {row['step']}: USD {row['usd']}; {row['asked']} asked; {row['calls_charged']} charged; "
        f"{row['stored_answers']} stored; {row['batch_calls']} batch; {row['refused']} refused"
        for row in spend["steps"]
    ]
    if spend["held_calls"]:
        out.append(
            f"  - {spend['held_words']}: {spend['held_calls']} calls, up to USD {spend['held_worst_usd']}"
        )
    if spend["unreadable_lines"]:
        out.append(
            f"  - {spend['unreadable_lines']} ledger lines could not be read: nobody can say whose they were, "
            "so this figure may be short"
        )
    return [*out, f"  - {spend['boundary']}"]


def run_figures(run: dict) -> dict:
    """The run's Claude figures for the audit's AI section: stored answers and spend per step."""
    return {**cache_figures(run), **spend_figures(run)}


def claude_lines(ai_use: dict) -> list[str]:
    return [*cache_lines(ai_use), *spend_lines(ai_use)]
