"""Order 302.4 c (PR #1456): the engineer's approval joins the review's card gate (card_trust.py,
checklist_scope.py, crs_mapping.py, rule_card_versions.in_force). Ids M1456-01.. (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_C = APP / "card_trust.py"
_S = APP / "checklist_scope.py"
_M = APP / "crs_mapping.py"
_T = "tests/test_302_card_gate.py"
_TAG = ("rule-cards", "approval")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1456-01",
        phase=1456,
        description="a card nobody approved is labelled as approved",
        path=_C,
        anchor='    if stand["state"] == "approved":',
        replacement='    if stand["state"] in ("approved", "tested"):',
        target=_T,
        keyword="tested_card_nobody_decided_is_tested_not_approved",
        tags=_TAG,
    ),
    Mutation(
        id="M1456-02",
        phase=1456,
        description="a rejected or draft card is not held",
        path=_C,
        anchor="\n    return rule_trust.UNPROVEN\n",
        replacement="\n    return rule_trust.TESTED_CARD\n",
        target=_T,
        keyword="rejected_card_is_held",
        tags=_TAG,
    ),
    Mutation(
        id="M1456-03",
        phase=1456,
        description="the review evaluates the committed card, not the engineer's edit",
        path=_S,
        anchor="        rules = rule_card_versions.in_force(connect(), rules)",
        replacement="        pass",
        target=_T,
        keyword="edit_takes_the_approval_away",
        tags=_TAG,
    ),
    Mutation(
        id="M1456-04",
        phase=1456,
        description="the CRS does not name the engineer who approved",
        path=_M,
        anchor='    if label == ENGINEER_CONFIRMED and finding.get("trust_by"):',
        replacement="    if False:",
        target=_T,
        keyword="crs_says_approved_by_name",
        tags=_TAG,
    ),
    Mutation(
        id="M1456-05",
        phase=1456,
        description="an approval counts with the switch off",
        path=_C,
        anchor='    if not (\n        settings.rule_cards_approval_enabled and result.get("checklist")\n    ) or result.get("local"):',
        replacement='    if not result.get("checklist") or result.get("local"):',
        target=_T,
        keyword="with_the_approval_switch_off",
        tags=_TAG,
    ),
    Mutation(
        id="M1456-06",
        phase=1456,
        description="a sizing calculation card can be approved",
        path=APP / "rule_card_versions.py",
        anchor='        if why := card_trust.structural_reason(card["equipment_type"], card["item"]):',
        replacement="        if False:",
        target=_T,
        keyword="sizing_calculation_card_cannot_be_approved",
        tags=_TAG,
    ),
    Mutation(
        id="M1456-07",
        phase=1456,
        description="an approval on a card the review cannot decide gives a verdict",
        path=_C,
        anchor='        if stand["structural"]:',
        replacement="        if False:",
        target=_T,
        keyword="stored_approval_on_a_card_the_review_cannot_decide",
        tags=_TAG,
    ),
)
