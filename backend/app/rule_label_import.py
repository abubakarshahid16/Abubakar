"""Import a label file into the database the SERVER holds (owner decision 1, 11 Nov 2026).

WHY AN IMPORT. The label job writes a database COPY only (`rule_label_job`); the live database is written by the
server and by nothing else. A label file (`rule_label_job.write_export`: ids, hashes, pages, kind, field, state, models,
prompt versions, agreed reading; no quote or answer text) crosses from the copy to the server through this module, and
the server's own check stands between the file and the table.

EVERY ROW IS CHECKED AGAIN, BY CODE, AGAINST THE RULE AS THIS DATABASE HOLDS IT NOW:
  * the rule must still exist (`unknown_rule`): a `standard_requirements` row, or a `rulebook_version` with provenance;
  * the quote hash the file carries must still be the hash of the stored quote text (`skipped_changed_quote`): a label
    belongs to the words it was made on;
  * a row that claims `ai_approved` must also pass `rule_labels.approval_guard` against the stored quote (two named,
    different model families, one accepted prompt version, both answer hashes, a kind and field, the reading re-proved
    against the quote), and the quote must stand word for word on the page it names, in the page text as the app cites
    it, on a page that is not low-confidence OCR. A failing check is never stored as an approval: `refused` (the
    guard, OCR) or `skipped_changed_quote` (the quote no longer stands on its page).
A row that is not `ai_approved` is stored as the file says (a `needs_human` or `quote_not_found` label approves nothing).
The file's `rule_version_id` is not trusted: it is derived again here from the stored rule.

TRUST. `origin: "lab-order12"` is declared by the file itself, and so is the file: the import trusts the ADMIN who places
it in the data directory (the route is admin only). It cannot tell a converter's file from a hand-written one. What the
file cannot do is skip a check: every row is still re-checked by code, as above, with or without the origin.

IDEMPOTENT. A row identical to the stored one is counted as stored and not written again (no new event); a changed row
updates the stored one (the table's trigger appends the event). Nothing is deleted. `rulebook_approval` and every other
existing table are never written.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

from . import rule_label_ocr, rule_labels
from .config import settings
from .rule_label_schema import (
    AI_APPROVED,
    PAPER_KINDS,
    SOURCES,
    STATES,
    create_tables,
    require_on,
)

logger = logging.getLogger(__name__)

EXPORT_FORMAT = "rule-labels-v1"
MAX_FILE_BYTES = 64 * 1024 * 1024
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ImportPathError(ValueError):
    """The path is not a label file under the data directory. Says why, never the path."""


def resolve_data_path(path: str) -> Path:
    """The file a caller named, only when it is a regular .json file of reasonable size INSIDE the data directory
    (symlinks and `..` resolved first). Anything else raises `ImportPathError`."""
    root = Path(settings.data_dir).resolve()
    text = str(path or "").strip()
    if not text or "\x00" in text:
        raise ImportPathError("no_path")
    raw = Path(text)
    target = (raw if raw.is_absolute() else root / raw).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ImportPathError("outside_the_data_directory") from None
    if target.suffix.lower() != ".json":
        raise ImportPathError("not_a_json_file")
    if not target.is_file():
        raise ImportPathError("no_such_file")
    if target.stat().st_size > MAX_FILE_BYTES:
        raise ImportPathError("file_too_large")
    return target


def read_file(path: Path) -> list[Any]:
    """The rows of a label file, or ImportPathError (not JSON, not this format, no rows list)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ImportPathError("not_valid_json") from None
    if (
        not isinstance(data, dict)
        or data.get("format") != EXPORT_FORMAT
        or not isinstance(data.get("rows"), list)
    ):
        raise ImportPathError("not_a_label_file")
    return data["rows"]


def _has(conn, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        is not None
    )


def _stored_rule(conn, source: str, ref: str) -> list[dict] | None:
    """The rule as this database holds it now: one entry per stored quote (document, cited page, quote), or None when the
    rule is not there. A rule-book version may cite more than one place."""
    if source == "requirement":
        if not _has(conn, "standard_requirements"):
            return None
        r = conn.execute(
            "SELECT standard_document_id, page, source_text FROM standard_requirements WHERE id = ?",
            (ref,),
        ).fetchone()
        return (
            None
            if r is None
            else [{"sdid": r[0], "page": r[1], "quote": str(r[2] or "")}]
        )
    if not (_has(conn, "rulebook_version") and _has(conn, "rulebook_provenance")):
        return None
    rows = conn.execute(
        "SELECT p.standard_document_id, p.page, p.quote FROM rulebook_provenance p WHERE p.rule_version_id = ? ORDER BY p.rowid",
        (ref,),
    ).fetchall()
    return [
        {"sdid": r[0], "page": r[1], "quote": str(r[2] or "")} for r in rows
    ] or None


def _clean(row: dict) -> str | None:
    """Why a row is not even readable as a label (None: well formed). The shape only; the meaning is checked later."""
    if (
        row.get("source") not in SOURCES
        or not isinstance(row.get("rule_ref"), str)
        or not row["rule_ref"]
    ):
        return "key"
    if row.get("state") not in STATES:
        return "state"
    if row.get("paper_kind") is not None and row["paper_kind"] not in PAPER_KINDS:
        return "paper_kind"
    if not _HEX64.match(str(row.get("quote_sha256") or "")):
        return "quote_hash"
    if row.get("quote_recovery") not in (None, "page") or (
        row.get("quote_recovery") == "page"
        and row.get("origin") != rule_labels.LAB_ORIGIN
    ):
        return "recovery_not_accepted"  # only a lab row's "page" recovery is re-provable here
    if not isinstance(row.get("labelled_at"), str) or not row["labelled_at"]:
        return "labelled_at"
    return None


def _as_stored(row: dict, version_id: str | None) -> dict:
    reading = row.get("reading")
    return {
        "rule_version_id": version_id,
        "paper_kind": row.get("paper_kind"),
        "field": row.get("field"),
        "state": row["state"],
        "disagreement": row.get("disagreement"),
        "a_model": row.get("a_model"),
        "a_prompt": row.get("a_prompt"),
        "a_answer_sha256": row.get("a_answer_sha256"),
        "b_model": row.get("b_model"),
        "b_prompt": row.get("b_prompt"),
        "b_answer_sha256": row.get("b_answer_sha256"),
        "a_answer_json": None,
        "b_answer_json": None,
        "quote_page": row.get("quote_page"),
        "quote_sha256": row["quote_sha256"],
        "quote_recovery": row.get("quote_recovery"),
        "reading_json": json.dumps(reading, sort_keys=True) if reading else None,
        "labelled_at": row["labelled_at"],
    }


def _approval_failure(
    conn, raw: dict, rule: dict, stored: dict, pages: dict
) -> str | None:
    """The count key a claimed approval fails under, or None when every check holds: the page the row names, the
    approval guard (with the lab prompt only for a lab row), the quote on its page, the page's OCR confidence."""
    from . import compiled_rule_report
    from .compiled_rule_proof import quote_verified

    lab = raw.get("origin") == rule_labels.LAB_ORIGIN
    page = raw.get("quote_page")
    if page != rule["page"] and not (lab and raw.get("quote_recovery") == "page"):
        return "refused"  # the page the row names is not the page the rule cites
    accepted = (
        *rule_labels.ACCEPTED_PROMPTS,
        *(rule_labels.LAB_PROMPTS if lab else ()),
    )
    if rule_labels.approval_guard(stored, rule["quote"], accepted=accepted) is not None:
        return "refused"
    if rule["sdid"] not in pages:
        pages[rule["sdid"]] = (
            compiled_rule_report.pages_of(conn, rule["sdid"]),
            compiled_rule_report.page_origin(conn, rule["sdid"]),
        )
    text, origin = pages[rule["sdid"]]
    if not quote_verified(rule["quote"], text.get(page)):
        return "skipped_changed_quote"
    if rule_label_ocr.quote_is_low(
        conn, rule["sdid"], page, rule["quote"], origin.get(page)
    ):
        return "refused"
    return None


def import_labels(conn: sqlite3.Connection, rows: list[Any]) -> dict:
    """Check and store `rows` on `conn` (the server's own connection). Returns
    {read, stored, skipped_changed_quote, unknown_rule, refused}: counts only. Switch off: raises `SwitchedOff`."""
    require_on()
    create_tables(conn)
    counts = {
        "read": 0,
        "stored": 0,
        "skipped_changed_quote": 0,
        "unknown_rule": 0,
        "refused": 0,
    }
    bridge = rule_labels.bridge_map(conn)
    pages: dict[str, tuple[dict, dict]] = {}
    for raw in rows:
        counts["read"] += 1
        if not isinstance(raw, dict) or _clean(raw) is not None:
            counts["refused"] += 1
            continue
        rule = _stored_rule(conn, raw["source"], raw["rule_ref"])
        if rule is None:
            counts["unknown_rule"] += 1
            continue
        held = next(
            (
                q
                for q in rule
                if rule_labels.quote_hash(q["quote"]) == raw["quote_sha256"]
            ),
            None,
        )
        if held is None:
            counts["skipped_changed_quote"] += 1
            continue
        quote, rule = held["quote"], held
        version_id = (
            raw["rule_ref"]
            if raw["source"] == "rulebook"
            else bridge.get((rule["sdid"], rule["page"], " ".join(quote.split())))
        )
        stored = _as_stored(raw, version_id)
        if raw["state"] == AI_APPROVED:
            failed = _approval_failure(conn, raw, rule, stored, pages)
            if failed:
                counts[failed] += 1
                continue
        elif raw.get("quote_page") is not None and not isinstance(
            raw["quote_page"], int
        ):
            counts["refused"] += 1
            continue
        if _write(conn, raw["source"], raw["rule_ref"], stored):
            counts["stored"] += 1
        else:
            counts["refused"] += 1
    logger.info("rule labels imported: %s", counts)
    return counts


def _write(conn: sqlite3.Connection, source: str, ref: str, cols: dict) -> bool:
    """Insert, or update when it differs; identical is left alone. False when the database's own guard refuses the row."""
    names = tuple(cols)
    try:
        have = conn.execute(
            f"SELECT {', '.join(names)} FROM rule_label WHERE source = ? AND rule_ref = ?",
            (source, ref),
        ).fetchone()
        if have is not None:
            if tuple(have) == tuple(cols.values()):
                return True
            sets = ", ".join(f"{k} = ?" for k in names)
            with conn:
                conn.execute(
                    f"UPDATE rule_label SET {sets} WHERE source = ? AND rule_ref = ?",
                    (*cols.values(), source, ref),
                )
            return True
        with conn:
            conn.execute(
                f"INSERT INTO rule_label (source, rule_ref, {', '.join(names)}) VALUES ({','.join('?' * (len(names) + 2))})",
                (source, ref, *cols.values()),
            )
        return True
    except sqlite3.IntegrityError:
        return False
