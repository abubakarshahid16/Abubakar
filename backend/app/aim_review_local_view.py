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


#: The plain name of each method step, for the "which model ran each step" line.
STEP_WORDS = {
    "aim_identify": "name",
    "aim_select": "choose",
    "aim_checklist": "checklist",
    "aim_checklist_knowledge": "checklist",
    "aim_checklist_retry": "checklist",
    "aim_attack": "attack",
    "aim_judge": "judge",
    "aim_reference": "judge",
    "aim_answered": "whole-paper check",
    "aim_second_read": "second reader",
    "aim_edit": "editor",
}


#: The end of a judge call's note when it read the whole paper (`local_model._note`); "... not the whole paper" is not it.
WHOLE = "; the whole paper"


def by_step(run: dict) -> dict:
    """{"steps": {step: [models]}, "sentence": ..., "paper": ...}: the models each step's calls recorded (from the run, never a
    setting), and for a local run whether every judge call saw the whole paper (owner, 25 Nov 2026: no blind chunking)."""
    steps: dict[str, list[str]] = {}
    for c in _calls(run):
        step, model = (
            STEP_WORDS.get(str(c.get("step") or "")),
            str(c.get("model") or ""),
        )
        if step and model and model not in steps.setdefault(step, []):
            steps[step].append(model)
    sentence = "; ".join(f"{k}: {', '.join(v)}" for k, v in steps.items()) or None
    notes = [
        str(c.get("note") or "")
        for c in _calls(run)
        if c.get("step") == "aim_judge" and c.get("note")
    ]
    if not notes:
        paper = None
    elif all(n.endswith(WHOLE) for n in notes):
        paper = f"The judge saw the whole paper in each of its {len(notes)} calls."
    else:
        part = sum(1 for n in notes if not n.endswith(WHOLE))
        paper = f"The judge saw a page window, not the whole paper, in {part} of its {len(notes)} calls."
    return {"steps": steps, "sentence": sentence, "paper": paper}


def engine_of(conn, run: dict) -> dict:
    """{"local": bool, "models": [...], "sentence": ..., "by_step": ...} for one stored general run."""
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
    steps = by_step(run)
    if not (planned or models):
        return {"local": False, "models": [], "sentence": None, "by_step": steps}
    named = ", ".join(models) if models else "no call was made"
    paper = f" {steps['paper']}" if steps["paper"] else ""
    return {
        "local": True,
        "models": models,
        # the local model's measured note is in the score line (`measured`), which the page draws (review of update 9, M6)
        "sentence": f"Local model ({named}): nothing left this computer, USD 0. {aim_review_gate.local_score_words(models)}.{paper}",
        "by_step": steps,
    }


def _blank(value):
    return None if value is None or value == "" else value


def measured(identity: dict | None, local: dict) -> dict | None:
    """The score line of the run: its kind's measured score (`aim_review_measured.for_run`), or for a local run the not-scored
    words (`aim_review_measured.for_local_run`) followed by the measured note of the model the run used (`aim_review_gate.local_measured_note`;
    the page draws this line, review of update 9, M6). None when a Claude run names no kind."""
    identity = identity if isinstance(identity, dict) else {}
    if local.get("local"):
        out = aim_review_measured.for_local_run(
            identity, list(local.get("models") or [])
        )
        steps = local.get("by_step") or {}
        extra = [
            x
            for x in (
                aim_review_gate.local_measured_note(local.get("models")),
                steps.get("sentence") and f"Model by step: {steps['sentence']}.",
                steps.get("paper"),
            )
            if x
        ]
        return out | {"sentence": " ".join([out["sentence"], *extra])}
    return aim_review_measured.for_run(
        {k: _blank(identity.get(k)) for k in ("kind", "equipment_type")}
    )
