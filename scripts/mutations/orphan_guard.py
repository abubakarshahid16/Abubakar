"""Mutations of `backend/app/orphan_guard.py`."""

from __future__ import annotations

from ._base import APP, _B38_TEST, _B40_TEST, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from B38_ORPHAN_GUARD --------------------------------------------
    #: B38: record, then refuse by default, on all four paths that delete
    #: requirement rows review findings cite. A path's mutation swaps its guard
    #: call for a no-op that accepts the same arguments.
    Mutation(
        id="M326", phase=38,
        description="the guard records but never refuses - orphaning by default again",
        path=APP / "orphan_guard.py",
        anchor="    if not acknowledge:\n        raise OrphaningRefused",
        replacement="    if False:\n        raise OrphaningRefused",
        target=_B38_TEST, keyword="refused or 409",
        tags=("critical",),
    ),
    Mutation(
        id="M331", phase=38,
        description="refuse or proceed WITHOUT a record - the only trace of "
                    "the destroyed evidence is gone",
        path=APP / "orphan_guard.py",
        anchor="    _record(action, document_id, orphaned, actor,",
        replacement="    (lambda *a, **k: None)(action, document_id, orphaned, actor,",
        target=_B38_TEST, keyword="recorded or 409",
        tags=("honesty",),
    ),
    Mutation(
        id="M333", phase=38,
        description="the refusal tells a screen user to set an API flag they "
                    "cannot reach, instead of what to do (Superseded by)",
        path=APP / "orphan_guard.py",
        # Re-anchored by B40: the message is now built per kind (requirements
        # or facts), so the wording moved into `advice`.
        anchor='            f"no longer be traced. {advice}")',
        replacement='            f"no longer be traced. Repeat with acknowledge_orphaned_findings=true.")',
        target=_B38_TEST, keyword="409",
        tags=("ui",),
    ),
    # ---- from B40_FACT_GUARD ----------------------------------------------
    #: B40 -> #179: `extract_facts(replace=True)` used to DELETE unconfirmed facts
    #: that findings cite by `fact_id` (B40 guarded it: count, record, refuse).
    #: Since #179 it SUPERSEDES them instead - the rows stay, marked
    #: `superseded_at`, and every reader of current facts leaves them out.
    #: M334-M336 keep their ids, re-anchored on the supersession; M440-M444 cover
    #: the readers and the record. Phase 56.
    Mutation(
        id="M336", phase=56,
        description="the citation count reads REQUIREMENT citations instead, so "
                    "the record says no finding cites the superseded rows",
        path=APP / "orphan_guard.py",
        anchor="            \"SELECT COUNT(*) FROM review_findings WHERE fact_id IN\"\n"
               "            f\" (SELECT id FROM submittal_facts WHERE {fact_where})\",",
        replacement="            \"SELECT COUNT(*) FROM review_findings WHERE requirement_id IN\"\n"
                    "            f\" (SELECT id FROM submittal_facts WHERE {fact_where})\",",
        target=_B40_TEST, keyword="recorded_without_refusing",
        tags=("honesty",),
    ),
)
