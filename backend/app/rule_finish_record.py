"""Recording the steps of the rule finishing line, each bound to the rule version and its quote.

  a, b, c, d, g  `record_code_step(conn, rule_version_id, step)`: the rule is loaded from the work copy (with its applied
                 repairs) and the standard's pages from the pages database, read only, HERE; the step function is called
                 here and its result is what is written. Nobody hands in a rule, pages or a result.
  e              `record_engineer_check`: an engineer output file of the closed checker kind, naming this rule by at least
                 8 characters of its full key; bound to the full key, the version id and the quote hash.
  f              `record_owner_sample`: the owner's tick file for this version and quote, with sample id and folder.

An e or f that is bound to another version or another quote is STALE and never counts (`current_steps`). Any applied
change sets both back to incomplete (`reset_checks`); history stays.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from .rule_finish import (
    CODE_STEPS,
    FAIL,
    INCOMPLETE,
    MODEL_NONE,
    PASS,
    conditions_of,
    evidence_source,
    fragments,
    limit_and_unit,
    quote_found,
)
from .rule_finish_store import (
    _append_step,
    latest_steps,
    load_rules_by_version,
    overlay_applied,
)

CHECKER_KIND = "ai_engineer_chat_helper"
MIN_KEY_PREFIX = 8
STALE = "stale"


def quote_sha256(rule: dict) -> str:
    return hashlib.sha256(
        " ".join(str(rule.get("quote") or "").split()).encode("utf-8")
    ).hexdigest()


def rule_of(conn: sqlite3.Connection, rule_version_id: str) -> dict:
    """The rule version as the work copy holds it, applied proposals and repairs laid over."""
    found = load_rules_by_version(conn, rule_version_id)
    if not found:
        raise ValueError("no such rule version in this copy")
    return overlay_applied(conn, found[0])


def _pages(rule: dict, pages_db: str | Path | None) -> dict[int, str]:
    if pages_db is None:
        raise ValueError("steps c and g need the pages database (pages_db)")
    from .compiled_rule_report import pages_of

    conn = sqlite3.connect(f"file:{pages_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return pages_of(conn, rule["standard_document_id"])
    finally:
        conn.close()


def record_code_step(
    conn: sqlite3.Connection,
    rule_version_id: str,
    step: str,
    *,
    run_id: str,
    pages_db: str | Path | None = None,
    note: str = "",
    checker: str = "code",
    at: str | None = None,
) -> tuple[str, str, dict]:
    if step not in CODE_STEPS:
        raise ValueError(f"step {step!r} is not recorded by code")
    rule = rule_of(conn, rule_version_id)
    pages = _pages(rule, pages_db) if step in ("c", "g") else None
    result, reason, evidence = {
        "a": lambda: limit_and_unit(rule),
        "b": lambda: evidence_source(rule),
        "c": lambda: fragments(rule, pages),
        "d": lambda: conditions_of(rule),
        "g": lambda: quote_found(rule, pages),
    }[step]()
    _append_step(
        conn,
        rule_version_id,
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


def _file(path: str | Path) -> tuple[dict, str, Path]:
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"refused: {p.name} does not exist")
    raw = p.read_bytes()
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"refused: {p.name} is not JSON") from exc
    if not isinstance(data, dict):
        raise ValueError(f"refused: {p.name} is not one record")
    return data, hashlib.sha256(raw).hexdigest(), p


def _checker_kind(data: dict) -> str | None:
    text = " ".join(
        str(data.get("checker_kind") or data.get("checker") or "").lower().split()
    )
    return (
        CHECKER_KIND
        if (
            text == CHECKER_KIND
            or ("claude chat helper" in text and "engineer" in text)
        )
        else None
    )


def _file_used_elsewhere(
    conn: sqlite3.Connection, step: str, digest: str, version_id: str
) -> bool:
    try:
        rows = conn.execute(
            "SELECT rule_version_id, evidence_json FROM rule_finish_step WHERE step = ?",
            (step,),
        ).fetchall()
    except sqlite3.OperationalError:
        return False
    return any(
        v != version_id and json.loads(e).get("sha256") == digest for v, e in rows
    )


def record_engineer_check(
    conn: sqlite3.Connection,
    rule_version_id: str,
    output_path: str | Path,
    *,
    run_id: str,
) -> str:
    """Step e. The output file must record ONE rule, name it by at least 8 characters that start its full key, carry an
    OK or NOT_OK verdict and a checker of the closed kind; a version id or quote hash inside it must match. The file's
    sha256 is recomputed here and a file already used for another version is refused (no replay)."""
    rule = rule_of(conn, rule_version_id)
    data, digest, path = _file(output_path)
    verdict = str(data.get("verdict") or "").strip().upper().replace(" ", "_")
    prefix = data.get("rule_key_prefix")
    problems = []
    if verdict not in ("OK", "NOT_OK"):
        problems.append("no OK or NOT_OK verdict")
    if _checker_kind(data) is None:
        problems.append("checker is not of the closed engineer kind")
    if (
        not isinstance(prefix, str)
        or len(prefix) < MIN_KEY_PREFIX
        or not rule["rule_key"].startswith(prefix)
    ):
        problems.append("the rule key prefix is too short or is not this rule's")
    if any(k in data for k in ("rule_keys", "rules", "rule_key_prefixes")):
        problems.append("one output file records one rule only")
    if data.get("rule_version_id", rule_version_id) != rule_version_id or data.get(
        "quote_sha256", quote_sha256(rule)
    ) != quote_sha256(rule):
        problems.append("bound to another version or quote")
    if _file_used_elsewhere(conn, "e", digest, rule_version_id):
        problems.append("this output file was recorded for another version")
    if problems:
        raise ValueError("refused: " + "; ".join(problems))
    result = PASS if verdict == "OK" else FAIL
    _append_step(
        conn,
        rule_version_id,
        "e",
        result,
        f"engineer_check_{verdict.lower()}",
        {
            "file": path.name,
            "path": str(path),
            "sha256": digest,
            "verdict": verdict,
            "rule_key": rule["rule_key"],
            "rule_version_id": rule_version_id,
            "quote_sha256": quote_sha256(rule),
        },
        checker=CHECKER_KIND,
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
    """Step f. The owner's tick file: {"sample_id", "folder", "ticks": {version_id: {"tick": "ok"|"wrong",
    "quote_sha256": ...}}}. The sample id, the version id and the quote hash must match; the sha256 is recomputed here."""
    rule = rule_of(conn, rule_version_id)
    data, digest, path = _file(tick_path)
    tick = (data.get("ticks") or {}).get(rule_version_id) or {}
    folder = str(data.get("folder") or "").strip()
    ok = (
        (sample_id or "").strip()
        and data.get("sample_id") == sample_id
        and folder
        and tick.get("tick") in ("ok", "wrong")
        and tick.get("quote_sha256") == quote_sha256(rule)
    )
    if not ok:
        raise ValueError(
            "refused: the tick file holds no tick for this sample, folder, version and quote"
        )
    result = PASS if tick["tick"] == "ok" else FAIL
    _append_step(
        conn,
        rule_version_id,
        "f",
        result,
        f"owner_sample_{tick['tick']}",
        {
            "sample_id": sample_id,
            "folder": folder,
            "path": str(path),
            "sha256": digest,
            "rule_version_id": rule_version_id,
            "quote_sha256": quote_sha256(rule),
        },
        checker="owner",
        model="none: owner tick",
        run_id=run_id,
    )
    return result


def current_steps(conn: sqlite3.Connection, rule_version_id: str) -> dict[str, str]:
    """The latest result per step, with an e or f that is bound to another version or quote shown as `stale`."""
    latest, current = (
        latest_steps(conn, rule_version_id),
        quote_sha256(rule_of(conn, rule_version_id)),
    )
    out = {}
    for step, row in latest.items():
        bound = row["evidence"]
        stale = (
            step in ("e", "f")
            and row["result"] in (PASS, FAIL)
            and (
                bound.get("rule_version_id") != rule_version_id
                or bound.get("quote_sha256") != current
            )
        )
        out[step] = STALE if stale else row["result"]
    return out


def reset_checks(
    conn: sqlite3.Connection, rule_version_id: str, who: str, at: str | None = None
) -> None:
    """After any applied change the engineer check (e) and the owner sample (f) no longer stand: both go back to
    incomplete (history stays)."""
    for step in ("e", "f"):
        _append_step(
            conn,
            rule_version_id,
            step,
            INCOMPLETE,
            "changed_after_check",
            {"approver": who},
            checker=who,
            model=MODEL_NONE,
            run_id="changed-after-check",
            at=at,
        )
