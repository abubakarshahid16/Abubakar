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
import os
import sqlite3
from pathlib import Path

from .rule_finish import (
    CODE_STEPS,
    COMPARATORS_ALLOWED,
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
from .rule_finish_guard import require_work_copy
from .rule_finish_store import (
    _append_step,
    latest_steps,
    load_rules_by_version,
    now_utc,
    overlay_applied,
)

CHECKER_KIND = "ai_engineer_chat_helper"
CHECKER_KINDS = frozenset({CHECKER_KIND})  # matched by equality, never by substring
STALE = "stale"
_ISSUED = """CREATE TABLE IF NOT EXISTS rule_finish_issued (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL CHECK (kind IN ('e','f')), rule_version_id TEXT NOT NULL,
    content_sha256 TEXT NOT NULL, sample_id TEXT, folder TEXT, input_sha256 TEXT NOT NULL, path TEXT NOT NULL,
    issued_at TEXT NOT NULL)"""


def quote_sha256(rule: dict) -> str:
    return hashlib.sha256(
        " ".join(str(rule.get("quote") or "").split()).encode("utf-8")
    ).hexdigest()


def content_sha256(rule: dict) -> str:
    """The sha256 of the rule's EFFECTIVE content: its figures, unit, comparator, conditions, exceptions and the
    evidence-source decision. A change to any of them is a change of content, and a check bound to the old content is
    stale."""
    payload = {
        "value": rule.get("value"),
        "value_low": rule.get("value_low"),
        "value_high": rule.get("value_high"),
        "unit": rule.get("unit"),
        "comparator": rule.get("comparator"),
        "figures": sorted(
            json.dumps(f, sort_keys=True) for f in rule.get("figures") or []
        ),
        "conditions": sorted(
            json.dumps([k, v]) for k, v in rule.get("applicability") or []
        ),
        "exceptions": sorted(str(e) for e in rule.get("exceptions") or []),
        "evidence_source": evidence_source(rule)[1],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _bound_to(evidence: dict, rule_version_id: str, rule: dict) -> bool:
    return (
        evidence.get("rule_version_id") == rule_version_id
        and evidence.get("quote_sha256") == quote_sha256(rule)
        and evidence.get("content_sha256") == content_sha256(rule)
    )


def rule_of(conn: sqlite3.Connection, rule_version_id: str) -> dict:
    """The rule version as the work copy holds it, applied proposals and repairs laid over, and the engineer's
    `confirmed_figures` when a PASS engineer check is bound to this exact version, quote and content."""
    found = load_rules_by_version(conn, rule_version_id)
    if not found:
        raise ValueError("no such rule version in this copy")
    rule = overlay_applied(conn, found[0])
    row = latest_steps(conn, rule_version_id).get("e")
    if (
        row
        and row["result"] == PASS
        and _bound_to(row["evidence"], rule_version_id, rule)
    ):
        rule = dict(
            rule, confirmed_figures=row["evidence"].get("confirmed_figures") or []
        )
    return rule


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


def _issued(
    conn: sqlite3.Connection,
    kind: str,
    version_id: str,
    content: str,
    input_sha: object,
    **where,
) -> bool:
    """An input (kind e) or sample sheet (kind f) with this sha256 was ISSUED by this tool for this version and content."""
    try:
        rows = conn.execute(
            "SELECT sample_id, folder FROM rule_finish_issued WHERE kind = ? AND rule_version_id = ? AND content_sha256 = ? "
            "AND input_sha256 = ?",
            (kind, version_id, content, str(input_sha)),
        ).fetchall()
    except sqlite3.OperationalError:
        return False
    return any(
        all(
            dict(zip(("sample_id", "folder"), r, strict=True)).get(k) == v
            for k, v in where.items()
        )
        for r in rows
    )


def _issue(
    conn, kind: str, rule: dict, document: dict, out_dir: str | Path, name: str, **extra
) -> tuple[Path, str]:
    require_work_copy(conn)
    conn.execute(_ISSUED)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / name
    raw = json.dumps(document, indent=1, sort_keys=True).encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
    digest = hashlib.sha256(raw).hexdigest()
    conn.execute(
        "INSERT INTO rule_finish_issued (kind, rule_version_id, content_sha256, sample_id, folder, input_sha256, path, issued_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            kind,
            rule["version_id"],
            content_sha256(rule),
            extra.get("sample_id"),
            extra.get("folder"),
            digest,
            str(path),
            now_utc(),
        ),
    )
    conn.commit()
    return path, digest


def _rule_document(rule: dict) -> dict:
    keys = (
        "rule_key",
        "version_id",
        "standard",
        "field",
        "kind",
        "comparator",
        "value",
        "value_low",
        "value_high",
        "unit",
        "figures",
        "exceptions",
        "applicability",
        "strength",
        "clause",
        "page",
        "quote",
    )
    return {
        **{k: rule.get(k) for k in keys},
        "quote_sha256": quote_sha256(rule),
        "content_sha256": content_sha256(rule),
    }


def make_engineer_input(
    conn: sqlite3.Connection,
    rule_version_id: str,
    out_dir: str | Path,
    pages_db: str | Path,
) -> tuple[Path, str]:
    """The input for the engineer helper, written by CODE: the rule's fields and content hash, and the standard's pages
    named by the rule's page and the next. Its sha256 is recorded as ISSUED; the engineer's output must carry it."""
    rule = rule_of(conn, rule_version_id)
    pages = _pages(rule, pages_db)
    wanted = {
        str(p): pages.get(p) for p in (rule["page"], rule["page"] + 1) if pages.get(p)
    }
    document = {
        "kind": "engineer_input",
        "rule": _rule_document(rule),
        "pages": wanted,
        "answer_with": [
            "rule_key",
            "rule_version_id",
            "quote_sha256",
            "content_sha256",
            "input_sha256",
            "checker_kind",
            "verdict",
            "confirmed_figures [{value, unit, comparator}]",
        ],
    }
    name = f"{rule['rule_key'][:12]}-{rule_version_id[:12]}-{content_sha256(rule)[:12]}.input.json"
    return _issue(conn, "e", rule, document, out_dir, name)


def make_sample_sheet(
    conn: sqlite3.Connection,
    rule_version_id: str,
    out_dir: str | Path,
    sample_id: str,
    folder: str,
) -> tuple[Path, str]:
    """The owner's sample sheet for one rule, written by code; its sha256 is recorded as ISSUED for this sample id and
    folder; the owner's tick file must carry it."""
    if not (sample_id or "").strip() or not (folder or "").strip():
        raise ValueError("a sample id and a folder are required")
    rule = rule_of(conn, rule_version_id)
    document = {
        "kind": "sample_sheet",
        "sample_id": sample_id,
        "folder": folder,
        "rule": _rule_document(rule),
    }
    name = f"{sample_id}-{rule['rule_key'][:12]}-{rule_version_id[:12]}.sheet.json"
    return _issue(
        conn, "f", rule, document, out_dir, name, sample_id=sample_id, folder=folder
    )


def _valid_figures(figures: object) -> bool:
    return isinstance(figures, list) and all(
        isinstance(f, dict)
        and _is_num(f.get("value"))
        and isinstance(f.get("unit"), str)
        and f["unit"].strip()
        and f.get("comparator") in COMPARATORS_ALLOWED
        for f in figures
    )


def _is_num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _engineer_problems(conn, rule: dict, version_id: str, data: dict) -> list[str]:
    problems = []
    if str(data.get("verdict") or "").strip().upper().replace(" ", "_") not in (
        "OK",
        "NOT_OK",
    ):
        problems.append("no OK or NOT_OK verdict")
    if data.get("checker_kind") not in CHECKER_KINDS:
        problems.append("checker_kind is not of the closed set")
    if (
        any(
            k in data
            for k in ("rule_keys", "rules", "rule_key_prefixes", "rule_key_prefix")
        )
        or data.get("rule_key") != rule["rule_key"]
    ):
        problems.append("the file must carry this rule's FULL key, one rule only")
    if data.get("rule_version_id") != version_id:
        problems.append("bound to another version")
    if data.get("quote_sha256") != quote_sha256(rule):
        problems.append("bound to another quote")
    if data.get("content_sha256") != content_sha256(rule):
        problems.append("bound to other content (the rule changed after this check)")
    if not _valid_figures(data.get("confirmed_figures")):
        problems.append("confirmed_figures missing or malformed")
    if not _issued(
        conn, "e", version_id, content_sha256(rule), data.get("input_sha256")
    ):
        problems.append(
            "input_sha256 is not an input issued for this version and content"
        )
    return problems


def record_engineer_check(
    conn: sqlite3.Connection,
    rule_version_id: str,
    output_path: str | Path,
    *,
    run_id: str,
) -> str:
    """Step e. The output file must be the answer to an input this tool ISSUED for this version and content (it carries
    that input's sha256), name the rule by its full key, and be bound to the version, the quote hash and the content hash;
    its checker kind is of the closed set (equality), its verdict OK or NOT_OK, and it carries confirmed_figures. The file's
    sha256 is recomputed here."""
    rule = rule_of(conn, rule_version_id)
    data, digest, path = _file(output_path)
    problems = _engineer_problems(conn, rule, rule_version_id, data)
    if problems:
        raise ValueError("refused: " + "; ".join(problems))
    verdict = str(data["verdict"]).strip().upper().replace(" ", "_")
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
            "content_sha256": content_sha256(rule),
            "input_sha256": data["input_sha256"],
            "confirmed_figures": data["confirmed_figures"],
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
    """Step f. The owner's tick file: {"sample_id", "folder", "input_sha256" (the sheet issued for this sample), "ticks":
    {version_id: {"tick": "ok"|"wrong", "quote_sha256", "content_sha256"}}}. Every binding must match; the file's sha256 is
    recomputed here."""
    rule = rule_of(conn, rule_version_id)
    data, digest, path = _file(tick_path)
    tick = (data.get("ticks") or {}).get(rule_version_id) or {}
    folder = str(data.get("folder") or "").strip()
    ok = (
        (sample_id or "").strip()
        and data.get("sample_id") == sample_id
        and tick.get("tick") in ("ok", "wrong")
        and tick.get("quote_sha256") == quote_sha256(rule)
        and tick.get("content_sha256") == content_sha256(rule)
        and _issued(
            conn,
            "f",
            rule_version_id,
            content_sha256(rule),
            data.get("input_sha256"),
            sample_id=sample_id,
            folder=folder,
        )
    )
    if not ok:
        raise ValueError(
            "refused: the tick file is not bound to an issued sheet for this sample, folder, version, quote and content"
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
            "content_sha256": content_sha256(rule),
            "input_sha256": data["input_sha256"],
        },
        checker="owner",
        model="none: owner tick",
        run_id=run_id,
    )
    return result


def current_steps(conn: sqlite3.Connection, rule_version_id: str) -> dict[str, str]:
    """The latest result per step, with an e or f that is bound to another version, quote or content shown as `stale`."""
    latest = latest_steps(conn, rule_version_id)
    rule = overlay_applied(conn, load_rules_by_version(conn, rule_version_id)[0])
    out = {}
    for step, row in latest.items():
        stale = (
            step in ("e", "f")
            and row["result"] in (PASS, FAIL)
            and not _bound_to(row["evidence"], rule_version_id, rule)
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
