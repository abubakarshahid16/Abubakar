"""Mutations of `backend/app/crs_mapping.py`."""

from __future__ import annotations

from ._base import APP, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from B163_EVIDENCE_TYPE_GATE -------------------------------------
    Mutation(
        id="M378", phase=49,
        description="drop the requires-other-document summary row, so a "
                    "submittal with hundreds of NOT_IN_DOCUMENT_SCOPE "
                    "findings exports a CRS that names none of them "
                    "(issue #165 criterion 4)",
        path=APP / "crs_mapping.py",
        anchor="    if other_doc_count:",
        replacement="    if False:",
        target="tests/test_crs_mapping.py",
        keyword="requires_other_document_gets_one_summary_row_not_individual_ones",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M379", phase=49,
        description="drop the missing-information summary row, so a "
                    "submittal with hundreds of MISSING_INFORMATION findings "
                    "exports a CRS that reads as though none exist",
        path=APP / "crs_mapping.py",
        anchor="    if missing_info_count:",
        replacement="    if False:",
        target="tests/test_crs_mapping.py",
        keyword="missing_information_never_enters_individually",
        tags=("honesty", "critical"),
    ),
    # ---- from B3_PAGE_LEDGER ----------------------------------------------
    #: Master order B3: the page ledger, and a review that never calls an unread
    #: page the contractor's omission. Phase 57.
    Mutation(
        id="M474", phase=57,
        description="every unread-page finding enters the CRS as its own "
                    "contractor comment again (B3)",
        path=APP / "crs_mapping.py",
        anchor='                if f.get("compliance_status") == "NEEDS_ENGINEER_REVIEW"\n'
               "                and not _unread(f)]\n",
        replacement='                if f.get("compliance_status") == "NEEDS_ENGINEER_REVIEW"]\n',
        target="tests/test_b3_crs_unread_pages.py",
        keyword="one_plain_summary_row",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M475", phase=57,
        description="the CRS says nothing about the requirements it could not "
                    "check, reading as if none existed (B3)",
        path=APP / "crs_mapping.py",
        anchor="    if unread_count:\n",
        replacement="    if False:\n",
        target="tests/test_b3_crs_unread_pages.py",
        keyword="one_plain_summary_row",
        tags=("honesty",),
    ),
)
