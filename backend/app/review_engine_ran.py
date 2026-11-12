"""What a review run really did, saved at its end (moved unchanged out of `review_engine`, file size): the Claude steps from the spend
ledger, the saved fact, and the web-check note of a run kept on this computer. Words and step names only."""

from __future__ import annotations

import json
import logging
import sqlite3

log = logging.getLogger(__name__)


def claude_steps_from_ledger(run_id: str) -> list[str]:
    """The steps of this run that reached Claude (a ledger line under its id, not a refusal). Step names only."""
    from . import claude_spend

    return sorted(
        {
            str(e.get("step") or "")
            for e in claude_spend.entries()
            if e.get("run") == run_id and not e.get("refused")
        }
        - {""}
    )


def save_ran(run_id: str | None) -> None:
    """At the END of a run, save what it really did: the steps that reached Claude. The sheet header reads this stored fact, so an
    export made later says what the first one said. Never raises."""
    from .db import connect

    if not run_id:
        return
    try:
        steps = claude_steps_from_ledger(run_id)
        conn = connect()
        got = conn.execute(
            "SELECT outcome_json FROM review_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if got is None:
            return
        outcome = json.loads(got["outcome_json"] or "{}")
        outcome["engine_ran"] = {"claude_steps": steps}
        with conn:
            conn.execute(
                "UPDATE review_runs SET outcome_json = ? WHERE id = ?",
                (json.dumps(outcome), run_id),
            )
    except (OSError, ValueError, sqlite3.Error) as exc:
        log.warning(
            "review engine: what the run did was not saved (%s)", type(exc).__name__
        )


def ran_steps(run_id: str) -> list[str]:
    """The Claude steps of a finished run: the SAVED fact when there is one, else (an older or unfinished run) the ledger's."""
    from .db import connect

    try:
        got = (
            connect()
            .execute("SELECT outcome_json FROM review_runs WHERE id = ?", (run_id,))
            .fetchone()
        )
        saved = json.loads((got["outcome_json"] if got else None) or "{}").get(
            "engine_ran"
        )
    except (sqlite3.Error, ValueError):
        saved = None
    if isinstance(saved, dict) and isinstance(saved.get("claude_steps"), list):
        return [str(x) for x in saved["claude_steps"]]
    return claude_steps_from_ledger(run_id)


def note_web_check_skipped(run_id: str) -> None:
    """The run was kept on this computer, so its public web check did not run: say so on the run. Best effort; never raises."""
    from . import absence
    from .db import connect

    status = absence.check_failed_status(
        "Web standards check",
        "this review was kept on this computer, so nothing was sent out",
    )
    try:
        conn = connect()
        with conn:
            conn.execute(
                "UPDATE review_runs SET web_check_status = ? WHERE id = ?",
                (json.dumps(status), run_id),
            )
    except sqlite3.Error as exc:
        log.warning(
            "review engine: the web check note was not written (%s)", type(exc).__name__
        )


def _notes(facts, plan, settings) -> list[str]:
    """Plain notes the panel shows below the plan."""
    from .review_engine import ON_CLAUDE, RULE_CHECK

    notes = []
    if facts.is_contract and not facts.scored_allowed:
        notes.append(
            "A recorded yes does not offer a contract for Claude while contracts are not scored against an answer key; it counts "
            "once contracts are scored, or when this install turns on the setting for unscored kinds."
        )
    if settings.review_web_standards_enabled:
        kept = not plan.text_leaves or plan.part(RULE_CHECK).engine != ON_CLAUDE
        notes.append(
            "The public web check of standards the library lacks will not run: this review is kept on this computer."
            if kept
            else "This install turns on the public web check of standards the library lacks; it can send those standard names out."
        )
    return notes
