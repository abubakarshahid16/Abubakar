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
        # Re-anchored 2026-09-26 (order 2f): a Review note per standard now.
        anchor="    for name in sorted(by_standard):\n",
        replacement="    for name in ():\n",
        target="tests/test_crs_mapping.py",
        keyword="review_note_by_standard",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M379", phase=49,
        description="drop the requirements no field answered from the CRS, so "
                    "a submittal with MISSING_INFORMATION findings exports a "
                    "CRS that reads as though none exist",
        path=APP / "crs_mapping.py",
        # Re-anchored 2026-09-27 (CRS quick wins): the summary row became one
        # row per requirement no field answered (the `not_found` bucket).
        anchor="                         (ROW_KIND_MISSING_INFORMATION, not_found),\n",
        replacement="",
        target="tests/test_crs_mapping.py",
        keyword="breaches_come_first_then_missing_values",
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
        # Re-anchored 2026-09-26: the line also excludes PAGE_READER_ONLY (M1023).
        anchor="                and not _unread(f) and not _page_reader_only(f)]\n",
        replacement="                and not _page_reader_only(f)]\n",
        target="tests/test_b3_crs_unread_pages.py",
        keyword="one_plain_summary_row",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M475", phase=57,
        description="the CRS says nothing about the requirements it could not "
                    "check, reading as if none existed (B3)",
        path=APP / "crs_mapping.py",
        # Re-anchored 2026-09-26 (order 2f): a Review note now.
        anchor="    if unread:\n",
        replacement="    if False:\n",
        target="tests/test_b3_crs_unread_pages.py",
        keyword="one_review_note_not_74",
        tags=("honesty",),
    ),
    # ---- CRS quick wins (2026-09-27, audit crs.md defects 2, 8) -----------
    Mutation(
        id="M1300", phase=96,
        description="every blank/missing value in a bucket collapses back "
                    "into ONE row regardless of which field it names - the "
                    "old un-itemised summary row, reintroduced",
        path=APP / "crs_mapping.py",
        anchor="        for group in _grouped(bucket):",
        replacement=(
            "        for group in ([bucket] if bucket and kind == "
            "ROW_KIND_MISSING_INFORMATION else _grouped(bucket)):"),
        target="tests/test_crs_mapping.py",
        keyword="every_missing_value_is_its_own_row_one_per_field",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1301", phase=96,
        description="Page/Section prints the standard's file name instead of "
                    "the datasheet's own field",
        path=APP / "crs_mapping.py",
        anchor="    field = _field_label(f)\n    tags = _items(group)\n    where = (f\"p.{_page_list(pages)}\" if pages else \"\")",
        replacement="    field = f.get(\"standard_name\")\n    tags = _items(group)\n    where = (f\"p.{_page_list(pages)}\" if pages else \"\")",
        target="tests/test_crs_mapping.py",
        keyword="page_section_is_the_datasheet_and_the_standard_has_its_own_column",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1302", phase=96,
        description="the comment quotes the machine's own rationale instead "
                    "of the engineer-voice requirement sentence",
        path=APP / "crs_mapping.py",
        anchor='    lead = f"{ref}: {_requirement_words(f)}"',
        replacement='    lead = f"{ref}: {f.get(\'ai_rationale\')}"',
        target="tests/test_crs_mapping.py",
        keyword="the_comment_is_an_engineers_with_a_contractor_action",
        tags=("honesty", "critical"),
    ),
)
