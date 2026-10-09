"""#711: the guarded --live mode of the #599 re-extraction. Ids M6001-M6014."""
from __future__ import annotations

from ._base import REPO, Mutation

_T = "tests/test_w6_711_live_reextraction.py"
_S = REPO / "scripts" / "rehearse_requirement_reextraction.py"
_TAG = ("w6", "live-write", "critical")


def _m(i, desc, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=_S, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(6001, "--live runs without a backup path",
       "    if backup is None:\n        raise LiveRunRefused(\"refusing: --live needs --i-have-a-backup <file> (a verified backup)\")\n",
       "", "without_a_backup_is_refused"),
    _m(6002, "a backup path is accepted without --live",
       "    if args.backup is not None and not args.live:\n        raise SystemExit(\"--i-have-a-backup is only for --live\")\n",
       "", "a_backup_without_live"),
    _m(6003, "--live runs on a copy or any live-shaped file",
       "    if not live_guard.is_live_shaped(live) or not (LIVE.exists() and os.path.samefile(live, LIVE)):",
       "    if False:", "on_a_copy or another_checkouts"),
    _m(6004, "only the live shape is checked, not that it is THIS checkout's file",
       "    if not live_guard.is_live_shaped(live) or not (LIVE.exists() and os.path.samefile(live, LIVE)):",
       "    if not live_guard.is_live_shaped(live):", "another_checkouts"),
    _m(6005, "a running backend is not a reason to refuse",
       "    reason = backend_running(live)\n    if reason:", "    reason = None\n    if reason:", "backend_is_running"),
    _m(6006, "a missing backup file is accepted",
       "    if not backup.is_file():\n        raise LiveRunRefused(f\"refusing: no backup file at {backup}\")\n", "",
       "missing_backup_file"),
    _m(6007, "a backup that fails its integrity check is accepted",
       "    if not report.get(\"ok\"):\n        raise LiveRunRefused(f\"refusing: the backup {backup} fails its integrity check\")\n", "",
       "not_ok_is_refused"),
    _m(6008, "a backup of another state is accepted",
       "    if not counts_match:", "    if False:", "different_state"),
    _m(6009, "live_guard.prepare_live_write is skipped",
       "        live_guard.prepare_live_write(live, reason=\"#599 requirement re-extraction (live, #711)\")",
       "        pass", "failed_live_guard"),
    _m(6010, "a failed prepare_live_write does not refuse",
       "        raise LiveRunRefused(f\"refusing: live_guard.prepare_live_write failed: {exc}\") from exc",
       "        pass", "failed_live_guard"),
    _m(6011, "the process stays cleared to write after the run",
       "        live_guard.revoke_all()", "        pass", "no_clearance"),
    _m(6012, "a run that lost rows is still called safe",
       "          and summary[\"after\"][\"requirements_total\"] >= summary[\"before\"][\"requirements_total\"])",
       "          and True)", "lost_rows"),
    _m(6013, "a process holding the file open is not noticed",
       "                if any(str(Path(f.path).resolve()) == target for f in proc.open_files()):",
       "                if False:", "holding_the_file_open"),
    _m(6014, "a check that cannot be made counts as stopped",
       "        return f\"could not check whether the backend is running ({type(exc).__name__})\"",
       "        return None", "cannot_be_made"),
)
