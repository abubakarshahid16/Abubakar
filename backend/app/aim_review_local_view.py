"""What the page and the file of a general review say about the MODEL that made it (planner 25 Nov 2026 22:35).

A run made on the local model (Local only: its stored plan puts the AI review on the local model, or one of its calls was answered
by the local model) names the model its OWN calls recorded (`calls_json`, the name the local engine reported, never the setting),
says that nothing left the computer, and says `aim_review_gate.LOCAL_NOT_SCORED` in place of its kind's measured score: every score in
`aim_review_measured` is of Claude reviews and does not apply to it. A Claude run is shown exactly as before. Reads the run row and
its stored engine choice only; no model, no network, no document text.
"""

from __future__ import annotations

import json
import sqlite3

from . import aim_review_gate, aim_review_measured


def _calls(run: dict) -> list[dict]:
    try:
        calls = json.loads(run.get("calls_json") or "[]")
    except ValueError:
        return []
    return [c for c in calls if isinstance(c, dict)] if isinstance(calls, list) else []


def engine_of(conn, run: dict) -> dict:
    """{"local": bool, "models": [...], "sentence": ...} for one stored general run."""
    from . import review_engine

    models = sorted(
        {str(c.get("model") or "") for c in _calls(run) if c.get("engine") == "local"}
        - {""}
    )
    try:
        planned = (
            review_engine.ai_review_engine(conn, run.get("run_id"))
            == review_engine.ON_LOCAL
        )
    except sqlite3.Error:  # an unreadable plan: the calls alone say it
        planned = False
    if not (planned or models):
        return {"local": False, "models": [], "sentence": None}
    named = ", ".join(models) if models else "no call was made"
    return {
        "local": True,
        "models": models,
        "sentence": f"Local model ({named}): nothing left this computer, USD 0. {aim_review_gate.LOCAL_NOT_SCORED}.",
    }


def _blank(value):
    return None if value is None or value == "" else value


def measured(identity: dict | None, local: dict) -> dict | None:
    """The score line of the run: its kind's measured score (`aim_review_measured.for_run`), or for a local run the not-scored
    words (`aim_review_measured.for_local_run`). None when a Claude run names no kind."""
    identity = identity if isinstance(identity, dict) else {}
    if local.get("local"):
        return aim_review_measured.for_local_run(
            identity, list(local.get("models") or [])
        )
    return aim_review_measured.for_run(
        {k: _blank(identity.get(k)) for k in ("kind", "equipment_type")}
    )
