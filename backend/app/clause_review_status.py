"""The words of the clause review's outcome (#1477): counts with their denominators, split
from `clause_review.py` so that file does not grow. Pure: it fills a status dict, stores nothing."""

from __future__ import annotations


def fill(status: dict, elapsed: float) -> None:
    """Add the counts and the plain sentence to the run's status (never document text).
    Whole-document mode adds a note: "N of M requirements reviewed; K not reviewed (time
    budget of T s reached); first not reviewed: ..." - not reviewed is never a pass."""
    status["elapsed_seconds"] = round(elapsed, 1)
    status["minutes_per_page"] = round(elapsed / 60 / max(1, status["pages"]), 3)
    status["not_reviewed_count"] = len(status["not_reviewed"])
    read = sum(
        status[k] for k in ("verified", "no_evidence", "unverified", "unreadable")
    )
    left = len(status["not_reviewed"]) + len(status["failed"])
    why = f" ({status['stopped']})" if status["stopped"] else ""
    named = [*status["not_reviewed"], *status["failed"]]
    listed = (
        f": {', '.join(named[:10])}{' ...' if len(named) > 10 else ''}" if named else ""
    )
    kind = f"document kind '{status['kind']}'" + (
        ""
        if status["kind_state"] == "confirmed"
        else f" ({status['kind_state']}, not confirmed)"
    )
    status["not_read_count"] = left
    if status.get("whole_document"):
        # Rule 4: every count with its denominator; not reviewed is never a pass.
        stop = (
            f" ({status['stopped']})"
            if status["stopped"] and status["not_reviewed"]
            else ""
        )
        first = (
            f"; first not reviewed: {', '.join(status['not_reviewed'][:10])}"
            if status["not_reviewed"]
            else ""
        )
        fail = (
            f"; {len(status['failed'])} failed (no answer): {', '.join(status['failed'][:10])}"
            if status["failed"]
            else ""
        )
        status["whole_document_note"] = (
            f"{read} of {status['requirements']} requirements reviewed; "
            f"{len(status['not_reviewed'])} not reviewed{stop}{first}{fail}"
        )
    status["plain"] = (
        f"AI clause review (suggestions only, engineer to confirm): {read} of {status['requirements']} "
        f"requirement(s) read - {status['verified']} with a verified quote, {status['no_evidence']} "
        f"with no passage found, {status['unverified']} with a quote that could not be verified, "
        f"{status['unreadable']} unreadable; {left} not reviewed{why}{listed}; {kind}."
    )
    if status.get("whole_document_note"):
        status["plain"] += f" {status['whole_document_note']}."
