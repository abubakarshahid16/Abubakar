"""Mutations of the engineer-approved rule tier (item 14, PR 1661)."""

from __future__ import annotations

from ._base import REPO, Mutation

_RT = REPO / "backend" / "app" / "rule_trust.py"
_T = "tests/test_805_review_reads_v2.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1661-01",
        phase=1661,
        description="the engineer switch is ignored: an engineer approval decides with it off",
        path=_RT,
        anchor='        approval.get("tier") == ENGINEER_TIER\n        and settings.engineer_approved_rules_decide_enabled\n',
        replacement='        approval.get("tier") == ENGINEER_TIER\n',
        target=_T,
        keyword="engineer_switch_off_an_engineer_approval_still_does_not_decide",
        tags=("crs", "trust"),
    ),
    Mutation(
        id="M1661-02",
        phase=1661,
        description="an engineer-approved rule is labelled as the owner's",
        path=_RT,
        anchor="        return ENGINEER_APPROVED if second_check(rule)[0] else UNPROVEN\n",
        replacement="        return OWNER_APPROVED if second_check(rule)[0] else UNPROVEN\n",
        target="tests/test_1661_engineer_tier.py",
        keyword="earns_the_engineer_label_never_the_owners",
        tags=("crs", "trust"),
    ),
)
