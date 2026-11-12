"""A review on the Claude lane never loads the local engine.

THE DEFECT (pilot, 2 Nov 2026). Claude read and matched the document, then the last
phase ("finishing: AI comments and wording") loaded the local 35B model, and the
machine stopped at 91% memory. So `review_jobs.run` runs under `barring_local_engine`:
with REASONING_PROVIDER=claude or per_task and the lane open, every local-engine step
of that run is refused where it would start. With REASONING_PROVIDER=ollama this
file changes nothing: the bar is never raised.

A SKIPPED AI STEP IS STATED, NEVER DROPPED (CLAUDE.md top rule). `refuses(step)` notes
the step and how many calls it would have made; `record_on_run` writes the notes to the
run's `outcome_json` and `review_audit` prints them. A step does not move to Claude
here: the provider switch and each step's own engine setting decide that (rule 1), so
a step that stays off is skipped and says so.

THE BAR ALSO HOLDS WHERE A STEP FORGOT. `model_transport.endpoint` refuses too, with
an error shaped like a stopped engine (`LocalEngineNotLoaded`), which every caller
already handles. It holds per job, in a context variable, so a chat answer on the
Local model on another thread is untouched. Step names and counts only, never text.
"""

from __future__ import annotations

import functools
import json
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

NOTE = "skipped: local engine not loaded in a Claude-lane run"
#: The run's `outcome_json` key.
OUTCOME_KEY = "ai_steps_skipped"
#: What the CRS and the review notes print for a skipped step.
NOT_CHECKED = "not checked: skipped in a Claude-lane run"
#: Plain names of the steps; any other prints its own step name.
STEP_WORDS = {
    "clause_review": "AI clause review",
    "crs_wording": "AI wording of the CRS comments",
    "b4-naming2": "AI field naming",
    "requirement-matcher": "AI requirement matching",
    "datasheet-ai-reader": "AI datasheet reading",
    "scope-reasoning-decide": "AI scope reasoning",
    "rule_equipment_scope": "AI equipment scope of a rule",
}
#: A gate-level note names a path, not a step: the words never print the path.
GATE_WORDS = "A local-engine AI step"


def _words(step: str) -> str:
    if step.startswith("ai_task:"):
        return f"AI {step.removeprefix('ai_task:').replace('_', ' ')}"
    return GATE_WORDS if step.startswith("local engine") else STEP_WORDS.get(step, step)


#: Already listed under its own status (`absence.check_failed_status`).
SAYS_ITSELF = frozenset({"review_ai_check"})

_SKIPPED: ContextVar[dict[str, int] | None] = ContextVar(
    "local_engine_barred", default=None
)


def active() -> bool:
    return _SKIPPED.get() is not None


def refuses(step: str, count: int = 1) -> bool:
    """True when the bar is up; the step is then noted as skipped."""
    skipped = _SKIPPED.get()
    if skipped is None:
        return False
    skipped[step] = skipped.get(step, 0) + count
    return True


def at_least(step: str, count: int) -> None:
    """A step noted once and then stopped: the parts it left unread are what it did not
    do, so the note says all of them. Nothing for a step the bar did not stop."""
    skipped = _SKIPPED.get()
    if skipped and step in skipped:
        skipped[step] = max(skipped[step], count)


#: THE per-step engine settings a normal review reads (each: "ollama" = local, "claude" = that step may go to Claude). The
#: ONE list: `is_claude_lane_run` reads it, and no other place names them. The AI reviewer's own `agent_review_engine` is not
#: here: it is a separate job (`agent_review`), not a step of a normal review.
REVIEW_ENGINE_SETTINGS = (
    "match_engine",
    "vision_reader_engine",
    "datasheet_ai_reader",
    "crs_ai_wording_engine",
    "review_ai_check_engine",
    "ai_clause_review_engine",
    "ai_division_scope_engine",
    "ai_engineering_review_pass_engine",
)


def is_claude_lane_run(agent_job: bool | None = False) -> bool:
    """True when THIS job can really go to Claude, and the lane itself is open. Decided per job, by ONE function.

    * the AI reviewer's job (`agent_job` True, rule review and general review): when its own gate is open
      (`claude_unavailable_for_task(agent_review_engine)`: claude, or per_task with `agent_review_engine` = claude).
    * a normal review (False), `claude`: every reasoning step may, so any review is one (as before).
    * a normal review, `per_task`: only when one of `REVIEW_ENGINE_SETTINGS` says claude. With every engine local the
      review runs exactly as under `ollama`: no bar, nothing skipped (owner, 12 Nov 2026).
    * the kind of job could not be read (None): barred when EITHER rule would bar it (the safe side).
    * anything else: never."""
    from . import reasoning_provider as rp
    from . import review_engine
    from .config import settings

    if review_engine.claude_barred():
        return False  # the run is kept on this computer: no Claude lane, so no bar on the local engine either
    if agent_job is None:
        return is_claude_lane_run(True) or is_claude_lane_run(False)
    if agent_job:
        return rp.claude_unavailable_for_task(settings.agent_review_engine)[0] is None
    provider = rp._provider_setting()
    if provider == rp.CLAUDE:
        return rp.claude_lane_open()
    if provider != rp.PER_TASK:
        return False
    if not any(
        str(getattr(settings, name, "") or "").strip().lower() == rp.CLAUDE
        for name in REVIEW_ENGINE_SETTINGS
    ):
        return False
    return rp.claude_lane_open()


def _is_agent_job(job_id) -> bool | None:
    """The kind of job, from its row (`jobs.stage`): True for the AI reviewer's job, False for a normal review, None when
    it cannot be read (no row, a database error). None is barred if either kind would be: the safe side."""
    from . import agent_review_gate
    from .db import connect

    try:
        row = (
            connect()
            .execute("SELECT stage FROM jobs WHERE id = ?", (job_id,))
            .fetchone()
        )
    except sqlite3.Error as exc:
        logging.getLogger(__name__).warning(
            "local engine bar: job kind unreadable (%s); barred if either kind would be",
            type(exc).__name__,
        )
        return None
    if row is None:
        logging.getLogger(__name__).warning(
            "local engine bar: job kind unreadable (no job row); barred if either kind would be"
        )
        return None
    return row["stage"] == agent_review_gate.STAGE


@contextmanager
def bar() -> Iterator[None]:
    token = _SKIPPED.set({})
    try:
        yield
    finally:
        _SKIPPED.reset(token)


def barring_local_engine(job):
    """The review job, with the bar up for the length of a Claude-lane run."""

    @functools.wraps(job)
    def wrapper(*args, **kwargs):
        if not is_claude_lane_run(agent_job=_is_agent_job(args[0]) if args else False):
            return job(*args, **kwargs)
        with bar():
            return job(*args, **kwargs)

    return wrapper


def unchecked_lines(outcome: dict) -> list[dict]:
    """Each step this run skipped, as `absence.unchecked_parts` lists it: a skipped step
    never leaves a sheet looking complete for that step."""
    return [
        {
            "part": f"skipped:{row['step']}",
            "line": f"{_words(row['step'])}: {NOT_CHECKED}.",
            "note": "Not checked",
        }
        for row in outcome.get(OUTCOME_KEY) or []
        if row.get("step") not in SAYS_ITSELF
    ]


def stated() -> list[dict]:
    """What the run skipped, for the run record and the audit."""
    skipped = _SKIPPED.get() or {}
    return [
        {"step": step, "calls_not_made": count, "note": NOTE}
        for step, count in sorted(skipped.items())
    ]


def record_on_run(review_run_id: str) -> None:
    """Add the notes to the run's outcome. Nothing is written when nothing was skipped."""
    rows = stated()
    if not rows:
        return
    from .db import connect

    conn = connect()
    row = conn.execute(
        "SELECT outcome_json FROM review_runs WHERE id = ?", (review_run_id,)
    ).fetchone()
    outcome = json.loads(row["outcome_json"] or "{}") if row is not None else {}
    outcome[OUTCOME_KEY] = rows
    with conn:
        conn.execute(
            "UPDATE review_runs SET outcome_json = ? WHERE id = ?",
            (json.dumps(outcome), review_run_id),
        )
