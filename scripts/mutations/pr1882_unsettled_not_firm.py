"""PR 1882 (order 14 LPH): a line the AI could not settle is a question, never "Not met". `crs_export.py` (danger zone, rule 6) carries
the stored state of an AI row's finding through the run file's view, so the file's Status is the page's (`crs_normal.settled`). Ids
M1882-01.. (named after the PR, rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1882-01",
        phase=1882,
        description="the run file's view drops the stored state, so an AI row whose finding records a verdict loses its class there",
        path=APP / "crs_export.py",
        anchor="        rows[-1][STORED_STATE] = finding.get(STORED_STATE)\n",
        replacement="",
        target="tests/test_o14_lph_unsettled_not_firm.py",
        keyword="run_files_view_keeps_the_stored_state",
        tags=("honesty", "critical"),
    ),
)
