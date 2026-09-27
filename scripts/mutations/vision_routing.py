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

    # -------------------------------------------------------- 2026-09-27 fix
    # `page_ledger.vision_status`/`vision_reason` used to be overwritten with
    # the SAME placeholder for every page, always, regardless of what
    # `vision_route` actually decided - the routing above was computed and
    # then thrown away before it reached the ledger's own two columns.
    Mutation(
        id="M1123", phase=94,
        description="B7: the real per-page vision decision is never computed for the ledger",
        path=_D,
        anchor="            if geometry_on:\n                why = vision_routing.get(page)\n",
        replacement="            if False:\n                why = vision_routing.get(page)\n",
        target=_T, keyword="real_per_page_vision_decision or reader_off_the_ledger",
        tags=("honesty", "critical")),
    Mutation(
        id="M1124", phase=94,
        description="B7: a routed page whose provider is unavailable is recorded as attempted anyway",
        path=_D,
        anchor="                elif why == VISION_ROUTED and vision_unavailable:\n",
        replacement="                elif False:\n",
        target=_T, keyword="provider_could_not_reach",
        tags=("honesty", "critical")),
    Mutation(
        id="M1125", phase=94,
        description="the page ledger ignores the recorded vision decision and always falls back",
        path=APP / "page_ledger.py",
        anchor='    recorded_vision = {r["page_no"]: r for r in conn.execute(\n',
        replacement="    recorded_vision = {}  # noqa: disabled\n    _unused = (\n",
        target="tests/test_b7_vision_routing.py",
        keyword="real_per_page_vision_decision or provider_could_not_reach",
        tags=("honesty", "critical")),
    Mutation(
        id="M1126", phase=94,
        description="a recorded vision decision is never marked 'extraction', so it never survives a refresh",
        path=APP / "page_ledger.py",
        anchor="                       vision_status = excluded.vision_status,\n"
               "                       vision_reason = excluded.vision_reason,\n"
               "                       vision_recorded_by = 'extraction',\n",
        replacement="                       vision_status = excluded.vision_status,\n"
                    "                       vision_reason = excluded.vision_reason,\n"
                    "                       vision_recorded_by = NULL,\n",
        target="tests/test_b7_vision_routing.py",
        keyword="real_per_page_vision_decision",
        tags=("honesty",)),
)
