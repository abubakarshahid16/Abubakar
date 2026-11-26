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
A sample row lands only for a rule whose second approval is held (or added with it) and with a verdict of the two words;
a measure lands only when code recounts it from its sample rows (`measure_does_not_match`), so no file can open the gate
with a count of its own. ONE TRANSACTION (BEGIN IMMEDIATE), the review question asked again inside it, rolled back on error.
DRY RUN (the default): every check runs and the counts are what would be added; nothing is written and no table is created.
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


class ImportBusy(RuntimeError):
    """The import cannot take the database now (nothing is written)."""


class ReviewRunning(ImportBusy):
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
    conn: sqlite3.Connection, data: dict, *, dry_run: bool = True
) -> dict:
    """Check and add the file's rows on `conn` (the server's own connection). Returns counts only: approvals by outcome and
    by family, samples and measures added. Dry run (the default): the same checks and counts, nothing written.

    A write is ONE transaction taken with BEGIN IMMEDIATE (no other writer, a review's queue among them, can start under it);
    the "no review queued or running" question is asked again inside it, and any error rolls every row back."""
    require_on()
    if review_running(conn):
        raise ReviewRunning("a review is queued or running; import after it ends")
    if dry_run:
        return _report(_add(conn, data, dry_run=True, tables=RS.has_tables(conn)), dry_run)
    if conn.in_transaction:
        raise ImportBusy("this connection holds an open transaction; nothing is imported")
    RS.create(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        if review_running(conn):
            raise ReviewRunning("a review is queued or running; import after it ends")
        counts = _add(conn, data, dry_run=False, tables=True)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return _report(counts, dry_run)


def _report(counts: tuple[Counter, dict], dry_run: bool) -> dict:
    flat, by_family = counts
    out = {**dict(flat), "dry_run": dry_run, "by_family": {k: dict(v) for k, v in sorted(by_family.items())}}
    log.info("second approvals imported: %s", {k: v for k, v in out.items() if k != "by_family"})
    return out


def _insert(conn, table: str, cols, row: dict) -> None:
    conn.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                 tuple(row[c] for c in cols))  # fmt: skip


def _add(conn, data: dict, *, dry_run: bool, tables: bool) -> tuple[Counter, dict]:
    counts: Counter = Counter()
    by_family: dict[str, Counter] = {}
    pages: dict = {}
    approved = (
        {r[0] for r in conn.execute("SELECT rule_ref FROM rule_second_approval WHERE state = ?", (RS.APPROVED,))}
        if tables else set()
    )  # fmt: skip
    for row in data["approvals"]:
        why, fam = _check(conn, row, pages)
        if not why and tables:
            have = _held(conn, "rule_second_approval", {"source": row["source"], "rule_ref": row["rule_ref"]},
                         RS.APPROVAL_COLUMNS)  # fmt: skip
            if have is not None:
                why = "already_held" if tuple(have) == tuple(row[c] for c in RS.APPROVAL_COLUMNS) else "conflict"
        outcome = why or ("would_add" if dry_run else "added") + ":" + row["state"]
        counts[outcome] += 1
        by_family.setdefault(fam, Counter())[outcome] += 1
        if not why and row["state"] == RS.APPROVED:
            approved.add(row["rule_ref"])
        if not why and not dry_run:
            _insert(conn, "rule_second_approval", RS.APPROVAL_COLUMNS, row)
    samples = _add_samples(conn, data["samples"], approved, counts, dry_run=dry_run, tables=tables)
    _add_measures(conn, data["measures"], samples, counts, dry_run=dry_run, tables=tables)
    return counts, by_family


def _sample_problem(row, approved: set) -> bool:
    """A sample row of the wrong shape, a verdict outside the two words, or of a rule with no second approval held here."""
    return (
        not isinstance(row, dict)
        or set(row) != set(RS.SAMPLE_COLUMNS)
        or row["verdict"] not in (None, "right", "wrong")
        or row["source"] != "requirement"
        or row["rule_ref"] not in approved
    )


def _add_samples(conn, rows, approved: set, counts: Counter, *, dry_run: bool, tables: bool) -> dict:
    """Add the sample rows; return every sample row held or added, by sample id (what a measure is recounted from)."""
    table, key = "rule_second_sample", ("sample_id", "source", "rule_ref")
    held: dict[str, list[dict]] = {}
    for row in rows:
        if _sample_problem(row, approved):
            counts[f"{table}:refused"] += 1
            continue
        have = _held(conn, table, {k: row[k] for k in key}, RS.SAMPLE_COLUMNS) if tables else None
        if have is not None:
            same = tuple(have) == tuple(row[c] for c in RS.SAMPLE_COLUMNS)
            counts[f"{table}:{'already_held' if same else 'conflict'}"] += 1
            continue
        counts[f"{table}:{'would_add' if dry_run else 'added'}"] += 1
        held.setdefault(row["sample_id"], []).append(row)
        if not dry_run:
            _insert(conn, table, RS.SAMPLE_COLUMNS, row)
    for sample_id in list(held):
        if tables and not dry_run:  # what is now held (the rows just added among them)
            held[sample_id] = [dict(zip(RS.SAMPLE_COLUMNS, r, strict=True)) for r in conn.execute(
                f"SELECT {', '.join(RS.SAMPLE_COLUMNS)} FROM {table} WHERE sample_id = ?", (sample_id,))]  # fmt: skip
        elif tables:
            held[sample_id] += [dict(zip(RS.SAMPLE_COLUMNS, r, strict=True)) for r in conn.execute(
                f"SELECT {', '.join(RS.SAMPLE_COLUMNS)} FROM {table} WHERE sample_id = ?", (sample_id,))]  # fmt: skip
    return held


def _recount(rows: list[dict]) -> tuple:
    """The measure the copy's `RS.measure` stores for these sample rows: judged, wrong, judge models, earliest draw."""
    judged = [r for r in rows if r["verdict"] is not None]
    models = {r["judge_model"] for r in judged if r["judge_model"]}
    return (len(judged), sum(r["verdict"] == "wrong" for r in judged), models,
            min((r["drawn_at"] for r in rows), default=None))  # fmt: skip


def _add_measures(conn, rows, samples: dict, counts: Counter, *, dry_run: bool, tables: bool) -> None:
    """A measure lands only when its counts are recounted, by code, from its sample rows (`measure_does_not_match`)."""
    table = "rule_second_measure"
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(RS.MEASURE_COLUMNS):
            counts[f"{table}:refused"] += 1
            continue
        mine = samples.get(row["sample_id"])
        if mine is None and tables:
            mine = [dict(zip(RS.SAMPLE_COLUMNS, r, strict=True)) for r in conn.execute(
                f"SELECT {', '.join(RS.SAMPLE_COLUMNS)} FROM rule_second_sample WHERE sample_id = ?",
                (row["sample_id"],))]  # fmt: skip
        judged, wrong, models, drawn = _recount(mine or [])
        claimed = set(str(row["judge_model"] or "").split(",")) - {""}
        if not mine or (row["judged"], row["wrong"], row["covers_until"]) != (judged, wrong, drawn) or claimed != models:
            counts[f"{table}:measure_does_not_match"] += 1
            continue
        have = _held(conn, table, {"sample_id": row["sample_id"], "measured_at": row["measured_at"]},
                     RS.MEASURE_COLUMNS) if tables else None  # fmt: skip
        if have is not None:
            same = tuple(have) == tuple(row[c] for c in RS.MEASURE_COLUMNS)
            counts[f"{table}:{'already_held' if same else 'conflict'}"] += 1
            continue
        counts[f"{table}:{'would_add' if dry_run else 'added'}"] += 1
        if not dry_run:
            _insert(conn, table, RS.MEASURE_COLUMNS, row)
