"""PR #1128 (order 109): `comparison.run_outcome` may take the run row its caller
already read. `comparison.py` is in the danger zone (rule 6)."""
from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1128-01", phase=1128,
             description="a handed-in run row for another run is trusted, so one run shows another run's outcome",
             path=APP / "comparison.py",
             anchor='    if run is None or run.get("id") != review_run_id:\n',
             replacement='    if run is None:\n',
             target="tests/test_109_fast_run_list.py",
             keyword="handed_in_row_for_another_run", tags=("honesty", "critical")),
)
