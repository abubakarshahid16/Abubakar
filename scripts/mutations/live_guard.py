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
    # ---- #1557: a different-case path or a hard link to the live file -----
    Mutation(
        id="M1561-01",
        phase=1561,
        description="the live-path shape is compared case-sensitively again, so "
        "Backend/Data/RAG_Intelligence.sqlite on macOS opens the live "
        "file without a backup (live guard)",
        path=APP / "live_guard.py",
        anchor='        p.name.casefold() == "rag_intelligence.sqlite"\n'
        '        and p.parent.name.casefold() == "data"\n'
        '        and p.parent.parent.name.casefold() == "backend"\n',
        replacement='        p.name == "rag_intelligence.sqlite"\n'
        '        and p.parent.name == "data"\n'
        '        and p.parent.parent.name == "backend"\n',
        target=_LIVE_GUARD_TEST,
        keyword="different_case_path",
        tags=("critical",),
    ),
    Mutation(
        id="M1561-02",
        phase=1561,
        description="a hard link to the live file under another name is not "
        "live, so db.connect() opens it freely (live guard)",
        path=APP / "live_guard.py",
        anchor="    return _same_file_as_a_live_one(p)\n",
        replacement="    return False\n",
        target=_LIVE_GUARD_TEST,
        keyword="hard_link_to_the_live",
        tags=("critical",),
    ),
    Mutation(
        id="M1561-03",
        phase=1561,
        description="any existing file counts as the live one, so a real "
        "diagnostic copy is refused (live guard)",
        path=APP / "live_guard.py",
        anchor="            if p.samefile(live):\n",
        replacement="            if True:\n",
        target=_LIVE_GUARD_TEST,
        keyword="real_copy",
    ),
    Mutation(
        id="M1561-04",
        phase=1561,
        description="from a git worktree the main checkout's live file is not "
        "known, so a hard link to it opens freely (live guard)",
        path=APP / "live_guard.py",
        anchor="    backends = (backend, shared_backend_dir(backend))\n",
        replacement="    backends = (backend,)\n",
        target=_LIVE_GUARD_TEST,
        keyword="main_checkouts_live_file_is_known",
        tags=("critical",),
    ),
    Mutation(
        id="M1561-05",
        phase=1561,
        description="a known live file that cannot be checked is taken as not "
        "live (fails open) (live guard)",
        path=APP / "live_guard.py",
        anchor="        except OSError:  # cannot tell: refuse rather than guess "
        '"not live"\n'
        "            return True\n",
        replacement="        except OSError:\n            continue\n",
        target=_LIVE_GUARD_TEST,
        keyword="cannot_be_checked",
        tags=("critical",),
    ),
)
