"""#884 PF4 step 2 / PR #1033: the CRS review notes carry the run's clause
coverage line (crs_mapping is danger zone, CLAUDE.md rule 6). Each entry
removes one part; tests/test_884_coverage_shown.py must notice. Ids named
after the PR (rule 12)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_884_coverage_shown.py"
_TAG = ("pf4", "honesty")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1033-01", phase=1033,
             description="the CRS review notes drop the clause coverage line",
             path=APP / "clause_coverage.py",
             anchor="    notes.extend(review_notes(outcome))\n    return notes\n",
             replacement="    return notes\n",
             target=_T, keyword="crs_review_notes_carry", tags=_TAG),
    Mutation(id="M1033-02", phase=1033,
             description="an outcome with no coverage record says nothing instead of 'not recorded'",
             path=APP / "crs_mapping.py",
             anchor="    if outcome is not None:\n        from .clause_coverage import outcome_notes\n",
             replacement="    if outcome and outcome.get('clause_coverage'):\n        from .clause_coverage import outcome_notes\n",
             target=_T, keyword="crs_review_notes_carry", tags=_TAG),
)
