"""#806 S3: only documents the owner approved may reach the cloud model.

THE RULE. Confidential documents (submittals, company standards, CRSs) may go
to the Claude API "only for documents the owner approved in writing". The lane
was already gated (two egress flags, a key, USD caps) but took any text. Now:

  * EVERY CALLER DECLARES what its prompt carries - `with carrying(ids):` -
    the ids of the documents whose text, field names, values or images are in
    the prompt. A prompt with no document content declares that too:
    `with carrying(()):`.
  * THE ONE CHOKE POINT REFUSES. `claude_spend.reserve_all` (every Claude call
    reserves its worst case there before it is sent: the `metered` lane and the
    `ClaudeProvider` lane both) asks `refusal()` first. A declared document
    that is not approved -> refused. NOTHING DECLARED -> refused (fail closed):
    a new call site that forgets to declare cannot leak, it just stops.
  * A DOCUMENT IS ITS FILE: the list holds sha256 hashes, so the same file is
    approved in the live database and in a copy, and a changed revision (a new
    hash) is not approved by its predecessor.

THE LIST is `<data_dir>/claude_approved_documents.json`, outside git, edited by
the owner; not `.env` (keys and approvals stay separate). Missing or empty =
nothing approved = no document content leaves. An entry counts only with
`"status": "approved"`; `pending_owner` entries are there to be answered.

    {"documents": [{"sha256": "...", "document_id": "doc_...", "label": "...",
                    "status": "approved", "approved_by": "...", "approved_on": "2026-10-11"}]}

A change to the file is written to the audit table (`sync_audit`): counts and
hashes only, never a title.

This module opens no socket and reads no document text.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
from contextvars import ContextVar
from pathlib import Path

from .config import settings

LIST_NAME = "claude_approved_documents.json"
APPROVED = "approved"
AUDIT_ACTION = "claude_approved_list_changed"

#: Why a call was refused, as the first word of the reason (and the ledger).
UNDECLARED = "undeclared"
NOT_APPROVED = "not_approved"
UNKNOWN_DOCUMENT = "unknown_document"

#: The documents the prompt being built carries. None = nobody declared
#: anything (refused); an empty set = declared to carry no document content.
_CARRIED: ContextVar[frozenset[str] | None] = ContextVar("claude_carried_documents", default=None)


@contextlib.contextmanager
def carrying(document_ids):
    """Declare the documents the Claude calls made inside this block carry.
    Nested blocks ADD (a chat turn that reads another document carries both);
    a declaration is never narrowed from inside."""
    ids = frozenset(str(d) for d in (document_ids or ()) if d)
    outer = _CARRIED.get()
    token = _CARRIED.set(ids if outer is None else outer | ids)
    try:
        yield
    finally:
        _CARRIED.reset(token)


def carried() -> frozenset[str] | None:
    return _CARRIED.get()


def list_path() -> Path:
    return Path(settings.data_dir) / LIST_NAME


def _entries() -> list[dict]:
    path = list_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # An unreadable list approves nothing; it never fails open.
        return []
    rows = data.get("documents") if isinstance(data, dict) else None
    return [r for r in (rows or []) if isinstance(r, dict)]


def approved_hashes() -> frozenset[str]:
    """The sha256 of every document the owner approved."""
    return frozenset(str(r.get("sha256") or "").strip().lower() for r in _entries()
                     if str(r.get("status") or "").strip().lower() == APPROVED
                     and str(r.get("sha256") or "").strip())


def counts() -> dict[str, int]:
    """How many entries per status (for the AI register; no titles)."""
    out: dict[str, int] = {}
    for r in _entries():
        status = str(r.get("status") or "unknown").strip().lower()
        out[status] = out.get(status, 0) + 1
    return out


def _hashes_of(document_ids: frozenset[str]) -> dict[str, str | None]:
    from .db import connect
    marks = ",".join("?" for _ in document_ids)
    rows = connect().execute(
        f"SELECT id, sha256 FROM documents WHERE id IN ({marks})", sorted(document_ids)).fetchall()
    found = {r["id"]: (r["sha256"] or "").strip().lower() or None for r in rows}
    return {d: found.get(d) for d in document_ids}


def review_documents(review_run_id: str) -> list[str]:
    """The documents a review's prompts can carry: its submittal and every
    standard applied to it. Empty when the run is not found (the callers'
    own checks say that; here it just declares nothing extra)."""
    import sqlite3

    from .db import connect
    conn = connect()
    try:
        run = conn.execute("SELECT submittal_document_id FROM review_runs WHERE id = ?",
                           (review_run_id,)).fetchone()
        if run is None:
            return []
        standards = [r["standard_document_id"] for r in conn.execute(
            "SELECT standard_document_id FROM review_applicable_standards"
            " WHERE review_run_id = ? AND COALESCE(included, 1) = 1", (review_run_id,))]
    except sqlite3.OperationalError:
        # No review tables at all (a database that never ran a review): there
        # is no review to declare. Declaring less can only refuse, never leak.
        return []
    return [run["submittal_document_id"], *standards]


def for_review(fn):
    """Decorator for a function whose first argument is a review run id and
    whose model calls carry that review's documents (its submittal and the
    standards applied to it): the whole call runs under that declaration."""
    import functools

    @functools.wraps(fn)
    def declared(review_run_id, *args, **kwargs):
        with carrying(review_documents(review_run_id)):
            return fn(review_run_id, *args, **kwargs)
    return declared


def refusal() -> tuple[str, str] | None:
    """`(code, reason)` when the Claude call about to be reserved must not
    leave, else None. Ids only in the reason - never a file name."""
    if not settings.claude_approved_list_enforced:
        return None
    ids = carried()
    if ids is None:
        return UNDECLARED, ("the caller did not declare which documents this prompt carries, "
                            "so nothing is sent (fail closed)")
    if not ids:
        return None
    hashes = _hashes_of(ids)
    unknown = sorted(d for d, h in hashes.items() if not h)
    if unknown:
        return UNKNOWN_DOCUMENT, (f"{len(unknown)} declared document(s) are not in the library "
                                  f"(ids: {', '.join(unknown)}), so nothing is sent")
    approved = approved_hashes()
    missing = sorted(d for d, h in hashes.items() if h not in approved)
    if missing:
        return NOT_APPROVED, (f"{len(missing)} of {len(ids)} document(s) in this prompt are not approved "
                              f"for the cloud model (ids: {', '.join(missing)}), so nothing is sent")
    return None


#: #838: what a review step says when it ran on the local model because its
#: documents are not on the list. `{n}` and `{of}` are counts, never a title.
LOCAL_INSTEAD = ("ran on the local model: {n} of {of} document(s) in its prompt are not approved "
                 "for the cloud model")


def local_instead() -> str | None:
    """#838 (planner decision, 11 Oct): a review step whose documents are NOT
    APPROVED runs on the local model instead of being refused - nothing leaves
    the machine - and says so. Returns that sentence when the call the caller
    is about to make would be refused as `NOT_APPROVED`, else None.

    ONLY that refusal. Undeclared and unknown documents are faults of the
    caller, and a budget refusal is the owner's cap: those stay refusals,
    shown and never replaced. This asks the same question as `refusal()` and
    opens no door: the choke point in `claude_spend.reserve_all` is untouched,
    so a caller that ignored the answer would still be refused there."""
    found = refusal()
    if found is None or found[0] != NOT_APPROVED:
        return None
    ids = carried() or frozenset()
    approved = approved_hashes()
    missing = sum(1 for h in _hashes_of(ids).values() if h not in approved)
    return LOCAL_INSTEAD.format(n=missing, of=len(ids))


def sync_audit() -> bool:
    """Write an audit row when the list file's content changed since the last
    row (who = the file, what = how many entries per status and the list's own
    hash). Returns True when a row was written. Called at startup and by the
    route that reports the list; an edit made with a text editor is recorded
    the next time either runs."""
    from .db import connect
    path = list_path()
    digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "absent"
    conn = connect()
    last = conn.execute("SELECT resource_id FROM audit_events WHERE action = ? ORDER BY id DESC LIMIT 1",
                        (AUDIT_ACTION,)).fetchone()
    if last is not None and last["resource_id"] == digest:
        return False
    if last is None and digest == "absent":
        return False
    from datetime import UTC, datetime
    with conn:
        conn.execute(
            "INSERT INTO audit_events (at, actor_user_id, actor_username, action, resource_type,"
            " resource_id, outcome, detail) VALUES (?, NULL, ?, ?, ?, ?, 'ok', ?)",
            (datetime.now(UTC).isoformat(timespec="seconds"), "file edit (owner)", AUDIT_ACTION,
             "claude_approved_list", digest, json.dumps({"entries_by_status": counts()}, sort_keys=True)))
    return True
