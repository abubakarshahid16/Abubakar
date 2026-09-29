"""Permanent CRS comment numbers and everything that happens to a comment after
it is issued: the contractor's reply, the reviewer's closure, carry-forward to
the next revision, and the comment's history.

WHY (2026-09-29, researched against CRS guides and document-control systems):
a Comment Resolution Sheet comment carries an ID that is "permanent and never
reused" and follows the comment to the next revision; the contractor answers
each comment with a response code (Accepted / Accepted with comment / Rejected
/ Clarification needed); "only the reviewer closes a comment"; open comments
"carry forward automatically between revisions". The sheet used to print Item
No 1..N - renumbered on every export - and had no reply or closure at all.

THE SHAPE. `CRS-<document no>-001`, printed in the client's own "Item No"
column, so the seven-column template is unchanged. The sequence runs per
DOCUMENT NUMBER - the contractor's own number printed on the datasheet, which
the classifier reads from the page (`classification._document_number_hits`)
and which stays the same across revisions. So Rev 1, uploaded as a new
document, continues Rev 0's sequence and its open comments carry forward. NOT
the transmittal number, which changes with every submission and would start a
new sequence each time. A submittal with no document number is sequenced by
its document id, never by a guess. Once a document's first comment is
numbered its sequence is FIXED (`crs_document_scope`), so a later edit of the
document number cannot renumber comments already issued.

WHEN A NUMBER IS MINTED. Only when a comment becomes an engineer's: an edit,
a confirmation, an acceptance, a comment filed from chat, or the final code
(`main._mint_crs_numbers`, called by those write routes). An unconfirmed
machine draft has no number: it is not a comment yet, and may never be issued.
The export and the preview only READ (`lookup`, `open_elsewhere`); they write
nothing, as the project's own test for them requires.

NEVER REUSED. A number is the next after the highest ever given in its scope,
and the table has no foreign key: deleting a document or a finding cannot free
a number. Two engineers confirming at the same moment cannot share one - the
table's UNIQUE (scope_key, seq) refuses the loser, who retries.

NEVER GUESSED. A reply whose text states no recognised response code is stored
with NO code, and says so - it is not read as "Accepted".

The stored comment text is local, like the findings it came from; it is never
logged. Log lines here carry ids, numbers and counts only.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from datetime import UTC, datetime

from .db import connect

log = logging.getLogger(__name__)

PREFIX = "CRS"
OPEN = "Open"
CLOSED = "Closed"
STATUSES = (OPEN, CLOSED)
#: A NUMBERED COMMENT AN ENGINEER REJECTED BEFORE THE CONTRACTOR ANSWERED IT
#: (audit 2026-09-30). Confirming a comment numbers it; rejecting it afterwards
#: left the number Open, so the issue copy printed the rejected comment as
#: "carried forward". Withdrawn is never carried forward, never marks a
#: re-raised draft as confirmed, and is not one of the reviewer's `STATUSES`:
#: only a rejection sets it, and the engineer making the comment theirs again
#: (`assign`) re-opens it. The number is kept - never reused.
WITHDRAWN = "Withdrawn"

#: The contractor's per-comment response codes, as industry CRS practice uses
#: them. Order matters for parsing: the longer "Accepted with comment" must be
#: tried before "Accepted".
RESPONSE_CODES = ("Accepted with comment", "Accepted", "Rejected", "Clarification needed")
#: How each code may be written back to us, folded. Anything else is NO code.
_RESPONSE_SPELLINGS = (
    ("Accepted with comment", ("accepted with comments", "accepted with comment",
                               "accepted w/ comment", "accepted w/ comments")),
    ("Accepted", ("accepted", "agreed", "noted and accepted")),
    ("Rejected", ("rejected", "not accepted", "disagree", "disagreed")),
    ("Clarification needed", ("clarification needed", "clarification required",
                              "clarification requested", "clarify")),
)

SOURCE_IMPORT = "imported reply sheet"
SOURCE_RECORDED = "recorded by engineer"

#: How many times minting retries when another writer took the number it
#: computed. Each retry re-reads the highest number, so two is already rare.
_ATTEMPTS = 5

_SNAPSHOT_FIELDS = ("document_name", "page_section", "comment", "comment_by",
                    "standard_reference")
_COLUMNS = ("row_key, seq, label, status, status_by, status_at, status_note,"
            " response_code, response_text, response_by, response_at, response_source,"
            " document_name, page_section, comment, comment_by, standard_reference,"
            " last_review_run_id")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def scope_for(submittal_number: str | None, document_id: str) -> tuple[str, str]:
    """(scope_key, printed label) for one submittal.

    The submittal's own number when it has one, folded for the key so "ABC-001"
    and "abc-001 " are one sequence, printed as the characters a file name and
    a reader can both carry. Without one, the document id - never an invented
    number."""
    number = (submittal_number or "").strip()
    if number:
        label = re.sub(r"[^A-Za-z0-9-]+", "-", number).strip("-").upper()
        if label:
            return "no:" + label.lower(), label
    short = re.sub(r"[^A-Za-z0-9]+", "", document_id.removeprefix("doc_"))[:8].upper()
    return "doc:" + document_id, short or "DOC"


def scope_of_document(document_id: str, document_number: str | None) -> tuple[str, str]:
    """READ ONLY. (scope_key, label) for one submittal document: the sequence
    it was fixed to when its first comment was numbered, else the one its
    document number gives now."""
    row = connect().execute(
        "SELECT scope_key, label FROM crs_document_scope WHERE document_id = ?",
        (document_id,)).fetchone()
    if row is not None:
        return row["scope_key"], row["label"]
    return scope_for(document_number, document_id)


def format_ref(label: str, seq: int) -> str:
    return f"{PREFIX}-{label}-{seq:03d}"


def parse_ref(ref: str) -> tuple[str, int] | None:
    """("<label>", seq) from "CRS-<label>-NNN", or None."""
    m = re.fullmatch(rf"{PREFIX}-(.+)-(\d+)", str(ref or "").strip(), flags=re.IGNORECASE)
    return (m.group(1).upper(), int(m.group(2))) if m else None


def parse_response(text: str | None) -> tuple[str | None, str]:
    """(code, the reply without it) from a contractor's reply.

    The code must LEAD the reply ("Rejected - the vendor's rating is..."), as
    the issued sheet asks. A reply that leads with anything else has no code:
    returned as (None, the whole reply), never read as agreement."""
    raw = str(text or "").strip()
    folded = " ".join(raw.lower().split())
    for code, spellings in _RESPONSE_SPELLINGS:
        for spelling in spellings:
            if folded == spelling or (folded.startswith(spelling)
                                      and not folded[len(spelling)].isalnum()):
                words = len(spelling.split())
                parts = raw.split(None, words)
                remainder = parts[words] if len(parts) > words else ""
                return code, remainder.lstrip(" .:;,-\u2013").strip()
    return None, raw


def row_keys(rows: list[dict]) -> list[str]:
    """Each row's key within this sheet, in row order.

    Two rows of one sheet can be about the same subject - most often after a
    re-run, which keeps an engineer's confirmed comment AND writes a fresh
    machine proposal about the same field beside it. They are different
    comments, so all but one take "#2", "#3". WHICH ONE KEEPS THE BARE KEY
    MATTERS: it is the key that already holds a number, so a confirmed row
    always claims it before an unconfirmed draft does, whatever order the
    sheet lists them in. Otherwise a re-run could hand the engineer's number
    to the draft. Ties keep the sheet's own order. Rows with no key (a caller
    from before keys existed) get none."""
    order = sorted(range(len(rows)),
                   key=lambda i: (not rows[i].get("engineer_confirmed"), i))
    seen: dict[str, int] = {}
    keys = [""] * len(rows)
    for i in order:
        key = rows[i].get("comment_key") or ""
        if not key:
            continue
        seen[key] = seen.get(key, 0) + 1
        keys[i] = key if seen[key] == 1 else f"{key}#{seen[key]}"
    return keys


def _record(r) -> dict:
    out = {k: r[k] for k in r.keys()}
    out["ref"] = format_ref(r["label"], r["seq"])
    return out


def lookup(scope_key: str, keys: list[str]) -> dict[str, dict]:
    """READ ONLY. {row_key: the comment's stored record, with "ref"} for the
    keys that already have a number. Used by the export and preview, which
    must write nothing."""
    wanted = [k for k in dict.fromkeys(keys) if k]
    if not wanted:
        return {}
    found: dict[str, dict] = {}
    conn = connect()
    for i in range(0, len(wanted), 500):
        chunk = wanted[i:i + 500]
        marks = ",".join("?" for _ in chunk)
        for r in conn.execute(
                f"SELECT {_COLUMNS} FROM crs_comment_numbers"
                f" WHERE scope_key = ? AND row_key IN ({marks})", (scope_key, *chunk)):
            found[r["row_key"]] = _record(r)
    return found


def get(scope_key: str, seq: int) -> dict | None:
    """READ ONLY. One comment by its number."""
    r = connect().execute(
        f"SELECT {_COLUMNS} FROM crs_comment_numbers WHERE scope_key = ? AND seq = ?",
        (scope_key, seq)).fetchone()
    return _record(r) if r is not None else None


def open_elsewhere(scope_key: str, present_keys: set[str]) -> list[dict]:
    """READ ONLY. The Open comments of this submittal (number) that the sheet
    being composed does NOT produce - an earlier run's or an earlier
    revision's. Industry practice carries them forward until the reviewer
    closes them; a comment is never silently dropped because a later run no
    longer raises it. In number order."""
    return [_record(r) for r in connect().execute(
        f"SELECT {_COLUMNS} FROM crs_comment_numbers"
        " WHERE scope_key = ? AND status = ? ORDER BY seq", (scope_key, OPEN))
        if r["row_key"] not in present_keys]


def _event(conn, scope_key: str, seq: int, by: str | None, event: str, detail: str = "") -> None:
    conn.execute(
        "INSERT INTO crs_comment_events (scope_key, seq, at, by, event, detail)"
        " VALUES (?, ?, ?, ?, ?, ?)", (scope_key, seq, _now(), by, event, detail))


def assign(scope_key: str, label: str, keys: list[str], *,
           document_id: str, review_run_id: str,
           snapshots: dict[str, dict] | None = None,
           user_id: str | None = None) -> dict[str, dict]:
    """Give every key that has no number the next one in its scope, and keep
    each key's snapshot current (what the comment says, for carry-forward).

    Idempotent: a key that already has a number keeps it. Returns `lookup` of
    all the keys afterwards."""
    conn = connect()
    snapshots = snapshots or {}
    if any(keys):
        # Fix this document to this sequence before its first number exists,
        # so the number and the sequence it belongs to can never disagree.
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO crs_document_scope"
                " (document_id, scope_key, label, fixed_at) VALUES (?, ?, ?, ?)",
                (document_id, scope_key, label, _now()))
    for key in dict.fromkeys(k for k in keys if k):
        # AN ENGINEER MAKING A WITHDRAWN COMMENT THEIRS AGAIN re-opens it: the
        # same subject, confirmed again, is the same comment with its number.
        with conn:
            reopened = conn.execute(
                "UPDATE crs_comment_numbers SET status = ?, status_by = ?, status_at = ?,"
                " status_note = NULL WHERE scope_key = ? AND row_key = ? AND status = ?",
                (OPEN, user_id, _now(), scope_key, key, WITHDRAWN)).rowcount
            if reopened:
                seq = conn.execute(
                    "SELECT seq FROM crs_comment_numbers WHERE scope_key = ? AND row_key = ?",
                    (scope_key, key)).fetchone()["seq"]
                _event(conn, scope_key, seq, user_id, "reopened",
                       f"confirmed again in review run {review_run_id}")
        for _ in range(_ATTEMPTS):
            if lookup(scope_key, [key]):
                break
            try:
                with conn:
                    # One statement: read the highest number and claim the
                    # next under the same write lock. OR IGNORE lets a writer
                    # that lost the race on either constraint fall through to
                    # the lookup above instead of raising.
                    claimed = conn.execute(
                        """INSERT OR IGNORE INTO crs_comment_numbers
                               (scope_key, row_key, seq, label, first_document_id,
                                first_review_run_id, assigned_at, status)
                           SELECT ?, ?, COALESCE(MAX(seq), 0) + 1, ?, ?, ?, ?, ?
                             FROM crs_comment_numbers WHERE scope_key = ?""",
                        (scope_key, key, label, document_id, review_run_id, _now(),
                         OPEN, scope_key)).rowcount
                    if claimed:
                        seq = conn.execute(
                            "SELECT seq FROM crs_comment_numbers"
                            " WHERE scope_key = ? AND row_key = ?", (scope_key, key)
                        ).fetchone()["seq"]
                        _event(conn, scope_key, seq, user_id, "numbered",
                               f"review run {review_run_id}")
            except sqlite3.OperationalError as exc:  # busy / stale snapshot: retry
                log.warning("crs number: retrying after %s", type(exc).__name__)
        else:
            if not lookup(scope_key, [key]):
                raise RuntimeError("could not assign a CRS comment number")
        snap = snapshots.get(key)
        if snap is not None:
            with conn:
                conn.execute(
                    "UPDATE crs_comment_numbers SET document_name = ?, page_section = ?,"
                    " comment = ?, comment_by = ?, standard_reference = ?,"
                    " last_review_run_id = ? WHERE scope_key = ? AND row_key = ?",
                    (*(str(snap.get(f) or "") for f in _SNAPSHOT_FIELDS),
                     review_run_id, scope_key, key))
    return lookup(scope_key, keys)


def withdraw(scope_key: str, keys: set[str] | list[str], *,
             user_id: str | None) -> list[int]:
    """Withdraw the numbered comments behind these keys: an engineer rejected
    them. Only a comment still Open and with NO contractor reply - a reply is
    proof it was issued, and an issued comment is the reviewer's to close, not
    to make disappear. Returns the numbers withdrawn."""
    wanted = [k for k in dict.fromkeys(keys) if k]
    done: list[int] = []
    if not wanted:
        return done
    conn = connect()
    with conn:
        for key in wanted:
            row = conn.execute(
                "SELECT seq FROM crs_comment_numbers WHERE scope_key = ? AND row_key = ?"
                " AND status = ? AND response_code IS NULL"
                " AND COALESCE(response_text, '') = ''", (scope_key, key, OPEN)).fetchone()
            if row is None:
                continue
            conn.execute(
                "UPDATE crs_comment_numbers SET status = ?, status_by = ?, status_at = ?,"
                " status_note = ? WHERE scope_key = ? AND seq = ?",
                (WITHDRAWN, user_id, _now(), "rejected by the engineer before issue",
                 scope_key, row["seq"]))
            _event(conn, scope_key, row["seq"], user_id, "withdrawn",
                   "the engineer rejected the comment")
            done.append(row["seq"])
    return done


def set_status(scope_key: str, seq: int, status: str, *, user_id: str,
               note: str | None = None) -> dict | None:
    """Open or close one comment. The caller's route has already checked the
    person may do this; the name recorded is always theirs. None when there is
    no such comment."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    note = (note or "").strip() or None
    conn = connect()
    with conn:
        changed = conn.execute(
            "UPDATE crs_comment_numbers SET status = ?, status_by = ?, status_at = ?,"
            " status_note = ? WHERE scope_key = ? AND seq = ?",
            (status, user_id, _now(), note, scope_key, seq)).rowcount
        if changed:
            _event(conn, scope_key, seq, user_id, status.lower(), note or "")
    return get(scope_key, seq) if changed else None


def set_response(scope_key: str, seq: int, *, code: str | None, text: str,
                 user_id: str, source: str) -> dict | None:
    """Store the contractor's reply to one comment. `code` is one of
    RESPONSE_CODES or None - a reply that stated no code keeps none. The
    person who entered it, and how, are recorded. None when there is no such
    comment."""
    if code is not None and code not in RESPONSE_CODES:
        raise ValueError(f"response code must be one of {RESPONSE_CODES}")
    conn = connect()
    with conn:
        changed = conn.execute(
            "UPDATE crs_comment_numbers SET response_code = ?, response_text = ?,"
            " response_by = ?, response_at = ?, response_source = ?"
            " WHERE scope_key = ? AND seq = ?",
            (code, (text or "").strip(), user_id, _now(), source, scope_key, seq)).rowcount
        if changed:
            _event(conn, scope_key, seq, user_id, "response",
                   f"{code or 'no code stated'} ({source})")
    return get(scope_key, seq) if changed else None


def history(scope_key: str, seq: int) -> list[dict]:
    """READ ONLY. Everything that happened to one comment, oldest first."""
    return [dict(r) for r in connect().execute(
        "SELECT at, by, event, detail FROM crs_comment_events"
        " WHERE scope_key = ? AND seq = ? ORDER BY id", (scope_key, seq))]


def response_cell(record: dict) -> str:
    """What the Contractor's Response column prints for a stored reply."""
    code = record.get("response_code") or ""
    text = record.get("response_text") or ""
    if code and text:
        return f"{code}: {text}"
    return code or text


def resolution_cell(record: dict) -> str:
    """What the Final Resolution column prints: the status, and the
    reviewer's closing note when there is one."""
    status = record.get("status") or OPEN
    note = record.get("status_note") or ""
    return f"{status}: {note}" if note else status
