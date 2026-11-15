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


def _notes(plan, settings) -> list[str]:
    """Plain notes the panel shows below the plan."""
    from .review_engine import ON_CLAUDE, RULE_CHECK

    notes = []
    if settings.review_web_standards_enabled:
        kept = not plan.text_leaves or plan.part(RULE_CHECK).engine != ON_CLAUDE
        notes.append(
            "The public web check of standards the library lacks will not run: this review is kept on this computer."
            if kept
            else "This install turns on the public web check of standards the library lacks; it can send those standard names out."
        )
    return notes


def _last_cost(conn, document_id: str) -> float | None:
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


def _usd(value: float) -> str:
    return f"USD {value:g}"


def _cost_words(each: dict, total: float, per_run: float) -> str:
    """The true upper bound per part and in total, from the caps in code: the rule check and the AI review are two runs, each with
    its own per-run cap. The day and month caps still apply on top. Never an exact figure."""
    bits = []
    if each["rule_check"] is not None:
        bits.append(f"rule check: at most {_usd(each['rule_check'])}")
    if each["ai_review"] is not None:
        bits.append(f"AI review: at most {_usd(each['ai_review'])}")
    together = f"; together at most {_usd(total)}" if len(bits) > 1 else ""
    return (
        "; ".join(bits)
        + together
        + f" (each review has its own cap of {_usd(per_run)}, the day and month caps still apply; the real cost is usually lower)"
    )
