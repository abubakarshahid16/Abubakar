"""Which findings enter a CRS, and as what text. Master plan §13 and §17.

Pure functions: findings in as plain dicts, comment rows out as plain dicts
for crs_export.build_crs. No db, no app imports. Pre-built and pre-tested by
Cowork (7 standalone tests) on branch cowork/phase-7-crs-export.

ISSUE #165, CRITERION 4. NON_COMPLIANT and NEEDS_ENGINEER_REVIEW findings
still enter one row each - they are the individual things an engineer acts
on. MISSING_INFORMATION and NOT_IN_DOCUMENT_SCOPE findings still never enter
individually (a real run over one of the pump-datasheet regression documents
carries hundreds of NOT_IN_DOCUMENT_SCOPE findings and dozens of MISSING_
INFORMATION ones - a row each would bury the handful of real defects under
noise, the same reasoning that already kept MISSING_INFORMATION out). But
dropping either bucket to nothing, as the code did before #165, is a
different defect: a client reading the sheet has no way to know either
question was ever asked. Each bucket instead gets ONE summary row, stating
its own count and boundary (CLAUDE.md rule 4: every count states its
boundary) - the same shape `missing_references` already uses for a cited
standard the library does not hold. `row_kind` rides on every row (never
printed) so `crs_export` can fill each kind its own colour without re-deciding
what the sheet says.
"""

INCLUDED_STATUSES = ("NON_COMPLIANT", "NEEDS_ENGINEER_REVIEW")

#: Read by `crs_export` to colour a row. Never printed. One tag per bucket
#: this module can produce, so a renderer can distinguish "already flagged
#: as a defect" (NON_COMPLIANT) from "needs a human's judgement"
#: (NEEDS_ENGINEER_REVIEW) from the two summary buckets from the standards-
#: gap rows - four visually different things, not two.
ROW_KIND_NON_COMPLIANT = "non_compliant"
ROW_KIND_NEEDS_ENGINEER_REVIEW = "needs_engineer_review"
ROW_KIND_MISSING_INFORMATION = "missing_information"
ROW_KIND_REQUIRES_OTHER_DOCUMENT = "requires_other_document"
ROW_KIND_MISSING_REFERENCE = "missing_reference"

#: The compliance status a MISSING_INFORMATION finding carries. Compared as a
#: literal, not imported from `comparison`, because this module stays pure
#: (no db, no app imports) on purpose - see the module docstring.
_MISSING_INFORMATION = "MISSING_INFORMATION"
_NOT_IN_DOCUMENT_SCOPE = "NOT_IN_DOCUMENT_SCOPE"

#: The leading token `comparison.REQUIRES_OTHER_DOCUMENT` embeds in
#: `ai_rationale` on a NOT_IN_DOCUMENT_SCOPE finding (issue #163). Duplicated
#: here as a literal for the same reason as `_MISSING_INFORMATION` above:
#: reading a stable, documented piece of text is not re-deciding the verdict
#: that produced it. A NOT_IN_DOCUMENT_SCOPE finding without this marker is
#: left out of the summary count rather than guessed into one - #165 found
#: none in three real runs, but a future branch of `comparison._reconcile`
#: could add one, and this module must not assume every reason for that
#: status is "needs another document".
_REQUIRES_OTHER_DOCUMENT_MARKER = "requires_other_document"

#: B3. The reason code `comparison.UNREAD_PAGES` leads `ai_rationale` with on a
#: finding whose value could sit on a page not yet read into fields. Duplicated
#: as a literal for the same reason as the two above. Such a finding is an
#: instruction to the ENGINEER, never a comment to the contractor, so it never
#: enters the CRS as its own row.
_UNREAD_PAGES_MARKER = "UNREAD_PAGES"
ROW_KIND_PAGES_NOT_READABLE = "pages_not_readable"


def _page_list(pages: list[int]) -> str:
    """`[1, 2, 3, 7]` -> `1-3, 7` - the shape the findings themselves use."""
    out, run = [], []
    for p in sorted(pages):
        if run and p == run[-1] + 1:
            run.append(p)
            continue
        if run:
            out.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
        run = [p]
    if run:
        out.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
    return ", ".join(out)


def _unread(finding: dict) -> bool:
    return (finding.get("compliance_status") == "NEEDS_ENGINEER_REVIEW"
            and (finding.get("ai_rationale") or "").startswith(_UNREAD_PAGES_MARKER))


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
                   submittal_name: str,
                   unread_pages: list[int] | None = None) -> list[dict]:
    """One row per NON_COMPLIANT or NEEDS_ENGINEER_REVIEW finding, then one
    summary row each for MISSING_INFORMATION and requires-another-document
    findings (present only when the run has at least one), then one row per
    cited-and-missing standard.

    NEITHER BUCKET ENTERS INDIVIDUALLY. A thousand rows of "no evidence" or
    "checked in another document" is noise a reader cannot use - the same
    reasoning issue #165's predecessor already applied to MISSING_INFORMATION
    alone. But saying nothing about either bucket is a different defect: it
    reads as "no such requirements existed" about a review that may have
    parked most of its work there. Each bucket gets exactly one row stating
    its own count, honouring CLAUDE.md rule 4 (every count states its
    boundary) the same way the missing-reference rows already do.

    Order: NON_COMPLIANT, then NEEDS_ENGINEER_REVIEW, then the summaries,
    then the standards gaps.

    B3: a NEEDS_ENGINEER_REVIEW finding whose reason is UNREAD_PAGES is not an
    individual row either. It says "the value may be on a page nobody has read
    into fields yet" - work for the reviewing engineer, not a question for the
    contractor - and on today's regression documents there are 55 to 79 of
    them per run. They get ONE plain summary row naming the pages
    (`unread_pages`, the run's stored page coverage).
    """
    rows = []
    ordered = [f for f in findings
               if f.get("compliance_status") == "NON_COMPLIANT"]
    ordered += [f for f in findings
                if f.get("compliance_status") == "NEEDS_ENGINEER_REVIEW"
                and not _unread(f)]
    for f in ordered:
        by = "AI Review"
        if f.get("confirmed_by"):
            by = f"AI Review, confirmed by {f['confirmed_by']}"
        row_kind = (ROW_KIND_NON_COMPLIANT
                    if f.get("compliance_status") == "NON_COMPLIANT"
                    else ROW_KIND_NEEDS_ENGINEER_REVIEW)
        rows.append({
            # THE FINDING'S OWN STORED ID, carried so `crs_export` can mint a
            # per-row reference that survives a re-export. It is never
            # printed: `review_findings.id` is a uuid an engineer cannot read
            # back, and the sheet shows the short reference derived from it.
            "finding_id": f.get("id") or "",
            "document_name": submittal_name,
            "page_section": _citation(f),
            "comment": _comment_text(f),
            "comment_by": by,
            "row_kind": row_kind,
        })

    other_doc_count = sum(
        1 for f in findings
        if f.get("compliance_status") == _NOT_IN_DOCUMENT_SCOPE
        and _REQUIRES_OTHER_DOCUMENT_MARKER in (f.get("ai_rationale") or ""))
    if other_doc_count:
        rows.append({
            "finding_id": "requires-other-document-summary",
            "document_name": submittal_name,
            "page_section": "",
            "comment": (
                f"{other_doc_count} requirement"
                f"{'s' if other_doc_count != 1 else ''} reviewed against this "
                "submittal name their own evidence - a certificate, drawing "
                "or other document type - which is not this datasheet. They "
                "are not itemized here; each has to be checked against the "
                "document it actually names."),
            "comment_by": "AI Review",
            "row_kind": ROW_KIND_REQUIRES_OTHER_DOCUMENT,
        })

    unread_count = sum(1 for f in findings if _unread(f))
    if unread_count:
        pages = _page_list(unread_pages or [])
        where = (f"page{'s' if len(unread_pages or []) != 1 else ''} {pages} of "
                 "this submittal" if pages else "some pages of this submittal")
        rows.append({
            "finding_id": "pages-not-readable-summary",
            "document_name": submittal_name,
            "page_section": f"Pages {pages}" if pages else "",
            "comment": (
                f"Pages not yet readable - needs engineer review. "
                f"{unread_count} requirement{'s' if unread_count != 1 else ''} "
                f"could not be checked because {where} "
                f"{'are' if len(unread_pages or []) != 1 else 'is'} not yet read "
                "into fields by the system, so the values may be there. An "
                "engineer will check those pages; this is not a comment to the "
                "contractor and nothing is missing until that check is done."),
            "comment_by": "AI Review",
            "row_kind": ROW_KIND_PAGES_NOT_READABLE,
        })

    missing_info_count = sum(
        1 for f in findings
        if f.get("compliance_status") == _MISSING_INFORMATION)
    if missing_info_count:
        rows.append({
            "finding_id": "missing-information-summary",
            "document_name": submittal_name,
            "page_section": "",
            # WHAT WAS CHECKED (honesty audit 50): "have no value stated for
            # them in it" claimed the document was silent; what is known is
            # that no field read from it answered them.
            "comment": (
                f"{missing_info_count} requirement"
                f"{'s' if missing_info_count != 1 else ''} reviewed against "
                "this submittal were not answered by any field read from it. "
                "This is an absence, not a breach - the vendor has not been "
                "asked yet - and is not itemized here for the same reason the "
                "count above is not."),
            "comment_by": "AI Review",
            "row_kind": ROW_KIND_MISSING_INFORMATION,
        })

    for ref in missing_references:
        rows.append({
            # A gap row has no finding behind it, so its identity is the
            # standard it names - stable for as long as that standard is
            # still cited and still missing.
            "finding_id": f"missing-reference:{ref}",
            "document_name": submittal_name,
            "page_section": "References",
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
            "row_kind": ROW_KIND_MISSING_REFERENCE,
        })
    return rows
