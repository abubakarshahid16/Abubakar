"""THE REVIEW MODEL SETTING (planner 25 Nov 2026 22:40; lead-4, 26 Nov 2026): the administrator chooses, on the Administration
page, the local model of the general review's Local only runs: ONE default and, where wanted, one per step (name, choose,
checklist, attack, judge, second reader, editor). Stored in the app's own database (table `review_model_setting`), not in .env;
the older env setting GENERAL_REVIEW_LOCAL_STEP_MODELS still counts for a step the stored setting does not name.

THE RULES (each one tested):
  * CLAUDE STAYS THE MAIN ENGINE. Automatic and Claude run on the method's own Claude models (GENERAL_REVIEW_LEAD_MODEL and
    GENERAL_REVIEW_STRONG_MODEL), the models the measured scores were made with. This setting never changes them, and Automatic
    never picks a local model (`review_engine_general.decide_general`).
  * A MODEL MAY BE CHOSEN only when its vendor is approved (`aim_review.model_socket`), its price is known (Claude: the price
    table of `claude_spend`; local: USD 0) and, for a local model, it is a model FILE on this computer (no cloud name, no
    remote host or model, a size and a digest: `local_model.is_local_file`, checked again at every run start) and fits this
    computer (its file at most `local_model.MAX_MODEL_BYTES`: the 35B is refused, owner 25 Nov 2026). A model with no measured score for a kind says
    "not yet scored": a Claude model is offered only with a measured score; a local model only for Local only, whose plan, page and
    file carry `aim_review_gate.LOCAL_NOT_SCORED`.
  * NOTHING LEAVES THIS COMPUTER and no model is loaded here: the installed models come from the local engine's own list
    (`/api/tags` through `model_transport`, loopback only).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from .db import connect

log = logging.getLogger(__name__)

TABLE = "review_model_setting"
DEFAULT = "default"
_SCHEMA = f"""CREATE TABLE IF NOT EXISTS {TABLE} (
    slot   TEXT PRIMARY KEY,
    model  TEXT NOT NULL,
    set_by TEXT,
    set_at TEXT NOT NULL
)"""
#: EVERY CHANGE IS KEPT (review of update 10, N6): one row per slot whose model changed at a save; ids only (the slot, the
#: model names, the administrator's user id, the time). Never updated or deleted by the app.
HISTORY = "review_model_setting_history"
_HISTORY_SCHEMA = f"""CREATE TABLE IF NOT EXISTS {HISTORY} (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    slot       TEXT NOT NULL,
    old_model  TEXT,
    new_model  TEXT,
    changed_by TEXT,
    changed_at TEXT NOT NULL
)"""
#: How many of the latest changes the Administration page's section is given.
HISTORY_SHOWN = 10

NOT_INSTALLED = "not installed on this computer"
TOO_LARGE = "too large for this computer (its file is over 15 GB)"
ENGINE_DOWN = "the local engine did not answer, so the installed models are not known"
CLAUDE_FIXED = "the method's own Claude model, as scored; Claude stays the main engine and this page does not change it"
UNKNOWN_STEP = "no such step"
NOT_LOCAL_FILE = "not a model file on this computer: the engine would pass the paper's text to another computer"


def steps() -> tuple[str, ...]:
    from .aim_review import local_model

    return tuple(local_model.STEP_GROUPS)


def _ensure(conn) -> None:
    conn.execute(_SCHEMA)
    conn.execute(_HISTORY_SCHEMA)


def ensure_schema(conn=None) -> None:
    """Both tables exist afterwards (additive only). Wired into the app's schema start-up (`main.lifespan`), so the first save
    on the live database is no schema change."""
    conn = conn or connect()
    _ensure(conn)
    conn.commit()


def _slots(saved: dict) -> dict[str, str]:
    return (
        {DEFAULT: saved["default"], **saved["steps"]}
        if saved["default"]
        else dict(saved["steps"])
    )


def history(conn=None, limit: int = HISTORY_SHOWN) -> list[dict]:
    """The latest changes, newest first: [{"slot", "old_model", "new_model", "changed_by", "changed_at"}]. Reads only; no
    table yet is no change yet."""
    conn = conn or connect()
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (HISTORY,)
        ).fetchone():
            return []
        rows = conn.execute(
            f"SELECT slot, old_model, new_model, changed_by, changed_at FROM {HISTORY} ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 - the section shows no history rather than fail; the log says why
        log.warning("review model history not read (%s)", type(exc).__name__)
        return []
    return [dict(r) for r in rows]


def stored(conn=None) -> dict:
    """{"default": model or None, "steps": {step: model}, "set_by", "set_at"} as saved; empty when nothing is saved. Reads only. A
    table that cannot be read counts as nothing saved (the review then keeps ANSWER_MODEL), and says so in the log."""
    out: dict = {"default": None, "steps": {}, "set_by": None, "set_at": None}
    try:
        conn = conn or connect()
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (TABLE,)
        ).fetchone():
            return out  # nothing saved yet; a read never creates the table
        rows = conn.execute(
            f"SELECT slot, model, set_by, set_at FROM {TABLE} ORDER BY slot"
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 - the review keeps its default model; the log says why
        log.warning("review model setting not read (%s)", type(exc).__name__)
        return out
    for r in rows:
        if r["slot"] == DEFAULT:
            out["default"] = r["model"]
        elif r["slot"] in steps():
            out["steps"][r["slot"]] = r["model"]
        if r["set_at"] and (out["set_at"] is None or r["set_at"] > out["set_at"]):
            out["set_at"], out["set_by"] = r["set_at"], r["set_by"]
    return out


def installed() -> list[dict] | None:
    """[{"name", "bytes", "local_file"}] of the models the local engine lists, or None when it does not answer. `local_file`:
    the entry is a model file on this computer (`local_model.is_local_file`). Loads no model."""
    from . import model_transport

    try:
        body = model_transport.get_json("/api/tags", timeout=3.0, required=False)
    except Exception as exc:  # noqa: BLE001 - "not known" is shown, never an empty list
        log.info("installed local models not read (%s)", type(exc).__name__)
        return None
    if not isinstance(body, dict) or not isinstance(body.get("models"), list):
        return None
    out = []
    for m in body["models"]:
        name = str((m or {}).get("name") or (m or {}).get("model") or "").strip()
        if name:
            from .aim_review import local_model

            out.append(
                {
                    "name": name,
                    "bytes": int((m or {}).get("size") or 0),
                    "local_file": local_model.is_local_file(name, m or {}),
                }
            )
    return sorted(out, key=lambda m: m["name"])


def scored_kinds() -> list[str]:
    """The kinds (and datasheet equipment types) with a measured score of the general review (`aim_review_measured`'s table).
    Those scores were measured on Claude runs."""
    from . import aim_review_measured

    try:
        table = aim_review_measured._table()
    except Exception as exc:  # noqa: BLE001 - no table: nothing is scored, and the log says why
        log.warning("measured score table not read (%s)", type(exc).__name__)
        return []
    out = []
    for kind, row in sorted((table.get("kinds") or {}).items()):
        if (row or {}).get("found_mean") is not None:
            out.append(str(row.get("label") or kind))
        for eq, sub in sorted(((row or {}).get("equipment_types") or {}).items()):
            if (sub or {}).get("found_mean") is not None:
                out.append(str(sub.get("label") or eq))
    return out


def _local_why(name: str, models: list[dict] | None) -> str | None:
    """None when this local model may be chosen, else why not."""
    from .aim_review import local_model, model_socket

    ok, words = model_socket.selectable(model_socket.LOCAL)
    if not ok:
        return words
    if local_model.is_cloud_name(name):
        return NOT_LOCAL_FILE
    if models is None:
        return ENGINE_DOWN
    found = next((m for m in models if m["name"] == name), None)
    if found is None:
        return NOT_INSTALLED
    if not found.get("local_file"):
        return NOT_LOCAL_FILE
    if found["bytes"] > local_model.MAX_MODEL_BYTES:
        return TOO_LARGE
    return None


def _claude_rows() -> list[dict]:
    from . import aim_review_gate, claude_spend
    from .aim_review import model_socket
    from .config import settings

    approved, _ = model_socket.selectable(model_socket.CLAUDE)
    kinds = scored_kinds()
    rows = []
    for name, used in (
        (settings.general_review_lead_model, "every step but the attack"),
        (settings.general_review_strong_model, "the attack on a new checklist"),
    ):
        priced = any(
            str(name).lower() == k or str(name).lower().startswith(k + "-")
            for k in claude_spend.PRICES
        )
        rows.append(
            {
                "name": str(name),
                "engine": model_socket.CLAUDE,
                "used_for": used,
                "approved": approved,
                "priced": priced,
                "scored_kinds": kinds,
                "score_words": f"measured on {len(kinds)} kinds"
                if kinds
                else aim_review_gate.NOT_YET_SCORED,
                "selectable": False,
                "why": CLAUDE_FIXED,
            }
        )
    return rows


def options(conn=None) -> dict:
    """The Administration page's Review model section: the Claude models (fixed, as scored), the installed local models with
    whether each may be chosen and why not, the steps, and what is saved."""
    from . import aim_review_gate, answer_model_choice

    models = installed()
    in_use = answer_model_choice.resolve()
    default = stored(conn)["default"] or in_use.name
    local = [
        {
            "name": m["name"],
            "engine": "local",
            "bytes": m["bytes"],
            "approved": True,
            "priced": True,
            "price_words": "USD 0 (runs on this computer)",
            "score_words": aim_review_gate.local_score_words([m["name"]]),
            "selectable": _local_why(m["name"], models) is None,
            "why": _local_why(m["name"], models),
            "is_default": m["name"] == default,
            "measured": aim_review_gate.LOCAL_MEASURED.get(m["name"]),
        }
        for m in models or []
    ]
    return {
        "claude": _claude_rows(),
        "local": local,
        "engine_down": models is None,
        "engine_down_words": ENGINE_DOWN if models is None else None,
        "steps": list(steps()),
        "answer_model": in_use.name,
        "answer_model_why": in_use.why,
        "stored": stored(conn),
        "history": history(conn),
        "used_by": "Local only runs of the general review; Automatic and Claude never use a local model.",
    }


class Refused(ValueError):
    """A choice that may not be saved; the message is the plain sentence."""


def save(choice: dict, actor: str | None, conn=None) -> dict:
    """Replace the saved setting with `choice` ({"default": model or None, "steps": {step: model}}); every model is checked first
    and nothing is saved when one is refused. An empty default or step clears it."""
    default = str(choice.get("default") or "").strip()
    picks = {
        " ".join(str(k).lower().split()): str(v or "").strip()
        for k, v in (choice.get("steps") or {}).items()
    }
    unknown = sorted(k for k in picks if k not in steps())
    if unknown:
        raise Refused(f"{UNKNOWN_STEP}: {', '.join(unknown)}")
    models = installed()
    for slot, name in [(DEFAULT, default), *picks.items()]:
        if name and (why := _local_why(name, models)):
            raise Refused(f"{name} cannot be chosen for {slot}: {why}")
    when = datetime.now(UTC).isoformat(timespec="seconds")
    conn = conn or connect()
    before = _slots(stored(conn))
    after = {slot: name for slot, name in [(DEFAULT, default), *picks.items()] if name}
    with conn:
        _ensure(conn)
        for slot in sorted(set(before) | set(after)):
            if before.get(slot) != after.get(slot):
                conn.execute(
                    f"INSERT INTO {HISTORY} (slot, old_model, new_model, changed_by, changed_at) VALUES (?, ?, ?, ?, ?)",
                    (slot, before.get(slot), after.get(slot), actor, when),
                )
        conn.execute(f"DELETE FROM {TABLE}")
        for slot, name in [(DEFAULT, default), *sorted(picks.items())]:
            if name:
                conn.execute(
                    f"INSERT INTO {TABLE} (slot, model, set_by, set_at) VALUES (?, ?, ?, ?)",
                    (slot, name, actor, when),
                )
    log.info(
        "review model setting saved: default %s, %d step(s)",
        default or "(answer model)",
        sum(1 for v in picks.values() if v),
    )
    return stored(conn)


def step_choices() -> dict[str, str]:
    """{step group: model} saved per step (empty when none)."""
    return dict(stored()["steps"])


def default_choice() -> str | None:
    """The saved default local model, or None (the review then uses ANSWER_MODEL)."""
    return stored()["default"]


def plan_line(default_name: str, per_step: dict[str, str] | None = None) -> str:
    """The plan's line for a Local only run: the default and each step group whose model differs (`local_model.step_models()`:
    the saved picks and the env setting alike), with the score label of those models (`aim_review_gate.local_score_words`, the
    same per-model source as the measured note)."""
    from . import aim_review_gate
    from .aim_review import local_model

    per_step = per_step or {}
    per = []
    for group, names in local_model.STEP_GROUPS.items():
        models = sorted(
            {
                per_step[n]
                for n in names
                if per_step.get(n) and per_step[n] != default_name
            }
        )
        if models:
            per.append(f"{group}: {', '.join(models)}")
    head = f"Review model: {default_name}" + ("; " + ", ".join(per) if per else "")
    return f"{head} ({aim_review_gate.local_score_words({default_name, *per_step.values()})})."
