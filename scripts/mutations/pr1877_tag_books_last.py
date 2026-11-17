"""PR 1877 (order 14, owner's item LPB): the rule check's division-scope reads take the run's tag-only books LAST
(`comparison._run_comparison` -> `ai_applicability.for_run`, danger zone). Ids M1877-01.. (rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1877-01",
        phase=1877,
        description="the rule check reads the division scopes without the run's tag-only books, so a book kept only by our "
        "equipment tags can take a read of the limit from a cited, governing or scope book",
        path=APP / "comparison.py",
        anchor="    divided = div.for_run(requirements, stored, facts, standard_labels, review_run_id)\n",
        replacement="    divided = div.division_gate_for_run(requirements, stored, facts, standard_labels)\n",
        target="tests/test_lpb_tag_books_last.py",
        keyword="test_a_review_run_gives_its_tag_only_books_to_the_division_reads",
    ),
)
