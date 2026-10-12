"""#645 clause to check: the review offers its undecided clause sentences to
the local model and stores what code verifies as drafts (comparison.py, danger
zone). Ids M864-01..03 (CLAUDE.md rule 12)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_645_clause_checks.py"
_P = APP / "comparison.py"
_TAG = ("review", "ai_clause_checks")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M864-01", phase=864, description="the review never offers its undecided sentences",
             path=_P, anchor="    if settings.ai_clause_checks_enabled:\n",
             replacement="    if False:\n",
             target=_T, keyword="review_proposes_drafts", tags=_TAG),
    Mutation(id="M864-02", phase=864, description="the run outcome loses the clause-check counts",
             path=_P, anchor='        split = {**split, "clause_checks": clause_checks}\n',
             replacement="        pass\n",
             target=_T, keyword="review_proposes_drafts", tags=_TAG),
    Mutation(id="M864-03", phase=864, description="every sentence is offered, decided or not",
             path=_P, anchor="            ai_requirements.undecided_statements(requirements, status_of),\n",
             replacement="            requirements,\n",
             target=_T, keyword="review_proposes_drafts", tags=_TAG),
)
