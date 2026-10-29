"""Order 302.4 (PR #1445): the engineer's step on a rule card - approve, edit, reject (rule_card_versions.py and
the runner's boundary rule). Ids M1445-01.. (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_V = APP / "rule_card_versions.py"
_C = APP / "rule_cards.py"
_T = "tests/test_302_rule_card_versions.py"
_TAG = ("rule-cards", "approval")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1445-01",
        phase=1445,
        description="a card that is not tested can be approved",
        path=_V,
        anchor='        if ran["state"] != TESTED:\n',
        replacement="        if False:\n",
        target=_T,
        keyword="needs_a_standard_we_do_not_hold_cannot_be_approved",
        tags=_TAG,
    ),
    Mutation(
        id="M1445-02",
        phase=1445,
        description="a stale screen decides anyway",
        path=_V,
        anchor='    if card["version"] != version or card["content_hash"] != seen_hash:\n',
        replacement="    if False:\n",
        target=_T,
        keyword="a_stale_screen_writes_nothing",
        tags=_TAG,
    ),
    Mutation(
        id="M1445-03",
        phase=1445,
        description="an approval survives a change of the committed card",
        path=_V,
        anchor='    if moved and last["version"] == 1:\n',
        replacement="    if False:\n",
        target=_T,
        keyword="approval_does_not_survive_a_change_of_the_committed_card",
        tags=_TAG,
    ),
    Mutation(
        id="M1445-04",
        phase=1445,
        description="a decision is written with nobody signed in",
        path=_V,
        anchor='    if not actor:\n        raise CardError("nobody is signed in; nothing is written")\n    rules = rules or dc.load_rules()\n    card = current(conn, equipment_type, card_id, rules)\n    _check_stale(card, version, seen_hash)\n    if card["decision"]:',
        replacement='    rules = rules or dc.load_rules()\n    card = current(conn, equipment_type, card_id, rules)\n    _check_stale(card, version, seen_hash)\n    if card["decision"]:',
        target=_T,
        keyword="nobody_signed_in_writes_nothing",
        tags=_TAG,
    ),
    Mutation(
        id="M1445-05",
        phase=1445,
        description="any text counts as a clause number",
        path=_V,
        anchor="    return bool(\n        _CLAUSE.match(",
        replacement="    return True or bool(\n        _CLAUSE.match(",
        target=_T,
        keyword="approve_needs_a_clause_number",
        tags=_TAG,
    ),
    Mutation(
        id="M1445-06",
        phase=1445,
        description="a limit card needs no at-the-limit case",
        path=_C,
        anchor='BOUNDARY_KINDS = ("compare", "constant", "percent_of", "above_by")',
        replacement="BOUNDARY_KINDS = ()",
        target="tests/test_296_rule_cards.py",
        keyword="a_limit_card_needs_an_at_the_limit_case",
        tags=_TAG,
    ),
    Mutation(
        id="M1445-07",
        phase=1445,
        description="a moved committed card cannot be approved again",
        path=_V,
        anchor='    if stored and stored["base_hash"] != base:',
        replacement="    if False:",
        target=_T,
        keyword="approved_again_after_the_committed_card_moved",
        tags=_TAG,
    ),
    Mutation(
        id="M1445-08",
        phase=1445,
        description="a number edit accepts nan and infinity",
        path=_V,
        anchor="        or not math.isfinite(value)",
        replacement="        or False",
        target=_T,
        keyword="number_edit_must_be_finite",
        tags=_TAG,
    ),
)
