"""#1495: a review that read nothing ends failed 'nothing read', never completed.

Own module so `review_jobs.run` and `submittal_review` do not grow.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import job_queue, page_ledger, stored_paths
from .config import settings
from .db import connect


class NothingRead(RuntimeError):
    """The review read nothing: no value, no page text, no page reading."""


class StoredFileAbsent(NothingRead):
    """The stored file is confirmed absent: a retry cannot help, fail at once."""


def _pages(document_id: str) -> str:
    row = (
        connect()
        .execute("SELECT page_count FROM documents WHERE id = ?", (document_id,))
        .fetchone()
    )
    pages = (row["page_count"] if row else None) or 0
    return f"{pages} page{'' if pages == 1 else 's'}"


def reason(document_id: str) -> str | None:
    """The plain reason when a submittal was read into NOTHING, else None.

    Nothing read = no CURRENT fact AND no page came back with text or a reading
    (no non-blank chunk, no ledger page with a reading). Pages read but holding
    no datasheet field (procedure prose) are not "nothing read": they are
    reviewed by their own path. General: it looks at what came back, never at a
    layout.
    """
    conn = connect()
    if conn.execute(
        "SELECT 1 FROM submittal_facts WHERE submittal_document_id = ?"
        " AND superseded_at IS NULL LIMIT 1",
        (document_id,),
    ).fetchone():
        return None
    path = stored_paths.of_document(document_id)
    if not path or not Path(path).is_file():
        raise StoredFileAbsent(
            "nothing read: the stored file could not be found or opened "
            f"({_pages(document_id)})"
        )
    if conn.execute(
        "SELECT 1 FROM chunks WHERE document_id = ? AND TRIM(COALESCE(text, '')) != ''"
        " LIMIT 1",
        (document_id,),
    ).fetchone():
        return None
    if any(page_ledger.page_has_reading(r) for r in page_ledger.rows(document_id)):
        return None
    return (
        "nothing read: the document could not be read "
        f"({_pages(document_id)}, 0 values)"
    )


def read_phase(submittal: str, scope: frozenset[str], run_id: str) -> None:
    """The review's read step: extract facts, then (switch on) refuse to go on
    when nothing was read."""
    from . import submittal_review

    submittal_review.ensure_facts_extracted(submittal, scope, review_run_id=run_id)
    if settings.nothing_read_fails_enabled:
        why = reason(submittal)
        if why:
            raise NothingRead(why)


def fail_run(job_id: str, run_id: str, exc: NothingRead) -> str:
    """End the job and its run failed at once (a retry reads the same nothing);
    no CRS row is numbered."""
    now = job_queue.now_iso()
    conn = connect()
    with conn:
        conn.execute(
            "UPDATE jobs SET state = ?, next_attempt_at = NULL, error_code = ?,"
            " error_message = ?, updated_at = ? WHERE id = ?",
            (job_queue.POISONED, "NothingRead", str(exc), now, job_id),
        )
        job_queue.audit(conn, "job.poisoned", job_id, detail="error=NothingRead")
        conn.execute(
            "UPDATE review_runs SET status = 'failed', outcome_json = ?, updated_at = ?"
            " WHERE id = ?",
            (json.dumps({"error": str(exc)}), now, run_id),
        )
    return job_queue.POISONED
