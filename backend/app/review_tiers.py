"""Order 95 piece 1: the CRS-first screen's three tiers, one per finding.

Review by exception: the engineer reads the finished comment sheet and touches
only the rows the machine is unsure about. Each finding of a run lands in ONE
tier with ONE reason word:

- ``comment``: goes on the sheet as a comment (does not meet / not stated /
  other document);
- ``needs_you``: the machine is unsure and an engineer decides (an AI guess
  nobody confirmed, a held rule, a safety tick, a page nobody read, a
  conditional, an engineer check, no verdict at all);
- ``met_or_not_applicable``: no comment is needed (meets / not applicable /
  not this document).

DISPLAY ONLY. This module reads stored fields and decides nothing: no verdict,
status or engine change. The rules run first-match-wins and an unknown status
is "needs you", never met - "not mentioned" is never "compliant", and a guess
stays a guess until a human confirms it. A finding an engineer removed
(``approval_status = 'rejected'``) is in no tier; it is counted as removed.
"""
from __future__ import annotations

from . import comparison

COMMENT = "comment"
NEEDS_YOU = "needs_you"
MET = "met_or_not_applicable"
TIERS = (COMMENT, NEEDS_YOU, MET)
REMOVED = "removed"

#: Findings written by an AI step; they stay a guess until `confirmed_by`.
_AI_ORIGINS = ("ai_engineering_check", "web_standard_check")

_NEEDS_REVIEW_WORD = {
    comparison.UNREAD_PAGES: "page not read",
    comparison.PAGE_READER_ONLY: "AI-read page",
}
_STATUS = {
    comparison.CONDITIONAL: (NEEDS_YOU, "conditional"),
    comparison.NON_COMPLIANT: (COMMENT, "does not meet"),
    comparison.COMPLIANT: (MET, "meets"),
    comparison.NOT_APPLICABLE: (MET, "not applicable"),
    comparison.NOT_IN_DOCUMENT_SCOPE: (MET, "not this document"),
}


def _reason_code(finding: dict) -> str | None:
    """The stored code (#921), or the code a pre-#921 rationale leads with."""
    return finding.get("reason_code") or comparison.reason_code_of(finding.get("ai_rationale"))


def tier_of(finding: dict) -> tuple[str, str]:
    """(tier, reason word) for one finding; (``REMOVED``, "removed") when an
    engineer removed it. First match wins."""
    if finding.get("approval_status") == "rejected":
        return REMOVED, "removed"
    confirmed = bool(finding.get("confirmed_by"))
    if finding.get("origin") in _AI_ORIGINS and not confirmed:
        return NEEDS_YOU, "AI guess"
    if finding.get("trust_label") == "UNPROVEN":
        return NEEDS_YOU, "rule not proven"
    if finding.get("show_for_engineer_tick") and not confirmed:
        return NEEDS_YOU, "safety tick"
    status = finding.get("compliance_status")
    code = _reason_code(finding)
    if status == comparison.NEEDS_ENGINEER_REVIEW:
        return NEEDS_YOU, _NEEDS_REVIEW_WORD.get(code or "", "engineer check")
    if status == comparison.MISSING_INFORMATION:
        return COMMENT, ("other document" if code == comparison.REQUIRES_OTHER_DOCUMENT
                         else "not stated")
    return _STATUS.get(status or "", (NEEDS_YOU, "no verdict"))


def missing_standard_of(finding: dict, missing: dict[str, str]) -> str | None:
    """Order 96: the key of the cited standard the library does not hold
    (MISSING_LOCALLY on the run) that this finding rests on, or None.

    `missing` maps `standards_acquisition`'s normalised identifier key to the
    identifier, from the run's stored `missing_references`. The finding names
    its standard where the AI check wrote it ("... Relates to: <name>.")."""
    text = finding.get("ai_rationale") or ""
    if not missing or "Relates to: " not in text:
        return None
    from .applicability import normalise_identifier
    key = normalise_identifier(text.split("Relates to: ", 1)[1].rstrip("."))
    return key if key in missing else None


def _order(row: dict) -> tuple:
    page = row["contractor_page"]
    return (TIERS.index(row["tier"]), page is None, page or 0, row["standard_clause"] or "")


def summarise(findings: list[dict], missing: dict[str, str] | None = None) -> dict:
    """Headline counts and one row per finding still in a tier, in screen
    order: tier, then contractor page (no page last), then clause."""
    counts = dict.fromkeys((*TIERS, REMOVED), 0)
    rows = []
    for f in findings:
        tier, reason = tier_of(f)
        counts[tier] += 1
        if tier != REMOVED:
            rows.append({"finding_id": f["id"], "tier": tier, "reason": reason,
                         "compliance_status": f.get("compliance_status"),
                         "standard_clause": f.get("standard_clause"),
                         "contractor_page": f.get("contractor_page"),
                         "equipment_tag": f.get("equipment_tag"),
                         "missing_standard_id": missing_standard_of(f, missing or {})})
    rows.sort(key=_order)
    return {"counts": {**counts, "total": len(findings)}, "rows": rows}
