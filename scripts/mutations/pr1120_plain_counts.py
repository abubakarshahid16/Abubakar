"""PR #1120 (order 112): the completeness reason writes its counts with
thousands separators. `comparison.py` is in the danger zone (rule 6)."""

from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1120-01",
        phase=1120,
        description="the completeness reason prints 6577 beside a headline's 6,584",
        path=APP / "comparison.py",
        anchor='            head = (f"{answered:,} of the {required:,} datasheet values the applicable "\n',
        replacement='            head = (f"{answered} of the {required} datasheet values the applicable "\n',
        target="tests/test_1120_plain_counts.py",
        keyword="thousands_separators",
        tags=("honesty",),
    ),
)
