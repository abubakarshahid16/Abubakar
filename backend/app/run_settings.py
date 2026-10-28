"""What a review run ran with (order 273.4): the model and the settings that change its answer.

`review_runs.model_name` was NULL on every run and no run said which reader switches it ran under, so a
gate on one set of switches could pass a sheet the live app (another set) got wrong. A run now stores
its `config_version`, the VALUES behind that version (`config.ANSWER_AFFECTING_SETTINGS`, no secret among
them) and, when it ends, the reader that read the sheet. The values are read from the running process, not
from a file, so gates and the mirror can read them from the run.
"""

from __future__ import annotations

import json

from . import config


def snapshot() -> dict:
    values = {
        k: getattr(config.settings, k) for k in sorted(config.ANSWER_AFFECTING_SETTINGS)
    }
    return {"config_version": config.config_version(), "settings": values}


def record(conn, run_id: str) -> None:
    """Stamp the run with the settings the process holds now. `model_name` is the model the review's AI
    tasks are configured to use; the reader that really read the sheet is added by `finish`."""
    stamp = snapshot()
    conn.execute(
        "UPDATE review_runs SET run_settings = ?, config_version = ?, model_name = ? WHERE id = ?",
        (
            json.dumps(stamp, default=str),
            stamp["config_version"],
            config.settings.ai_task_model,
            run_id,
        ),
    )


def finish(conn, run_id: str, submittal_id: str) -> None:
    """Add the reader that read the sheet (engine and model, as it reported them), if one is recorded."""
    from . import datasheets

    reader = datasheets.latest_reader_summary(submittal_id) or {}
    row = conn.execute(
        "SELECT run_settings FROM review_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if row is None or not row[0]:
        return
    stamp = json.loads(row[0])
    stamp["reader"] = {
        k: reader.get(k) for k in ("engine", "model", "pages", "pages_read")
    }
    with conn:
        conn.execute(
            "UPDATE review_runs SET run_settings = ? WHERE id = ?",
            (json.dumps(stamp, default=str), run_id),
        )


def of_run(conn, run_id: str) -> dict | None:
    row = conn.execute(
        "SELECT run_settings, model_name FROM review_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if row is None or not row[0]:
        return None
    return {**json.loads(row[0]), "model_name": row[1]}
