"""The approved checklist as an item of the AI review's exit (owner, 12 Nov 2026, STATE section 37; `ONE-REVIEWER.md`).

A line made by the calculator (`agent_review_calculator`, source "code") for an APPROVED checklist check has no rule row and no tier of its own: the
owner approved the checklist entry (`reference/datasheet_checks.json`). Its item stands as an owner-tier item ONLY when the entry exists in that approved
data: the marker alone is never taken on trust (as `agent_review_verdict.is_checklist_item`). An id the approved file does not hold is a rule with no tier,
and its Pass or Fail is capped by the exit. Reads the approved file only; no database, no model, no network.
"""

from __future__ import annotations

from collections.abc import Mapping

_IDS: list[frozenset[str]] = []


def approved_check_ids() -> frozenset[str]:
    """The ids of the approved checklist entries: every entry of the file that has an id. Remembered only when the data loaded; an empty or failed
    load is asked again, never kept."""
    if _IDS:
        return _IDS[0]
    from . import datasheet_checks

    ids: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, Mapping):
            if isinstance(node.get("id"), str):
                ids.add(node["id"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    try:
        walk(datasheet_checks.load_rules())
    except (OSError, ValueError):
        return frozenset()
    found = frozenset(ids)
    if found:
        _IDS.append(found)
    return found


def is_approved_code_item(item: Mapping | None) -> bool:
    """Source "code", the marker, and a rule id that EXISTS in the approved data."""
    return (
        isinstance(item, Mapping)
        and item.get("source") == "code"
        and item.get("approved_checklist") is True
        and item.get("rule_id") in approved_check_ids()
    )
