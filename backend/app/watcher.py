"""Watched-folder auto-ingest.

The client's team drops PDFs into a share; this brings them into the corpus
without anybody opening the app. It is the SECOND ingestion path, and every
decision here exists because it is the second one rather than the first.

WHAT MAKES A DROP FOLDER DIFFERENT FROM AN UPLOAD BUTTON

  * NOBODY IS WATCHING. A manual upload reports its outcome to the person who
    pressed the button. A file dropped into a share reports to nobody, so a
    document that was seen and refused looks exactly like one that was never
    dropped. Every decision this loop makes - ingested, duplicate, failed -
    is written to `watch_events`, and /api/watch/status is where an operator
    reads them back. A silent refusal here would be a client believing their
    specification is searchable when it is not.

  * THE FILE IS STILL BEING WRITTEN. A 40 MB PDF copied onto a network share
    exists, is listed, and is openable long before it is complete. Ingesting
    it produces a truncated document that extracts, chunks and answers
    questions wrongly - the worst possible failure, because it looks like a
    success. So a file is eligible only when its size AND mtime are UNCHANGED
    across two consecutive scans. That costs one interval of latency and buys
    the difference between a partial document and no document.

  * THE SOURCE IS NOT OURS. The folder belongs to the client. Nothing here
    modifies, moves, renames or deletes anything in it - the bytes are COPIED
    into managed storage by the same code the upload route uses, and the
    original is left exactly as found. A watcher that tidies up after itself
    is a watcher that one day deletes a file it should not have.

  * IT MUST NOT BE ABLE TO STOP. One corrupt PDF, one file locked by the
    person still copying it, one permission error - none of these may end the
    loop. Each is caught per file, recorded, and the scan moves to the next
    one; the scan itself is caught too, so the next one still happens on
    schedule.

REUSE, NOT REIMPLEMENTATION. `upload.ingest` does the streaming, the PDF magic
check, the size ceiling, the hashing, the dedup and the atomic rename, and
`admin.grant_on_upload` makes the result readable. Both are called here
exactly as the POST /api/documents handler calls them. A second copy of that
sequence would be a second set of rules about what a document is.

ONE SCAN IS A PLAIN CALLABLE. `FolderWatcher.scan_once()` does a whole pass
and returns what it did; the thread is a loop around it and nothing else. That
is what makes the behaviour testable without sleeping through a five-minute
interval, and it keeps the interesting logic out of the part that cannot be
called directly.
"""

from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import access
from . import admin as admin_mod
from . import errors
from . import upload as upload_mod
from .config import settings
from .db import connect

#: Outcomes, matching the CHECK constraint on `watch_events.outcome`. Named so
#: a typo is an ImportError here rather than an IntegrityError at 3am.
INGESTED = "ingested"
DUPLICATE = "duplicate"
FAILED = "failed"

#: What a scan found the folder to be. Reported, and logged only when it
#: CHANGES - a missing share logged every five minutes is a log nobody reads,
#: and the transition is the event worth recording anyway.
STATE_DISABLED = "disabled"
STATE_OK = "ok"
STATE_MISSING = "missing"
STATE_UNREADABLE = "unreadable"

#: The ONE sentence a scan-level failure is ever reported with, and it names
#: nothing. `settings.watch_folder` is withheld from non-administrators by
#: /api/watch/status; a failure message that quoted the path would hand it
#: back to exactly the callers the field was withheld from, which is how
#: /api/health's disclosures ended up on /api/metrics rather than being fixed.
#:
#: AND THE OPERATING SYSTEM'S OWN TEXT IS NEVER PASSED THROUGH. `OSError`
#: carries `filename`, so `str(exc)` for a permission failure reads
#: "[Errno 13] Permission denied: '//fileserver/Engineering/drop'" - the whole
#: path, the share name and the host, in the field most likely to be shown on
#: a screen. The cause is reported by KIND, from the exception class, and the
#: full error goes to the local log like every other internal detail.
FOLDER_UNREADABLE = "the watched folder could not be read"

#: Exception class -> the half-sentence that explains it without locating it.
#: Keyed by class rather than by errno so a platform that raises a different
#: errno for the same condition still reads correctly.
_UNREADABLE_CAUSES = {
    "PermissionError": "permission was denied",
    "FileNotFoundError": "it is no longer there",
    "NotADirectoryError": "the configured path is not a directory",
}

#: `watch_events.sha256` is NOT NULL, and a file that cannot be opened cannot
#: be hashed. This is the marker for that one case; every row carrying it also
#: says so in `detail`, because a blank column that a reader has to interpret
#: is the kind of quiet dishonesty this codebase keeps auditing out of itself.
NO_HASH = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


#: The three ways a configured owner can fail to be one. Constants, so the
#: watcher and its tests name the same thing and a reworded sentence cannot
#: quietly become a different refusal.
#:
#: NONE OF THEM ECHOES THE CONFIGURED EMAIL. `detail` reaches the panel every
#: engineer can open, and `watch_owner_email` is a real person's address that
#: the operator put in a file - reflecting it back would publish an identity
#: through a status screen, which is the same class of disclosure the `folder`
#: field is withheld for. Each sentence says what to change and where, which
#: is what an operator needs, and none says what the value currently is.
OWNER_UNSET = (
    "no owner is configured for the watched folder: set WATCH_OWNER_EMAIL in "
    "the backend .env file to the email of an existing active user who holds "
    "a discipline role. Without an owner an auto-ingested document would be "
    "granted to nobody and could not be read by anyone, including an "
    "administrator."
)
OWNER_UNKNOWN = (
    "WATCH_OWNER_EMAIL does not match any active user account. Check it "
    "against the Users screen and set it to an existing active user who holds "
    "a discipline role."
)
OWNER_HAS_NO_DISCIPLINE = (
    "the user named by WATCH_OWNER_EMAIL holds no discipline role, so an "
    "auto-ingested document would be granted to no discipline and would "
    "appear on no engineer's screen. Give that user a discipline on the Users "
    "screen, or point WATCH_OWNER_EMAIL at a user who already has one."
)


def _active_user_id_by_email(email: str) -> str | None:
    """The user id for an email, or None.

    WRITTEN HERE BECAUSE NOTHING REUSABLE EXISTS. `auth.login` holds the only
    lookup of this shape and it is a login - it verifies a password, records a
    failed-attempt, and writes an audit row, none of which may happen because
    a background thread read a configuration file. `admin.py` asks only
    whether an email is TAKEN, and returns no id. So this is a new query and
    it is deliberately the same query: `lower(email) = ?` exactly as
    `auth.login` spells it, so a mixed-case address in `.env` resolves to the
    same person who can sign in with it.

    `is_active = 1` matches `auth.resolve_user_id`, which re-reads it on every
    request precisely so that deactivating somebody takes effect immediately.
    A deactivated owner is not an owner, and documents must stop flowing to
    their disciplines the moment they are deactivated rather than at some
    later restart.
    """
    row = connect().execute(
        "SELECT id FROM users WHERE lower(email) = ? AND is_active = 1",
        (email.strip().lower(),),
    ).fetchone()
    return row["id"] if row is not None else None


def _holds_a_discipline(user_id: str) -> bool:
    """Does this user hold a role of kind `discipline`?

    THE SAME PREDICATE `admin.grant_on_upload` USES to choose what to grant -
    `roles.kind = 'discipline'`, not the role's name. If this asked the
    question a different way the check and its consequence could disagree, and
    the failure mode of that disagreement is a document granted to nothing
    while the watcher reports it ingested.
    """
    return connect().execute(
        """SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id
           WHERE ur.user_id = ? AND r.kind = 'discipline' LIMIT 1""",
        (user_id,),
    ).fetchone() is not None


def resolve_owner() -> tuple[str | None, str | None]:
    """Who a dropped document belongs to: `(user_id, refusal)`.

    Exactly one of the two is meaningful. A refusal is a sentence to write to
    `watch_events`; `user_id` is what to hand `admin.grant_on_upload`, and
    None there means "no owner and that is correct", not "unknown".

    THE OWNERSHIP RULE, TAKEN FROM THE UPLOAD ROUTE RATHER THAN INVENTED.
    `POST /api/documents` calls `_require_identity_to_write(scope)` and then
    `admin.grant_on_upload(document_id, scope.user_id)`. Those two lines are
    one rule: a document is accepted only when there is an identity to grant
    it to, because `document_role_access` is written by `grant()` and by
    nothing else, and a document with no grant row is invisible to everyone
    including an administrator.

      * AUTH_MODE=disabled - `unrestricted_scope()` gives every caller every
        document and `grant_on_upload(id, None)` deliberately writes nothing,
        so a manual upload in this mode is ALREADY an ungranted document that
        everybody can read. The folder behaves identically, and there is no
        grant system running to weaken.

      * AUTH_MODE=demo_required - the file has no identity of its own, so the
        administrator supplies one: `settings.watch_owner_email`, a real user
        who already exists. The document then gets precisely the grants a
        manual upload by that person would produce, because it is the same
        call with the same argument. Nothing here can grant more than that -
        there is no second write, and this function returns an id, never a
        role.

    Three ways that can fail, and each says which it is. An operator reading
    the panel has to be able to act without reading this file.
    """
    if settings.auth_mode == access.AUTH_DISABLED:
        return None, None

    email = (settings.watch_owner_email or "").strip()
    if not email:
        return None, OWNER_UNSET

    user_id = _active_user_id_by_email(email)
    if user_id is None:
        return None, OWNER_UNKNOWN

    if not _holds_a_discipline(user_id):
        return None, OWNER_HAS_NO_DISCIPLINE

    return user_id, None


def record_event(filename: str, source_path: str, sha256: str, outcome: str,
                 document_id: str | None = None, detail: str | None = None) -> None:
    """Append one row to `watch_events`. The only writer of that table."""
    with connect() as conn:
        conn.execute(
            """INSERT INTO watch_events
                   (filename, source_path, sha256, observed_at, outcome,
                    document_id, detail)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (filename, source_path, sha256, _now(), outcome, document_id, detail),
        )


def hash_file(path: Path) -> str:
    """SHA-256 of the file on disk, read in the same blocks upload streams in.

    Deliberately NOT reading the file whole: the drop folder is expected to
    receive the same 1,400-page documents the upload route is sized for.
    """
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(settings.upload_chunk_bytes)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


class FolderWatcher:
    """Polls one folder. One instance holds the memory that makes it work.

    Two dictionaries, and they answer different questions:

      * `_seen` is what the LAST scan measured, per filename. A file is stable
        when this scan measures the same size and mtime. This is the anti-
        half-copied-file rule and nothing else.

      * `_handled` is what has already been DECIDED, keyed by filename and
        carrying the size/mtime the decision was made about. A file already
        handled is skipped - including a failed one, so a corrupt PDF is
        reported once rather than every five minutes forever. Because the
        recorded size/mtime is part of it, REPLACING the file with a corrected
        version makes it eligible again, which is what an operator would
        expect after fixing a bad drop.

    `_duplicate_hashes` is the same idea at the level of content rather than
    filename: a copy of an already-ingested document appearing under a third
    name is still nothing new, and re-announcing it on every scan would bury
    the events that matter.

    In memory, never a table. A restart re-observes the folder from scratch,
    which costs one extra interval and re-derives every one of these facts
    from the filesystem and from `documents` - the two things that are
    actually authoritative.
    """

    def __init__(self, poll_seconds: float | None = None) -> None:
        #: None means "read `settings.watch_interval_seconds` at each sleep",
        #: so changing the interval does not require a restart and a test can
        #: pass a short one explicitly.
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._seen: dict[str, tuple[int, int]] = {}
        self._handled: dict[str, tuple[int, int]] = {}
        self._duplicate_hashes: set[str] = set()
        #: ISO-8601 UTC of the last COMPLETED scan, or None if none has
        #: finished. Null rather than a zero timestamp: "never scanned" and
        #: "scanned at the epoch" are different facts.
        self.last_scan_at: str | None = None
        self.last_state: str | None = None
        #: Did the MOST RECENT scan find the folder readable? None until one
        #: has run, and None is the whole point of the field: `enabled` says
        #: the feature is CONFIGURED, which at the client's site means a
        #: network share that can be unmounted, un-permissioned or left behind
        #: by a dropped VPN. Without this the panel stays perfectly healthy
        #: while `last_scan_at` quietly ages, which is the dishonesty this
        #: codebase keeps auditing out of itself.
        #:
        #: NEVER False before a scan. False is an OBSERVATION - somebody
        #: looked and could not read it - and claiming one that has not
        #: happened is the same defect as a measurement reported as 0.
        self.last_reachable: bool | None = None
        #: Why the last scan could not read the folder, or None when it could.
        #: SCAN-LEVEL ONLY. A corrupt PDF is a per-file 'failed' event and
        #: says nothing about the folder; letting one bad drop raise a
        #: folder-level alarm would train an operator to ignore the alarm.
        self.last_error: str | None = None
        #: The folder the above state was observed for. Kept so that changing
        #: `settings.watch_folder` re-logs the new folder's state instead of
        #: staying quiet because the STATE happens to match.
        self._state_folder: str | None = None

    # ------------------------------------------------------------- lifecycle

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="watch-folder", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _interval(self) -> float:
        if self.poll_seconds is not None:
            return float(self.poll_seconds)
        return float(max(1, settings.watch_interval_seconds))

    def _run(self) -> None:
        """The loop. It may not end for any reason other than being stopped.

        Every exception is caught HERE as well as per file, because the
        per-file guards can only catch what happens inside them: a folder that
        vanishes mid-listing, a database locked longer than its timeout, an
        error in this module's own bookkeeping. A watcher that dies leaves the
        client dropping files into a folder nothing is reading, and reports
        nothing at all - it is the exact failure this feature is supposed to
        remove.
        """
        while not self._stop.is_set():
            try:
                self.scan_once()
            except Exception as exc:  # noqa: BLE001 - the loop must outlive any scan
                errors.record_failure(exc, stage="watch-folder")
            self._stop.wait(self._interval())

    # ------------------------------------------------------------- one scan

    @staticmethod
    def _unreadable_because(exc: OSError) -> str:
        """A safe sentence for a folder that could not be listed.

        Built from the exception CLASS. `str(exc)` is never used: see
        FOLDER_UNREADABLE for what it contains and why that cannot be shown.
        An unrecognised class degrades to its own name, which is a Python
        type and not a filesystem location.
        """
        cause = _UNREADABLE_CAUSES.get(
            exc.__class__.__name__,
            f"the operating system reported {exc.__class__.__name__}")
        return f"{FOLDER_UNREADABLE}: {cause}"

    def _note_state(self, state: str, folder: str, detail: str) -> None:
        """Log a folder-state transition once. Never once per scan."""
        if state == self.last_state and folder == self._state_folder:
            return
        self.last_state = state
        self._state_folder = folder
        errors.logger().info("watch folder %s: %s", state, detail)

    def scan_once(self) -> dict:
        """One whole pass. Returns what it did; raises nothing it can help.

        The return value is for tests and for the log - the durable record of
        a scan is the `watch_events` rows it wrote, not this dict.
        """
        configured = (settings.watch_folder or "").strip()
        if not configured:
            self._note_state(STATE_DISABLED, "", "no folder configured; nothing is watched")
            # Off is not unreachable. Nothing was looked at, so there is
            # nothing to report about it - and a previously configured folder
            # that has since been unset must not leave a stale verdict behind.
            self.last_reachable = None
            self.last_error = None
            return self._result(STATE_DISABLED, None)

        folder = Path(configured)
        try:
            if not folder.is_dir():
                self._note_state(
                    STATE_MISSING, configured,
                    f"{configured!r} is not a directory that exists; waiting for it")
                self.last_reachable = False
                # No path, here or anywhere else this string can reach.
                self.last_error = (
                    f"{FOLDER_UNREADABLE}: no directory exists at the "
                    "configured path")
                return self._result(STATE_MISSING, configured)
            entries = sorted(
                p for p in folder.iterdir()
                if p.is_file() and p.suffix.lower() == ".pdf"
            )
        except OSError as exc:
            # A share that is present but not readable, or that disappeared
            # between the check and the listing. Not fatal, and not a crash:
            # the next scan asks again.
            self._note_state(
                STATE_UNREADABLE, configured,
                f"{configured!r} could not be listed: {exc.__class__.__name__}")
            self.last_reachable = False
            self.last_error = self._unreadable_because(exc)
            return self._result(STATE_UNREADABLE, configured)

        self._note_state(STATE_OK, configured, f"watching {configured!r}")
        # Read, listed, and about to be processed. Cleared here rather than at
        # the end of the pass on purpose: the folder's reachability is settled
        # by the listing, and whatever the individual files turn out to be
        # must not change the answer.
        self.last_reachable = True
        self.last_error = None

        present = {p.name for p in entries}
        # Bounded memory: a file that is gone is a file we have no facts about.
        # Re-appearing means re-observing, which is correct - it may be a
        # different file with the same name.
        self._seen = {k: v for k, v in self._seen.items() if k in present}
        self._handled = {k: v for k, v in self._handled.items() if k in present}

        result = self._result(STATE_OK, configured)
        for path in entries:
            try:
                stat = path.stat()
            except OSError:
                # Deleted or locked between listing and stat. Nothing has been
                # decided about it, so nothing is recorded; the next scan sees
                # whatever is actually there.
                continue
            fingerprint = (stat.st_size, stat.st_mtime_ns)
            previous = self._seen.get(path.name)
            self._seen[path.name] = fingerprint

            if self._handled.get(path.name) == fingerprint:
                result["already_handled"].append(path.name)
                continue
            if previous != fingerprint:
                # Either new to us, or still changing. Both mean "not yet".
                result["unstable"].append(path.name)
                continue

            outcome = self._handle(path, fingerprint)
            result[outcome].append(path.name)

        # Re-stamped at the END. `_result` stamped the start so the early
        # returns above have a time at all; a pass that ingested a 1,400-page
        # document took real minutes, and "last scan" means the moment it
        # finished, not the moment it began.
        result["at"] = self.last_scan_at = _now()
        return result

    def _result(self, state: str, folder: str | None) -> dict:
        """A completed pass, stamped. A scan that found the folder MISSING is
        still a scan that ran, and `last_scan_at` has to say so - otherwise
        the status screen shows "never scanned" for a watcher that has been
        looking faithfully every five minutes at a share that is not there,
        which points an operator at the wrong problem."""
        self.last_scan_at = _now()
        return {
            "state": state,
            "folder": folder,
            "at": self.last_scan_at,
            INGESTED: [],
            DUPLICATE: [],
            FAILED: [],
            "unstable": [],
            "already_handled": [],
        }

    def _handle(self, path: Path, fingerprint: tuple[int, int]) -> str:
        """Decide about one stable file, record it, and never raise.

        Returns the outcome, which is also the key the caller counts it under.
        Marked handled whatever happens - a failure re-reported every interval
        is noise that hides the next real one, and replacing the file changes
        its fingerprint and makes it eligible again.
        """
        source = str(path)
        try:
            sha256 = hash_file(path)
        except OSError as exc:
            self._handled[path.name] = fingerprint
            record_event(
                path.name, source, NO_HASH, FAILED,
                detail=(f"no sha256: the file could not be read "
                        f"({exc.__class__.__name__}); it may be locked by "
                        f"whoever is writing it, or unreadable by this process"),
            )
            return FAILED

        self._handled[path.name] = fingerprint

        # The dedup mechanism is `upload.find_by_hash`, which is what
        # `upload.ingest` itself consults - the same question against the same
        # table, asked early so an already-known document is never re-copied.
        try:
            existing = upload_mod.find_by_hash(sha256)
        except Exception as exc:  # noqa: BLE001 - one file must not end the scan
            errors.record_failure(exc, stage="watch-folder")
            record_event(path.name, source, sha256, FAILED,
                         detail="the document store could not be queried")
            return FAILED

        if existing is not None:
            if sha256 in self._duplicate_hashes:
                # Announced once already, under this or another name. Silence
                # here is not a lost fact: the event exists and the document
                # exists.
                return DUPLICATE
            self._duplicate_hashes.add(sha256)
            record_event(
                path.name, source, sha256, DUPLICATE, document_id=existing["id"],
                detail="already in the corpus with the same sha256; nothing was copied",
            )
            return DUPLICATE

        owner_id, refusal = resolve_owner()
        if refusal is not None:
            record_event(path.name, source, sha256, FAILED, detail=refusal)
            return FAILED

        try:
            with path.open("rb") as fh:
                row, job_id, duplicate_of = upload_mod.ingest(fh, path.name)
        except upload_mod.UploadError as exc:
            # A refusal the upload route would have answered 400 to: not a
            # PDF, empty, or over the size ceiling. The client's own error,
            # stated as such rather than as a system failure.
            record_event(path.name, source, sha256, FAILED,
                         detail=f"{exc.code}: {exc.message}")
            return FAILED
        except Exception as exc:  # noqa: BLE001 - one file must not end the scan
            safe = errors.record_failure(exc, stage="watch-folder")
            record_event(path.name, source, sha256, FAILED,
                         detail=f"{safe['code']}: {safe['message']}")
            return FAILED

        if duplicate_of is not None:
            # Raced with something else that stored the same bytes between the
            # hash above and the write. `ingest` already declined to copy.
            self._duplicate_hashes.add(sha256)
            record_event(path.name, source, sha256, DUPLICATE,
                         document_id=duplicate_of,
                         detail="already in the corpus with the same sha256; nothing was copied")
            return DUPLICATE

        # The second half of the upload route's acceptance, and the ONLY write
        # to the grant tables anywhere in this module. The same function the
        # route calls, with the same kind of argument, so the document ends up
        # with precisely the grants a manual upload by `owner_id` would have
        # produced - their disciplines plus the admin capability. Under
        # `disabled` the id is None and this deliberately writes nothing.
        #
        # There is no second grant, no widening and no special case. A watcher
        # that wrote a row `grant_on_upload` would not write would be handing
        # out access the upload route cannot, which is a privilege escalation
        # dressed as a convenience.
        granted = admin_mod.grant_on_upload(row["id"], owner_id)
        record_event(
            path.name, source, sha256, INGESTED, document_id=row["id"],
            detail=(f"queued as job {job_id}" if job_id else "queued")
            + (f"; granted to {', '.join(granted)}" if granted else ""),
        )
        return INGESTED


# ------------------------------------------------------------- module handle
#
# Shaped exactly like `ingest.get_worker` / `start_worker` / `stop_worker`, so
# the two background threads in this system are started, stopped and reached
# the same way. main.py's lifespan owns the calls.

_watcher: FolderWatcher | None = None
_watcher_lock = threading.Lock()


def get_watcher() -> FolderWatcher:
    global _watcher
    with _watcher_lock:
        if _watcher is None:
            _watcher = FolderWatcher()
        return _watcher


def start_watcher() -> str | None:
    """Start the loop. Returns None if it started, or WHY it did not.

    A reason string rather than a bare False: "no watch folder is configured"
    and "the thread is already running" are different facts, and a caller that
    logs the return value says something true either way. Not an exception -
    an unconfigured folder is the DEFAULT state of this system, not an error.
    """
    if not (settings.watch_folder or "").strip():
        return ("no watch folder is configured (settings.watch_folder is empty),"
                " so nothing is watched")
    w = get_watcher()
    if w.alive:
        return "the watch-folder thread is already running"
    w.start()
    return None


def stop_watcher() -> None:
    global _watcher
    with _watcher_lock:
        if _watcher is not None:
            _watcher.stop()
            _watcher = None


def reset_watcher() -> None:
    """Test helper - drop the singleton, exactly as `db.reset_connection` does.

    The in-memory stability state is what makes a scan mean anything, so a
    test that inherited a previous test's dictionaries would be testing the
    wrong thing.
    """
    global _watcher
    with _watcher_lock:
        _watcher = None


def scan_once() -> dict:
    """One pass on the shared watcher. The loop and a caller run the same code."""
    return get_watcher().scan_once()


def last_scan_at() -> str | None:
    """ISO-8601 UTC of the last completed scan, or None if none has completed.

    Reads the singleton WITHOUT creating one: no scan has happened if no
    watcher exists, and manufacturing one here to answer a status question
    would make the answer depend on who asked.
    """
    return _watcher.last_scan_at if _watcher is not None else None


def last_reachable() -> bool | None:
    """Whether the last scan could read the folder; None if none has run.

    Reads the singleton WITHOUT creating one, for the same reason
    `last_scan_at` does: a status question must not manufacture the thing it
    is asking about. No watcher means no scan means no observation - None,
    never False.
    """
    return _watcher.last_reachable if _watcher is not None else None


def last_error() -> str | None:
    """The last SCAN-LEVEL failure, or None. Safe to show to any caller -
    it never names the folder. Per-file failures are `watch_events` rows."""
    return _watcher.last_error if _watcher is not None else None
