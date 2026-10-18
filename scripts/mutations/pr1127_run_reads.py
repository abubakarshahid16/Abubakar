"""PR #1127 (order 109): `comparison.run_outcome` is the scoped read plus the
one parser in `run_record`. `comparison.py` is in the danger zone (rule 6)."""

from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1127-01",
        phase=1127,
        description="run_outcome stops returning the run's stored outcome",
        path=APP / "comparison.py",
        anchor="    return None if run is None else run_record.outcome_of(run)\n",
        replacement="    return None if run is None else {}\n",
        target="tests/test_109_run_reads.py",
        keyword="run_outcome_is_the_scoped_read",
        tags=("honesty",),
    ),
)
