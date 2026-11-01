"""PR 1544 (#525 part 1): the CRS sentence "on N of M pages" must not count a
page intake read only in part. backend/tests/test_w5b_525_intake.py must notice."""

from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1544-01",
        phase=1544,
        description="the CRS pages sentence counts a partly read page as read",
        path=APP / "comparison.py",
        anchor="    read = intake.pages_read_count(page_coverage)",
        replacement='    read = len((page_coverage or {}).get("fact_pages") or [])',
        target="tests/test_w5b_525_intake.py",
        keyword="partly_read",
        tags=("c1_525", "intake"),
    ),
)
