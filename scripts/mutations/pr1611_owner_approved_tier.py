"""#1584 / PR #1611: a rule the owner approved may decide, labelled apart from an engineer's
(rule_trust.tier_for_approved, switch `owner_approved_rules_decide_enabled`). Ids M1611-01.. (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_C = APP / "comparison.py"
_D = APP / "deferred_value.py"
_P = APP / "coverage_pair.py"
_R = APP / "rule_trust.py"
_T = "tests/test_owner_approved_tier.py"
_TAG = ("rule_trust", "owner-approved", "honesty")


def _m(
    n: int, description: str, path, anchor: str, replacement: str, keyword: str
) -> Mutation:
    return Mutation(
        id=f"M1611-{n:02d}",
        phase=1611,
        description=description,
        path=path,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=_TAG,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        1,
        "the switch is ignored: an owner approval gets the tier with it off",
        _R,
        "    if not settings.owner_approved_rules_decide_enabled or not isinstance(\n"
        "        approval, dict\n"
        "    ):\n",
        "    if not isinstance(approval, dict):\n",
        "function_with_the_switch_off",
    ),
    _m(
        2,
        "the label says quote-verified but code never verified the quote",
        _R,
        "    return OWNER_APPROVED if second_check(rule)[0] else UNPROVEN\n",
        "    return OWNER_APPROVED\n",
        "quote_code_cannot_verify",
    ),
    _m(
        3,
        "any approval tier counts as the owner's",
        _R,
        '        approval.get("tier") != OWNER_TIER\n        or not approval.get("by")\n',
        '        not approval.get("by")\n',
        "whole_owner_approval",
    ),
    _m(
        4,
        "an owner rule that also says confirmed_by prints as engineer-approved",
        _R,
        '    if _owner_tier(rule):\n        return tier_for_approved(rule.get("approval"), rule)\n',
        "",
        "never_labelled_engineer_approved",
    ),
    _m(
        5,
        "the CRS words call the owner's rule an engineer's",
        _R,
        'OWNER_APPROVED_WORDS = "AI-built, quote-verified, owner-approved"\n',
        'OWNER_APPROVED_WORDS = "engineer-approved rule"\n',
        "words_reach_the_cell",
    ),
    _m(
        6,
        "an owner rule's verdict stands with no read value",
        _R,
        "        out = _hold_without_a_value(out, fact)\n",
        "        pass\n",
        "no_read_value",
    ),
    _m(
        7,
        "a safety-tier COMPLIANT loses the engineer's tick",
        _R,
        '               show_for_engineer_tick=level == SAFETY and out.get("status") == COMPLIANT)',
        "               show_for_engineer_tick=False)",
        "keeps_it",
    ),
    _m(
        8,
        "the second switch labels nothing: the review never reaches the owner's rules",
        _C,
        "        settings.rule_auto_use_enabled or settings.owner_approved_rules_decide_enabled\n",
        "        settings.rule_auto_use_enabled\n",
        "words_reach_the_cell",
    ),
    _m(
        9,
        "the review drops the fact, so every owner verdict is held",
        _C,
        "        return rule_trust.label_finding(verdict, rule, self.proof(rule), fact=fact)\n",
        "        return rule_trust.label_finding(verdict, rule, self.proof(rule))\n",
        "words_reach_the_cell",
    ),
    _m(
        10,
        "the run record does not say which tier decided",
        _C,
        "        **rule_trust.decided_by_tier(rows),\n",
        "",
        "run_record_states_who_decided",
    ),
    _m(
        11,
        "with the switch on a deferred value is judged as final",
        _D,
        "        or settings.owner_approved_rules_decide_enabled\n",
        "",
        "deferred_value_is_a_query",
    ),
    _m(
        12,
        "a safety Pass waiting for its tick counts as decided by the owner's rule",
        _R,
        '        "owner_approved": len(decided(owner)) - len(ticks),',
        '        "owner_approved": len(decided(owner)),',
        "run_record_states_who_decided",
    ),
    _m(
        13,
        "the pair adds engineer-approved rules into the owner's count",
        _P,
        '            "engineer_approved": len(keys[ENGINEER_CONFIRMED] - keys[OWNER_APPROVED]),',
        '            "engineer_approved": 0,',
        "counted_apart",
    ),
    _m(
        14,
        "the pair's line does not state the tier",
        _P,
        "{_outside_words(pair)}{_tier_words(pair)}",
        "{_outside_words(pair)}",
        "counted_apart",
    ),
    _m(
        15,
        "with both switches off a run labels findings and stores a rule_trust record",
        _C,
        "        settings.rule_auto_use_enabled or settings.owner_approved_rules_decide_enabled\n",
        "        True\n",
        "byte_identical",
    ),
)
