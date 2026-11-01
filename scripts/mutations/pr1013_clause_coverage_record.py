"""#884 / PR #1013 (PF4 step 1): the run stores its clause coverage from the
ledger's own decisions, and the trace's COVERAGE step reads it. Each entry
removes one of those; tests/test_884_clause_coverage.py and
tests/test_791_trace_store.py must notice. Ids named after the PR (rule 12)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_884_clause_coverage.py"
_TAG = ("pf4", "honesty")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1013-01", phase=1013,
             description="the run stores no clause coverage (the record is None)",
             path=APP / "comparison.py",
             anchor="    clause_cov = clause_coverage.summarise(decisions)\n",
             replacement="    clause_cov = None\n",
             target=_T, keyword="stores_the_coverage", tags=_TAG),
    Mutation(id="M1013-02", phase=1013,
             description="the stored coverage counts a wrong denominator (does-not-apply inside it)",
             path=APP / "clause_coverage.py",
             anchor="    applicable = sum(counts[s] for s in STATES)\n    adds_up = applicable + counts[DOES_NOT_APPLY] + queries == len(decisions)\n",
             replacement="    applicable = len(decisions)\n    adds_up = True\n",
             target=_T, keyword="summarise_is_the_routes_arithmetic or stores_the_coverage", tags=_TAG),
    Mutation(id="M1013-03", phase=1013,
             description="the trace's COVERAGE step ignores the stored clause coverage",
             path=APP / "review_trace.py",
             anchor='    clause = outcome.get("clause_coverage") or {}\n',
             replacement='    clause = {}\n',
             target="tests/test_791_trace_store.py", keyword="coverage_step_carries", tags=_TAG),
)
