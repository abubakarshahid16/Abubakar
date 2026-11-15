"""The cost lines of the Review plan: the measured cost of a paper's last AI review and the true upper bound per part and in total
(moved unchanged out of `review_engine`, which decides what leaves; this module decides nothing). No network, no document text."""

from __future__ import annotations

import sqlite3


def last_cost(conn, document_id: str) -> float | None:
    """The real cost of the paper's last AI review (its stored `usd`); None when there is none or it was not measured."""
    try:
        row = conn.execute(
            "SELECT a.usd FROM agent_review_run a JOIN review_runs r ON r.id = a.run_id"
            " WHERE r.submittal_document_id = ? AND a.usd IS NOT NULL ORDER BY r.started_at DESC LIMIT 1",
            (document_id,),
        ).fetchone()
    except sqlite3.Error:
        return None
    return float(row["usd"]) if row and row["usd"] is not None else None


def usd(value: float) -> str:
    return f"USD {value:g}"


def cost_words(each: dict, total: float, per_run: float) -> str:
    """The true upper bound per part and in total, from the caps in code: the rule check and the AI review are two runs, each with
    its own per-run cap. The day and month caps still apply on top. Never an exact figure."""
    bits = []
    if each["rule_check"] is not None:
        bits.append(f"rule check: at most {usd(each['rule_check'])}")
    if each["ai_review"] is not None:
        bits.append(f"AI review: at most {usd(each['ai_review'])}")
    together = f"; together at most {usd(total)}" if len(bits) > 1 else ""
    return (
        "; ".join(bits)
        + together
        + f" (each review has its own cap of {usd(per_run)}, the day and month caps still apply; the real cost is usually lower)"
    )
