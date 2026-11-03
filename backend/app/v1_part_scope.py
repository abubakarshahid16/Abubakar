"""Owner 3 Nov 13:50, behind V1_PART_SCOPE_ENABLED: the Part-or-Appendix scope clause (`rule_part_scope`, #1644) also
narrows the rulebook version 1 requirements a review reads.

WHY. #1644 ran only on rulebook v2, so a v1 requirement from a Part that is written for other equipment (an
Appendix on one kind of fitting, say) was still paired to the sheet's values. WHICH FIX. Applying the same scope check
to v1 only NARROWS what the review reads and keeps every v1 row that is in scope or whose scope is unknown. The other
choice, reading only v2 rules for a standard that has a v2 snapshot, would drop every v1 finding until a person had
approved v2 rules, so true findings would be lost; this does not.

A requirement is left out only when `rule_part_scope` says OUTSIDE (a model's reading of the Part's scope clause, stored
in `ai_task_cache`, verified by code in the Part's text). It goes to the run's "not applied" list with the Part named,
never silently. Unknown scope stays in, as today. Reads only; no model, no socket; nothing is written.
"""

from __future__ import annotations

from . import rule_part_scope
from .config import settings
from .db import connect

CODE = "outside_part_scope"


def enabled() -> bool:
    return bool(settings.v1_part_scope_enabled)


def _rule(requirement: dict) -> dict:
    return {
        "standard_document_id": requirement.get("standard_document_id"),
        "quote": requirement.get("source_text") or requirement.get("requirement_text"),
        "page": requirement.get("page"),
        "clause": requirement.get("clause"),
    }


def gate(requirements: list[dict], equipment_type, not_applied: list) -> list[dict]:
    """The requirements this review reads. Off, or no equipment type: all of them, unchanged."""
    if not enabled() or not equipment_type:
        return list(requirements)
    conn = connect()
    kept: list[dict] = []
    for requirement in requirements:
        scope = rule_part_scope.of_rule(conn, _rule(requirement), equipment_type)
        if scope.reason == rule_part_scope.OUTSIDE_EQUIPMENT_SCOPE:
            not_applied.append(
                {"requirement": requirement, "code": CODE, "detail": scope.words}
            )
        else:
            kept.append(requirement)
    return kept
