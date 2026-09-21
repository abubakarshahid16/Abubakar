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
    rationale = _client_facing(finding.get("ai_rationale"))
    if rationale:
        lines.append(rationale)
    tag = finding.get("equipment_tag")
    if tag:
        lines.append(f"Equipment: {tag}")
    return "\n".join(lines)


#: Lines the machine wrote to itself, never to the client. A CRS row is the
#: reviewing company's comment to the contractor; "Rechecked by model" or
#: "Paired by model; engineer must confirm" are notes for the engineer's screen
#: and a client reading them on the sheet would rightly ask who reviewed it.
#: The engineer confirms or edits in the app; what leaves is the comment.
INTERNAL_NOTE_PREFIXES = (
    "Rechecked by model",
    "Paired by model",
    "Proposed by model",
    "[Draft by model",
)


def _client_facing(text: str | None) -> str:
    """`text` with every internal note line removed."""
    if not text:
        return ""
    kept = [line for line in str(text).splitlines()
            if not line.strip().startswith(INTERNAL_NOTE_PREFIXES)]
    return "\n".join(kept).strip()


def build_crs_rows(findings: list[dict], missing_references: list[str],
                   submittal_name: str, submittal_number: str = "",
                   reference_pages: dict[str, int] | None = None) -> list[dict]:
    """One row per NON_COMPLIANT or NEEDS_ENGINEER_REVIEW finding, then one
    row per cited-and-missing standard. MISSING_INFORMATION findings never
    enter individually - a thousand rows of 'no evidence' is noise, and 13
    covers the gap through the missing-reference rows instead.
    Order: NON_COMPLIANT first, then NEEDS_ENGINEER_REVIEW, then gaps.

    `submittal_number` is repeated on every row for the "Submittal No."
    column. Blank stays blank - it is never filled with a placeholder.

    `reference_pages` maps a cited-but-missing identifier to the page it was
    found on, so a gap row can say "References p12" instead of bare
    "References". A identifier absent from the mapping keeps "References"
    exactly as before: the page is READ, never inferred.
    """
    pages = reference_pages or {}
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
            # THE FINDING'S OWN STORED ID, carried so `crs_export` can mint a
            # per-row reference that survives a re-export. It is never
            # printed: `review_findings.id` is a uuid an engineer cannot read
            # back, and the sheet shows the short reference derived from it.
            "finding_id": f.get("id") or "",
            "submittal_number": submittal_number or "",
            "document_name": submittal_name,
            "page_section": _citation(f),
            "comment": _comment_text(f),
            "comment_by": by,
        })
    for ref in missing_references:
        rows.append({
            # A gap row has no finding behind it, so its identity is the
            # standard it names - stable for as long as that standard is
            # still cited and still missing.
            "finding_id": f"missing-reference:{ref}",
            "submittal_number": submittal_number or "",
            "document_name": submittal_name,
            # THE PAGE THE IDENTIFIER WAS ACTUALLY FOUND ON, when the caller
            # could find it. "References" alone told a reader to go and search
            # the whole submittal for the citation this row is about. A
            # missing entry keeps the old text rather than guessing a page.
            "page_section": (f"References p{pages[ref]}" if pages.get(ref)
                             else "References"),
            # "NOT IN THE STANDARDS LIBRARY", not "not available". The
            # second reads as a claim that a CAPABILITY is missing, and
            # test_copy_matches_reality bans it for exactly that reason; the
            # first says the narrower thing that is actually true - this one
            # document was not loaded. It also tells the reader what would fix
            # it, which "not available" does not.
            "comment": (f"Referenced standard {ref} is cited by this "
                        "submittal but is not in the standards library for "
                        "this review. Requirements governed by it were not "
                        "evaluated."),
            "comment_by": "AI Review",
        })
    return rows
