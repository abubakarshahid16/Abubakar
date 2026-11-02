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
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

NOTE = "skipped: local engine not loaded in a Claude-lane run"
#: The run's `outcome_json` key.
OUTCOME_KEY = "ai_steps_skipped"

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


def is_claude_lane_run() -> bool:
    """REASONING_PROVIDER says claude or per_task, and the lane itself is open."""
    from . import reasoning_provider as rp

    return rp._provider_setting() in (rp.CLAUDE, rp.PER_TASK) and rp.claude_lane_open()


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
        if not is_claude_lane_run():
            return job(*args, **kwargs)
        with bar():
            return job(*args, **kwargs)

    return wrapper


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
