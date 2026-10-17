"""#947 / PR #1010: the rule_trust held count covers every finding of the
run, the datasheet checks included. The entry puts the summary back over the
rule loop's rows alone, which is what s2's real-group run caught (51 reported,
1,555 held); tests/test_947_rule_trust_wiring.py must notice. Ids named after
the PR (CLAUDE.md rule 12)."""
from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1010-01", phase=1010,
             description="the held count is over the rule loop's rows only, not the datasheet checks",
             path=APP / "comparison.py",
             anchor="    rule_trust_summary = _rule_trust_summary(trust, review_run_id, facts, requirements,\n"
                    "                                             findings)\n",
             replacement="    rule_trust_summary = _rule_trust_summary(trust, review_run_id, facts, requirements,\n"
                         "                                             prepared_rows)\n",
             target="tests/test_947_rule_trust_wiring.py", keyword="unproven_rule_never_decides",
             tags=("rule_trust", "honesty")),
    Mutation(id="M1010-02", phase=1010,
             description="the summary states no boundary (findings_counted dropped)",
             path=APP / "comparison.py",
             anchor='        "findings_counted": len(rows),\n',
             replacement='        "findings_counted": None,\n',
             target="tests/test_947_rule_trust_wiring.py", keyword="unproven_rule_never_decides",
             tags=("rule_trust", "honesty")),
)
