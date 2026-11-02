"""#1612: a review reads approved version 2 rules: the four hooks in `comparison.py`, the danger-zone module it touches."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_805_review_reads_v2.py"
_M = APP / "comparison.py"
_TAGS = ("honesty", "critical")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1612-01",
        phase=1612,
        description="the review never reads the approved rules",
        path=_M,
        anchor="    rulebook = run_parts.rulebook(\n        run, stored, facts, prepared_rows, findings, allowed_document_ids\n    )\n",
        replacement="    rulebook = None\n",
        target=_T,
        keyword="one_that_meets_and_one_that_breaks",
        tags=_TAGS,
    ),
    Mutation(
        id="M1612-02",
        phase=1612,
        description="a checklist item that disagrees with a rule keeps its verdict",
        path=_M,
        anchor="    check_results = run_parts.checks(rulebook, check_results)\n",
        replacement="",
        target=_T,
        keyword="review_settles_its_checks",
        tags=_TAGS,
    ),
    Mutation(
        id="M1612-03",
        phase=1612,
        description="a version 2 breach is left out of the recommended code",
        path=_M,
        anchor="    findings.extend(run_parts.written(rulebook))\n",
        replacement="    run_parts.written(rulebook)\n",
        target=_T,
        keyword="v2_breach_counts_in_the_recommended_code",
        tags=_TAGS,
    ),
    Mutation(
        id="M1612-04",
        phase=1612,
        description="the run stops stating the rulebook part",
        path=_M,
        anchor="    split = run_parts.stated(split, cited_scope, checklist_coverage, divided, rulebook)\n",
        replacement="    split = run_parts.stated(split, cited_scope, checklist_coverage, divided, None)\n",
        target=_T,
        keyword="states_version_2_apart",
        tags=_TAGS,
    ),
)
