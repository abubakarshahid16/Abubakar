"""PR #1631 (#1608): the Run record sheet on the internal CRS. Entries for the one `crs_export.py` guard (danger zone);
`run_record.py` is outside it, so its guards were reverted by hand in the PR."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_1608_run_record.py"
_E = APP / "crs_export.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1631-01",
        phase=1631,
        description="the run record reaches the contractor's copy",
        path=_E,
        anchor='    if internal and meta.get("run_record"):\n',
        replacement='    if meta.get("run_record"):\n',
        target=_T,
        keyword="issue_copy_has_no_run_record",
        tags=("crs", "critical"),
    ),
    Mutation(
        id="M1631-02",
        phase=1631,
        description="the internal copy never draws the run record",
        path=_E,
        anchor='    if internal and meta.get("run_record"):\n',
        replacement='    if False and meta.get("run_record"):\n',
        target=_T,
        keyword="internal_copy_has_the_sheet",
        tags=("crs",),
    ),
)
