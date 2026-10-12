"""PF5 (#885): no unfinished CRS reaches a contractor.

"Unfinished" (owner, PROOF FIRST, 13 Oct 2026) is any UNREAD PAGE of the
submittal or any UNDECIDED FINDING or question. While either exists the
contractor copy is refused; the internal copy stays available.

WHAT COUNTS:
  * an unread page: a page the run could not read into fields, as stored on
    the run (`page_coverage.pages_not_read_into_fields`, the same pages the
    CRS names), unless an engineer has recorded that they checked it by eye.
    A run with NO page coverage on record is unfinished too - "nothing was
    accounted for" is not "every page was read".
  * an undecided finding: a CRS row that stands on a finding no engineer has
    confirmed or rejected (`crs_mapping` marks it `engineer_confirmed`
    False). These are exactly the rows the issue copy used to drop without
    a word.

THE ENGINEER DECIDES WITHOUT WAITING FOR AI. Every open item can be closed by
a recorded decision - who, when and why - kept here beside the finding's own
audit trail. A finding decision is also written on the finding (confirmed or
rejected, by the caller), so the CRS and every other screen read it the same.

THE ISSUED COPY IS KEPT. The exact workbook bytes that leave the building are
stored with their sha256, the run, who issued it and when; the list and each
copy can be read back. Ids, counts and reasons only in this table - never
document text.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .config import settings
from .db import connect

PAGE, FINDING = "page", "finding"
ACCEPT, REJECT, CHECKED = "accept", "reject", "checked_by_eye"
FINDING_DECISIONS = (ACCEPT, REJECT)

#: Why a run's contractor copy cannot be issued yet - plain words.
NO_PAGE_COVERAGE = "no page coverage is recorded for this run, so no page can be called read"


class IssueError(ValueError):
    """A decision or an issue that cannot be recorded, with why (plain words)."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def ensure_schema() -> None:
    conn = connect()
    with conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS crs_issue_decisions (
            id TEXT PRIMARY KEY,
            review_run_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            subject TEXT NOT NULL,
            decision TEXT NOT NULL,
            reason TEXT NOT NULL,
            decided_by TEXT NOT NULL,
            decided_at TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS crs_issued_copies (
            id TEXT PRIMARY KEY,
            review_run_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            path TEXT NOT NULL,
            issued_by TEXT NOT NULL,
            issued_at TEXT NOT NULL)""")


def _has(table: str) -> bool:
    """READ ONLY: does the table exist yet? (a GET creates nothing)"""
    return connect().execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() is not None


def decisions(review_run_id: str) -> list[dict]:
    if not _has("crs_issue_decisions"):
        return []
    return [dict(r) for r in connect().execute(
        "SELECT * FROM crs_issue_decisions WHERE review_run_id = ? ORDER BY decided_at, id",
        (review_run_id,))]


def open_items(review_run_id: str, rows: list[dict], page_coverage: dict | None) -> dict:
    """What still stands between this run and its contractor copy.

    `rows` are the run's CRS rows (internal composition); `page_coverage` is
    the run's stored page coverage. Returns {unread_pages: [{page, reason}],
    open_findings: [{finding_id, row_kind, item}], blockers: [plain words],
    issuable: bool}. Read only."""
    checked = {d["subject"] for d in decisions(review_run_id)
               if d["kind"] == PAGE and d["decision"] == CHECKED}
    blockers: list[str] = []
    unread: list[dict] = []
    if not page_coverage or page_coverage.get("pages_total") is None:
        blockers.append(NO_PAGE_COVERAGE)
    else:
        reasons = page_coverage.get("not_read_reasons") or {}
        for page in page_coverage.get("pages_not_read_into_fields") or []:
            if str(page) not in checked:
                unread.append({"page": int(page), "reason": reasons.get(str(page)) or None})
    seen: set[str] = set()
    findings: list[dict] = []
    for n, row in enumerate(rows, start=1):
        fid = row.get("finding_id") or ""
        if not fid or row.get("engineer_confirmed") or fid in seen:
            continue
        seen.add(fid)
        findings.append({"finding_id": fid, "row_kind": row.get("row_kind") or None, "item": n})
    if unread:
        blockers.append(f"{len(unread)} page(s) of the submittal were not read and no "
                        "engineer has recorded checking them")
    if findings:
        blockers.append(f"{len(findings)} finding(s) on the sheet have no engineer's decision")
    return {"unread_pages": unread, "open_findings": findings, "blockers": blockers,
            "issuable": not blockers}


def _record(review_run_id: str, kind: str, subject: str, decision: str, reason: str,
            actor: str) -> dict:
    reason = " ".join((reason or "").split())
    if len(reason) < 3:
        raise IssueError("a decision needs the engineer's reason")
    if not actor:
        raise IssueError("a decision must name the engineer who made it")
    ensure_schema()
    row = {"id": uuid.uuid4().hex, "review_run_id": review_run_id, "kind": kind,
           "subject": subject, "decision": decision, "reason": reason,
           "decided_by": actor, "decided_at": _now()}
    conn = connect()
    with conn:
        conn.execute("INSERT INTO crs_issue_decisions (id, review_run_id, kind, subject, decision,"
                     " reason, decided_by, decided_at) VALUES (?,?,?,?,?,?,?,?)",
                     tuple(row.values()))
    return row


def decide_page(review_run_id: str, page: int, *, unread: list[int], reason: str,
                actor: str) -> dict:
    """The engineer checked an unread page by eye. Only a page the run could
    not read can be decided - a decision on any other page means nothing."""
    if int(page) not in {int(p) for p in unread}:
        raise IssueError("that page is not an unread page of this run")
    return _record(review_run_id, PAGE, str(int(page)), CHECKED, reason, actor)


def decide_finding(review_run_id: str, finding_id: str, decision: str, *, reason: str,
                   actor: str) -> dict:
    """The engineer accepts or rejects one finding of the run. The caller
    writes the decision on the finding itself; this keeps the reason."""
    if decision not in FINDING_DECISIONS:
        raise IssueError("a finding is accepted or rejected")
    return _record(review_run_id, FINDING, finding_id, decision, reason, actor)


def _archive_dir() -> Path:
    path = Path(settings.data_dir) / "crs_issued"
    path.mkdir(parents=True, exist_ok=True)
    return path


def archive(review_run_id: str, workbook: bytes, filename: str, *, actor: str) -> dict:
    """Keep the exact bytes issued to the contractor, with their sha256."""
    if not actor:
        raise IssueError("an issued copy must name the engineer who issued it")
    ensure_schema()
    copy_id = uuid.uuid4().hex
    path = _archive_dir() / f"{copy_id}.xlsx"
    path.write_bytes(workbook)
    row = {"id": copy_id, "review_run_id": review_run_id, "filename": filename,
           "sha256": hashlib.sha256(workbook).hexdigest(), "size_bytes": len(workbook),
           "path": str(path), "issued_by": actor, "issued_at": _now()}
    conn = connect()
    with conn:
        conn.execute("INSERT INTO crs_issued_copies (id, review_run_id, filename, sha256, size_bytes,"
                     " path, issued_by, issued_at) VALUES (?,?,?,?,?,?,?,?)", tuple(row.values()))
    return row


def issued(review_run_id: str) -> list[dict]:
    """The copies issued for this run, newest first. Read only; no path."""
    if not _has("crs_issued_copies"):
        return []
    return [{k: v for k, v in dict(r).items() if k != "path"} for r in connect().execute(
        "SELECT * FROM crs_issued_copies WHERE review_run_id = ? ORDER BY issued_at DESC, id",
        (review_run_id,))]


def issued_bytes(review_run_id: str, copy_id: str) -> tuple[dict, bytes] | None:
    """One issued copy exactly as issued, or None. A copy whose stored bytes
    no longer match their sha256 is refused - an archive that cannot prove
    what it holds is not an archive."""
    if not _has("crs_issued_copies"):
        return None
    row = connect().execute("SELECT * FROM crs_issued_copies WHERE id = ? AND review_run_id = ?",
                            (copy_id, review_run_id)).fetchone()
    if row is None:
        return None
    data = Path(row["path"]).read_bytes() if Path(row["path"]).exists() else b""
    if hashlib.sha256(data).hexdigest() != row["sha256"]:
        raise IssueError("the archived copy no longer matches its recorded sha256")
    return {k: v for k, v in dict(row).items() if k != "path"}, data
