"""The rule finishing line's store: the table `rule_finish_step`, reading rules from a rulebook copy, applying a proposal.

Split from `rule_finish` (which holds the pure steps and never imports this module). The table is created only in a COPY of
a database, never in the live one; nothing here writes an original database.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .rule_finish import MODEL_NONE, PASS, RESULTS, STEPS, limit_and_unit

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
    """Create `rule_finish_step` (append-only history; the latest row per rule version and step is the current one)."""
    conn.execute(_TABLE)
    conn.execute(_INDEX)
    conn.commit()


def now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_step(
    conn: sqlite3.Connection,
    rule_version_id: str,
    step: str,
    result: str,
    reason: str,
    evidence: dict | None = None,
    *,
    checker: str,
    model: str,
    run_id: str,
    at: str | None = None,
) -> int:
    """Append one step result. Steps e (AI engineer check) and f (owner sample) are written here by their own processes;
    both must name who checked."""
    if step not in STEPS:
        raise ValueError(f"unknown step {step!r}")
    if result not in RESULTS:
        raise ValueError(f"unknown result {result!r}")
    if step in ("e", "f") and not (checker or "").strip():
        raise ValueError(f"step {step} needs a named checker")
    if (
        not (reason or "").strip()
        or not (run_id or "").strip()
        or not (model or "").strip()
    ):
        raise ValueError("reason, model and run_id are required")
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
            checker or "",
            model,
            run_id,
            at or now_utc(),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


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

ORIGINAL_DB_NAMES = frozenset(
    {"psv-all.sqlite", "compile.sqlite", "combined-run.sqlite", "crsfix-run.sqlite"}
)
_APPLIED = """CREATE TABLE IF NOT EXISTS rule_finish_applied (
    id INTEGER PRIMARY KEY AUTOINCREMENT, rule_version_id TEXT NOT NULL, value REAL, value_low REAL, value_high REAL,
    unit TEXT NOT NULL, comparator TEXT, approver TEXT NOT NULL, at TEXT NOT NULL)"""


def _db_file(conn: sqlite3.Connection) -> str:
    for _, name, path in conn.execute("PRAGMA database_list"):
        if name == "main":
            return path or ""
    return ""


def apply_proposal(
    conn_copy: sqlite3.Connection, rule_version_id: str, proposal: dict, approver: str
) -> dict:
    """Write a proposed value, unit and comparator into the WORK COPY (never automatic: only an explicit call, named
    approver). Refuses an original database and a proposal whose value or unit does not stand in the rule's quote:
    step a must pass with the proposal applied. The rulebook rows stay as they are (append-only); the applied figure is
    kept in `rule_finish_applied` and step a is recorded as pass with reason `proposal_applied`."""
    path = _db_file(conn_copy)
    if not path or Path(path).name in ORIGINAL_DB_NAMES:
        raise PermissionError(
            "refused: an original database; a proposal is applied only in a copy"
        )
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
    result, reason, evidence = limit_and_unit(trial)
    if result != PASS:
        raise ValueError(
            f"refused: the proposal does not stand in the quote ({reason})"
        )
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
    record_step(
        conn_copy,
        rule_version_id,
        "a",
        PASS,
        "proposal_applied",
        dict(evidence, approver=approver),
        checker=approver,
        model=MODEL_NONE,
        run_id="apply-proposal",
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
