"""PF5 (#885): no unfinished CRS reaches a contractor.

"Unfinished" (owner, PROOF FIRST, 13 Oct 2026) is any UNREAD PAGE of the
submittal or any UNDECIDED FINDING or question. While either exists the
contractor copy is refused; the internal copy stays available.

WHAT COUNTS:
  * an unread page: a page of the run's one unread list (order 127,
    `page_ledger.run_unread_pages`: pages the code readers could not read
    into fields, pages the configured AI reader did not read, and on an older
    run the AI reader's time-outs - the same list the run summary shows),
    unless an engineer has recorded that they checked it by eye.
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

from . import page_ledger
from .config import settings
from .crs_mapping import ROW_KIND_SAFETY_TICK, row_has_no_text
from .db import connect

PAGE, FINDING = "page", "finding"
ACCEPT, REJECT, CHECKED = "accept", "reject", "checked_by_eye"
FINDING_DECISIONS = (ACCEPT, REJECT)

#: Order 95 piece 6a: why a comment is left off the sheet - the closed list
#: (spec 1.2), code -> the words the sheet shows. A reject may carry one; a
#: code outside this list is refused, never stored as free text.
REMOVAL_REASONS = {
    "not_applicable": "Not applicable to this equipment",
    "already_complies": "Contractor already complies",
    "extraction_wrong": "Extraction wrong",
    "accept_deviation": "Accept deviation",
    "duplicate": "Duplicate",
}

#: Why a run's contractor copy cannot be issued yet - plain words.
NO_PAGE_COVERAGE = (
    "no page coverage is recorded for this run, so no page can be called read"
)


def no_text_blocker(n: int) -> str:
    """Order 139 part 2 (spec e): the blocker for confirmed rows that would
    reach the contractor with an empty COMPANY Comments cell."""
    return f"{n} confirmed comment(s) on the sheet have no text"


def _issued_without_text(row: dict) -> bool:
    """A row the issue copy would carry (`crs_export.build_crs_view`: an
    engineer confirmed it, it is not rejected, not a safety tick and not an
    AI draft) whose comment text is empty. The export leaves such a row out
    as a last guard; this gate is what normally stops it."""
    return (
        row.get("engineer_confirmed") is True
        and not row.get("engineer_rejected")
        and row.get("row_kind") != ROW_KIND_SAFETY_TICK
        and not str(row.get("ai_review_comment") or "").strip()
        and row_has_no_text(row)
    )


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
        columns = {r[1] for r in conn.execute("PRAGMA table_info(crs_issue_decisions)")}
        if "reason_code" not in columns:  # piece 6a; older rows keep NULL
            conn.execute("ALTER TABLE crs_issue_decisions ADD COLUMN reason_code TEXT")
        conn.execute("""CREATE TABLE IF NOT EXISTS crs_issued_copies (
            id TEXT PRIMARY KEY,
            review_run_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            path TEXT NOT NULL,
            issued_by TEXT NOT NULL,
            issued_at TEXT NOT NULL)""")
    ensure_indexes()


def ensure_indexes() -> None:
    """Order 109: `last_issued_at` runs once per row of the review list; this
    index answers it without reading every issued copy. Only where the table
    exists, so the server's startup (which calls this) creates no table."""
    if _has("crs_issued_copies"):
        with connect() as conn:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_crs_issued_copies_run"
                " ON crs_issued_copies(review_run_id, issued_at)"
            )


def _has(table: str) -> bool:
    """READ ONLY: does the table exist yet? (a GET creates nothing)"""
    return (
        connect()
        .execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        )
        .fetchone()
        is not None
    )


def decisions(review_run_id: str) -> list[dict]:
    if not _has("crs_issue_decisions"):
        return []
    return [
        dict(r)
        for r in connect().execute(
            "SELECT * FROM crs_issue_decisions WHERE review_run_id = ? ORDER BY decided_at, id",
            (review_run_id,),
        )
    ]


def history(review_run_id: str) -> list[dict]:
    """Piece 6a: every decision recorded on this run, newest first - nothing
    is overwritten, so an earlier decision on the same item stays listed.
    `reason_code` is null on a decision recorded before codes existed. Two
    decisions in the same second keep the order they were written (rowid)."""
    if not _has("crs_issue_decisions"):
        return []
    rows = connect().execute(
        "SELECT * FROM crs_issue_decisions WHERE review_run_id = ?"
        " ORDER BY decided_at DESC, rowid DESC",
        (review_run_id,),
    )
    return [{**dict(r), "reason_code": dict(r).get("reason_code")} for r in rows]


def pages_to_check(page_coverage: dict | None, reader: dict | None = None) -> list[int]:
    """The pages an engineer must check before the contractor's copy is issued:
    the run's unread pages, one definition (order 127,
    `page_ledger.run_unread_pages`): pages the code readers did not read into
    fields, pages (PF3, #883) the AI reader was asked to read and did not
    (time-out, unavailable, failed), and on a run stored before PF3 the AI
    reader's own time-outs (`reader` is the run's `requirement_split.reader`)."""
    return page_ledger.run_unread_pages(page_coverage, reader)


def _page_items(
    review_run_id: str, page_coverage: dict | None, reader: dict | None
) -> tuple[list[dict], list[int], int | None]:
    """The run's unread pages split into those left to tick ([{page, reason}])
    and those an engineer ticked, with the page total; ([], [], None) when the
    run stored no page coverage or no total. A stale tick on a page no longer
    in the list is not counted (order 127)."""
    if not page_coverage or page_coverage.get("pages_total") is None:
        return [], [], None
    checked = {
        d["subject"]
        for d in decisions(review_run_id)
        if d["kind"] == PAGE and d["decision"] == CHECKED
    }
    reasons = page_ledger.run_unread_reasons(page_coverage, reader)
    unread: list[dict] = []
    checked_pages: list[int] = []
    for page in pages_to_check(page_coverage, reader):
        if str(page) in checked:
            checked_pages.append(int(page))
        else:
            unread.append({"page": int(page), "reason": reasons.get(str(page)) or None})
    return unread, checked_pages, page_coverage.get("pages_total")


def open_items(
    review_run_id: str,
    rows: list[dict],
    page_coverage: dict | None,
    reader: dict | None = None,
) -> dict:
    """What still stands between this run and its contractor copy.

    `rows` are the run's CRS rows (internal composition); `page_coverage` is
    the run's stored page coverage; `reader` its `requirement_split.reader`.
    Returns {unread_pages: [{page, reason}] (left to tick), checked_pages
    (pages of the same list an engineer ticked), pages_total, open_findings:
    [{finding_id, row_kind, item}], blockers: [plain words], issuable: bool}.
    `unread_pages` and `checked_pages` together are exactly
    `page_ledger.run_unread_pages` (order 127). Read only."""
    blockers: list[str] = []
    unread, checked_pages, pages_total = _page_items(
        review_run_id, page_coverage, reader
    )
    if pages_total is None:
        blockers.append(NO_PAGE_COVERAGE)
    seen: set[str] = set()
    findings: list[dict] = []
    for n, row in enumerate(rows, start=1):
        # A9/#923: a row with NO finding_id (#754 F5b's "standard not cited"/
        # "standard not applicable" rows have none - they are synthesised
        # from the applicability check, not from a review_findings row) used
        # to be skipped here unconditionally, which meant it could never
        # become a blocker: the issue gate never saw it, whatever an engineer
        # had or had not decided about it. `crs_row_key` (main._crs_content,
        # from the row's own `comment_key`) is set on EVERY row, with or
        # without a finding_id, and `engineer_confirmed` is already derived
        # from it uniformly (`crs_numbers.row_keys`/`lookup`) - so a
        # no-finding_id row is gated the same way a finding-bearing one is,
        # not skipped.
        subject = row.get("finding_id") or row.get("crs_row_key") or ""
        if (
            not subject
            or row.get("engineer_confirmed")
            or row.get("engineer_rejected")
            or subject in seen
        ):
            continue
        seen.add(subject)
        # `finding_id` here is `crs_row_key` (the row's `comment_key`), not a
        # real review_findings id, when the row has none. #986: the decide
        # route accepts that key and records the decision against it.
        findings.append(
            {"finding_id": subject, "row_kind": row.get("row_kind") or None, "item": n}
        )
    if unread:
        blockers.append(
            f"{len(unread)} page(s) of the submittal were not read and no "
            "engineer has recorded checking them"
        )
    if findings:
        blockers.append(
            f"{len(findings)} finding(s) on the sheet have no engineer's decision"
        )
    # Order 139 part 2 (spec e): every line issued has plain text, or is not
    # issued - a confirmed row with an empty comment blocks the issue.
    no_text = sum(1 for row in rows if _issued_without_text(row))
    if no_text:
        blockers.append(no_text_blocker(no_text))
    return {
        "unread_pages": unread,
        "checked_pages": checked_pages,
        "pages_total": pages_total,
        "open_findings": findings,
        "blockers": blockers,
        "issuable": not blockers,
    }


#: A9/#923: "n/a", "ok." and "idk" are each 3 characters and said nothing -
#: the audit's own example of what the old `< 3` floor let through. Ten is
#: still short (not a word-count or content check, which would be a
#: different, harder kind of validation), but it is long enough that a
#: placeholder typed without thinking does not clear it by accident.
MIN_REASON_LENGTH = 10


def _record(
    review_run_id: str,
    kind: str,
    subject: str,
    decision: str,
    reason: str,
    actor: str,
    reason_code: str | None = None,
) -> dict:
    reason = " ".join((reason or "").split())
    if reason_code is not None:
        # Order 95 piece 6a (a): a listed removal reason IS the engineer's
        # reason; with nothing typed, its own words are stored.
        reason = reason or REMOVAL_REASONS[reason_code]
    elif len(reason) < MIN_REASON_LENGTH:
        raise IssueError(
            f"a decision needs the engineer's reason "
            f"({MIN_REASON_LENGTH} characters minimum)"
        )
    if not actor:
        raise IssueError("a decision must name the engineer who made it")
    ensure_schema()
    row = {
        "id": uuid.uuid4().hex,
        "review_run_id": review_run_id,
        "kind": kind,
        "subject": subject,
        "decision": decision,
        "reason": reason,
        "decided_by": actor,
        "decided_at": _now(),
        "reason_code": reason_code,
    }
    conn = connect()
    with conn:
        conn.execute(
            "INSERT INTO crs_issue_decisions (id, review_run_id, kind, subject, decision,"
            " reason, decided_by, decided_at, reason_code) VALUES (?,?,?,?,?,?,?,?,?)",
            tuple(row.values()),
        )
    return row


def decide_page(
    review_run_id: str, page: int, *, unread: list[int], reason: str, actor: str
) -> dict:
    """The engineer checked an unread page by eye. Only a page the run could
    not read can be decided - a decision on any other page means nothing."""
    if int(page) not in {int(p) for p in unread}:
        raise IssueError("that page is not an unread page of this run")
    return _record(review_run_id, PAGE, str(int(page)), CHECKED, reason, actor)


def decide_finding(
    review_run_id: str,
    finding_id: str,
    decision: str,
    *,
    reason: str,
    actor: str,
    reason_code: str | None = None,
) -> dict:
    """The engineer accepts or rejects one finding of the run. The caller
    writes the decision on the finding itself; this keeps the reason, and
    tells rule_trust when the finding was decided by a proven rule.

    Piece 6a: a reject may name why from REMOVAL_REASONS; an accept carries
    no removal code, and an unknown code is refused."""
    if decision not in FINDING_DECISIONS:
        raise IssueError("a finding is accepted or rejected")
    if reason_code is not None and (
        decision != REJECT or reason_code not in REMOVAL_REASONS
    ):
        raise IssueError(
            "a removal reason is one of the listed reasons, and only on a removal"
        )
    record = _record(
        review_run_id, FINDING, finding_id, decision, reason, actor, reason_code
    )
    # rule_trust (#947 step 10): on a finding a PROVEN rule decided, this
    # decision is the family's spot-check outcome (a reject drops its proof).
    from . import review, rule_trust

    rule_trust.record_engineer_decision(
        review.get(finding_id) or {}, decision, actor=actor, note=reason
    )
    return record


def apply_row_decisions(review_run_id: str, rows: list[dict]) -> None:
    """#986: A ROW WITH NO FINDING BEHIND IT (standard not cited, standard not
    applicable) is decided by its row key, recorded here. Accepted: the
    engineer made it theirs and the contractor copy prints it. Rejected:
    withdrawn - not printed and no longer an open item. Marks the rows."""
    verdicts = {
        d["subject"]: d["decision"]
        for d in decisions(review_run_id)
        if d["kind"] == FINDING
    }
    for row in rows:
        verdict = (
            None if row.get("finding_id") else verdicts.get(row.get("crs_row_key"))
        )
        if verdict == ACCEPT:
            row["engineer_confirmed"] = True
        elif verdict == REJECT:
            row["engineer_rejected"] = True


def is_open_row_key(rows: list[dict], subject: str) -> bool:
    """#986: is `subject` the row key of an undecided row with no finding -
    the id the issue gate names for it, and the one the decide route takes?"""
    return any(
        not r.get("finding_id")
        and r.get("crs_row_key") == subject
        and not r.get("engineer_confirmed")
        and not r.get("engineer_rejected")
        for r in rows
    )


def finding_changes(decision: str | None, actor: str, now: str) -> dict:
    """What a decision writes on a finding: accepted (and confirmed) or
    rejected, by the caller, now."""
    changes = {
        "approval_status": "accepted" if decision == ACCEPT else "rejected",
        "approved_by": actor,
        "approved_at": now,
    }
    if decision == ACCEPT:
        changes.update({"confirmed_by": actor, "confirmed_at": now})
    return changes


def group_of(rows: list[dict], finding_id: str) -> list[str]:
    """#986: every finding the row of `finding_id` stands on (itself first). A
    decision on the row covers all of them, or the row stays open with the
    next finding behind it."""
    group = next(
        (r.get("finding_ids") or [] for r in rows if r.get("finding_id") == finding_id),
        [],
    )
    return list(dict.fromkeys([finding_id, *group]))


def _archive_dir() -> Path:
    path = Path(settings.data_dir) / "crs_issued"
    path.mkdir(parents=True, exist_ok=True)
    return path


def archive(review_run_id: str, workbook: bytes, filename: str, *, actor: str) -> dict:
    """Keep the exact bytes issued to the contractor, with their sha256.

    A9/#923: the DB ROW IS WRITTEN FIRST. The old order wrote the file, then
    the row - a crash between them left an untracked file on disk forever,
    invisible (no error, no record, just wasted disk). Writing the row first
    means the only way to fail now is a crash between the (committed) row
    and the file, which `issued_bytes` already turns into a loud
    `IssueError` ("no longer matches its recorded sha256") rather than
    silently serving nothing - so this reorder is cleaned up by deleting the
    row if the file write itself fails, rather than left to be discovered."""
    if not actor:
        raise IssueError("an issued copy must name the engineer who issued it")
    ensure_schema()
    copy_id = uuid.uuid4().hex
    path = _archive_dir() / f"{copy_id}.xlsx"
    row = {
        "id": copy_id,
        "review_run_id": review_run_id,
        "filename": filename,
        "sha256": hashlib.sha256(workbook).hexdigest(),
        "size_bytes": len(workbook),
        "path": str(path),
        "issued_by": actor,
        "issued_at": _now(),
    }
    conn = connect()
    with conn:
        conn.execute(
            "INSERT INTO crs_issued_copies (id, review_run_id, filename, sha256, size_bytes,"
            " path, issued_by, issued_at) VALUES (?,?,?,?,?,?,?,?)",
            tuple(row.values()),
        )
    try:
        path.write_bytes(workbook)
    except OSError:
        with conn:
            conn.execute("DELETE FROM crs_issued_copies WHERE id = ?", (copy_id,))
        raise
    return row


def issued(review_run_id: str) -> list[dict]:
    """The copies issued for this run, newest first. Read only; no path."""
    if not _has("crs_issued_copies"):
        return []
    return [
        {k: v for k, v in dict(r).items() if k != "path"}
        for r in connect().execute(
            "SELECT * FROM crs_issued_copies WHERE review_run_id = ? ORDER BY issued_at DESC, id",
            (review_run_id,),
        )
    ]


def last_issued_at(review_run_id: str) -> str | None:
    """Order 95 piece 3: when this run's newest contractor copy was issued -
    the inbox's "Signed". None when nothing was issued (or the table does not
    exist yet); read only."""
    if not _has("crs_issued_copies"):
        return None
    sql = "SELECT MAX(issued_at) AS at FROM crs_issued_copies WHERE review_run_id = ?"
    row = connect().execute(sql, (review_run_id,)).fetchone()
    return row["at"] if row else None


def issued_bytes(review_run_id: str, copy_id: str) -> tuple[dict, bytes] | None:
    """One issued copy exactly as issued, or None. A copy whose stored bytes
    no longer match their sha256 is refused - an archive that cannot prove
    what it holds is not an archive."""
    if not _has("crs_issued_copies"):
        return None
    row = (
        connect()
        .execute(
            "SELECT * FROM crs_issued_copies WHERE id = ? AND review_run_id = ?",
            (copy_id, review_run_id),
        )
        .fetchone()
    )
    if row is None:
        return None
    data = Path(row["path"]).read_bytes() if Path(row["path"]).exists() else b""
    if hashlib.sha256(data).hexdigest() != row["sha256"]:
        raise IssueError("the archived copy no longer matches its recorded sha256")
    return {k: v for k, v in dict(row).items() if k != "path"}, data
