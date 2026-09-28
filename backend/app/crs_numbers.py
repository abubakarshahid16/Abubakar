"""Permanent CRS comment numbers, and the Open/Closed status that goes with them.

WHY (2026-09-29, researched against CRS guides and document-control systems):
a Comment Resolution Sheet comment carries an ID that is "permanent and never
reused" and follows the comment to the next revision, and "only the reviewer
closes a comment". The sheet used to print Item No 1..N - renumbered on every
export - and a digest reference that changed with every review run, so a
contractor answering item 3 could find a different comment at item 3 next time.

THE SHAPE. `CRS-<submittal no>-001`, printed in the client's own "Item No"
column, so the seven-column template is unchanged. The sequence runs per
submittal NUMBER, so a revision uploaded as a new document with the same
submittal number continues it rather than restarting at 001. A submittal that
carried no number is sequenced by its document id instead, never by a guess.

WHEN A NUMBER IS MINTED. Only when a comment becomes an engineer's: an edit,
a confirmation, an acceptance, a comment filed from chat, or the final code
(`mint_for_run`, called by those write routes). An unconfirmed machine draft
has no number, because it is not a comment yet - and it may never be issued,
which would leave a gap a contractor would ask about. The export and the
preview only READ numbers (`lookup`); they write nothing, as the project's own
test for them requires.

NEVER REUSED. A number is the next after the highest ever given in its scope,
and the table has no foreign key: deleting a document or a finding cannot free
a number. Two engineers confirming at the same moment cannot share one - the
table's UNIQUE (scope_key, seq) refuses the loser, who retries.

Ids, numbers and statuses only. Never document text.
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

#: How many times minting retries when another writer took the number it
#: computed. Each retry re-reads the highest number, so two is already rare.
_ATTEMPTS = 5


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


def format_ref(label: str, seq: int) -> str:
    return f"{PREFIX}-{label}-{seq:03d}"


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


def lookup(scope_key: str, keys: list[str]) -> dict[str, dict]:
    """READ ONLY. {row_key: {seq, label, ref, status, status_by, status_at}}
    for the keys that already have a number. Used by the export and preview,
    which must write nothing."""
    wanted = [k for k in dict.fromkeys(keys) if k]
    if not wanted:
        return {}
    found: dict[str, dict] = {}
    conn = connect()
    for i in range(0, len(wanted), 500):
        chunk = wanted[i:i + 500]
        marks = ",".join("?" for _ in chunk)
        for r in conn.execute(
                f"SELECT row_key, seq, label, status, status_by, status_at"
                f" FROM crs_comment_numbers WHERE scope_key = ? AND row_key IN ({marks})",
                (scope_key, *chunk)):
            found[r["row_key"]] = {
                "seq": r["seq"], "label": r["label"],
                "ref": format_ref(r["label"], r["seq"]),
                "status": r["status"], "status_by": r["status_by"],
                "status_at": r["status_at"],
            }
    return found


def assign(scope_key: str, label: str, keys: list[str], *,
           document_id: str, review_run_id: str) -> dict[str, dict]:
    """Give every key that has no number the next one in its scope.

    Idempotent: a key that already has a number keeps it. Returns `lookup` of
    all the keys afterwards."""
    conn = connect()
    for key in dict.fromkeys(k for k in keys if k):
        for _ in range(_ATTEMPTS):
            if lookup(scope_key, [key]):
                break
            try:
                with conn:
                    # One statement: read the highest number and claim the
                    # next under the same write lock. OR IGNORE lets a writer
                    # that lost the race on either constraint fall through to
                    # the lookup above instead of raising.
                    conn.execute(
                        """INSERT OR IGNORE INTO crs_comment_numbers
                               (scope_key, row_key, seq, label, first_document_id,
                                first_review_run_id, assigned_at, status)
                           SELECT ?, ?, COALESCE(MAX(seq), 0) + 1, ?, ?, ?, ?, ?
                             FROM crs_comment_numbers WHERE scope_key = ?""",
                        (scope_key, key, label, document_id, review_run_id, _now(),
                         OPEN, scope_key))
            except sqlite3.OperationalError as exc:  # busy / stale snapshot: retry
                log.warning("crs number: retrying after %s", type(exc).__name__)
        else:
            if not lookup(scope_key, [key]):
                raise RuntimeError("could not assign a CRS comment number")
    return lookup(scope_key, keys)


def set_status(scope_key: str, seq: int, status: str, *, user_id: str) -> dict | None:
    """Open or close one comment. The caller's route has already checked the
    person may do this; the name recorded is always theirs. None when there is
    no such comment."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    conn = connect()
    with conn:
        changed = conn.execute(
            "UPDATE crs_comment_numbers SET status = ?, status_by = ?, status_at = ?"
            " WHERE scope_key = ? AND seq = ?",
            (status, user_id, _now(), scope_key, seq)).rowcount
    if not changed:
        return None
    r = conn.execute(
        "SELECT row_key, seq, label, status, status_by, status_at FROM crs_comment_numbers"
        " WHERE scope_key = ? AND seq = ?", (scope_key, seq)).fetchone()
    return {"ref": format_ref(r["label"], r["seq"]), "seq": r["seq"],
            "status": r["status"], "status_by": r["status_by"], "status_at": r["status_at"]}


def parse_ref(ref: str) -> tuple[str, int] | None:
    """("<label>", seq) from "CRS-<label>-NNN", or None."""
    m = re.fullmatch(rf"{PREFIX}-(.+)-(\d+)", (ref or "").strip(), flags=re.IGNORECASE)
    return (m.group(1).upper(), int(m.group(2))) if m else None
