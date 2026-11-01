"""A value the sheet defers to the contractor is a query, never a verdict (owner decision D2, #1475).

The datasheet reader keeps a figure printed with a deferral phrase ("340 psig By Contractor") as a value and
the phrase as its `value_note` (#725 F3). Both deciders then judged the figure as if it were final: the
datasheet checklist wrote "is stated" or did the arithmetic, and the standards comparison compared it, so the
CRS showed a Pass on a number the sheet itself says is not final.

Behind `settings.deferred_value_is_query_enabled` (OFF by default) such a value becomes
NEEDS_ENGINEER_REVIEW, whether the numbers read pass or breach, in both deciders:

  * `reason(fact)`: the standards comparison (`comparison._hold_low_trust_breach` asks it);
  * `hold_results(results, facts, rules, wanted)`: the datasheet checks (`datasheet_checks.evaluate`), for the
    value a result is about and for the value it is checked against (the right-hand role of its rule).

Only COMPLIANT and NON_COMPLIANT are held; every other status passes unchanged. The arithmetic stays in the
words so the engineer sees what the numbers said.
"""

from __future__ import annotations

from . import blank_markers
from .config import settings

DEFERRED_VALUE = "deferred_value"
_DECIDED = ("COMPLIANT", "NON_COMPLIANT")
_QUERY = "NEEDS_ENGINEER_REVIEW"


def note_of(fact: dict | None) -> str | None:
    """The deferral phrase printed beside a stated figure ("By Contractor", "TBA"), else None."""
    note = " ".join(str((fact or {}).get("value_note") or "").split())
    return note if note and blank_markers.names_a_marker(note) else None


def reason(fact: dict | None) -> str | None:
    """Why a decided verdict on this value must wait (switch ON), or None. Read by the comparison's existing
    hold (`comparison._hold_low_trust_breach`), which turns COMPLIANT and NON_COMPLIANT into a query that keeps
    the arithmetic in the words."""
    if not settings.deferred_value_is_query_enabled:
        return None
    note = note_of(fact)
    if note is None:
        return None
    return f"{DEFERRED_VALUE}: the datasheet marks this value {note!r}, so it is a deferred value"


def _right_roles(rules: dict) -> dict[str, str]:
    """rule id -> the role its value is checked against (consistency pairs and checklist items)."""
    found = {
        r["id"]: r["right"] for r in rules.get("consistency", []) if r.get("right")
    }
    for checklist in rules.get("checklists", {}).values():
        if not isinstance(checklist, dict):
            continue
        for item in checklist.get("items", []):
            rule = item.get("rule") or {}
            right = rule.get("right") or rule.get("percent_of_role")
            if right:
                found[item["id"]] = right
    return found


def hold_results(
    results: list[dict], facts: list[dict], rules: dict, wanted
) -> list[dict]:
    """`results` with every decided result about a deferred value turned into a query (switch ON)."""
    if not settings.deferred_value_is_query_enabled or not results:
        return results
    from .datasheet_checks import role_of

    by_id = {f.get("id"): f for f in facts}
    noted: dict[tuple, str] = {}
    for fact in facts:
        note = note_of(fact)
        role = role_of(fact.get("field_name") or "", rules, wanted) if note else None
        if role:
            noted[(fact.get("equipment_tag"), role)] = note
    right_of = _right_roles(rules)
    out = []
    for r in results:
        if r.get("status") not in _DECIDED:
            out.append(r)
            continue
        right = right_of.get(r.get("rule_id"))
        note = note_of(by_id.get(r.get("fact_id"))) or (
            right
            and (noted.get((r.get("equipment_tag"), right)) or noted.get((None, right)))
        )
        if not note:
            out.append(r)
            continue
        out.append(
            {
                **r,
                "status": _QUERY,
                "detail": (
                    f"Could not be judged: the sheet marks a value this check rests on '{note}', so it is "
                    f"deferred to the contractor. The numbers read {r['status']}; engineer to confirm. "
                    f"{r.get('detail') or ''}"
                ).strip(),
            }
        )
    return out
