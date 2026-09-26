"""Mutations of the B7 vision routing in `backend/app/datasheets.py`."""

from __future__ import annotations

from ._base import APP, Mutation

_D = APP / "datasheets.py"
_T = "tests/test_b7_vision_routing.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M812", phase=70, description="B7: a page the text readers already read is still sent to the model",
        path=_D,
        anchor="    if facts_on_page or geometry_on_page:\n        return False, VISION_NOT_NEEDED\n",
        replacement="",
        target=_T, keyword="routing_rule or only_the_page",
    ),
    Mutation(
        id="M813", phase=70, description="B7: an image-only page (no text layer) is sent to the model",
        path=_D,
        anchor="    if text_words < VISION_MIN_TEXT_WORDS:\n        return False, VISION_NO_TEXT_LAYER\n",
        replacement="",
        target=_T, keyword="routing_rule or only_the_page",
    ),
    Mutation(
        id="M814", phase=70, description="B7: the per-document vision page budget is ignored",
        path=_D,
        anchor="    if routed_so_far >= budget:\n        return False, VISION_BUDGET\n",
        replacement="",
        target=_T, keyword="budget",
    ),
    Mutation(
        id="M815", phase=70, description="B7: the routing decision is ignored - every page is read by the model",
        path=_D,
        anchor="        if routed:\n            readings[page] = _vision_reading(",
        replacement="        if True:\n            readings[page] = _vision_reading(",
        target=_T, keyword="only_the_page or budget",
    ),
    Mutation(
        id="M816", phase=70, description="B7: the plan pass is not rolled back (it writes, and vision never runs)",
        path=_D,
        anchor="            raise _PlanOnly()\n",
        replacement="            pass\n",
        target=_T, keyword="only_the_page or plan_pass",
    ),
    Mutation(
        id="M817", phase=70, description="B7: the ledger no longer says why a page was not sent to vision",
        path=_D,
        anchor="                              if vision_routing.get(page) != VISION_ROUTED else\n",
        replacement="                              if False else\n",
        target=_T, keyword="ledger_says_why",
    ),
)
