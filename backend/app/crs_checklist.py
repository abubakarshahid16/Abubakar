"""CRS rows for the review checklist (#1352 follow-up, 28 Oct planner audit of a live run).

A checklist item the system could not decide (two values, a mandatory field on an unread page,
wording seen but not read) is stored as NEEDS_ENGINEER_REVIEW. It used to be only a count in the
Review notes; the engineer needs the item itself as a row. A checklist item is told from any
other datasheet check by the clause it cites, which only checklist results carry.
A draft checklist (not signed off by an engineer) says so on its row.
"""

from __future__ import annotations

DRAFT_WORDS = "Draft checklist, engineer to confirm"


def is_row(status: str | None, finding: dict) -> bool:
    """Whether a datasheet-check finding is a CRS row: a breach, a gap, a check held because its
    rule is not proven, or a checklist item left to the engineer."""
    held = status == "NEEDS_ENGINEER_REVIEW" and bool(finding.get("standard_clause"))
    return (
        status in ("NON_COMPLIANT", "MISSING_INFORMATION")
        or bool(finding.get("rule_said"))
        or held
    )


def draft_bits(finding: dict) -> list[str]:
    """The reasoning line's note that the checklist item is a draft, or nothing."""
    from .datasheet_checks import is_draft_checklist

    return [DRAFT_WORDS] if is_draft_checklist(finding.get("requirement")) else []
