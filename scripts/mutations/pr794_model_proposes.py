"""PR #794 (owner order 2026-10-11, item 4; planner decision 09:11 UTC): the
model matcher only proposes - its choice is used when, and only when, it
passes the match refusal rules."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_model_matching.py"
_C = APP / "comparison.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M794-01", phase=794, description="a model proposal skips the match refusal rules",
             path=_C, anchor='                refused = (match_rules.refusal(requirement, chosen["fact"], sheet=sheet)\n',
             replacement='                refused = (None\n',
             target=_T, keyword="refusal_rule_refuses", tags=("honesty", "critical")),
    Mutation(id="M794-02", phase=794, description="an AI-paired finding does not say who paired it",
             path=_C, anchor="                    f\"{MODEL_PAIR_PREFIX}{match.get('reason') or ''}. \"\n",
             replacement="",
             target=_T, keyword="labelled_medium", tags=("honesty",)),
    Mutation(id="M794-03", phase=794, description="a refused model proposal is not counted by its rule",
             path=_C, anchor='                    rule_refusals[refused] = rule_refusals.get(refused, 0) + 1\n',
             replacement='',
             target=_T, keyword="refusal_rule_refuses", tags=("honesty",)),
    # MATCH_ENGINE=claude (R32): the one Claude lane, gated and metered.
    Mutation(id="M794-04", phase=794, description="the claude matcher is not metered by claude_spend",
             path=_C, anchor=('        call = reader_api.model_call_via(claude_spend.metered(\n'
                              '            transport, MATCH_STEP, unbilled=reader_transport.unbilled), cfg=cfg)\n'),
             replacement='        call = reader_api.model_call_via(transport, cfg=cfg)\n',
             target=_T, keyword="metered_lane or spend_cap", tags=("budget", "egress", "critical")),
    Mutation(id="M794-05", phase=794, description="the claude matcher skips the 'may Claude be used' check",
             path=_C, anchor=('        code, _why = claude_unavailable()\n'
                              '        if code is not None:\n'
                              '            return None, MODEL_UNAVAILABLE\n'
                              '        transport = reader_transport.transport()\n'),
             replacement='        transport = reader_transport.transport()\n',
             target=_T, keyword="refused_unless", tags=("egress", "critical")),
    Mutation(id="M794-06", phase=794, description="the matcher asks Claude although MATCH_ENGINE is ollama",
             path=_C, anchor='    if (str(settings.match_engine or "ollama").strip().lower()) == "claude":\n',
             replacement='    if True:\n',
             target=_T, keyword="labelled_medium or refusal_rule_refuses", tags=("egress", "critical")),
)
