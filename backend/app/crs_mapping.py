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
#: Chat redesign PR 5: a comment an ENGINEER filed from the Chat screen
#: (`chat_actions.file_comment`, `origin = 'chat'`). Their words and their
#: name - never "AI Review", because the model did not decide to send it.
ROW_KIND_ENGINEER_COMMENT = "engineer_comment"
#: Owner order 2d/2f: an AI engineering check item (kind C,
#: `origin = 'ai_engineering_check'`). Unconfirmed, its text rides in the
#: "AI Review Comments" column with COMPANY Comments empty; confirmed by an
#: engineer, it moves to COMPANY Comments under their name. Rejected, it is
#: not on the sheet at all.
ROW_KIND_AI_ENGINEERING_CHECK = "ai_engineering_check"
_AI_ORIGIN = "ai_engineering_check"
#: Owner order 2c: a datasheet self-check (kind B), labelled "Datasheet check".
ROW_KIND_DATASHEET_CHECK = "datasheet_check"
_DATASHEET_ORIGIN = "datasheet_check"
_AI_CONFIRMED_BY = "AI engineering check, confirmed by "
#: Owner order 2d-2: a public-web standards check item (kind D,
#: `origin = 'web_standard_check'`). Same confirm-or-off-the-sheet rule as
#: kind C - unconfirmed rides in "AI Review Comments", confirmed moves to
#: COMPANY Comments under the engineer's name, rejected is not on the sheet.
ROW_KIND_WEB_STANDARD_CHECK = "web_standard_check"
_WEB_ORIGIN = "web_standard_check"
_WEB_CONFIRMED_BY = "Web check, confirmed by "

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
#: Honesty audit entry 68: `comparison.PAGE_READER_ONLY` - the value was not
#: found on a page only the geometry/vision reader read. Engineer work, like
#: UNREAD_PAGES, so never an individual row to the contractor.
_PAGE_READER_ONLY_MARKER = "PAGE_READER_ONLY"
ROW_KIND_PAGE_READER_ONLY = "page_reader_only"


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


def _page_reader_only(finding: dict) -> bool:
    return (finding.get("compliance_status") == "NEEDS_ENGINEER_REVIEW"
            and (finding.get("ai_rationale") or "").startswith(_PAGE_READER_ONLY_MARKER))


def _ai_relates_to(finding: dict) -> str:
    """The standard NAME an AI item relates to, as `ai_engineering_check`
    stored it on the rationale ("... Relates to: <name>.")."""
    text = finding.get("ai_rationale") or ""
    name = text.split("Relates to: ", 1)[1].rstrip(".") if "Relates to: " in text else ""
    return "" if name == "no standard named" else name


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


def _rejected(finding: dict) -> bool:
    """Owner order section 3: an engineer rejected this comment - it is left
    off the sheet. The finding and the rejection both stay on record."""
    return finding.get("approval_status") == "rejected"


def _edited_by(finding: dict) -> str:
    who = finding.get("confirmed_by_name") or finding.get("confirmed_by") or "an engineer"
    return f"AI Review, edited and confirmed by {who}"


def _comment_text(finding: dict) -> str:
    # Owner order section 3: THE ENGINEER'S WORDING, when they edited it, is
    # the comment. The review's own text stays on the finding, not the sheet.
    if finding.get("engineer_comment"):
        return finding["engineer_comment"]
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


def _fold(text) -> str:
    return " ".join(str(text or "").lower().split())


def _merge_same_rule(ordered: list[dict]) -> list[tuple[dict, list[dict]]]:
    """Owner order 2e: THE SAME RULE FROM SEVERAL STANDARDS IS ONE COMMENT.

    Two standards carrying the same requirement text, decided the same way
    against the same datasheet value, printed twice was the design-pressure
    rule the owner saw repeated. One row now, citing every standard. Only
    IDENTICAL requirement text (whitespace and case folded) against the same
    submitted value and page, with the same status, is merged - a similar
    rule is a different rule until a person says otherwise.
    """
    groups: dict[tuple, list[dict]] = {}
    order: list[tuple] = []
    for f in ordered:
        text = _fold(f.get("requirement_source_text"))
        # An engineer's edited wording is theirs for THAT finding: two
        # findings they worded differently are never printed as one.
        key = ((f.get("compliance_status"), text, _fold(f.get("contractor_evidence_text")),
                f.get("contractor_page"), f.get("engineer_comment"))
               if text else ("__unique__", f.get("id") or id(f)))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(f)
    return [(groups[k][0], groups[k][1:]) for k in order]


#: The "Review notes" sheet (owner order 2f): the engineer's internal list.
NOTE_MISSING_STANDARD = "Standard not in your library - upload required"
NOTE_UNREAD_PAGES = "Pages not yet readable - engineer to check"
NOTE_PAGE_READER = "Value not found by the page reader - engineer to check the page"
NOTE_OTHER_DOCUMENT = "Requires another document"


def build_review_notes(findings: list[dict], missing_references: list[str],
                       unread_pages: list[int] | None = None) -> list[dict]:
    """The engineer's internal notes for one run - never a contractor comment.

    One row per cited standard not held; one row for the pages not read into
    fields; one for values the page reader did not find; and the requirements
    that name their own evidence (a certificate, procedure, drawing) GROUPED
    BY STANDARD with a count each, not one row per requirement (2e). Every
    count states its boundary: "of this run's requirements from <standard>".
    """
    notes: list[dict] = []
    for ref in missing_references:
        notes.append({"note": NOTE_MISSING_STANDARD, "standard": ref, "count": None,
                      "detail": (f"Cited by this submittal and not in the standards "
                                 f"library; its requirements were not checked.")})
    unread = [f for f in findings if _unread(f)]
    if unread:
        pages = _page_list(unread_pages or [])
        notes.append({"note": NOTE_UNREAD_PAGES, "standard": "", "count": len(unread),
                      "detail": (f"{len(unread)} requirement{'s' if len(unread) != 1 else ''} "
                                 "could not be checked because "
                                 + (f"page{'s' if len(unread_pages or []) != 1 else ''} {pages}"
                                    if pages else "some pages")
                                 + " of this submittal are not yet read into fields; the "
                                 "values may be there.")})
    reader = [f for f in findings if _page_reader_only(f)]
    if reader:
        notes.append({"note": NOTE_PAGE_READER, "standard": "", "count": len(reader),
                      "detail": (f"{len(reader)} requirement{'s' if len(reader) != 1 else ''} "
                                 "had no value on pages read only by the page layout "
                                 "reader, which does not find every field on a page.")})
    by_standard: dict[str, int] = {}
    for f in findings:
        if (f.get("compliance_status") == _NOT_IN_DOCUMENT_SCOPE
                and _REQUIRES_OTHER_DOCUMENT_MARKER in (f.get("ai_rationale") or "")):
            name = str(f.get("standard_name") or f.get("standard_document_id") or "")
            by_standard[name] = by_standard.get(name, 0) + 1
    for name in sorted(by_standard):
        n = by_standard[name]
        notes.append({"note": NOTE_OTHER_DOCUMENT, "standard": name, "count": n,
                      "detail": (f"{n} of this run's requirements from {name or 'this standard'} "
                                 "name their own evidence - a certificate, procedure, "
                                 "drawing or other document - which is not this "
                                 "datasheet. Check each against the document it names.")})
    return notes


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

    Order: NON_COMPLIANT, then NEEDS_ENGINEER_REVIEW, then comments engineers
    filed from chat (their words, their name), then the summaries,
    then the standards gaps.

    B3: a NEEDS_ENGINEER_REVIEW finding whose reason is UNREAD_PAGES is not an
    individual row either. It says "the value may be on a page nobody has read
    into fields yet" - work for the reviewing engineer, not a question for the
    contractor - and on today's regression documents there are 55 to 79 of
    them per run. They get ONE plain summary row naming the pages
    (`unread_pages`, the run's stored page coverage).
    """
    rows = []
    findings = [f for f in findings if not _rejected(f)]
    ordered = [f for f in findings
               if f.get("compliance_status") == "NON_COMPLIANT"]
    ordered += [f for f in findings
                if f.get("compliance_status") == "NEEDS_ENGINEER_REVIEW"
                and not _unread(f) and not _page_reader_only(f)]
    # Owner order 2c: a datasheet check's missing value is a comment of its
    # own ("Hydrotest pressure is marked 'TBA'"), not one of the uncounted
    # absences summarised below.
    ordered += [f for f in findings
                if f.get("origin") == _DATASHEET_ORIGIN
                and f.get("compliance_status") == _MISSING_INFORMATION]
    for f, also in _merge_same_rule(ordered):
        if f.get("origin") == _DATASHEET_ORIGIN:
            rows.append({
                "finding_id": f.get("id") or "",
                "document_name": submittal_name,
                "page_section": " / ".join(p for p in (
                    f"submittal p{f['contractor_page']}" if f.get("contractor_page") else "",
                    f.get("contractor_section") or "") if p),
                # "Datasheet check: ..." - the finding's own words, which say
                # the calculation ("Design pressure 20 barg (page 1) is not at
                # least operating pressure 23.5 barg (page 1).").
                "comment": f.get("engineer_comment") or f.get("finding") or "",
                "comment_by": (_edited_by(f) if f.get("engineer_comment")
                               else f"AI Review, confirmed by {f['confirmed_by']}"
                               if f.get("confirmed_by") else "AI Review"),
                "row_kind": ROW_KIND_DATASHEET_CHECK,
            })
            continue
        by = "AI Review"
        if f.get("engineer_comment"):
            by = _edited_by(f)
        elif f.get("confirmed_by"):
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
            "page_section": "; ".join([_citation(f), *(_citation(o) for o in also)]),
            "comment": _comment_text(f) + (
                "\nThe same requirement is in: " + "; ".join(_citation(o) for o in also)
                if also else ""),
            "comment_by": by,
            "row_kind": row_kind,
        })

    # An engineer's own comments, filed from chat, after the review's rows and
    # before its summaries: they are individual comments to the contractor,
    # like the rows above, but the engineer's rather than the machine's.
    for f in findings:
        if f.get("origin") != "chat":
            continue
        rows.append({
            "finding_id": f.get("id") or "",
            "document_name": submittal_name,
            "page_section": "",
            "comment": f.get("engineer_comment") or f.get("finding") or "",
            "comment_by": f"{f.get('confirmed_by') or 'Engineer'} (filed from chat)",
            "row_kind": ROW_KIND_ENGINEER_COMMENT,
        })

    # Owner order 2d/2f and 2d-2: AI engineering check (kind C) and public-web
    # standards check (kind D) items. Neither is ever a verdict - a question
    # for the contractor once an engineer has confirmed it, and until then a
    # draft in its own column that COMPANY Comments never holds.
    for f in findings:
        origin = f.get("origin")
        if origin not in (_AI_ORIGIN, _WEB_ORIGIN) or f.get("approval_status") == "rejected":
            continue
        text = f.get("engineer_comment") or " ".join(
            p for p in (f.get("finding"), f.get("required_action")) if p)
        if origin == _AI_ORIGIN:
            relates = _ai_relates_to(f)
            if relates and not f.get("engineer_comment"):
                text += f" (Relates to {relates}.)"
        where = " / ".join(p for p in (
            f"submittal p{f['contractor_page']}" if f.get("contractor_page") else "",
            f.get("contractor_section") or "") if p)
        confirmed = bool(f.get("confirmed_by"))
        confirmed_by_prefix = _AI_CONFIRMED_BY if origin == _AI_ORIGIN else _WEB_CONFIRMED_BY
        row_kind = ROW_KIND_AI_ENGINEERING_CHECK if origin == _AI_ORIGIN else ROW_KIND_WEB_STANDARD_CHECK
        rows.append({
            "finding_id": f.get("id") or "",
            "document_name": submittal_name,
            "page_section": where,
            "comment": text if confirmed else "",
            "comment_by": (f"{confirmed_by_prefix}{f.get('confirmed_by_name') or f['confirmed_by']}"
                           if confirmed else ""),
            "ai_review_comment": "" if confirmed else text,
            "row_kind": row_kind,
        })

    # OWNER ORDER 2f: THE INTERNAL NOTES LEFT THIS SHEET. Requirements that
    # need another document, pages not yet read, values the page reader did
    # not find, and cited standards not in the library are the ENGINEER'S
    # to-do list - they were printed in the contractor's COMPANY Comments
    # column as "AI Review". They are now the "Review notes" sheet
    # (`build_review_notes`), which the contractor's copy does not carry.

    missing_info_count = sum(
        1 for f in findings
        if f.get("compliance_status") == _MISSING_INFORMATION
        and f.get("origin") != _DATASHEET_ORIGIN)
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
                "asked yet - and is not itemized here: a row each would bury "
                "the comments above."),
            "comment_by": "AI Review",
            "row_kind": ROW_KIND_MISSING_INFORMATION,
        })

    return rows
