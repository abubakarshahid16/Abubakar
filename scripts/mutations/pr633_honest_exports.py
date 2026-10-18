"""#633 items 6 and 7 (PR 633-honest-exports): a CRS for a run that did not
complete says so on ROW 1 of the sheet, with the run's status, its reason,
the unread pages and the missing standards; a completed run's sheet is
unchanged. The entries drop the note from the view and from the workbook, and
tests/test_633_honest_exports.py must notice. `crs_export.py` is rule-6
danger zone; ids are named after the PR (CLAUDE.md rule 12)."""
from __future__ import annotations

from ._base import APP, Mutation

_TEST = "tests/test_633_honest_exports.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M633-01", phase=633,
             description="the view drops the run status note: an incomplete run's sheet "
                         "and preview read like a complete review",
             path=APP / "crs_export.py",
             anchor='        "run_status_note": str(meta.get("run_status_note") or ""),\n',
             replacement='        "run_status_note": "",\n',
             target=_TEST, keyword="incomplete_run_carries_the_marker",
             tags=("crs", "honesty", "633")),
    Mutation(id="M633-02", phase=633,
             description="the workbook prints the title alone on row 1, the note never "
                         "reaches the file",
             path=APP / "crs_export.py",
             anchor='    put(1, 1, "\\n".join(p for p in (view["run_status_note"], view["title"]) if p),',
             replacement='    put(1, 1, view["title"],',
             target=_TEST, keyword="incomplete_run_carries_the_marker",
             tags=("crs", "honesty", "633")),
)
