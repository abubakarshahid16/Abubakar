"""What a Claude model id accepts, and which model a run record names.

THE `thinking` FIELD. `{type: enabled, budget_tokens}` is a 400 on Sonnet 5 and
5.5, Opus 5 and 5.5 and Haiku 5.5. `settings.claude_models_with_thinking_budget`
lists the older ids that still take a budget; every other id gets
`{type: adaptive}`, so a model released after that list fails towards the shape
current models accept. `{type: disabled}` is never sent (a 400 on Sonnet 5.5 and
Opus 5.5): a caller that wants no budget leaves the field out.

THE OUTPUT ROOM. A model that thinks by default spends `max_tokens` on thinking too, so
`shape_output` raises a short cap (`claude_spend.output_cap`) whatever the route.

THE EFFORT is the route's, by name, and NEVER follows the cap. `LOW_EFFORT_ROUTES` are
transcription, lookup and labelling, where code checks the value against the page or a
fixed list; low effort is the owner's cost lever there. `MODEL_DEFAULT_ROUTES` are
judgements code does not verify: they keep the model's default effort, or the one the
caller set. A route on neither list also keeps the default. Document kind has no model
call, so it is on neither. Not `thinking: between_tools`: only Sonnet 5.5 takes it.

THE RUN RECORD. `record_run` writes the models the API REPORTED, read from the
spend ledger, answers served from the response cache included, never the name
configuration asked for. NULL means no Claude call had answered by the end of the
comparison. The AI check runs after that, and `review_audit` takes its model from its
own status. A ledger that cannot be read is written as `LEDGER_UNREADABLE`, never NULL.
"""

from __future__ import annotations

import json
import logging

from . import claude_spend
from .config import settings
from .db import connect

log = logging.getLogger(__name__)

#: Step or route names, as `reasoning_provider` and `output_limits.model_call_for` pass them.
LOW_EFFORT_ROUTES = frozenset(
    {
        "sentence_reader",  # `reader_api.call_claude`: each proposal goes through `accept`
        "datasheet_read",  # field filling: every value's quote is verified
        "b4-vision",  # a page image read into fields (`vision_reader.EFFORT`)
        "b4-naming2",  # field names and statement roles, from a fixed list
    }
)
MODEL_DEFAULT_ROUTES = frozenset(
    {
        "match",
        "requirement-matcher",
        "recheck",
        "select_standards",
        "applicability",
        "clause_applicability",
        "division_scope",
        "scope-reasoning-decide",
        "b8-answer-judge",
        "engineering_check",
        "review_ai_check",
        "crs_wording",
        "chat",
        claude_spend.STANDARD_STEP_PREFIX,  # the compiler; a second check would join this list
    }
)
ROUTE_SENTENCE_READER = "sentence_reader"
#: `review_runs.model_name` when the ledger could not be read: not "no Claude call".
LEDGER_UNREADABLE = "not recorded: spend ledger unreadable"
#: Separate work on the same ledger, not part of a review run.
NOT_REVIEW_STEPS = ("chat", claude_spend.STANDARD_STEP_PREFIX)


def reader_model(env, fallback) -> str | None:
    """The readers' model: STANDARDS_READER_MODEL in the process, then in `backend/.env`,
    then CLAUDE_REASONING_MODEL. An injected environment (`fallback` None) is obeyed as it is."""
    named = str(env.get("STANDARDS_READER_MODEL") or "").strip()
    if named or fallback is None:
        return named or None
    return fallback.standards_reader_model or fallback.claude_reasoning_model


def thinking_for(model: str | None, budget: int) -> dict:
    """The `thinking` field for a caller that wants `budget` tokens of thought."""
    name = (model or "").lower()
    if any(
        name == p or name.startswith(p + "-")
        for p in settings.claude_models_with_thinking_budget
    ):
        return {"type": "enabled", "budget_tokens": int(budget)}
    return {"type": "adaptive"}


def shape_output(body: dict, route: str | None = None) -> None:
    """On a model that thinks by default, set a request `body`'s `max_tokens` and, for a
    route in `LOW_EFFORT_ROUTES`, low effort. Older ids are left as they are."""
    model = body.get("model")
    if not claude_spend.thinks_by_default(model):
        return
    body["max_tokens"] = claude_spend.output_cap(
        model, int(body.get("max_tokens") or 0)
    )
    if route in LOW_EFFORT_ROUTES:
        body["output_config"] = {"effort": "low"}


def record_run(review_run_id: str, *, match_step: str) -> None:
    """Put the Claude models that answered up to now, since this run started, in
    `review_runs.model_name` (comma-joined) and in its AI matcher's `model`,
    which until now says only the engine. The boundary is the run's time window
    on this ledger (`claude_spend.models_used`). A ledger that cannot be read says
    so on the run and never breaks a finished review. It also records the rule
    version the run used (`standards_compiler`, nothing with its switch off)."""
    from . import run_record, standards_compiler

    standards_compiler.record_rule_version(review_run_id)
    run_record.record_on_run(review_run_id)  # #1608
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
        log.warning("run models: the ledger is unreadable (%s)", type(exc).__name__)
        used, matcher = [LEDGER_UNREADABLE], []
    outcome = json.loads(row["outcome_json"] or "{}")
    summary = outcome.get("ai_matcher")
    if isinstance(summary, dict) and summary.get("engine") == "claude" and matcher:
        summary["model"] = ", ".join(matcher)
    with conn:
        conn.execute(
            "UPDATE review_runs SET model_name = ?, outcome_json = ? WHERE id = ?",
            (", ".join(used) or None, json.dumps(outcome), review_run_id),
        )
