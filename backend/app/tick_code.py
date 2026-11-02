"""What an engineer's tick does to a run's stored review code (owner decision on #1584).

With TICK_HOLDS_REVIEW_CODE_ENABLED the code waits for the tick: while a safety row is open,
`rule_trust.hold_open_ticks` makes an approval a manual review. A review writes its rows to tick
as open, so a stored code would stay manual for good unless a tick looked again. So a change to
a tick row works the code out again, here, with the inputs the run stored and the rows as they
are now, through the one function (`comparison.recommend_code`).

It writes the run's recommendation only when the code changes: a tick that leaves others open
leaves the code and its dated reason as they were. An engineer's recorded final code is theirs:
a run that has one is not touched, recommendation included, because that is what they decided
beside. The change is on the audit record, ids and codes only.

OFF: a tick does not touch the run, as before. A stored trace keeps the code it was built with.
"""

from __future__ import annotations

import json

from .config import settings
from .db import connect


def _stored_inputs(outcome: dict) -> dict:
    """`comparison.recommend_code`'s inputs, as `_store_run_outcome` stored them."""
    return {
        "missing_references": [
            m.get("identifier") if isinstance(m, dict) else m
            for m in outcome.get("missing_references") or []
        ],
        "page_coverage": outcome.get("page_coverage"),
        "unchecked_standards": outcome.get("standards_not_checked") or [],
        "unchecked_counts": outcome.get("unchecked_counts"),
    }


def checked(finding: dict | None, actor_user_id: str | None = None) -> dict | None:
    """`after_change`, for the writer to return its row through."""
    after_change(finding, actor_user_id)
    return finding


def after_change(finding: dict | None, actor_user_id: str | None = None) -> str | None:
    """Work the run's code out again after a change to this finding. The new code when it
    changed, else None. Only a tick row of a run with a stored code and no final code."""
    if (
        not settings.tick_holds_review_code_enabled
        or not finding
        or not finding.get("show_for_engineer_tick")
        or not finding.get("review_run_id")
    ):
        return None
    from . import comparison

    run_id = finding["review_run_id"]
    conn = connect()
    # ONE TRANSACTION, the write lock taken first: a re-run stores its whole outcome on this
    # row, and a read outside the lock would write back the outcome it replaced.
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        run = conn.execute(
            "SELECT status, outcome_json, engineer_final_code FROM review_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if run is None or run["engineer_final_code"] or run["status"] != "completed":
            return None
        outcome = json.loads(run["outcome_json"] or "{}")
        if not outcome.get("recommended_code"):
            return None
        rows = conn.execute(
            "SELECT * FROM review_findings WHERE review_run_id = ?", (run_id,)
        ).fetchall()
        result = comparison.recommend_code(
            [dict(r) for r in rows],
            outcome.get("completeness") or {},
            **_stored_inputs(outcome),
        )
        before = outcome["recommended_code"]
        if result["code"] == before:
            return None
        outcome.update(
            recommended_code=result["code"],
            reason=result["reason"],
            details=result.get("details"),
        )
        # a caller with no user row (auth off) is still a tick: the record names no one
        known = (
            actor_user_id
            and conn.execute(
                "SELECT 1 FROM users WHERE id = ?", (actor_user_id,)
            ).fetchone()
        )
        conn.execute(
            "UPDATE review_runs SET outcome_json = ? WHERE id = ?",
            (json.dumps(outcome), run_id),
        )
        comparison._audit(
            conn,
            "review.code_rechecked_after_tick",
            {"id": actor_user_id} if known else None,
            run_id,
            f"{before} -> {result['code']}",
        )
    return result["code"]
