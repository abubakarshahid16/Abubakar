"""Mutations of `backend/app/live_guard.py`."""

from __future__ import annotations

from ._base import APP, _LIVE_GUARD_TEST, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from B3_PAGE_LEDGER ----------------------------------------------
    #: Master order B3: the page ledger, and a review that never calls an unread
    #: page the contractor's omission. Phase 57.
    Mutation(
        id="M466", phase=57,
        description="PUT THE INCIDENT BACK: db.connect() opens a live database "
                    "for any process, with no backup and no drill (live guard)",
        path=APP / "live_guard.py",
        anchor="    if not is_live_shaped(path) or is_server_process():\n        return\n",
        replacement="    return\n",
        target=_LIVE_GUARD_TEST, keyword="refused_without_a_verified_backup",
        tags=("critical",),
    ),
    Mutation(
        id="M467", phase=57,
        description="clear a live write without comparing the backup with the "
                    "live file, so a backup of the wrong contents is a rollback "
                    "point (live guard)",
        path=APP / "live_guard.py",
        anchor="    if live_counts != report[\"tables\"]:\n",
        replacement="    if False:\n",
        target=_LIVE_GUARD_TEST, keyword="does_not_match_the_live_file",
        tags=("critical",),
    ),
    Mutation(
        id="M468", phase=57,
        description="skip the restore drill: a backup nobody has restored is "
                    "trusted as the rollback point (live guard)",
        path=APP / "live_guard.py",
        anchor="    _restore_drill(backup_path, report[\"tables\"])\n",
        replacement="",
        target=_LIVE_GUARD_TEST, keyword="failed_restore_drill",
        tags=("critical",),
    ),
    Mutation(
        id="M471", phase=57,
        description="a live write with no stated reason is cleared (live guard)",
        path=APP / "live_guard.py",
        anchor="    if not reason or not reason.strip():\n"
               "        raise LiveWriteRefused(\"a live write needs a stated reason\")\n",
        replacement="",
        target=_LIVE_GUARD_TEST, keyword="needs_a_reason",
    ),
)
