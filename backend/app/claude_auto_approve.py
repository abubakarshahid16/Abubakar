"""#1584 (owner decision, 2 Nov 2026): a document uploaded for review joins the
approved list by itself, unless it is blocked.

Behind `claude_auto_approve_reviews_enabled`, off by default: off, every hook
here returns at once and touches nothing.

WHAT GETS AN ENTRY, AND WHEN
  * a contractor submittal, when its role is set (an upload usually has no role
    yet; the role is what says it is for review) or when an upload arrives that
    already has one;
  * the subject of a review, when the review starts, so documents uploaded
    earlier are covered. A subject with no role is listed: it is being reviewed.
    A subject whose role says standard, contract, supporting or template is not;
  * a standard a review cites (`included` = 1), when the review starts or when
    the review records it, whichever is first: a review chooses its standards
    after it starts, so "at the start" alone would miss all of them. Never the
    whole library, and never a standard the review ruled out.

WHAT NEVER GETS ONE
  * a blocked hash: a `status: blocked` row on the list, or a hash in the local
    block file. Existing rows are never rewritten, so an owner's block or a
    `pending_owner` row stays exactly as it was written;
  * a file named like the register (`claude_approved.is_register_name`): it gets
    a `blocked` row instead, so the same bytes stay blocked under any other name.
    A blocked row beside an earlier approved row wins at the gate.

FAIL CLOSED. If the list or the block file cannot be read, nothing is added and
the file is left alone; the gate refuses on the same reading.

A write is one lock (threads and processes) around read, change, and an atomic
replace; the list stays under `data_dir`, outside git.

NEVER RAISES into an upload, a role change or a review start: an entry that was
not written means the document stays off the list, and off the list nothing is
sent. Logs and audit rows carry ids and hashes, never a file name or a title.
This module opens no socket, reads no document text and touches no grant
(CLAUDE.md rule 5: this is what may leave the machine, not who may read).
"""

from __future__ import annotations

import contextlib
import functools
import json
import logging
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

from . import claude_approved
from .claude_approved import APPROVED, BLOCKED
from .db import connect

log = logging.getLogger(__name__)

AUTO_BY = "auto: owner decision #1584"
AUDIT_ADDED = "claude_auto_approved"
AUDIT_BLOCKED = "claude_auto_blocked"
SOURCE = "auto"
REVIEW_ROLE = "CONTRACTOR_SUBMITTAL"

_THREAD_LOCK = threading.Lock()


def _on() -> bool:
    return claude_approved.auto_approve_on()


@contextlib.contextmanager
def _locked():
    """One writer of the list at a time, across threads and processes."""
    from .claude_spend import (
        _os_lock,
        _os_unlock,
    )  # the ledger's own cross-platform file lock

    path = claude_approved.list_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _THREAD_LOCK, path.with_name(path.name + ".lock").open("a+b") as fh:
        _os_lock(fh)
        try:
            yield
        finally:
            _os_unlock(fh)


def _write(data: dict) -> None:
    """All of the new list or none of it: a crash mid-write leaves the old one."""
    path = claude_approved.list_path()
    fd, temp = tempfile.mkstemp(
        dir=path.parent, prefix=".claude_approved.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        Path(temp).replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            Path(temp).unlink()
        raise


def _apply(wanted: list[dict]) -> list[dict]:
    """Add what `wanted` asks for, under the lock. Returns what was written.
    `wanted`: {document_id, sha256, label, source, names}. Raises when the list
    or the block file cannot be read: the caller adds nothing."""
    today = datetime.now(UTC).date().isoformat()
    written: list[dict] = []
    with _locked():
        data = claude_approved.read_list_strict()
        rows = data["documents"]
        blocks = claude_approved.blocked_hashes()
        for want in wanted:
            sha = want["sha256"]
            ours = [
                r for r in rows if str(r.get("sha256") or "").strip().lower() == sha
            ]
            base = {
                "sha256": sha,
                "document_id": want["document_id"],
                "label": want["label"],
            }
            if any(claude_approved.is_register_name(n) for n in want["names"]):
                if sha not in blocks:
                    entry = {
                        **base,
                        "status": BLOCKED,
                        "blocked_by": f"{AUTO_BY}: register file name",
                        "blocked_on": today,
                        "source": SOURCE,
                    }
                    rows.append(entry)
                    blocks = blocks | {sha}
                    written.append(entry)
            elif sha not in blocks and not ours:
                entry = {
                    **base,
                    "status": APPROVED,
                    "approved_by": AUTO_BY,
                    "approved_on": today,
                    "source": want["source"],
                }
                rows.append(entry)
                written.append(entry)
        if written:
            _write(data)
    return written


def _audit(written: list[dict]) -> None:
    """One audit row per entry (hash and id, never the label), then the list's own."""
    if written:
        conn = connect()
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with conn:
            conn.executemany(
                "INSERT INTO audit_events (at, actor_user_id, actor_username, action, resource_type,"
                " resource_id, outcome, detail) VALUES (?, NULL, ?, ?, ?, ?, 'ok', ?)",
                [
                    (
                        now,
                        AUTO_BY,
                        AUDIT_BLOCKED if e["status"] == BLOCKED else AUDIT_ADDED,
                        "claude_approved_list",
                        e["sha256"],
                        json.dumps(
                            {"document_id": e["document_id"], "source": e["source"]},
                            sort_keys=True,
                        ),
                    )
                    for e in written
                ],
            )
    claude_approved.sync_audit(*([AUTO_BY] if written else []))


def _document(document_id: str):
    return (
        connect()
        .execute(
            "SELECT d.id, d.filename, d.sha256, c.document_role FROM documents d"
            " LEFT JOIN document_classification c ON c.document_id = d.id WHERE d.id = ?",
            (document_id,),
        )
        .fetchone()
    )


def _want(row, source: str, *extra_names) -> dict | None:
    sha = (row["sha256"] or "").strip().lower()
    if not sha:
        return None
    return {
        "document_id": row["id"],
        "sha256": sha,
        "label": row["filename"],
        "source": source,
        "names": (row["filename"], *extra_names),
    }


def _run(what: str, subject: str, build) -> None:
    """Build the wanted entries, write them, audit them. Never raises."""
    if not _on():
        return
    try:
        wanted = [w for w in build() if w]
        _audit(_apply(wanted))
    except Exception as exc:  # noqa: BLE001 - off the list means nothing is sent
        log.warning(
            "claude auto-approve %s %s: nothing added (%s)",
            what,
            subject,
            type(exc).__name__,
        )


def on_upload(document_id: str, uploaded_name: str | None = None) -> None:
    """An upload arrived or a role was set. `uploaded_name` is what this upload
    called the file: for a duplicate it differs from the stored name."""

    def build():
        row = _document(document_id)
        if row is None:
            return []
        names = (uploaded_name,) if uploaded_name else ()
        if row["document_role"] == REVIEW_ROLE or any(
            claude_approved.is_register_name(n) for n in (row["filename"], *names)
        ):
            return [_want(row, SOURCE, *names)]
        return []

    _run("upload", document_id, build)


def on_review_start(review_run_id: str) -> None:
    """A review started: its subject, and any standard already on the run."""

    def build():
        ids = claude_approved.review_documents(review_run_id)
        if not ids:
            return []
        subject = _document(ids[0])
        out = []
        if subject is not None and subject["document_role"] in (None, REVIEW_ROLE):
            out.append(_want(subject, SOURCE))
        for standard_id in ids[1:]:
            standard = _document(standard_id)
            if standard is not None:
                out.append(_want(standard, f"auto: cited by {ids[0]}"))
        return out

    _run("review", review_run_id, build)


def on_standard_cited(review_run_id: str, standard_document_id: str) -> None:
    """A running review recorded a standard as applying to it."""

    def build():
        run = (
            connect()
            .execute(
                "SELECT submittal_document_id FROM review_runs WHERE id = ?",
                (review_run_id,),
            )
            .fetchone()
        )
        standard = _document(standard_document_id)
        if run is None or standard is None:
            return []
        return [_want(standard, f"auto: cited by {run['submittal_document_id']}")]

    _run("citation", standard_document_id, build)


def lists_cited(record):
    """For the function that records a standard on a review: an `included` row it
    wrote lists that standard. A kept engineer row is not this citation's doing."""

    @functools.wraps(record)
    def recorded(*args, **kwargs):
        row = record(*args, **kwargs)
        if row.get("included") and not row.get("kept_engineer_override"):
            on_standard_cited(row["review_run_id"], row["standard_document_id"])
        return row

    return recorded
