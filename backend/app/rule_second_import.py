"""Import the second-model approval file into the database the SERVER holds (planner, 25 Nov 2026; built like
`rule_label_import`). The pass writes a database COPY only (`rule_second_approval`); its file crosses to the server here.

EVERY APPROVAL IS CHECKED AGAIN, BY CODE, AGAINST THE LIVE BOOK BEFORE IT LANDS:
  * the rule exists here (`unknown_rule`) and its stored label is still `needs_human` (`not_needs_human_here`): a second
    approval is only ever of such a rule, and `rule_label` is never written;
  * the file's quote hash is the hash of the quote held here (`changed_quote`), and for an approval the quote stands word for
    word on the page it names in this database's page text (`quote_not_on_page`);
  * the row's shape (`refused`): its state, approver, model, the answer hash of its answer, and for an approval the agreeing
    pass, kind and reading.
APPEND-ONLY AND IDEMPOTENT: a row already held identically is counted `already_held` and not written; a row held
DIFFERENTLY is never changed (`conflict`). Samples and measures are added the same way, so the gate (`gate`) reads the
measure the copy made. REFUSES while a review is queued or running (`ReviewRunning`): nothing changes under a review.
DRY RUN: every check runs and the counts are what would be added; nothing is written and no table is created.
Counts are by standards family (`by_family`)."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter
from pathlib import Path

from . import compiled_rule_report, rule_labels
from . import rule_second_approval as RS
from .compiled_rule_proof import quote_verified
from .rule_label_job import family_of
from .rule_label_schema import NEEDS_HUMAN, require_on

log = logging.getLogger(__name__)


class ReviewRunning(RuntimeError):
    """A review is queued or running on this database: the import waits."""


class NotASecondFile(ValueError):
    """Not a second-approval file of this format."""


def read_file(path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise NotASecondFile("not_valid_json") from None
    if not isinstance(data, dict) or data.get("format") != RS.EXPORT_FORMAT:
        raise NotASecondFile("not_a_second_approval_file")
    if not all(
        isinstance(data.get(k), list) for k in ("approvals", "samples", "measures")
    ):
        raise NotASecondFile("not_a_second_approval_file")
    return data


def review_running(conn) -> bool:
    have = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    return (
        "review_run_id" in have
        and conn.execute(
            "SELECT 1 FROM jobs WHERE review_run_id IS NOT NULL AND state IN ('queued', 'running', 'retrying') LIMIT 1"
        ).fetchone()
        is not None
    )


def _shape_problem(row: dict) -> bool:
    if (
        not isinstance(row, dict)
        or set(row) != set(RS.APPROVAL_COLUMNS)
        or row["source"] != "requirement"
    ):
        return True
    if (
        row["state"] not in (RS.APPROVED, RS.REFUSED)
        or row["approver"] != RS.APPROVER
        or not str(row["model"] or "").strip()
    ):
        return True
    if not isinstance(row["quote_page"], int) or isinstance(row["quote_page"], bool):
        return True
    try:
        answer = json.loads(row["answer_json"])
    except (TypeError, ValueError):
        return True
    if rule_labels.answer_hash(answer) != row["answer_sha256"]:
        return True
    if row["state"] == RS.APPROVED:
        return (
            row["agrees_with"] not in ("a", "b")
            or not row["paper_kind"]
            or not row["reading_json"]
            or row["refused_because"]
        )
    return not row["refused_because"]


def _check(conn, row: dict, pages: dict) -> tuple[str, str]:
    """(why the row does not land, or "", the rule's standards family) by code, against this database."""
    if _shape_problem(row):
        return "refused", "unknown"
    rule = conn.execute(
        "SELECT s.standard_document_id, s.page, s.source_text, COALESCE(d.filename, s.standard_document_id) FROM"
        " standard_requirements s LEFT JOIN documents d ON d.id = s.standard_document_id WHERE s.id = ?", (row["rule_ref"],)
    ).fetchone()  # fmt: skip
    if rule is None:
        return "unknown_rule", "unknown"
    fam = family_of(str(rule[3]))
    label = conn.execute(
        "SELECT state FROM rule_label WHERE source = 'requirement' AND rule_ref = ?",
        (row["rule_ref"],),
    ).fetchone()
    if label is None or label[0] != NEEDS_HUMAN:
        return "not_needs_human_here", fam
    if (
        rule_labels.quote_hash(" ".join(str(rule[2] or "").split()))
        != row["quote_sha256"]
    ):
        return "changed_quote", fam
    if row["state"] == RS.APPROVED:
        if rule[0] not in pages:
            pages[rule[0]] = compiled_rule_report.pages_of(conn, rule[0])
        if row["quote_page"] != rule[1] or not quote_verified(
            " ".join(str(rule[2]).split()), pages[rule[0]].get(rule[1])
        ):
            return "quote_not_on_page", fam
    return "", fam


def _held(conn, table: str, keys: dict, cols) -> tuple | None:
    where = " AND ".join(f"{k} = ?" for k in keys)
    return conn.execute(
        f"SELECT {', '.join(cols)} FROM {table} WHERE {where}", tuple(keys.values())
    ).fetchone()


def import_second(
    conn: sqlite3.Connection, data: dict, *, dry_run: bool = False
) -> dict:
    """Check and add the file's rows on `conn` (the server's own connection). Returns counts only: approvals by outcome and
    by family, samples and measures added. Dry run: the same checks and counts, nothing written."""
    require_on()
    if review_running(conn):
        raise ReviewRunning("a review is queued or running; import after it ends")
    tables = RS.has_tables(conn)
    if not dry_run:
        RS.create(conn)
        tables = True
    counts: Counter = Counter()
    by_family: dict[str, Counter] = {}
    pages: dict = {}
    for row in data["approvals"]:
        why, fam = _check(conn, row, pages)
        if not why and tables:
            have = _held(
                conn,
                "rule_second_approval",
                {"source": row["source"], "rule_ref": row["rule_ref"]},
                RS.APPROVAL_COLUMNS,
            )
            why = (
                ""
                if have is None
                else (
                    "already_held"
                    if tuple(have) == tuple(row[c] for c in RS.APPROVAL_COLUMNS)
                    else "conflict"
                )
            )
        outcome = why or ("would_add" if dry_run else "added") + ":" + row["state"]
        counts[outcome] += 1
        by_family.setdefault(fam, Counter())[outcome] += 1
        if not why and not dry_run:
            conn.execute(f"INSERT INTO rule_second_approval ({', '.join(RS.APPROVAL_COLUMNS)}) VALUES"
                         f" ({', '.join('?' * len(RS.APPROVAL_COLUMNS))})", tuple(row[c] for c in RS.APPROVAL_COLUMNS))  # fmt: skip
    for table, cols, key, rows in (("rule_second_sample", RS.SAMPLE_COLUMNS, ("sample_id", "source", "rule_ref"), data["samples"]),
                                   ("rule_second_measure", RS.MEASURE_COLUMNS, ("sample_id", "measured_at"), data["measures"])):  # fmt: skip
        for row in rows:
            if not isinstance(row, dict) or set(row) != set(cols):
                counts[f"{table}:refused"] += 1
                continue
            have = (
                _held(conn, table, {k: row[k] for k in key}, cols) if tables else None
            )
            if have is not None:
                counts[
                    f"{table}:{'already_held' if tuple(have) == tuple(row[c] for c in cols) else 'conflict'}"
                ] += 1
                continue
            counts[f"{table}:{'would_add' if dry_run else 'added'}"] += 1
            if not dry_run:
                conn.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                             tuple(row[c] for c in cols))  # fmt: skip
    if not dry_run:
        conn.commit()
    out = {
        **dict(counts),
        "dry_run": dry_run,
        "by_family": {k: dict(v) for k, v in sorted(by_family.items())},
    }
    log.info(
        "second approvals imported: %s",
        {k: v for k, v in out.items() if k != "by_family"},
    )
    return out
