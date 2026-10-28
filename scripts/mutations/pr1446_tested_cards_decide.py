"""Order 306.1 (PR #1446): a relief-valve card tested under the stricter rule may decide while its engineer
approval is pending (card_trust.py, rule_trust.check_label). Ids M1446-01.. (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_C = APP / "card_trust.py"
_R = APP / "rule_trust.py"
_T = "tests/test_306_tested_cards_decide.py"
_TAG = ("rule-cards", "tested-cards-decide")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1446-01",
        phase=1446,
        description="the switch is ignored: a tested card decides with TESTED_CARDS_DECIDE off",
        path=_R,
        anchor="    if settings.tested_cards_decide_enabled and card_trust.decides(result):",
        replacement="    if card_trust.decides(result):",
        target=_T,
        keyword="with_the_switch_off_nothing_changes",
        tags=_TAG,
    ),
    Mutation(
        id="M1446-02",
        phase=1446,
        description="a weak-source card decides",
        path=_C,
        anchor='    if item.get("weak_source"):',
        replacement="    if False:",
        target=_T,
        keyword="weak_or_waiting_card_stays_held",
        tags=_TAG,
    ),
    Mutation(
        id="M1446-03",
        phase=1446,
        description="a card with generated cases only decides",
        path=_C,
        anchor='    if not any(r["kind"] == "written" for r in ran["runs"]):',
        replacement="    if False:",
        target=_T,
        keyword="generated_cases_only_stays_held",
        tags=_TAG,
    ),
    Mutation(
        id="M1446-04",
        phase=1446,
        description="a card whose source is not a clause number decides",
        path=_C,
        anchor="    if not has_clause_number(item):",
        replacement="    if False:",
        target=_T,
        keyword="source_that_is_not_a_clause_number_stays_held",
        tags=_TAG,
    ),
    Mutation(
        id="M1446-05",
        phase=1446,
        description="a card whose tests failed decides",
        path=_C,
        anchor='    if ran["status"] != "tested":',
        replacement="    if False:",
        target=_T,
        keyword="whose_tests_fail_stays_held",
        tags=_TAG,
    ),
    Mutation(
        id="M1446-06",
        phase=1446,
        description="cards of every equipment type decide",
        path=_C,
        anchor="    if equipment_type not in DECIDING_TYPES:",
        replacement="    if False:",
        target=_T,
        keyword="only_the_relief_valve_cards_decide_for_now",
        tags=_TAG,
    ),
    Mutation(
        id="M1446-07",
        phase=1446,
        description="a local item decides",
        path=_C,
        anchor='        and not result.get("local")',
        replacement="",
        target=_T,
        keyword="local_item_never_decides",
        tags=_TAG,
    ),
    Mutation(
        id="M1446-08",
        phase=1446,
        description="a compliant verdict on a safety field is not shown for the engineer's tick",
        path=_R,
        anchor='            show_for_engineer_tick=is_safety and out.get("status") == COMPLIANT,',
        replacement="            show_for_engineer_tick=False,",
        target=_T,
        keyword="safety_field_goes_to_the_engineers_tick",
        tags=_TAG,
    ),
    Mutation(
        id="M1446-09",
        phase=1446,
        description="a tested card is labelled as a proven family (the CRS then says proven)",
        path=_R,
        anchor="        return TESTED_CARD  # order 306.1",
        replacement="        return AUTO_PROVEN  # order 306.1",
        target=_T,
        keyword="crs_words_say_tested_never_proven",
        tags=_TAG,
    ),
    Mutation(
        id="M1446-10",
        phase=1446,
        description="a sizing calculation card decides without an at-the-limit case",
        path=_C,
        anchor='    if item["rule"]["kind"] == "calc":',
        replacement="    if False:",
        target=_T,
        keyword="sizing_calculation_card_never_decides",
        tags=_TAG,
    ),
)
