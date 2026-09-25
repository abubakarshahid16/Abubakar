"""Mutations of `backend/app/review.py`."""

from __future__ import annotations

from ._base import APP, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from PHASE_1 -----------------------------------------------------
    Mutation(
        id="M7", phase=1,
        description="remove the review_findings compliance column migration",
        path=APP / "review.py",
        anchor='            "review_run_id": "TEXT",\n            "compliance_status": "TEXT",',
        replacement='            # "review_run_id": "TEXT",\n            # "compliance_status": "TEXT",',
        target="tests/test_submittal_review_foundation.py",
        keyword="existing_review_findings or guided_review",
        tags=("migration",),
    ),
    Mutation(
        id="M10", phase=1,
        description="give a finding's standard_document_id a CASCADE foreign key",
        path=APP / "review.py",
        anchor="                standard_document_id TEXT,",
        replacement="                standard_document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,",
        target="tests/test_submittal_review_foundation.py",
        keyword="deleting_a_standard_does_not_erase",
        tags=("foreign-key",),
    ),
    # ---- from REACHABLE ---------------------------------------------------
    #: Findings a reviewer can reach, keep and correct.
    Mutation(
        id="M128", phase=8,
        description="drop the review_run_id filter, so one run's findings can "
                    "only be found by fetching every finding ever written",
        path=APP / "review.py",
        anchor='        clauses.append("review_run_id = ?")',
        replacement='        clauses.append("1 = 1 OR ? IS NULL")',
        target="tests/test_findings_reachable.py",
        keyword="run_filter_returns_only_that_run",
    ),
    Mutation(
        id="M129", phase=8,
        description="LET A RUN ID REACH PAST THE GRANT TABLES, returning "
                    "findings for a submittal the caller may not read",
        path=APP / "review.py",
        anchor="    if allowed_document_ids is not None:\n        if not allowed_document_ids:\n            return []",
        replacement="    if allowed_document_ids is not None:\n        if not allowed_document_ids:\n            allowed_document_ids = None",
        target="tests/test_findings_reachable.py",
        keyword="cannot_reach_a_document_the_caller_may_not_read",
        tags=("permission", "critical"),
    ),
)
