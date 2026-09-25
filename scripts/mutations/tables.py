"""Mutations of `backend/app/tables.py`."""

from __future__ import annotations

from ._base import APP, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from PHASE_3B ----------------------------------------------------
    #: Phase 3B: tables, limits, units, exceptions, conflicts, the queue.
    #: `phase=4` only because `--phase 3` already selects 3A; the ids are the
    #: stable handle and the tags say what each one is about.
    Mutation(
        id="M41", phase=4,
        description="report an unparsed table as parsed, so completeness lies",
        path=APP / "tables.py",
        anchor='                unparsed_reason="no recoverable table geometry on this page",',
        replacement="                unparsed_reason=None,",
        target="tests/test_standards_3b.py",
        keyword="unparsed_table_lowers_completeness",
        tags=("honesty", "table"),
    ),
    Mutation(
        id="M47", phase=4,
        description="accept character fragmentation as a real table",
        path=APP / "tables.py",
        anchor="                if width > MAX_COLUMNS or _is_fragmented(rows):",
        replacement="                if False:",
        target="tests/test_standards_3b.py",
        keyword="character_fragmentation_is_not_accepted",
        tags=("table", "honesty"),
    ),
    # ---- from B175_CASCADE_AND_CONFIDENCE ---------------------------------
    #: #175: cascaded extractor (table column-scoping, reused from the parked
    #: B58 fix, renumbered M356-M358 -> M365-M367 to avoid colliding with
    #: mutation ids already added on this branch since the two diverged), OCR
    #: fallback routing, and confidence-based NEEDS_ENGINEER_REVIEW routing.
    Mutation(
        id="M370", phase=47,
        description="stop folding a continuation header line into the "
                    "composite column name for a STANDARDS table, so a "
                    "merged multi-row header (region/sub-region/code) loses "
                    "everything but its first line",
        path=APP / "tables.py",
        anchor="        if candidate[0]:\n            break",
        replacement="        if True:\n            break",
        target="tests/test_standards_3b.py",
        keyword="merged_multi_row_header_still_names_its_column",
        tags=("table", "honesty"),
    ),
)
