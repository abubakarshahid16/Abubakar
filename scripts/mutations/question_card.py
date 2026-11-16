"""PR #1849 (order 14 lane D, review of the three AI-draft limits): `backend/app/question_card.py`, split out of the
datasheet_checks danger zone (CLAUDE.md rule 6). A card whose limit no engineer confirmed (`limit_draft`) decides
nothing on any switch; a condition value that rules nothing out never says "does not apply". Each entry deletes one
part of that; the named tests must notice. Ids named after the PR (rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_Q = APP / "question_card.py"
_KIT = APP / "kit_core.py"
_DC = APP / "datasheet_checks.py"
_ROUTE = "tests/test_routing_draft_pass.py"
_PUMP = "tests/test_1478_pump_kit_prep.py"
_VESSEL = "tests/test_1480_vessel_kit_prep.py"
_TAG = ("o14", "datasheet", "honesty", "critical")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1849-01", phase=1849,
             description="a QUESTION ONLY card's Pass or Fail stands again (a draft pass that leaves the CRS)",
             path=_Q,
             anchor='    if not question_only(item) or result.get("status") not in _DECIDED:\n        return result\n',
             replacement="    if True:\n        return result\n",
             target=_ROUTE, keyword="question_only", tags=_TAG),
    Mutation(id="M1849-02", phase=1849,
             description="the question-only mark is read from another key: no card is question only",
             path=_Q, anchor='QUESTION_ONLY_KEY = "limit_draft"\n', replacement='QUESTION_ONLY_KEY = "limit_confirmed"\n',
             target=_ROUTE, keyword="question_only", tags=_TAG),
    Mutation(id="M1849-03", phase=1849,
             description="a placeholder condition value ('TBA', '*', 'HOLD', '-') says 'does not apply' again",
             path=_Q, anchor="    if blank_markers.fact_is_placeholder(fact):\n        marker = _said(fact)",
             replacement="    if False:\n        marker = _said(fact)",
             target=_PUMP, keyword="placeholder_fluid", tags=_TAG),
    Mutation(id="M1849-04", phase=1849,
             description="a stated 'water' (no service named) says 'does not apply' to the firewater card again",
             path=_Q, anchor='    if _names(fact, condition.get("may_be_any")):\n', replacement="    if False:\n",
             target=_PUMP, keyword="stated_water", tags=_TAG),
    Mutation(id="M1849-05", phase=1849,
             description="a QUESTION ONLY card with two sides no longer asks for the second (a missing MOP is not said)",
             path=_Q, anchor="    if right and (\n        other is None", replacement="    if False and (\n        other is None",
             target=_VESSEL, keyword="asks_for_the_mop", tags=_TAG),
    Mutation(id="M1849-06", phase=1849,
             description="the checklist does not pass its results through the question-only rule (kit_core.rows)",
             path=_KIT, anchor="    from .question_card import decide_nothing\n",
             replacement="    def decide_nothing(item, result, roles, common):\n        return result\n",
             target=_ROUTE, keyword="question_only", tags=_TAG),
    Mutation(id="M1849-07", phase=1849,
             description="the checklist says 'does not apply' to every condition value naming none of its words again",
             path=_DC, anchor="            return _not_matched(cond_fact, condition, res, held)\n",
             replacement='            return res(NOT_APPLICABLE, "Does not apply.", cond_fact, condition["role"])\n',
             target=_PUMP, keyword="placeholder_fluid or stated_water", tags=_TAG),
)
