"""Mutations of `backend/app/page_ledger.py`."""

from __future__ import annotations

from ._base import APP, _B3_TEST, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from B3_PAGE_LEDGER ----------------------------------------------
    #: Master order B3: the page ledger, and a review that never calls an unread
    #: page the contractor's omission. Phase 57.
    Mutation(
        id="M454", phase=57,
        description="a page no retrievable chunk covers reads as an ordinary "
                    "page with no fields, hiding that extraction never saw it (B3)",
        path=APP / "page_ledger.py",
        anchor='        elif index_status != "retrievable":\n',
        replacement="        elif False:\n",
        target=_B3_TEST, keyword="no_retrievable_chunk_covers",
        tags=("honesty",),
    ),
    Mutation(
        id="M455", phase=57,
        description="a refresh overwrites extraction's own per-page record with "
                    "a derivation (B3)",
        path=APP / "page_ledger.py",
        anchor="        elif p in recorded:\n",
        replacement="        elif False:\n",
        target=_B3_TEST, keyword="keeps_extractions_own",
    ),
    Mutation(
        id="M459", phase=57,
        description="a page never reached by extraction is left out of the "
                    "pages not read into fields (B3)",
        path=APP / "page_ledger.py",
        anchor='NOT_READ_INTO_FIELDS = frozenset({"no_facts", "unreadable", "not_reached", "not_run"})',
        replacement='NOT_READ_INTO_FIELDS = frozenset({"no_facts", "unreadable", "not_run"})',
        target=_B3_TEST, keyword="no_retrievable_chunk_covers",
        tags=("honesty",),
    ),
)
