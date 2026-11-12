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
    (CLAUDE.md rule 3), in any case or spacing, or whose name contains the name of a
    file the owner marked in the block file (`"blocked_names"`). Owner, 12 Nov 2026
    afternoon: the register is blocked BY NAME, built in, so no block file is needed;
    a hash blocks the same bytes under any other name.
  * OFF IS A ROLLBACK: with the switch off a row whose `source` starts `auto` does
    not count as approved, so what the switch added stops at once. The block file
    is then not required (a damaged one still refuses).
  * A LAPSED ROLE: an automatic submittal row whose document no longer has a
    qualifying role is refused, whether or not its withdrawal was written.
  * FAIL CLOSED: if the list cannot be read, or the block file EXISTS and cannot
    be read, nothing carrying a document is sent. An absent block file is simply
    no marked file (the register's name block does not need it).
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
REVIEW_ROLE = "CONTRACTOR_SUBMITTAL"
#: Owner decision 12 Nov 2026 (#1584, comment 6820183348): "Specifications: approved for Claude." A specification
#: uploaded for review qualifies exactly as a contractor submittal does (`REVIEW_ROLES`, the one list).
SPECIFICATION_ROLE = "SPECIFICATION"
REVIEW_ROLES = (REVIEW_ROLE, SPECIFICATION_ROLE)
#: A yes the owner's admin recorded for ONE contract file (`contract_yes`): its row's `source`. Not `auto`, so the switch
#: does not roll it back and no role lapse withdraws it; a withdrawn yes is a `withdrawn` row.
CONTRACT_YES_SOURCE = "contract_yes"
#: A rule book (a company standard): the only kind of document the AI reviewer's rule books may be (`claude_auto_approve`).
STANDARD_ROLE = "COMPANY_STANDARD"
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
#: The review run whose documents the calls inside `reviewing()` carry. With `claude_spend.current_run()` it is how the gate
#: knows a prompt belongs to a review run (so which document is the paper under review). None = not a review run.
_REVIEW_RUN: ContextVar[str | None] = ContextVar("claude_review_run", default=None)


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


@contextlib.contextmanager
def reviewing(review_run_id):
    """Name the review run the calls inside this block belong to, so the gate can tell the paper under review from a
    cited specification (`review_shown`). It declares no document: `carrying` does."""
    token = _REVIEW_RUN.set(str(review_run_id) if review_run_id else None)
    try:
        yield
    finally:
        _REVIEW_RUN.reset(token)


@contextlib.contextmanager
def review_declaration(review_run_id):
    """`carrying` the review's documents (`review_documents`) and `reviewing` that run: what a review route declares."""
    with carrying(review_documents(review_run_id)), reviewing(review_run_id):
        yield


def review_run() -> str | None:
    """The review run this call belongs to: `reviewing`, else the spend ledger's `for_run`."""
    from . import claude_spend

    return _REVIEW_RUN.get() or claude_spend.current_run()


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


_EXTENSION = re.compile(r"\.[a-z0-9]{1,5}$")
#: A name the owner marks must have at least this many letters and digits, else it would block almost every file.
MIN_MARKED_KEY = 5


def name_key(filename: str | None) -> str:
    """A file name as letters and digits only: lower case, extension dropped, every
    space, underscore, hyphen and bracket gone. "Name_ (1).PDF" and "name copy" both
    reduce to something that starts with the key of "Name"."""
    folded = unicodedata.normalize("NFKC", filename or "").casefold().strip()
    return "".join(c for c in _EXTENSION.sub("", folded) if c.isalnum())


def is_register_name(filename: str | None) -> bool:
    """Is this file named like the register, in any case, spacing or punctuation,
    with anything around it ("Copy of ... (1).pdf")? Errs toward blocking."""
    return REGISTER_NAME_KEY in name_key(filename)


def _present(path: Path) -> bool:
    """Is there a file here? An operating-system refusal is `BlockListUnreadable`, never a crash."""
    try:
        return path.exists()
    except OSError as exc:
        raise BlockListUnreadable("the block file cannot be read") from exc


def marked_name_keys() -> frozenset[str]:
    """The keys of the file NAMES the owner marked in the block file
    (`"blocked_names": [...]`). Raises `BlockListUnreadable` for a block file that is
    damaged, and for a name with too few letters and digits (it would block nearly
    everything: fail closed). An absent file marks nothing."""
    path = block_file_path()
    if not _present(path):
        return frozenset()
    names = _read_block_file(path).get("blocked_names")
    if names is None:
        return frozenset()
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise BlockListUnreadable("the block file has the wrong shape")
    keys = [name_key(n) for n in names]
    if any(len(k) < MIN_MARKED_KEY for k in keys):
        raise BlockListUnreadable("a blocked name is too short to be a file name")
    return frozenset(keys)


def name_is_blocked(filename: str | None, marked: frozenset[str] | None = None) -> bool:
    """Is a file with this stored name blocked BY NAME: named like the register, or
    containing the name of a file the owner marked (`marked`: `marked_name_keys()`).
    A near-name, a copy suffix, a date or revision after the name, another
    extension and different spacing all match: the safer error is to block."""
    key = name_key(filename)
    if REGISTER_NAME_KEY in key:
        return True
    return any(m in key for m in (marked or ()))


def blocked_by_name(filename: str | None) -> bool:
    """`name_is_blocked` against the block file as it is now. A block file that cannot
    be read answers True: when in doubt the file is blocked."""
    try:
        return name_is_blocked(filename, marked_name_keys())
    except BlockListUnreadable:
        return True


def _read_block_file(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BlockListUnreadable("the block file cannot be read") from exc
    if not isinstance(data, dict):
        raise BlockListUnreadable("the block file has the wrong shape")
    return data


def read_list_strict() -> dict:
    """The whole list, or `BlockListUnreadable`; an absent list is an empty one.
    Unlike `_entries`, a damaged file is an answer of its own: it can hold a block
    that could not be seen, so it must not read as "nothing is blocked"."""
    path = list_path()
    try:
        if not path.is_file():
            return {"documents": []}
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
    hash: a typo must not unblock. An ABSENT block file is none, switch on or off
    (the register is blocked by its file name without it; owner, 12 Nov 2026); one that
    exists and cannot be read raises."""
    path = block_file_path()
    listed: list = []
    if _present(path):
        listed = _read_block_file(path).get("blocked_sha256")
        if listed is None:
            listed = []
        if not isinstance(listed, list):
            raise BlockListUnreadable("the block file has the wrong shape")
        marked_name_keys()  # a damaged name list is as bad as a damaged hash list
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
    marked = marked_name_keys()
    marks = ",".join("?" for _ in hashes)
    rows = (
        connect()
        .execute(
            f"SELECT id, filename FROM documents WHERE id IN ({marks})", sorted(hashes)
        )
        .fetchall()
    )
    named = {r["id"] for r in rows if name_is_blocked(r["filename"], marked)}
    return frozenset(d for d, h in hashes.items() if h in blocks or d in named)


def _lapsed_ids(hashes: dict[str, str | None]) -> frozenset[str]:
    """#1584: the documents whose only approval is a submittal's automatic row
    (`source` exactly `auto`) and whose role no longer qualifies. A withdrawal can
    fail to be written (switch off, list unreadable), so the gate asks the role
    itself. A row from the owner or a citation does not lean on the role."""
    leaning, standing = set(), set()
    for row in _entries():
        if str(row.get("status") or "").strip().lower() == APPROVED:
            sha = str(row.get("sha256") or "").strip().lower()
            (leaning if row.get("source") == AUTO_SOURCE else standing).add(sha)
    ids = sorted(d for d, h in hashes.items() if h in leaning and h not in standing)
    if not ids:
        return frozenset()
    from .db import connect

    marks = ",".join("?" for _ in ids)
    rows = (
        connect()
        .execute(
            f"SELECT document_id, document_role FROM document_classification"
            f" WHERE document_id IN ({marks})",
            ids,
        )
        .fetchall()
    )
    return frozenset(
        r["document_id"]
        for r in rows
        if r["document_role"] not in (None, *REVIEW_ROLES)
    )


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
        with carrying(review_documents(review_run_id)), reviewing(review_run_id):
            return fn(review_run_id, *args, **kwargs)
    return declared


def carried_hashes() -> dict[str, str | None] | None:
    """The documents declared for this prompt with their file hashes, for the answer
    cache's file; None when nobody declared. Ids and hashes only."""
    ids = carried()
    if ids is None:
        return None
    return _hashes_of(ids) if ids else {}


def still_holds(documents: dict[str, str] | None) -> bool:
    """Whether a stored answer written under `documents` may still be served: each
    is in the library as the same file and, with the list enforced, still approved.
    A document deleted, replaced, withdrawn or blocked means no. Asked ON TOP of
    `refusal()`, which only knows what THIS caller declares."""
    if not documents:
        return True
    hashes = _hashes_of(frozenset(documents))
    # A block wins over the guard and over consent.
    if hashes != documents or _blocked_ids(hashes):
        return False
    if not settings.claude_approved_list_enforced:
        return True
    if _REQUEST_CONSENT.get():
        return frozenset(documents) <= (carried() or frozenset())
    approved = frozenset(documents.values()) <= approved_hashes()
    return approved and not _lapsed_ids(hashes)


def _block_stop(ids: frozenset[str]) -> tuple[str, str] | None:
    """#1584: a blocked document stops the call. The code stays NOT_APPROVED so a
    review step runs locally instead (#838)."""
    import sqlite3

    try:
        blocked = sorted(_blocked_ids(_hashes_of(ids)))
    except BlockListUnreadable as exc:
        why = str(exc)
        return (
            NOT_APPROVED,
            f"the approved list or the block file has a fault ({why}), so nothing is sent (fail closed)",
        )
    except sqlite3.OperationalError:
        # Guard off and no library at all: nothing is there to be blocked.
        if settings.claude_approved_list_enforced:
            raise
        return None
    if blocked:
        return NOT_APPROVED, (
            f"{len(blocked)} of {len(ids)} document(s) in this prompt are blocked "
            f"for the cloud model by file name or checksum (ids: {', '.join(blocked)}), so nothing is sent"
        )
    return None


def contracts_without_yes(ids) -> frozenset[str]:
    """The declared documents that are a CONTRACT (by role, or by the code's own kind decision; unreadable counts as a contract) and
    have no standing recorded yes (`contract_yes`). Owner, 12 Nov 2026 (#1584): a contract goes to Claude only with the owner's yes
    for that upload. Asked on EVERY route to the gate (a review's paper, a cited document, an AI reviewer's book), never narrowed
    by how the document came onto the list."""
    from . import claude_auto_approve, contract_yes

    return frozenset(
        d
        for d in ids
        if claude_auto_approve.is_contract_paper(d) and not contract_yes.has_yes(d)
    )


def _unshown_specifications(ids) -> frozenset[str]:
    """Owner, 12 Nov 2026 (#1584): the screen lists every document that will leave before the review starts. Inside a review
    run, a SPECIFICATION that is not the paper under review goes only if the run's stored list names it (`review_shown`);
    no list stored = none goes. Outside a review run (chat, a standalone reader) nothing changes. Only NARROWS. A library
    that cannot be read holds every declared document (fail closed)."""
    run = review_run()
    if not run or not ids:
        return frozenset()
    import sqlite3

    from . import review_shown
    from .db import connect

    try:
        return review_shown.unshown_specifications(connect(), run, ids)
    except sqlite3.Error:
        return frozenset(ids)


def refusal() -> tuple[str, str] | None:
    """`(code, reason)` when the Claude call about to be reserved must not
    leave, else None. Ids only in the reason - never a file name.

    FIRST, before every other question and whatever the list says: a run whose plan keeps it on this computer
    (`review_engine.barring`: Local only, or a part the plan put on the local model) sends nothing, ever."""
    from . import review_engine

    if review_engine.claude_barred():
        return review_engine.BARRED_CODE, review_engine.BARRED_WORDS
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
    held = _unshown_specifications(ids)
    if held:
        return NOT_APPROVED, (
            f"{len(held)} of {len(ids)} document(s) in this prompt are specifications this review cites "
            f"that were not on the list shown before the start (ids: {', '.join(sorted(held))}), "
            f"so nothing is sent"
        )
    approved = approved_hashes()
    lapsed = _lapsed_ids(hashes) | contracts_without_yes(ids)
    missing = sorted(d for d, h in hashes.items() if h not in approved or d in lapsed)
    if missing:
        return NOT_APPROVED, (f"{len(missing)} of {len(ids)} document(s) in this prompt are not approved "
                              f"for the cloud model (ids: {', '.join(missing)}), so nothing is sent")
    return None


#: #838: what a review step says when it ran on the local model because its
#: documents are not on the list. `{n}` and `{of}` are counts, never a title.
LOCAL_INSTEAD = ("ran on the local model: {n} of {of} document(s) in its prompt are not approved "
                 "for the cloud model")
LOCAL_INSTEAD_NOT_SHOWN = (
    "ran on the local model: {n} of {of} document(s) in its prompt are specifications "
    "that were not on the list shown before the start"
)


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
    held = _unshown_specifications(ids)
    if held:
        return LOCAL_INSTEAD_NOT_SHOWN.format(n=len(held), of=len(ids))
    approved = approved_hashes()
    hashes = _hashes_of(ids)
    try:
        blocked = _blocked_ids(hashes)
    except BlockListUnreadable:
        blocked = ids
    blocked = blocked | _lapsed_ids(hashes) | contracts_without_yes(ids)
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

