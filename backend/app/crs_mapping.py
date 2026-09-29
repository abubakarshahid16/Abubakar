"""Which findings enter a CRS, and as what text. Master plan §13 and §17.

Pure functions: findings in as plain dicts, comment rows out as plain dicts
for crs_export.build_crs. No db, no app imports. Pre-built and pre-tested by
Cowork (7 standalone tests) on branch cowork/phase-7-crs-export.

CRS QUICK WINS (2026-09-27, audit crs.md defects 2, 5, 8, 9) - supersedes
issue #165's summary rows. NON_COMPLIANT, MISSING_INFORMATION and
NEEDS_ENGINEER_REVIEW findings enter ONE ROW PER FIELD ISSUE: the same clause,
field and printed value across several tags (or several standards stating the
same words) is one row naming them all. The old single "N requirements ...
not itemized here" row hid a vibration breach, a hydrotest shortfall and a
nozzle-size breach on the audit's planted-defect sheets; a blank "vendor to
advise" value is the most common comment a reviewing engineer writes, so it
is a row of its own. NOT_IN_DOCUMENT_SCOPE, unread-page and page-reader
questions stay off the sheet as Review notes (owner order 2f), each note
counting its own boundary. The comment is written in an engineer's voice
(`engineer_comment_text`), Page/Section is the DATASHEET's page and field,
the standard and clause ride in `standard_reference`, and every row carries
`engineer_confirmed` - the issue-to-contractor copy prints only those.
`row_kind` rides on every row (never printed) so `crs_export` can fill each
kind its own colour without re-deciding what the sheet says.
"""

import hashlib
import re

INCLUDED_STATUSES = ("NON_COMPLIANT", "NEEDS_ENGINEER_REVIEW", "MISSING_INFORMATION")

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
#: An Open comment from an earlier run or revision of this submittal that the
#: current run no longer raises. Industry practice carries it forward until a
#: reviewer closes it (`crs_numbers.open_elsewhere`); never dropped silently.
ROW_KIND_CARRIED_FORWARD = "carried_forward"
_WEB_ORIGIN = "web_standard_check"
_WEB_CONFIRMED_BY = "Web check, confirmed by "
#: Honesty audit entry 70: an unconfirmed kind C/D item left "Comment By"
#: BLANK - not "not mentioned", not a status, just absent, on a row that the
#: sheet otherwise clearly attributes to the AI (the "AI Review Comments"
#: column holds its text). A blank byline reads as an oversight, not as "not
#: yet confirmed"; these say so.
_AI_UNCONFIRMED_BY = "AI - engineer to confirm"
_WEB_UNCONFIRMED_BY = "Web check - engineer to confirm"

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


def _rejected(finding: dict) -> bool:
    """Owner order section 3: an engineer rejected this comment - it is left
    off the sheet. The finding and the rejection both stay on record."""
    return finding.get("approval_status") == "rejected"


def _edited_by(finding: dict) -> str:
    who = finding.get("confirmed_by_name") or finding.get("confirmed_by") or "an engineer"
    return f"AI Review, edited and confirmed by {who}"


def _fold(text) -> str:
    return " ".join(str(text or "").lower().split())


def comment_key(*parts) -> str:
    """WHAT A CRS COMMENT IS ABOUT, as a stable key for its permanent number.

    Industry practice (CRS guides, document-control systems): a comment's ID
    is permanent, never reused, and follows the comment to the next revision.
    So the key is built from the comment's SUBJECT - the requirement, the
    datasheet field, the value the sheet states, the page - and never from
    the review run, a finding's database id, the row's position, who
    confirmed it, its status, or the wording template. A re-run of the same
    datasheet, a re-export, or an engineer re-wording the comment keeps the
    number; a different requirement or a different stated value is a
    different comment and gets a new one. Case and spacing are folded so a
    re-extraction that only changes whitespace does not renumber.
    """
    joined = "\x1f".join(_fold(p) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]


def _subject_key(f: dict) -> str:
    """`comment_key` for a finding paired against a requirement: the
    requirement's own words, the datasheet field, the stated value, the page,
    and whether it is a datasheet self-check."""
    return comment_key(
        "requirement",
        f.get("requirement_source_text") or f.get("finding"),
        f.get("crs_field_label") or f.get("matched_phrase") or f.get("contractor_section"),
        f.get("contractor_evidence_text"),
        f.get("contractor_page"),
        f.get("origin") == _DATASHEET_ORIGIN,
    )


#: The "Review notes" sheet (owner order 2f): the engineer's internal list.
NOTE_MISSING_STANDARD = "Standard not in your library - upload required"
NOTE_UNREAD_PAGES = "Pages not yet readable - engineer to check"
NOTE_PAGE_READER = "Value not found by the page reader - engineer to check the page"
NOTE_OTHER_DOCUMENT = "Requires another document"
#: CRS quick wins: a statement no datasheet field was found for. NOT "requires
#: another document" - the clause names no document (audit crs.md defect 5:
#: the note claimed 9, 2 were true).
NOTE_NO_FIELD = "No datasheet field found - engineer to check"
_NO_FIELD_MARKER = "no_field_matched"


def build_review_notes(findings: list[dict], missing_references: list[str],
                       unread_pages: list[int] | None = None) -> list[dict]:
    """The engineer's internal notes for one run - never a contractor comment.

    One row per cited standard not held; one row for the pages not read into
    fields; one for values the page reader did not find; and the requirements
    that name their own evidence (a certificate, procedure, drawing) GROUPED
    BY STANDARD with a count each, not one row per requirement (2e) - and,
    apart from them, the statements no datasheet field was found for, which
    name no document (quick wins; they were counted as the first kind). Every
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
                and (f.get("ai_rationale") or "").startswith(_REQUIRES_OTHER_DOCUMENT_MARKER)):
            name = str(f.get("standard_name") or f.get("standard_document_id") or "")
            by_standard[name] = by_standard.get(name, 0) + 1
    for name in sorted(by_standard):
        n = by_standard[name]
        notes.append({"note": NOTE_OTHER_DOCUMENT, "standard": name, "count": n,
                      "detail": (f"{n} of this run's requirements from {name or 'this standard'} "
                                 "name their own evidence - a certificate, procedure, "
                                 "drawing or other document - which is not this "
                                 "datasheet. Check each against the document it names.")})
    no_field: dict[str, int] = {}
    for f in findings:
        if (f.get("compliance_status") == _NOT_IN_DOCUMENT_SCOPE
                and (f.get("ai_rationale") or "").startswith(_NO_FIELD_MARKER)):
            standard = str(f.get("standard_name") or f.get("standard_document_id") or "")
            no_field[standard] = no_field.get(standard, 0) + 1
    for name in sorted(no_field):
        n = no_field[name]
        notes.append({"note": NOTE_NO_FIELD, "standard": name, "count": n,
                      "detail": (f"{n} of this run's requirements from {name or 'this standard'} "
                                 "state no value, and no field read from this datasheet "
                                 "was found for them. They do not name another document; "
                                 "check each against the datasheet, or the document "
                                 "that governs it.")})
    return notes


def _std_short(name) -> str:
    """"SAES-D-901.pdf" -> "SAES-D-901": a reference, not a file name."""
    text = str(name or "").strip()
    return re.sub(r"\.(pdf|docx?|xlsx?)$", "", text, flags=re.IGNORECASE)


def _standard_reference(finding: dict) -> str:
    """The Standard Reference column: "SAES-D-901 cl. 4.3 (p.1)", or
    "Datasheet check DS-M1" for a kind B check. Its OWN column (quick wins):
    it used to ride in Page/Section as "SAES-D-901.pdf clause 4.3 p1 /
    submittal p1", where the contractor looks for THEIR page."""
    if finding.get("origin") == _DATASHEET_ORIGIN:
        m = re.match(r"(Datasheet check [A-Z]+-[A-Z0-9]+)",
                     finding.get("requirement_source_text") or finding.get("ai_rationale") or "")
        return m.group(1) if m else "Datasheet check"
    std = _std_short(finding.get("standard_name") or finding.get("standard_document_id"))
    if not std:
        return ""
    clause = finding.get("standard_clause")
    page = finding.get("standard_page")
    return std + (f" cl. {clause}" if clause else "") + (f" (p.{page})" if page else "")


def _field_label(finding: dict) -> str:
    """What the DATASHEET calls the field, as it printed it, else the phrase
    the pairing matched, else the datasheet check's field."""
    label = (finding.get("crs_field_label") or finding.get("contractor_section")
             if finding.get("origin") == _DATASHEET_ORIGIN
             else finding.get("crs_field_label") or finding.get("matched_phrase"))
    if not label and not (finding.get("fact_id") or finding.get("contractor_page")):
        # NOT FOUND ON THE SHEET: the clause's own subject names the field,
        # when it is a clean noun phrase.
        subject = " ".join(str((finding.get("requirement_limit") or {}).get("subject")
                               or "").split())
        if subject and len(subject) <= 70 and " shall " not in f" {subject.lower()} ":
            label = subject
    label = " ".join(str(label or "").split())
    if label and label.isupper() and len(label) > 5:
        # "CORROSION ALLOWANCE" reads as "Corrosion allowance"; an acronym
        # the sheet printed as its whole label ("PWHT", "MAWP") stays one.
        label = label.capitalize()
    elif label and label.islower():
        label = label[0].upper() + label[1:]
    return label


def _items(group: list[dict]) -> list[str]:
    """The equipment tags (or nozzle marks) a grouped row is about, in order."""
    seen: list[str] = []
    for f in group:
        tag = f.get("equipment_tag")
        if tag and tag not in seen:
            seen.append(str(tag))
    return seen


def _page_section(group: list[dict]) -> str:
    """The DATASHEET's page and field: "p.1 - Corrosion allowance (V-2001)".
    Never the standard's file name - that is the Standard Reference column."""
    f = group[0]
    pages = sorted({g.get("contractor_page") for g in group if g.get("contractor_page")})
    field = _field_label(f)
    tags = _items(group)
    where = (f"p.{_page_list(pages)}" if pages else "")
    if field:
        where = f"{where} - {field}" if where else field
    if tags:
        where += f" ({', '.join(tags)})"
    # The chunk's section heading is NOT printed here: on a ruled form it is
    # routinely another cell's text ("3.5 RATED POWER" on the audit's pump
    # sheet), and the page + field + tag already say where the value is.
    return where


_OP_WORDS = {">=": "not less than", "<=": "not more than", ">": "more than",
             "<": "less than", "=": "equal to", "==": "equal to"}


def _clause_sentence(finding: dict, limit: int = 220) -> str:
    """The clause's own words, without its leading clause number, cut short
    with "..." rather than pasted whole."""
    text = " ".join(str(finding.get("requirement_source_text")
                        or finding.get("requirement") or "").split())
    clause = str(finding.get("standard_clause") or "")
    if clause and text.startswith(clause + " "):
        text = text[len(clause) + 1:]
    text = text.rstrip(".")
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + " ..."
    return text


def _requirement_words(finding: dict) -> str:
    """"requires <subject> not less than 3 mm" - ONLY for a verdict the
    arithmetic made (COMPLIANT / NON_COMPLIANT), where the parsed limit is the
    one that was compared. Everywhere else the clause's own sentence is
    quoted: a blank field or an engineer's question must not restate a limit
    the parser may have got wrong ("30 %" read from "30 % of rated flow")."""
    limit = finding.get("requirement_limit") or {}
    subject = " ".join(str(limit.get("subject") or "").split())
    clean_subject = subject and len(subject) <= 70 and " shall " not in f" {subject.lower()} "
    if (limit.get("operator") in _OP_WORDS and limit.get("raw_value") not in (None, "")
            and clean_subject
            and finding.get("compliance_status") in ("NON_COMPLIANT", "COMPLIANT")):
        unit = f" {limit['raw_unit']}" if limit.get("raw_unit") else ""
        return (f"requires {subject[0].lower() + subject[1:]} "
                f"{_OP_WORDS[limit['operator']]} {limit['raw_value']}{unit}.")
    sentence = _clause_sentence(finding)
    return f"\"{sentence}.\"" if sentence else "states a requirement."


def _provided(finding: dict) -> str:
    """What the datasheet says, in its own words."""
    value = " ".join(str(finding.get("contractor_evidence_text") or "").split())
    blank = finding.get("crs_is_blank")
    if blank or (finding.get("ai_rationale") or "").startswith(
            "the submittal leaves this field to be provided"):
        return f"is left to be provided ('{value}')" if value else "is left blank"
    return f"states {value}" if value else "states no readable value"


def _reason_words(finding: dict) -> str:
    """An engineer-review reason without its machine code: "unit_mismatch:
    the requirement is in ..." -> "the requirement is in ..."."""
    text = " ".join(str(finding.get("ai_rationale") or "").split())
    return re.sub(r"^[a-z_]+:\s*", "", text)


def _action(finding: dict, field: str) -> str:
    status = finding.get("compliance_status")
    what = field or "the value"
    if status == "NON_COMPLIANT":
        return (f"Contractor to revise {what} to meet the requirement, or submit a "
                "deviation request with justification for Company approval.")
    if status == _MISSING_INFORMATION:
        if finding.get("fact_id") or finding.get("contractor_page"):
            return f"Contractor to provide {what}."
        return f"Contractor to state {what} on the datasheet."
    return f"Engineer to check: {_reason_words(finding).rstrip('.')}."


def engineer_comment_text(group: list[dict]) -> str:
    """THE COMMENT, IN AN ENGINEER'S VOICE (CRS quick wins, audit crs.md
    defect 8):

        <Standard> cl. <clause>: requires <required>. Datasheet <page/field>
        states <provided | blank>. Contractor to <action>.

    It replaced a log line ("Requirement: <whole clause> / Submitted: 1.5 mm /
    the submitted value 1.5 mm is outside the required >= 3 mm / Equipment:
    V-2001") that pasted the clause, printed operator symbols and machine
    reason codes, and never said what the contractor should do. Every
    number in it is one already on the finding - nothing is re-derived.
    """
    f = group[0]
    refs = list(dict.fromkeys(r for r in (_standard_reference(g) for g in group) if r))
    ref = "; ".join(refs) or "Requirement"
    field = _field_label(f)
    tags = _items(group)
    where = " ".join(p for p in (
        f"p.{f['contractor_page']}," if f.get("contractor_page") else "",
        field or "", f"({', '.join(tags)})" if tags else "") if p)
    lead = f"{ref}: {_requirement_words(f)}"
    if not (f.get("fact_id") or f.get("contractor_page")):
        # NOT FOUND IS NOT "NOT STATED" (honesty audit 50): what is known is
        # that no field READ from the sheet answered it, with the pages that
        # were read - never that the document is silent.
        checked = (f.get("ai_rationale") or "").partition("; ")[2].strip().rstrip(".")
        said = ("Not answered by any field read from the datasheet"
                + (f" ({checked})" if checked else "") + ".")
    else:
        said = f"Datasheet {where} {_provided(f)}." if where else f"The datasheet {_provided(f)}."
    return f"{lead} {said} {_action(f, field)}"


def _confirmed(finding: dict) -> bool:
    """Has an ENGINEER confirmed this comment? (the issue copy's gate)"""
    return bool(finding.get("confirmed_by") or finding.get("engineer_comment")
                or finding.get("approval_status") == "accepted"
                or finding.get("origin") == "chat")


def _group_key(f: dict) -> tuple:
    """ONE ROW PER FIELD ISSUE: the same requirement wording, the same
    status, the same datasheet field (by its printed label) and the same
    printed value - whichever tags carry it and whichever standards state it.
    An engineer's own wording is theirs for THAT finding, never merged."""
    text = _fold(f.get("requirement_source_text"))
    if not text or f.get("engineer_comment"):
        return ("__unique__", f.get("id") or id(f))
    return (f.get("compliance_status"), text,
            _fold(f.get("crs_field_label") or f.get("matched_phrase") or f.get("contractor_section")),
            _fold(f.get("contractor_evidence_text")), f.get("contractor_page"),
            f.get("origin") == _DATASHEET_ORIGIN)


def _grouped(ordered: list[dict]) -> list[list[dict]]:
    groups: dict[tuple, list[dict]] = {}
    order: list[tuple] = []
    for f in ordered:
        key = _group_key(f)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(f)
    return [groups[k] for k in order]


def _by(group: list[dict]) -> str:
    f = group[0]
    if f.get("engineer_comment"):
        return _edited_by(f)
    if f.get("confirmed_by"):
        return f"AI Review, confirmed by {f.get('confirmed_by_name') or f['confirmed_by']}"
    return "AI Review"


def build_crs_rows(findings: list[dict], missing_references: list[str],
                   submittal_name: str,
                   unread_pages: list[int] | None = None) -> list[dict]:
    """The CRS rows for one run - ONE ROW PER FIELD ISSUE.

    CRS QUICK WINS (2026-09-27, audit crs.md defects 2, 8, 9):

      * EVERY MISSING / BLANK / "VENDOR TO ADVISE" VALUE IS ITS OWN ROW. The
        one summary row ("4 requirements ... were not answered ... not
        itemized here") hid a vibration breach, a hydrotest shortfall and a
        nozzle-size breach on the audit's planted-defect sheets. A value the
        sheet leaves blank is the most common comment a reviewing engineer
        writes; it is one row per field, the tags that share it listed on it.
      * THE COMMENT IS AN ENGINEER'S (`engineer_comment_text`); Page/Section
        is the DATASHEET's page and field; the standard and clause sit in
        their own column (`standard_reference`).
      * EVERY ROW SAYS WHETHER AN ENGINEER HAS CONFIRMED IT
        (`engineer_confirmed`), which is all the issue-to-contractor copy
        carries - `crs_export` drops the rest there, so an AI draft or an
        internal question never leaves the building.

    Order: breaches, then values left blank, then values not found, then
    datasheet self-checks, then the engineer's open questions, then the
    engineer's own chat comments, then AI/web check items.

    Never rows: rejected findings; UNREAD_PAGES and PAGE_READER_ONLY
    questions and NOT_IN_DOCUMENT_SCOPE (all Review notes, B3/2f); a
    COMPLIANT result.
    """
    rows: list[dict] = []
    findings = [f for f in findings if not _rejected(f)]
    standard = [f for f in findings
                if f.get("origin") not in (_DATASHEET_ORIGIN, _AI_ORIGIN, _WEB_ORIGIN, "chat")]
    status = lambda f: f.get("compliance_status")  # noqa: E731
    paired = lambda f: bool(f.get("fact_id") or f.get("contractor_page"))  # noqa: E731
    breaches = [f for f in standard if status(f) == "NON_COMPLIANT"]
    blanks = [f for f in standard if status(f) == _MISSING_INFORMATION and paired(f)]
    not_found = [f for f in standard if status(f) == _MISSING_INFORMATION and not paired(f)]
    questions = [f for f in standard if status(f) == "NEEDS_ENGINEER_REVIEW"
                 and not _unread(f) and not _page_reader_only(f)]
    # A datasheet check about a field a standard's row already names (the
    # same fact) is that row, not a second one.
    covered = {f.get("fact_id") for f in breaches + blanks if f.get("fact_id")}
    checks = [f for f in findings if f.get("origin") == _DATASHEET_ORIGIN
              and status(f) in ("NON_COMPLIANT", _MISSING_INFORMATION)
              and not (f.get("fact_id") and f.get("fact_id") in covered)]
    for kind, bucket in ((ROW_KIND_NON_COMPLIANT, breaches),
                         (ROW_KIND_MISSING_INFORMATION, blanks),
                         (ROW_KIND_MISSING_INFORMATION, not_found),
                         (ROW_KIND_DATASHEET_CHECK, checks),
                         (ROW_KIND_NEEDS_ENGINEER_REVIEW, questions)):
        for group in _grouped(bucket):
            f = group[0]
            if kind == ROW_KIND_DATASHEET_CHECK:
                text = f.get("engineer_comment") or " ".join(p for p in (
                    f.get("finding"), f.get("required_action")) if p)
            else:
                text = f.get("engineer_comment") or engineer_comment_text(group)
            rows.append({
                # THE FINDING'S OWN STORED ID, carried so `crs_export` can mint
                # a per-row reference that survives a re-export; never printed.
                "finding_id": f.get("id") or "",
                "document_name": submittal_name,
                "page_section": _page_section(group),
                "comment": text,
                "comment_by": _by(group),
                "standard_reference": "; ".join(dict.fromkeys(
                    r for r in (_standard_reference(g) for g in group) if r)),
                "row_kind": kind,
                "engineer_confirmed": all(_confirmed(g) for g in group),
                # Never printed: what the permanent CRS number is keyed on.
                "comment_key": _subject_key(f),
            })

    # An engineer's own comments, filed from chat: individual comments to the
    # contractor, the engineer's rather than the machine's.
    for f in findings:
        if f.get("origin") != "chat":
            continue
        rows.append({
            "finding_id": f.get("id") or "",
            "document_name": submittal_name,
            "page_section": "",
            "comment": f.get("engineer_comment") or f.get("finding") or "",
            "comment_by": f"{f.get('confirmed_by') or 'Engineer'} (filed from chat)",
            "standard_reference": "",
            "row_kind": ROW_KIND_ENGINEER_COMMENT,
            "engineer_confirmed": True,
            # An engineer's own free-text comment IS its subject.
            "comment_key": comment_key(
                "chat", f.get("engineer_comment") or f.get("finding"),
                f.get("contractor_page"), f.get("contractor_section")),
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
        # The datasheet's page and field, in the shape every row uses.
        where = " - ".join(p for p in (
            f"p.{f['contractor_page']}" if f.get("contractor_page") else "",
            f.get("contractor_section") or "") if p)
        confirmed = bool(f.get("confirmed_by"))
        confirmed_by_prefix = _AI_CONFIRMED_BY if origin == _AI_ORIGIN else _WEB_CONFIRMED_BY
        # Owner order group HONESTY (2026-09-27): unconfirmed is a state, not
        # an absence - "Comment By" says whose draft it is even before an
        # engineer confirms it, never blank.
        unconfirmed_by = _AI_UNCONFIRMED_BY if origin == _AI_ORIGIN else _WEB_UNCONFIRMED_BY
        row_kind = ROW_KIND_AI_ENGINEERING_CHECK if origin == _AI_ORIGIN else ROW_KIND_WEB_STANDARD_CHECK
        rows.append({
            "finding_id": f.get("id") or "",
            "document_name": submittal_name,
            "page_section": where,
            "comment": text if confirmed else "",
            "comment_by": (f"{confirmed_by_prefix}{f.get('confirmed_by_name') or f['confirmed_by']}"
                           if confirmed else unconfirmed_by),
            "ai_review_comment": "" if confirmed else text,
            "standard_reference": relates if origin == _AI_ORIGIN and not f.get("engineer_comment") else "",
            "row_kind": row_kind,
            "engineer_confirmed": confirmed,
            # The machine's finding text, not the engineer's edit of it, so
            # confirming or re-wording an AI/web item keeps its number.
            "comment_key": comment_key(
                origin, f.get("finding"), f.get("required_action"),
                f.get("contractor_page"), f.get("contractor_section")),
        })

    # OWNER ORDER 2f: THE INTERNAL NOTES LEFT THIS SHEET. Requirements that
    # need another document, pages not yet read, values the page reader did
    # not find, and cited standards not in the library are the ENGINEER'S
    # to-do list - the "Review notes" sheet (`build_review_notes`), which the
    # contractor's copy does not carry.
    return rows
