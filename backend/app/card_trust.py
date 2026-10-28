"""Which rule cards may decide a checklist verdict while the engineer's approval is pending (order 306.1).

Every checklist is still a DRAFT, so `rule_trust.check_label` holds each checklist result for the engineer
(UNPROVEN). With the switch `tested_cards_decide_enabled` ON, a relief-valve checklist card that is TESTED under
the stricter rule gets its own label, TESTED_CARD, with the words "automatic (tested rule, engineer approval
pending)" (never "proven": nothing here proves a family). The stricter rule, each part checked by code:

  * the real code passed the card's meets, breaks and unclear cases, and an at-the-limit case for a limit rule
    (`rule_cards.run_card`);
  * its tests include cases WRITTEN from the rule's meaning (generated cases only test the code path, not that
    the box the card names is the right one);
  * its source is a clause NUMBER, not a definition, not a "datasheet fields" placeholder;
  * it is not marked `weak_source`, and it does not wait for a standard we do not hold.

Every other card stays UNPROVEN. A COMPLIANT verdict on a safety field still goes to the engineer's tick
(`rule_trust.tier`). Tested is not approved: the approval screen (order 302.4) is the engineer's step.
"""

from __future__ import annotations

import re
from functools import cache, lru_cache

from . import datasheet_checks as dc
from . import rule_cards

#: The equipment types whose cards may decide (owner order 306: the relief valve first).
DECIDING_TYPES = ("Pressure Safety Valve",)
_CLAUSE = re.compile(r"^(?:\d+(?:\.\d+)*|[A-Za-z]{1,5}-\d+(?:\.\d+)*)$")


@lru_cache(maxsize=1)
def _cards() -> dict[str, tuple[str, dict]]:
    rules = dc.load_rules()
    return {
        item["id"]: (equipment_type, item)
        for equipment_type, checklist in rules["checklists"].items()
        if isinstance(checklist, dict)
        for item in checklist["items"]
    }


def has_clause_number(item: dict) -> bool:
    return bool(
        _CLAUSE.match(str((item.get("source") or {}).get("clause") or "").strip())
    )


@cache
def why_not(rule_id: str) -> str | None:
    """None when the card may decide; otherwise the reason, in words."""
    found = _cards().get(rule_id)
    if found is None:
        return "not a committed card"
    equipment_type, item = found
    if equipment_type not in DECIDING_TYPES:
        return "this equipment type's cards do not decide yet"
    if item.get("weak_source"):
        return "weak source"
    if item.get("needs"):
        return item["needs"]
    if not has_clause_number(item):
        return "the source is not a clause number"
    ran = rule_cards.run_card(item, equipment_type)
    if ran["status"] != "tested":
        return ran["why"]
    if not any(r["kind"] == "written" for r in ran["runs"]):
        return "generated cases only"
    return None


def decides(result: dict) -> bool:
    """May this checklist result decide? Only a committed card's result, never a local or draft-only item."""
    return (
        bool(result.get("checklist"))
        and not result.get("local")
        and why_not(result.get("rule_id")) is None
    )


def safety(rule_id: str) -> bool:
    """Is the card's rule about a safety field (set pressure, design pressure, relief capacity...)? Then a COMPLIANT
    verdict is shown to the engineer to tick, like any safety-tier rule."""
    from . import rule_trust

    item = _cards()[rule_id][1]
    rule = item["rule"]
    for key in ("field", "left", "right"):
        name = rule.get(key)
        probe = {
            "field": str(name).replace("_", " "),
            "requirement_text": item["text"],
            "condition": item.get("condition"),
        }
        if name and rule_trust.tier(probe)[0] == rule_trust.SAFETY:
            return True
    return False


def clear() -> None:
    """Forget what was worked out (the tests change the rules)."""
    _cards.cache_clear()
    why_not.cache_clear()
