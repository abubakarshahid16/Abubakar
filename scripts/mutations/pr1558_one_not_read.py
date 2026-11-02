"""PR 1558 (#1550): with PAGE_READ_BY_READING_ENABLED, "not read" means no reading
came back; the danger-zone call sites must say a page no field was taken from as
that. backend/tests/test_c1_1550_one_not_read.py must notice."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_c1_1550_one_not_read.py"
_TAG = ("pr1558", "honesty", "crs")


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1558-01",
        phase=1558,
        description="the CRS Review note calls pages no field was taken from 'not yet read'",
        path=APP / "crs_mapping.py",
        anchor="    if unread and (note := page_not_read.field_note(outcome, unread, unread_pages)):\n",
        replacement="    if False and (note := page_not_read.field_note(outcome, unread, unread_pages)):\n",
        target=_T,
        keyword="crs_review_note_says_no_field_taken_when_on",
        tags=_TAG,
    ),
    Mutation(
        id="M1558-02",
        phase=1558,
        description="a finding's rationale calls pages no field was taken from 'not read'",
        path=APP / "comparison.py",
        anchor='            f"{page_not_read.unread_clause(pages, unread)}"  # 1550\n',
        replacement='            f"{page_not_read.unread_clause(None, unread)}"  # 1550\n',
        target=_T,
        keyword="finding_rationale_words_follow_the_switch",
        tags=_TAG,
    ),
    Mutation(
        id="M1558-03",
        phase=1558,
        description="the held approval calls pages no field was taken from 'not read in full'",
        path=APP / "comparison.py",
        anchor="        pages = page_not_read.incomplete_words(page_coverage, reading)\n",
        replacement="        pages = page_not_read.incomplete_words(None, reading)\n",
        target=_T,
        keyword="held_approval_words_follow_the_switch",
        tags=_TAG,
    ),
)
