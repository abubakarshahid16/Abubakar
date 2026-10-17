"""#845: the AI matcher's counts are stored on the run with what each is out
of, so the run card can show them (comparison.py, danger zone). Ids
M851-01..06 (CLAUDE.md rule 12)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_845_ai_numbers.py"
_P = APP / "comparison.py"
_TAG = ("review", "ai_numbers")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M851-01", phase=851, description="a model proposal is not counted as proposed",
             path=_P, anchor='                    matcher_counts["proposed"] += 1\n',
             replacement='                    pass\n',
             target=_T, keyword="used_pairing_is_stored or rule_refused", tags=_TAG),
    Mutation(id="M851-02", phase=851, description="a proposal a rule refused is not counted as refused",
             path=_P, anchor='                    matcher_counts["refused_by_rule"] += 1\n',
             replacement='',
             target=_T, keyword="rule_refused", tags=_TAG),
    Mutation(id="M851-03", phase=851, description="a requirement the budget stopped is counted as asked",
             path=_P, anchor='        "asked": counts["sent"] - counts["no_candidates"] - budget,\n',
             replacement='        "asked": counts["sent"] - counts["no_candidates"],\n',
             target=_T, keyword="spent_budget", tags=_TAG),
    Mutation(id="M851-04", phase=851, description="a requirement with no candidate field is counted as asked",
             path=_P, anchor='                    matcher_counts["no_candidates"] += 1\n',
             replacement='                    pass\n',
             target=_T, keyword="no_candidate_field", tags=_TAG),
    Mutation(id="M851-05", phase=851, description="the run does not store the matcher's counts",
             # Re-anchored 2026-10-17 (#947 wiring, PR #985): the rule_trust key follows it.
             # PF4 #884 step 1 (PR #1013) adds clause_coverage after rule_trust; anchor unchanged.
             path=_P, anchor='                "ai_matcher": ai_matcher,\n                # rule_trust',
             replacement='                # rule_trust',
             target=_T, keyword="stored_on_the_run or rule_refused or declined", tags=_TAG),
    Mutation(id="M851-06", phase=851, description="a switched-off matcher reports itself on",
             path=_P, anchor='    if not settings.match_enabled:\n        return {"enabled": False}\n    engine = ',
             replacement='    if False:\n        return {"enabled": False}\n    engine = ',
             target=_T, keyword="switched_off", tags=_TAG),
)
