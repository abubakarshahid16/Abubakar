"""The rule finishing line's store: the table `rule_finish_step`, reading rules from a rulebook copy, applying a proposal.

Split from `rule_finish` (which holds the pure steps and never imports this module). The table is created only in a COPY of
a database, never in the live one; nothing here writes an original database.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .rule_finish import (
    CODE_STEPS,
    COMPARATORS_ALLOWED,
    FAIL,
    MODEL_NONE,
    PASS,
    RESULTS,
    STEPS,
    conditions_of,
    evidence_source,
    fragments,
    limit_and_unit,
    quote_found,
)
from .rule_finish_figures import implied_comparator
from .rule_finish_guard import require_work_copy

# --------------------------------------------------------------------------- persistence (a COPY of a database only)

_TABLE = """CREATE TABLE IF NOT EXISTS rule_finish_step (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_version_id TEXT NOT NULL,
    step TEXT NOT NULL CHECK (step IN ('a','b','c','d','e','f','g')),
    result TEXT NOT NULL CHECK (result IN ('pass','fail','not_applicable','incomplete')),
    reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    checker TEXT NOT NULL,
    model TEXT NOT NULL,
    run_id TEXT NOT NULL,
    at TEXT NOT NULL)"""
_INDEX = "CREATE INDEX IF NOT EXISTS idx_rule_finish_step ON rule_finish_step(rule_version_id, step, id)"


def ensure_table(conn: sqlite3.Connection) -> None:
    """Create `rule_finish_step` (append-only history; the latest row per rule version and step is the current one).
    Only in a marked work copy (`rule_finish_guard`)."""
    require_work_copy(conn)
    conn.execute(_TABLE)
    conn.execute(_INDEX)
    conn.commit()


def now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _append_step(
    conn: sqlite3.Connection,
    rule_version_id: str,
    step: str,
    result: str,
    reason: str,
    evidence: dict | None,
    *,
    checker: str,
    model: str,
    run_id: str,
    at: str | None = None,
) -> int:
    """The one writer of `rule_finish_step`; module-private: a step is recorded only through `record_code_step` (a to d
    and g, recomputed here), `record_engineer_check` (e), `record_owner_sample` (f) or the repair's own records."""
    if step not in STEPS:
        raise ValueError(f"unknown step {step!r}")
    if result not in RESULTS:
        raise ValueError(f"unknown result {result!r}")
    if (
        not (reason or "").strip()
        or not (run_id or "").strip()
        or not (model or "").strip()
        or not (checker or "").strip()
    ):
        raise ValueError("reason, checker, model and run_id are required")
    ensure_table(conn)
    cur = conn.execute(
        "INSERT INTO rule_finish_step (rule_version_id, step, result, reason, evidence_json, checker, model, run_id, at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            rule_version_id,
            step,
            result,
            reason,
            json.dumps(evidence or {}, sort_keys=True),
            checker,
            model,
            run_id,
            at or now_utc(),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def record_code_step(
    conn: sqlite3.Connection,
    rule: dict,
    step: str,
    pages: dict[int, str] | None = None,
    *,
    run_id: str,
    note: str = "",
    checker: str = "code",
    at: str | None = None,
) -> tuple[str, str, dict]:
    """Steps a, b, c, d and g: the step function is called HERE on the rule and its result is what is written. Nobody
    hands in a result."""
    if step not in CODE_STEPS:
        raise ValueError(f"step {step!r} is not recorded by code")
    result, reason, evidence = {
        "a": lambda: limit_and_unit(rule),
        "b": lambda: evidence_source(rule),
        "c": lambda: fragments(rule, pages),
        "d": lambda: conditions_of(rule),
        "g": lambda: quote_found(rule, pages),
    }[step]()
    _append_step(
        conn,
        rule["version_id"],
        step,
        result,
        f"{note}{reason}",
        evidence,
        checker=checker,
        model=MODEL_NONE,
        run_id=run_id,
        at=at,
    )
    return result, reason, evidence


def _file_evidence(path: str | Path) -> tuple[dict, str, Path]:
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"refused: {p.name} does not exist")
    raw = p.read_bytes()
    try:
        return json.loads(raw), hashlib.sha256(raw).hexdigest(), p
    except ValueError as exc:
        raise ValueError(f"refused: {p.name} is not JSON") from exc


def _rule_key(conn: sqlite3.Connection, version_id: str) -> str:
    found = load_rules_by_version(conn, version_id)
    if not found:
        raise ValueError("no such rule version in this copy")
    return found[0]["rule_key"]


def record_engineer_check(
    conn: sqlite3.Connection,
    rule_version_id: str,
    output_path: str | Path,
    *,
    run_id: str,
) -> str:
    """Step e from the engineer's output file: its sha256 is recomputed here, its verdict must be OK or NOT_OK, it must
    name its checker and the rule it is about (a prefix of this rule's key). Returns the result written."""
    out, digest, path = _file_evidence(output_path)
    verdict = str(out.get("verdict") or "").strip().upper().replace(" ", "_")
    if verdict not in ("OK", "NOT_OK"):
        raise ValueError("refused: the engineer output has no OK or NOT_OK verdict")
    checker = str(out.get("checker") or "").strip()
    prefix = str(out.get("rule_key_prefix") or "")
    if (
        not checker
        or not prefix
        or not _rule_key(conn, rule_version_id).startswith(prefix)
    ):
        raise ValueError(
            "refused: the engineer output names no checker or another rule"
        )
    result = PASS if verdict == "OK" else FAIL
    _append_step(
        conn,
        rule_version_id,
        "e",
        result,
        f"engineer_check_{verdict.lower()}",
        {"file": path.name, "path": str(path), "sha256": digest, "verdict": verdict},
        checker=checker,
        model="Claude chat helper",
        run_id=run_id,
    )
    return result


def record_owner_sample(
    conn: sqlite3.Connection,
    rule_version_id: str,
    sample_id: str,
    tick_path: str | Path,
    *,
    run_id: str,
) -> str:
    """Step f from the owner's tick file: JSON {"sample_id": ..., "ticks": {rule_key: "ok" | "wrong"}}; the sample id must
    match and the rule must be in the file; the sha256 of the file is recomputed here."""
    data, digest, path = _file_evidence(tick_path)
    tick = (data.get("ticks") or {}).get(_rule_key(conn, rule_version_id))
    if (
        not (sample_id or "").strip()
        or data.get("sample_id") != sample_id
        or tick not in ("ok", "wrong")
    ):
        raise ValueError(
            "refused: the tick file does not hold this sample id and this rule's tick"
        )
    result = PASS if tick == "ok" else FAIL
    _append_step(
        conn,
        rule_version_id,
        "f",
        result,
        f"owner_sample_{tick}",
        {"sample_id": sample_id, "path": str(path), "sha256": digest},
        checker="owner",
        model="none: owner tick",
        run_id=run_id,
    )
    return result


def latest_steps(conn: sqlite3.Connection, rule_version_id: str) -> dict[str, dict]:
    """The current row per step for one rule version ({} when none, or when the table does not exist)."""
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT s.* FROM rule_finish_step s WHERE s.rule_version_id = ? AND s.id = "
            "(SELECT MAX(id) FROM rule_finish_step t WHERE t.rule_version_id = s.rule_version_id AND t.step = s.step)",
            (rule_version_id,),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return {}
        raise
    out = {}
    for row in rows:
        r = dict(row)
        r["evidence"] = json.loads(r.pop("evidence_json") or "{}")
        out[r["step"]] = r
    return out


# --------------------------------------------------------------------------- reading rules (any rulebook copy)


def load_rules(
    conn: sqlite3.Connection,
    *,
    standard: str | None = None,
    key_prefix: str | None = None,
) -> list[dict]:
    """The latest version of every rule of `standard` (or whose rule_key starts with `key_prefix`), with its first
    provenance and its applicability rows, as plain dicts. Read only."""
    conn.row_factory = sqlite3.Row
    where, args = [], []
    if standard:
        where.append("r.standard = ?")
        args.append(standard)
    if key_prefix:
        where.append("r.rule_key LIKE ? ESCAPE '\\'")
        args.append(
            key_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            + "%"
        )
    if not where:
        raise ValueError("give a standard or a rule key prefix")
    sql = (
        "SELECT r.id AS rule_id, r.rule_key, r.standard, v.id AS version_id, v.version_no, v.kind, v.field, v.comparator, "
        "v.value, v.value_low, v.value_high, v.value_text, v.unit, v.unit_dimension, v.strength, v.sentence_strength, "
        "v.context_flag FROM rulebook_rule r JOIN rulebook_version v ON v.rule_id = r.id "
        "WHERE "
        + " AND ".join(where)
        + " AND v.version_no = (SELECT MAX(version_no) FROM rulebook_version x WHERE x.rule_id = r.id) "
        "ORDER BY r.rule_key"
    )
    rules = []
    for row in conn.execute(sql, args).fetchall():
        rule = dict(row)
        prov = conn.execute(
            "SELECT standard_document_id, edition, clause, page, quote, quote_start, quote_end, page_source "
            "FROM rulebook_provenance WHERE rule_version_id = ? ORDER BY id LIMIT 1",
            (rule["version_id"],),
        ).fetchone()
        if prov is not None:
            rule.update(dict(prov))
        rule["applicability"] = [
            (a["key_type"], a["value"])
            for a in conn.execute(
                "SELECT key_type, value FROM rulebook_applicability WHERE rule_version_id = ? ORDER BY id",
                (rule["version_id"],),
            )
        ]
        rules.append(rule)
    return rules


# --------------------------------------------------------------------------- applying a proposal (a COPY only, by explicit call)

_APPLIED = """CREATE TABLE IF NOT EXISTS rule_finish_applied (
    id INTEGER PRIMARY KEY AUTOINCREMENT, rule_version_id TEXT NOT NULL, value REAL, value_low REAL, value_high REAL,
    unit TEXT NOT NULL, comparator TEXT, approver TEXT NOT NULL, at TEXT NOT NULL)"""


def _quote(rule: dict) -> str:
    return " ".join(str(rule.get("quote") or "").split())


def comparator_problem(quote: str, proposal: dict) -> str | None:
    """None when the proposal's comparator is the one the quote's own phrase gives THAT figure (a single value), or
    when a range proposal has no comparator and its ends are the quote's low (>=) and high (<=) ends; else the reason."""
    unit = proposal.get("unit")
    if proposal.get("value") is not None:
        wanted = implied_comparator(quote, proposal["value"], unit)
        given = proposal.get("comparator")
        if given not in COMPARATORS_ALLOWED:
            return "comparator_not_allowed"
        return None if wanted == given else "comparator_not_implied_by_this_figure"
    low = implied_comparator(quote, proposal["value_low"], unit)
    high = implied_comparator(quote, proposal["value_high"], unit)
    ok = low == ">=" and high == "<=" and proposal.get("comparator") in (None, "")
    return None if ok else "range_ends_not_implied"


def apply_proposal(
    conn_copy: sqlite3.Connection, rule_version_id: str, proposal: dict, approver: str
) -> dict:
    """Write a proposed value, unit and comparator into the WORK COPY (never automatic: only an explicit call, named
    approver). Refuses an original database and a proposal whose value or unit does not stand in the rule's quote:
    step a must pass with the proposal applied. The rulebook rows stay as they are (append-only); the applied figure is
    kept in `rule_finish_applied` and step a is recorded as pass with reason `proposal_applied`."""
    require_work_copy(conn_copy)
    if not (approver or "").strip():
        raise ValueError("an approver is required")
    rules = load_rules_by_version(conn_copy, rule_version_id)
    if not rules:
        raise ValueError("no such rule version in this copy")
    unit = proposal.get("unit")
    trial = dict(
        rules[0],
        value=proposal.get("value"),
        value_low=proposal.get("value_low"),
        value_high=proposal.get("value_high"),
        unit=unit,
        comparator=proposal.get("comparator"),
    )
    if trial["value"] is None and trial["value_low"] is None:
        raise ValueError("a proposal needs a value")
    result, reason, _ = limit_and_unit(trial)
    if result != PASS:
        raise ValueError(
            f"refused: the proposal does not stand in the quote ({reason})"
        )
    wrong = comparator_problem(_quote(rules[0]), trial)
    if wrong:
        raise ValueError(f"refused: the comparator is not the quote's own ({wrong})")
    ensure_table(conn_copy)
    conn_copy.execute(_APPLIED)
    at = now_utc()
    conn_copy.execute(
        "INSERT INTO rule_finish_applied (rule_version_id, value, value_low, value_high, unit, comparator, approver, at) VALUES (?,?,?,?,?,?,?,?)",
        (
            rule_version_id,
            trial["value"],
            trial["value_low"],
            trial["value_high"],
            unit,
            trial["comparator"],
            approver,
            at,
        ),
    )
    conn_copy.commit()
    record_code_step(
        conn_copy,
        overlay_applied(conn_copy, rules[0]),
        "a",
        run_id="apply-proposal",
        note="proposal_applied: ",
        checker=approver,
        at=at,
    )
    return trial


def overlay_applied(conn: sqlite3.Connection, rule: dict) -> dict:
    """The rule with the latest applied proposal of this copy laid over its value, unit and comparator."""
    try:
        row = conn.execute(
            "SELECT value, value_low, value_high, unit, comparator FROM rule_finish_applied WHERE rule_version_id = ? ORDER BY id DESC LIMIT 1",
            (rule["version_id"],),
        ).fetchone()
    except sqlite3.OperationalError:
        row = None
    if row is not None:
        rule = dict(
            rule,
            value=row[0],
            value_low=row[1],
            value_high=row[2],
            unit=row[3],
            comparator=row[4],
        )
    return _overlay_repairs(conn, rule)


_REPAIR = """CREATE TABLE IF NOT EXISTS rule_finish_repair (
    id INTEGER PRIMARY KEY AUTOINCREMENT, rule_version_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('field','comparator','figure','condition','exception')),
    payload_json TEXT NOT NULL, approver TEXT NOT NULL, at TEXT NOT NULL)"""


def _overlay_repairs(conn: sqlite3.Connection, rule: dict) -> dict:
    """Append-only repair rows of this copy laid over the rule: field, comparator, the figures (one per condition),
    condition rows added to its applicability, and its exceptions."""
    try:
        rows = conn.execute(
            "SELECT kind, payload_json FROM rule_finish_repair WHERE rule_version_id = ? ORDER BY id",
            (rule["version_id"],),
        ).fetchall()
    except sqlite3.OperationalError:
        return rule
    out = dict(rule)
    figures, conditions, exceptions = [], [], list(rule.get("exceptions") or ())
    for kind, payload in rows:
        item = json.loads(payload)
        if kind == "field":
            out["field"] = item["text"]
        elif kind == "comparator":
            out["comparator"] = item["text"]
        elif kind == "figure":
            figures.append(item)
        elif kind == "condition":
            conditions.append(("condition", item["text"]))
        elif kind == "exception":
            exceptions.append(item["text"])
    if figures:
        out["figures"] = figures
        if len(figures) == 1 and figures[0].get("value") is not None:
            out["value"], out["unit"] = figures[0]["value"], figures[0].get("unit")
    out["applicability"] = [*out.get("applicability", ()), *conditions]
    out["exceptions"] = exceptions
    return out


def load_rules_by_version(conn: sqlite3.Connection, version_id: str) -> list[dict]:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT r.rule_key FROM rulebook_version v JOIN rulebook_rule r ON r.id = v.rule_id WHERE v.id = ?",
        (version_id,),
    ).fetchone()
    if row is None:
        return []
    return [
        r
        for r in load_rules(conn, key_prefix=row["rule_key"])
        if r["version_id"] == version_id
    ]
