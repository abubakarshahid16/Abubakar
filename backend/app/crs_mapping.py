"""Which findings enter a CRS, and as what text. Master plan §13 and §17.

Pure functions: findings in as plain dicts, comment rows out as plain dicts
for crs_export.build_crs. No db, no app imports. Pre-built and pre-tested by
Cowork (7 standalone tests) on branch cowork/phase-7-crs-export.
"""

INCLUDED_STATUSES = ("NON_COMPLIANT", "NEEDS_ENGINEER_REVIEW")


def _citation(finding: dict) -> str:
    parts = []
    std = finding.get("standard_name") or finding.get("standard_document_id")
    if std:
        clause = finding.get("standard_clause")
        page = finding.get("standard_page")
        bits = [str(std)]
        if clause:
            bits.append(f"clause {clause}")
        if page:
            bits.append(f"p{page}")
        parts.append(" ".join(bits))
    cpage = finding.get("contractor_page")
    if cpage:
        parts.append(f"submittal p{cpage}")
    return " / ".join(parts)


def _comment_text(finding: dict) -> str:
    lines = []
    req = finding.get("requirement_source_text")
    if req:
        lines.append(f"Requirement: {req}")
    value = finding.get("contractor_evidence_text")
    if value:
        lines.append(f"Submitted: {value}")
    rationale = finding.get("ai_rationale")
    if rationale:
        lines.append(rationale)
    tag = finding.get("equipment_tag")
    if tag:
        lines.append(f"Equipment: {tag}")
    return "\n".join(lines)


def build_crs_rows(findings: list[dict], missing_references: list[str],
                   submittal_name: str) -> list[dict]:
    """One row per NON_COMPLIANT or NEEDS_ENGINEER_REVIEW finding, then one
    row per cited-and-missing standard. MISSING_INFORMATION findings never
    enter individually - a thousand rows of 'no evidence' is noise, and 13
    covers the gap through the missing-reference rows instead.
    Order: NON_COMPLIANT first, then NEEDS_ENGINEER_REVIEW, then gaps.
    """
    rows = []
    ordered = [f for f in findings
               if f.get("compliance_status") == "NON_COMPLIANT"]
    ordered += [f for f in findings
                if f.get("compliance_status") == "NEEDS_ENGINEER_REVIEW"]
    for f in ordered:
        by = "AI Review"
        if f.get("confirmed_by"):
            by = f"AI Review, confirmed by {f['confirmed_by']}"
        rows.append({
            "document_name": submittal_name,
            "page_section": _citation(f),
            "comment": _comment_text(f),
            "comment_by": by,
        })
    for ref in missing_references:
        rows.append({
            "document_name": submittal_name,
            "page_section": "References",
            "comment": (f"Referenced standard {ref} is cited by this "
                        "submittal but is not available to this review. "
                        "Requirements governed by it were not evaluated."),
            "comment_by": "AI Review",
        })
    return rows
