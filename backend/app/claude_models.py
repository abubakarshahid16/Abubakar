"""What a Claude model id accepts, and which model a run record names.

THE `thinking` FIELD. `{type: enabled, budget_tokens}` is a 400 on Sonnet 5 and
5.5, Opus 5 and 5.5 and Haiku 5.5. `settings.claude_models_with_thinking_budget`
lists the older ids that still take a budget; every other id gets
`{type: adaptive}`, so a model released after that list fails towards the shape
current models accept. `{type: disabled}` is never sent (a 400 on Sonnet 5.5 and
Opus 5.5): a caller that wants no budget leaves the field out.

THE RUN RECORD. `record_run` writes the models the API REPORTED, read from the
spend ledger, never the name configuration asked for. A local-only run has no
ledger line and keeps NULL; its local model is named by the step that ran it.
"""

from __future__ import annotations

import json
import logging

from . import claude_spend
from .config import settings
from .db import connect

log = logging.getLogger(__name__)

#: Separate work on the same ledger, not part of a review run.
NOT_REVIEW_STEPS = ("chat", claude_spend.STANDARD_STEP_PREFIX)


def thinking_for(model: str | None, budget: int) -> dict:
    """The `thinking` field for a caller that wants `budget` tokens of thought."""
    name = (model or "").lower()
    if any(
        name == p or name.startswith(p + "-")
        for p in settings.claude_models_with_thinking_budget
    ):
        return {"type": "enabled", "budget_tokens": int(budget)}
    return {"type": "adaptive"}


def record_run(review_run_id: str, *, match_step: str) -> None:
    """Put the Claude models that answered since this run started in
    `review_runs.model_name` (comma-joined) and in its AI matcher's `model`,
    which until now says only the engine. The boundary is the run's time window
    on this ledger (`claude_spend.models_used`). A ledger that cannot be read
    leaves the run unnamed and never breaks a finished review."""
    conn = connect()
    row = conn.execute(
        "SELECT started_at, created_at, outcome_json FROM review_runs WHERE id = ?",
        (review_run_id,),
    ).fetchone()
    since = (row["started_at"] or row["created_at"]) if row else None
    if not since:
        return
    try:
        used = claude_spend.models_used(since=since, exclude_prefixes=NOT_REVIEW_STEPS)
        matcher = claude_spend.models_used(since=since, steps={match_step})
    except OSError as exc:
        log.warning(
            "run models not recorded: the ledger is unreadable (%s)", type(exc).__name__
        )
        return
    outcome = json.loads(row["outcome_json"] or "{}")
    summary = outcome.get("ai_matcher")
    if isinstance(summary, dict) and summary.get("engine") == "claude" and matcher:
        summary["model"] = ", ".join(matcher)
    with conn:
        conn.execute(
            "UPDATE review_runs SET model_name = ?, outcome_json = ? WHERE id = ?",
            (", ".join(used) or None, json.dumps(outcome), review_run_id),
        )
