"""PR #909 (#882 technique 2): one small exact question to the local model
per requirement left without a value. `comparison.py` is in the danger zone
(rule 6)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_882_small_exact_questions.py"
_C = APP / "comparison.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M909-01", phase=909,
             description="a verdict resting on a value found by the model's question is stated, not held",
             path=_C,
             anchor='                           "status": NEEDS_ENGINEER_REVIEW if held else status,\n',
             replacement='                           "status": status,\n',
             target=_T, keyword="readers_value_the_rules_could_not_pair",
             tags=("false-compliant", "critical")),
    Mutation(id="M909-02", phase=909,
             description="an answer code refused reads as 'no field answers this' (an absence)",
             path=_C,
             anchor="                        model_reason = ASK_REFUSED\n",
             replacement="                        pass\n",
             target=_T, keyword="refused_and_not_an_absence",
             tags=("honesty",)),
    Mutation(id="M909-03", phase=909,
             description="the per-run cap on questions is not applied",
             path=_C,
             anchor='            if ask_counts["asked"] >= max(settings.match_ask_max_per_run, 0):\n',
             replacement="            if False:\n",
             target=_T, keyword="per_run_cap",
             tags=("budget",)),
)
