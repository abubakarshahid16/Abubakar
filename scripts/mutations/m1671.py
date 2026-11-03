"""#1671: the requirement progress wrapper only counts; it never changes what the comparison sees."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_review_progress_overall.py"
_TAGS = ("honesty", "critical")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1671-01",
        phase=1671,
        description="the progress wrapper drops the last requirement, so it is never compared",
        path=APP / "job_progress.py",
        anchor="        yield item\n",
        replacement="        if number < total:\n            yield item\n",
        target=_T,
        keyword="counting_yields_every_item_unchanged",
        tags=_TAGS,
    ),
    Mutation(
        id="M1671-02",
        phase=1671,
        description="the comparison loop no longer goes through the progress wrapper",
        path=APP / "comparison.py",
        anchor="    for requirement in job_progress.counting(requirements):\n",
        replacement="    for requirement in requirements:\n",
        target=_T,
        keyword="comparison_loop_reports_each_requirement",
        tags=_TAGS,
    ),
)
