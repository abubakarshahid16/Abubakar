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

#1584 (owner decision). `claude_auto_approve` adds documents to the list by
itself behind `claude_auto_approve_reviews_enabled`, off by default, and the list
stays the record. Here, at the gate:

  * BLOCKS WIN, WHATEVER THE SWITCH SAYS, whatever `claude_approved_list_enforced`
    says, and before the chat consent below: a hash with a `blocked` row on the
    list, a hash in `<data_dir>/claude_blocked_hashes.json` (outside git;
    `{"blocked_sha256": ["..."]}`), or a document named like the register
    (CLAUDE.md rule 3), in any case or spacing. THE HASH IS THE BLOCK; the name is
    a backstop, and a re-saved copy of the register needs its own hash.
  * OFF IS A ROLLBACK: with the switch off a row whose `source` starts `auto` does
    not count as approved, so what the switch added stops at once. The block file
    is then not required (a damaged one still refuses).
  * FAIL CLOSED, SWITCH ON: if the list cannot be read, or the block file is
    missing, cannot be read or holds NO hash, nothing carrying a document is sent.
    The owner's real register hash must be in it before the switch is turned on.
  * EVERY SEND IS RECORDED, switch on, on its spend-ledger line (`sent_documents`:
    id and hash, with the line's step, model and time; never a title). A later
    `releases` line for that reservation means the call provably did no work.

This module opens no socket and reads no document text.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import re
import unicodedata
from contextvars import ContextVar
from pathlib import Path

from .config import settings

LIST_NAME = "claude_approved_documents.json"
APPROVED = "approved"
BLOCKED = "blocked"
WITHDRAWN = "withdrawn"
AUTO_SOURCE = "auto"
BLOCK_FILE_NAME = "claude_blocked_hashes.json"
#: The register file of CLAUDE.md rule 3, letters and digits only, lower case.
REGISTER_NAME_KEY = "engineeringdeliverables"
_SHA256 = re.compile(r"[0-9a-f]{64}")
AUDIT_ACTION = "claude_approved_list_changed"

#: Why a call was refused, as the first word of the reason (and the ledger).
UNDECLARED = "undeclared"
NOT_APPROVED = "not_approved"
UNKNOWN_DOCUMENT = "unknown_document"

#: The documents the prompt being built carries. None = nobody declared
#: anything (refused); an empty set = declared to carry no document content.
_CARRIED: ContextVar[frozenset[str] | None] = ContextVar("claude_carried_documents", default=None)
_REQUEST_CONSENT: ContextVar[bool] = ContextVar("claude_request_consent", default=False)


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


@contextlib.contextmanager
def per_request_consent(document_ids):
    """Scope explicit chat consent to exactly the user's selected documents.

    Unlike ``carrying``, this replaces the conversation's broader history
    scope: a user opting to send two selected files must not implicitly send
    every other document mentioned earlier in that conversation. The consent
    is local to this context and never changes the owner allowlist for other
    Claude workflows.
    """
    ids = frozenset(str(d) for d in (document_ids or ()) if d)
    token_ids = _CARRIED.set(ids)
    token_consent = _REQUEST_CONSENT.set(bool(ids))
    try:
        yield
    finally:
        _REQUEST_CONSENT.reset(token_consent)
        _CARRIED.reset(token_ids)


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


def auto_approve_on() -> bool:
    return bool(settings.claude_auto_approve_reviews_enabled)


def block_file_path() -> Path:
    return Path(settings.data_dir) / BLOCK_FILE_NAME


class BlockListUnreadable(Exception):
    """The list or the block file could not be read. Never carries their content."""


def is_register_name(filename: str | None) -> bool:
    """Is this file named like the register, in any case, spacing or punctuation,
    with anything around it ("Copy of ... (1).pdf")? Errs toward blocking."""
    folded = unicodedata.normalize("NFKC", filename or "").casefold()
    return REGISTER_NAME_KEY in "".join(c for c in folded if c.isalnum())


def read_list_strict() -> dict:
    """The whole list, or `BlockListUnreadable`; an absent list is an empty one.
    Unlike `_entries`, a damaged file is an answer of its own: it can hold a block
    that could not be seen, so it must not read as "nothing is blocked"."""
    path = list_path()
    if not path.is_file():
        return {"documents": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BlockListUnreadable("the approved list cannot be read") from exc
    rows = data.get("documents") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise BlockListUnreadable("the approved list has the wrong shape")
    return data


def blocked_hashes() -> frozenset[str]:
    """Every blocked hash: `blocked` rows on the list and the block file's. Raises
    `BlockListUnreadable` when either cannot be read, and for a value that is not a
    hash: a typo must not unblock. Switch on, a block file that is absent or holds
    no hash raises too; switch off, an absent one is simply none."""
    path = block_file_path()
    required = auto_approve_on()
    listed: list = []
    if required or path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BlockListUnreadable("the block file cannot be read") from exc
        listed = data.get("blocked_sha256") if isinstance(data, dict) else None
        if not isinstance(listed, list):
            raise BlockListUnreadable("the block file has the wrong shape")
        if required and not listed:
            raise BlockListUnreadable("the block file holds no hash")
    found = [str(h).strip().lower() for h in listed]
    found += blocked_rows(read_list_strict()["documents"])
    if not all(_SHA256.fullmatch(h) for h in found):
        raise BlockListUnreadable("a blocked entry does not hold a sha256")
    return frozenset(found)


def blocked_rows(rows: list[dict]) -> list[str]:
    """The hash of every `blocked` row among `rows`."""
    return [
        str(r.get("sha256") or "").strip().lower()
        for r in rows
        if str(r.get("status") or "").strip().lower() == BLOCKED
    ]


def _counts_as_approved(row: dict) -> bool:
    """An `approved` row. With the #1584 switch off, not one the switch added."""
    if str(row.get("status") or "").strip().lower() != APPROVED:
        return False
    source = str(row.get("source") or "").strip().lower()
    return auto_approve_on() or not source.startswith(AUTO_SOURCE)


def approved_hashes() -> frozenset[str]:
    """The sha256 of every document approved: never a blocked one, and none at all
    when the blocks cannot be read."""
    approved = frozenset(
        str(r.get("sha256") or "").strip().lower()
        for r in _entries()
        if _counts_as_approved(r) and str(r.get("sha256") or "").strip()
    )
    try:
        return approved - blocked_hashes()
    except BlockListUnreadable:
        return frozenset()


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


def _blocked_ids(hashes: dict[str, str | None]) -> frozenset[str]:
    """The documents among `hashes` (id -> sha256) that are blocked. Raises
    `BlockListUnreadable`."""
    from .db import connect

    blocks = blocked_hashes()
    marks = ",".join("?" for _ in hashes)
    rows = (
        connect()
        .execute(
            f"SELECT id, filename FROM documents WHERE id IN ({marks})", sorted(hashes)
        )
        .fetchall()
    )
    named = {r["id"] for r in rows if is_register_name(r["filename"])}
    return frozenset(d for d, h in hashes.items() if h in blocks or d in named)


def sent_documents() -> list[dict]:
    """#1584: what the call being reserved carries, for its ledger line: id and
    hash, never a title. Empty with the switch off or with no document content."""
    ids = carried()
    if not auto_approve_on() or not ids:
        return []
    hashes = _hashes_of(ids)
    return [{"document_id": d, "sha256": hashes[d]} for d in sorted(ids)]


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


def _block_stop(ids: frozenset[str]) -> tuple[str, str] | None:
    """#1584: a blocked document stops the call. The code stays NOT_APPROVED so a
    review step runs locally instead (#838)."""
    import sqlite3

    try:
        blocked = sorted(_blocked_ids(_hashes_of(ids)))
    except BlockListUnreadable:
        return (
            NOT_APPROVED,
            "the approved list or the block file cannot be read, so nothing is sent (fail closed)",
        )
    except sqlite3.OperationalError:
        # Guard off and no library at all: nothing is there to be blocked.
        if settings.claude_approved_list_enforced:
            raise
        return None
    if blocked:
        return NOT_APPROVED, (
            f"{len(blocked)} of {len(ids)} document(s) in this prompt are blocked "
            f"for the cloud model (ids: {', '.join(blocked)}), so nothing is sent"
        )
    return None


def refusal() -> tuple[str, str] | None:
    """`(code, reason)` when the Claude call about to be reserved must not
    leave, else None. Ids only in the reason - never a file name."""
    ids = carried()
    if ids:  # before the guard and the consent below: a block wins over both
        stopped = _block_stop(ids)
        if stopped is not None:
            return stopped
    if not settings.claude_approved_list_enforced:
        return None
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
    # Chat collection-summary consent is explicit, per request and per selected
    # file. It waives only the static owner list for this narrowly scoped call;
    # egress flags, API-key checks and spend limits remain enforced downstream.
    if _REQUEST_CONSENT.get():
        return None
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
    hashes = _hashes_of(ids)
    try:
        blocked = _blocked_ids(hashes)
    except BlockListUnreadable:
        blocked = ids
    missing = sum(1 for d, h in hashes.items() if h not in approved or d in blocked)
    return LOCAL_INSTEAD.format(n=missing, of=len(ids))


def sync_audit(actor: str = "file edit (owner)") -> bool:
    """Write an audit row when the list file's content changed since the last
    row (who = `actor`, what = how many entries per status and the list's own
    hash). Returns True when a row was written. Called by `claude_auto_approve`
    (#1584 switch on): after an entry is added and when a review starts, so an
    edit made with a text editor is recorded then. Nothing else calls it: with
    the switch off the list's changes are not audited (A-1587)."""
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
            (datetime.now(UTC).isoformat(timespec="seconds"), actor, AUDIT_ACTION,
             "claude_approved_list", digest, json.dumps({"entries_by_status": counts()}, sort_keys=True)))
    return True

