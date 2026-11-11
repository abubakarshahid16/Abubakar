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
  * a rule book the AI reviewer ASKS rules from (`on_agent_standards`, order 12 N3, owner 16.7 point 3): the books of the
    rules it declares to the Claude gate (`agent_review_jobs._ask` declares the paper and these books), whatever method chose
    them. Before this, a book chosen by equipment type or service, not cited, never joined the list and every call of the
    run was refused `not_approved`. Only when the paper itself qualifies (role none or CONTRACTOR_SUBMITTAL);
  * a standard a review CITES, or the standard that GOVERNS its equipment type,
    labelled apart (`LISTED_METHODS`), when the review starts or records it: a
    review chooses its standards after it starts, so "at the start" alone would
    miss all of them. Not a standard applied by equipment type, service, project
    or scope, by the model or by hand: nothing cited it. `record_on_run` puts how
    many of those there were on the review's could-not-check list. Never the
    whole library, and never a standard the review ruled out.

WITHDRAWN. A row this module added for a submittal (`source` exactly `auto`) goes
to `status: withdrawn` when the document's role stops qualifying: the record
stays, and it is audited. An owner's row and a citation's row are not touched.

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
from .claude_approved import APPROVED, BLOCKED, REVIEW_ROLE, WITHDRAWN
from .db import connect

log = logging.getLogger(__name__)

AUTO_BY = "auto: owner decision #1584"
AUDIT_ADDED = "claude_auto_approved"
AUDIT_BLOCKED = "claude_auto_blocked"
AUDIT_WITHDRAWN = "claude_auto_withdrawn"
#: `selection_method` of a review's standard -> how its list entry says so. The
#: methods are `applicability.METHOD_*`, which imports this module.
LISTED_METHODS = {
    "referenced": "auto: cited by",
    "governing_standard": "auto: governing standard for",
}
RUN_KEY = "claude_unlisted_standards"
SOURCE = "auto"

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


def _withdraw(ours: list[dict], today: str) -> list[dict]:
    """Withdraw this module's submittal rows among `ours`, in place."""
    rows = [
        r for r in ours if r.get("status") == APPROVED and r.get("source") == SOURCE
    ]
    for row in rows:
        row.update(status=WITHDRAWN, withdrawn_by=AUTO_BY, withdrawn_on=today)
    return rows


def _apply(wanted: list[dict]) -> list[dict]:
    """Do what `wanted` asks, under the lock. Returns what was written. `wanted`:
    {document_id, sha256, label, source, names, withdraw?}. Raises when the list
    cannot be read: nothing is written. When only the block file cannot be read,
    nothing is approved, but a block or a withdrawal is still written: it only
    narrows what may leave, and a block must not be lost."""
    today = datetime.now(UTC).date().isoformat()
    written: list[dict] = []
    with _locked():
        data = claude_approved.read_list_strict()
        rows = data["documents"]
        try:
            blocks = claude_approved.blocked_hashes()
            readable = True
        except claude_approved.BlockListUnreadable:
            blocks = frozenset(claude_approved.blocked_rows(rows))
            readable = False
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
            elif want.get("withdraw"):
                written += _withdraw(ours, today)
            elif (
                readable
                and sha not in blocks
                and not [r for r in ours if r.get("status") != WITHDRAWN]
            ):
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


_AUDIT_ACTION = {
    BLOCKED: AUDIT_BLOCKED,
    WITHDRAWN: AUDIT_WITHDRAWN,
    APPROVED: AUDIT_ADDED,
}


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
                        _AUDIT_ACTION[e["status"]],
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


def _want(row, source: str, *extra_names, withdraw: bool = False) -> dict | None:
    sha = (row["sha256"] or "").strip().lower()
    if not sha:
        return None
    return {
        "document_id": row["id"],
        "sha256": sha,
        "label": row["filename"],
        "source": source,
        "names": (row["filename"], *extra_names),
        "withdraw": withdraw,
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
        role = row["document_role"]
        if role == REVIEW_ROLE or any(
            claude_approved.is_register_name(n) for n in (row["filename"], *names)
        ):
            return [_want(row, SOURCE, *names)]
        return [_want(row, SOURCE, withdraw=True)] if role else []

    _run("upload", document_id, build)


def _standards_on(review_run_id: str):
    return (
        connect()
        .execute(
            "SELECT standard_document_id, selection_method FROM review_applicable_standards"
            " WHERE review_run_id = ? AND COALESCE(included, 1) = 1",
            (review_run_id,),
        )
        .fetchall()
    )


def _subject_of(review_run_id: str) -> str | None:
    run = (
        connect()
        .execute(
            "SELECT submittal_document_id FROM review_runs WHERE id = ?",
            (review_run_id,),
        )
        .fetchone()
    )
    return run["submittal_document_id"] if run else None


def on_review_start(review_run_id: str) -> None:
    """A review started: its subject, and any listed standard already on the run."""

    def build():
        subject_id = _subject_of(review_run_id)
        if subject_id is None:
            return []
        subject = _document(subject_id)
        out = []
        if subject is not None:
            qualifies = subject["document_role"] in (None, REVIEW_ROLE)
            out.append(_want(subject, SOURCE, withdraw=not qualifies))
        for row in _standards_on(review_run_id):
            label = LISTED_METHODS.get(row["selection_method"])
            standard = _document(row["standard_document_id"])
            if label and standard is not None:
                out.append(_want(standard, f"{label} {subject_id}"))
        return out

    _run("review", review_run_id, build)


def on_agent_standards(subject_document_id: str, standard_document_ids) -> None:
    """The AI reviewer is about to ask rules of these rule books for this paper: they join the list, labelled apart, when the
    paper itself qualifies. The register and a blocked hash never do (`_apply`). Never raises; nothing with the switch off."""

    def build():
        subject = _document(subject_document_id)
        if subject is None or subject["document_role"] not in (None, REVIEW_ROLE):
            return []
        out = []
        for sid in sorted({str(d) for d in standard_document_ids or () if d}):
            standard = _document(sid)
            if standard is not None:
                out.append(
                    _want(
                        standard, f"auto: asked by AI review of {subject_document_id}"
                    )
                )
        return out

    _run("agent review", subject_document_id, build)


def on_standard_cited(
    review_run_id: str, standard_document_id: str, method: str
) -> None:
    """A running review recorded a standard as applying to it by `method`."""

    def build():
        subject_id = _subject_of(review_run_id)
        standard = _document(standard_document_id)
        label = LISTED_METHODS.get(method)
        if subject_id is None or standard is None or label is None:
            return []
        return [_want(standard, f"{label} {subject_id}")]

    _run("citation", standard_document_id, build)


def record_on_run(review_run_id: str) -> None:
    """Put on the run's stored outcome how many of its standards nothing cited and
    so stayed off the list: `absence.unchecked_parts` says so. Counts only. Never
    raises; nothing is written with the switch off or when there are none."""
    if not _on():
        return
    try:
        standards = _standards_on(review_run_id)
        conn = connect()
        marks = ",".join("?" for _ in standards)
        rows = conn.execute(
            f"SELECT id, sha256 FROM documents WHERE id IN ({marks})",
            [s["standard_document_id"] for s in standards],
        ).fetchall()
        sha = {r["id"]: (r["sha256"] or "").strip().lower() for r in rows}
        approved = claude_approved.approved_hashes()
        unlisted = [
            s
            for s in standards
            if s["selection_method"] not in LISTED_METHODS
            and sha.get(s["standard_document_id"]) not in approved
        ]
        if not unlisted:
            return
        with conn:
            row = conn.execute(
                "SELECT outcome_json FROM review_runs WHERE id = ?", (review_run_id,)
            ).fetchone()
            outcome = json.loads(row["outcome_json"] or "{}")
            outcome[RUN_KEY] = {"not_listed": len(unlisted), "of": len(standards)}
            conn.execute(
                "UPDATE review_runs SET outcome_json = ? WHERE id = ?",
                (json.dumps(outcome), review_run_id),
            )
    except Exception as exc:  # noqa: BLE001 - a note must not fail a finished review
        log.warning(
            "claude auto-approve run note %s: %s", review_run_id, type(exc).__name__
        )


def run_lines(outcome: dict) -> list[dict]:
    """The could-not-check line for `record_on_run`'s count. `detail`: the local
    check still read those standards, so the sheet is not called incomplete."""
    unlisted = outcome.get(RUN_KEY) or {}
    if not unlisted.get("not_listed"):
        return []
    line = (
        f"{unlisted['not_listed']} of {unlisted['of']} standard(s) applied to this review "
        "were not cited by it, so they are not on the cloud model's approved list and "
        "the cloud model did not read them."
    )
    note = "Not read by the cloud model"
    return [{"part": RUN_KEY, "line": line, "note": note, "detail": True}]


def notes_after(compare):
    """For the comparison: it rewrites the run's stored outcome, so every comparison
    of a run, a repeat included, puts `record_on_run`'s count back."""

    @functools.wraps(compare)
    def compared(review_run_id, *args, **kwargs):
        result = compare(review_run_id, *args, **kwargs)
        record_on_run(review_run_id)
        return result

    return compared


def lists_cited(record):
    """For the function that records a standard on a review: an `included` row it
    wrote by a listed method lists that standard. A kept engineer row is not this
    citation's doing."""

    @functools.wraps(record)
    def recorded(*args, **kwargs):
        row = record(*args, **kwargs)
        if row.get("included") and not row.get("kept_engineer_override"):
            on_standard_cited(
                row["review_run_id"],
                row["standard_document_id"],
                row["selection_method"],
            )
        return row

    return recorded
