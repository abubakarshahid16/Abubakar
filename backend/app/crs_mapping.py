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

from . import standard_ids

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
#: #754 F5b: a standard that APPLIES to this submittal (its equipment type or
#: a service condition it declares) and that the contractor did not
#: reference - ONE row per standard, never one per requirement.
ROW_KIND_STANDARD_NOT_CITED = "standard_not_cited"
#: #754 F5b: a standard the contractor cites that does not appear to apply
#: (it governs another equipment type, or a service the sheet declares absent).
ROW_KIND_STANDARD_NOT_APPLICABLE = "standard_not_applicable"
#: An Open comment from an earlier run or revision of this submittal that the
#: current run no longer raises. Industry practice carries it forward until a
#: reviewer closes it (`crs_numbers.open_elsewhere`); never dropped silently.
ROW_KIND_CARRIED_FORWARD = "carried_forward"
#: rule_trust (#947 step 8): a COMPLIANT verdict from a SAFETY-tier rule used
#: automatically, shown for an ENGINEER'S TICK - the clause, the value read
#: and where. Internal copy only; never a comment to the contractor (there is
#: nothing to ask), and the sheet is not issued until it is ticked.
ROW_KIND_SAFETY_TICK = "safety_tick"
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


_LEGACY_MARKERS = (_REQUIRES_OTHER_DOCUMENT_MARKER, _UNREAD_PAGES_MARKER, _PAGE_READER_ONLY_MARKER)


def _reason(finding: dict) -> str | None:
    """WHY the finding is what it is, as the CODE the review stored (#921).
    A row written before the column existed has none (NULL); for those, the
    leading words of the rationale are read, here and nowhere else. A row
    written after it has the code by construction, so the words add nothing."""
    code = finding.get("reason_code")
    if code:
        return str(code)
    text = finding.get("ai_rationale") or ""
    for marker in (*_LEGACY_MARKERS, _NO_FIELD_MARKER, _CONDITION_NOT_MET_MARKER):
        if text.startswith(marker):
            return marker
    return None


def _unread(finding: dict) -> bool:
    return (finding.get("compliance_status") == "NEEDS_ENGINEER_REVIEW"
            and _reason(finding) == _UNREAD_PAGES_MARKER)


def _page_reader_only(finding: dict) -> bool:
    return (finding.get("compliance_status") == "NEEDS_ENGINEER_REVIEW"
            and _reason(finding) == _PAGE_READER_ONLY_MARKER)


def _ai_relates_to(finding: dict) -> str:
    """The standard NAME an AI item relates to, as `ai_engineering_check`
    stored it on the rationale ("... Relates to: <name>.")."""
    text = finding.get("ai_rationale") or ""
    name = text.split("Relates to: ", 1)[1].rstrip(".") if "Relates to: " in text else ""
    return "" if name == "no standard named" else name


def _ai_unverified(finding: dict) -> bool:
    """W5b-11 (#559): an AI item resting on a standard the library does not
    hold (`ai_engineering_check.UNVERIFIED_LABEL` leads its rationale)."""
    from .ai_engineering_check import UNVERIFIED_LABEL
    return (finding.get("ai_rationale") or "").startswith(UNVERIFIED_LABEL)


def _rejected(finding: dict) -> bool:
    """Owner order section 3: an engineer rejected this comment - it is left
    off the sheet. The finding and the rejection both stay on record."""
    return finding.get("approval_status") == "rejected"


def finding_comment_key(f: dict) -> str:
    """The permanent-number key of the comment one finding makes - the same
    key `build_crs_rows` gives the row it leads. One home for all three
    shapes (a requirement comment, a chat comment, an AI/web check item)."""
    origin = f.get("origin")
    if origin == "chat":
        return comment_key(
            "chat", f.get("engineer_comment") or f.get("finding"),
            f.get("contractor_page"), f.get("contractor_section"))
    if origin in (_AI_ORIGIN, _WEB_ORIGIN):
        return comment_key(
            origin, f.get("finding"), f.get("required_action"),
            f.get("contractor_page"), f.get("contractor_section"))
    return _subject_key(f)


def rejected_comment_keys(findings: list[dict]) -> set[str]:
    """The comment keys of the findings an engineer rejected. A rejected
    comment is never issued: `main._crs_content` never carries these forward
    and `main._mint_crs_numbers` withdraws their numbers."""
    return {finding_comment_key(f) for f in findings if _rejected(f)}


def _finding_text(f: dict) -> str:
    return " ".join(p for p in (f.get("finding"), f.get("required_action")) if p)


#: The shapes a stored "Comment By" names one person in, as `_by`, the
#: AI/web rows and chat comments write them: (prefix, the person, suffix).
_BYLINE_SHAPES = (
    re.compile(r"^(AI Review, (?:edited and )?confirmed by )(?P<who>.+?)()$"),
    re.compile("^(" + re.escape(_AI_CONFIRMED_BY) + r")(?P<who>.+?)()$"),
    re.compile("^(" + re.escape(_WEB_CONFIRMED_BY) + r")(?P<who>.+?)()$"),
    re.compile(r"^()(?P<who>.+?)( \(filed from chat\))$"),
)


def byline_person(byline: str | None) -> str | None:
    """The person a stored "Comment By" names, or None when it names nobody
    ("AI Review", an unconfirmed draft's label)."""
    for shape in _BYLINE_SHAPES:
        match = shape.match(byline or "")
        if match:
            return match.group("who")
    return None


def resolve_byline(byline: str | None, names: dict[str, str]) -> str:
    """A stored "Comment By" with a raw user id replaced by that user's
    display name. Audit leftover 2026-09-30: carry-forward snapshots written
    before bylines printed names still say "confirmed by eng-1". Only an id
    that `names` maps to a non-empty display name is replaced - a name is
    never invented, and a byline that already names a person, or names an
    unknown one, is returned unchanged."""
    text = byline or ""
    for shape in _BYLINE_SHAPES:
        match = shape.match(text)
        if match:
            name = names.get(match.group("who"))
            if name:
                return f"{match.group(1)}{name}{match.group(3)}"
            return text
    return text


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
#: Review conditions (2026-09-30): a requirement the datasheet's own facts
#: put OUTSIDE its condition ("for pipes larger than 2 inch" against NPS 1).
#: NOT a contractor comment and NOT a breach - there is nothing for the
#: contractor to do - but never silently dropped either: the engineer sees
#: each one, with the condition and the value that excused it, and can
#: overrule it. One note per finding, because each has its own evidence.
NOTE_CONDITION_NOT_MET = "Not applicable - datasheet is outside the requirement's condition"
#: `comparison.CONDITION_NOT_MET`, as a literal for the reason given above.
_CONDITION_NOT_MET_MARKER = "condition_not_met"
_NOT_APPLICABLE = "NOT_APPLICABLE"


def build_review_notes(findings: list[dict], missing_references: list[str],
                       unread_pages: list[int] | None = None,
                       outcome: dict | None = None) -> list[dict]:
    """The engineer's internal notes for one run - never a contractor comment.

    One row per cited standard not held; one row for the pages not read into
    fields; one for values the page reader did not find; and the requirements
    that name their own evidence (a certificate, procedure, drawing) GROUPED
    BY STANDARD with a count each, not one row per requirement (2e) - and,
    apart from them, the statements no datasheet field was found for, which
    name no document (quick wins; they were counted as the first kind). Every
    count states its boundary: "of this run's requirements from <standard>".
    Last, one note per requirement found NOT APPLICABLE because the
    datasheet's own facts put it outside the requirement's condition, quoting
    the condition and the value (and page) that decided it. Last of all,
    rule_trust (#947): the fields no rule checked and the spot-check sample,
    from the run's stored `outcome` (`rule_trust.review_notes`).
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
                and _reason(f) == _REQUIRES_OTHER_DOCUMENT_MARKER):
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
                and _reason(f) == _NO_FIELD_MARKER):
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
    for f in findings:
        if (f.get("compliance_status") == _NOT_APPLICABLE
                and _reason(f) == _CONDITION_NOT_MET_MARKER):
            ref = _standard_reference(f)
            notes.append({"note": NOTE_CONDITION_NOT_MET,
                          "standard": ref, "count": None,
                          "detail": (f"{_clause_sentence(f, 160)}. Not checked: "
                                     f"{_reason_words(f)}")})
    if outcome is not None:
        from .clause_coverage import outcome_notes
        notes.extend(outcome_notes(outcome, findings))
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
    # A-761b: a standard whose clause values are table numbers, not paragraph
    # ids (`standards.paragraph_ids_known`), never prints them as a clause.
    if clause and finding.get("clause_identified") is False:
        return std + " (paragraph not identified)" + (f" (p.{page})" if page else "")
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


#: R30: a finding's verdict in the words the reasoning line uses.
_RESULT_WORDS = {"COMPLIANT": "meets", "NON_COMPLIANT": "does not meet",
                 "MISSING_INFORMATION": "value not given", "NEEDS_ENGINEER_REVIEW": "engineer to check",
                 "NOT_IN_DOCUMENT_SCOPE": "needs another document", "NOT_APPLICABLE": "does not apply"}


def reasoning_text(group: list[dict]) -> str:
    """R30 (#763): the chain behind a CRS row, for the INTERNAL copy only -
    per finding it groups: the value read and its page, the clause, the
    result, and the code's own why (a calculation's inputs and numbers
    included). Only what the findings STORED, never re-worded or guessed: a
    value not read says so, a missing clause or result prints nothing."""
    lines = []
    for f in group:
        bits = []
        field = str(f.get("contractor_section") or "").strip()
        value = str(f.get("contractor_evidence_text") or "").strip()
        page = f.get("contractor_page")
        if field or value:
            bits.append(f"Read: {field or 'value'}" + (f" = {value}" if value else " (no value read)")
                        + (f" (p.{page})" if page else ""))
        reference = _standard_reference(f)
        if reference:
            bits.append(f"Clause: {reference}")
        status = f.get("compliance_status")
        if status:
            bits.append(f"Result: {_RESULT_WORDS.get(status, status)}")
        why = str(f.get("ai_rationale") or "").strip()
        if why:
            bits.append(f"Why: {why}")
        if bits:
            lines.append(". ".join(bits))
    return "\n".join(dict.fromkeys(lines))


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
    the requirement is in ..." -> "the requirement is in ...", and
    "LOW_TRUST_VALUE: the value was read ..." -> "the value was read ..."."""
    text = " ".join(str(finding.get("ai_rationale") or "").split())
    return re.sub(r"^(?:[a-z_]+|[A-Z][A-Z_]+):\s*", "", text)


def _action(finding: dict, field: str) -> str:
    status = finding.get("compliance_status")
    what = field or "the value"
    if status == "NON_COMPLIANT":
        return (f"Contractor to revise {what} to meet the requirement, or submit a "
                "deviation request with justification for Company approval.")
    if status == _MISSING_INFORMATION:
        if finding.get("fact_id") or finding.get("contractor_page"):
            return f"Contractor to provide {what}."
        # #725 F7: NOT PAIRED IS THE SYSTEM'S MISS UNTIL AN ENGINEER SAYS
        # OTHERWISE. No field read from the sheet answered it; the sheet may
        # state it under another name. Never "Contractor to state" here.
        return (f"Engineer to check whether the datasheet states {what}: no field this "
                "system read was paired with it.")
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
    pages = sorted({g.get("contractor_page") for g in group if g.get("contractor_page")})
    where = " ".join(p for p in (
        f"p.{_page_list(pages)}," if pages else "",
        field or "", f"({', '.join(tags)})" if tags else "") if p)
    lead = f"{ref}: {_requirement_words(f)}"
    if not (f.get("fact_id") or f.get("contractor_page")):
        # NOT FOUND IS NOT "NOT STATED" (honesty audit 50): what is known is
        # that no field READ from the sheet answered it, with the pages that
        # were read - never that the document is silent.
        checked = (f.get("ai_rationale") or "").partition("; ")[2].strip().rstrip(".")
        said = ("Not answered by any field read from the datasheet"
                + (f" ({checked})" if checked else "") + ".")
    elif len({(_provided(g), g.get("contractor_page")) for g in group}) > 1:
        # #725 F7: the tags in one row say different things - each tag's own
        # value and page, never the first tag's value printed for all.
        per_tag = "; ".join(
            f"{g.get('equipment_tag') or 'untagged'} {_provided(g)}"
            + (f" (p.{g['contractor_page']})" if g.get("contractor_page") else "")
            for g in group)
        said = f"Datasheet {field or 'value'}: {per_tag}."
    else:
        said = f"Datasheet {where} {_provided(f)}." if where else f"The datasheet {_provided(f)}."
    return f"{lead} {said} {_action(f, field)}"


def trust_words(finding: dict) -> str:
    """rule_trust (#947): the label's words for the CRS ("engineer-approved
    rule", "automatic (proven rule)", ...), from the ONE table in
    `rule_trust.TRUST_WORDS`. "" on a finding the run did not label."""
    label = finding.get("trust_label")
    if not label:
        return ""
    from .rule_trust import TRUST_WORDS
    return TRUST_WORDS.get(label, str(label))


def safety_tick_text(f: dict) -> str:
    """The safety-tick row's text: what the rule required, what the sheet
    states and where, and that the automatic result was "meets" - for the
    engineer to read against the page and tick. Every value is one already
    on the finding; nothing is re-derived."""
    ref = _standard_reference(f) or "Requirement"
    value = str(f.get("contractor_evidence_text") or "").strip()
    page = f.get("contractor_page")
    field = _field_label(f) or str(f.get("contractor_section") or "").strip()
    where = " ".join(p for p in (f"p.{page}," if page else "", field) if p)
    said = (f"Datasheet {where} states {value}." if where and value
            else f"Datasheet states {value}." if value else "")
    return " ".join(p for p in (
        f"ENGINEER TO TICK (safety field): {ref}: {_requirement_words(f)}.", said,
        f"Automatic result: meets the standard ({trust_words(f) or 'automatic rule'}). "
        "Read the clause and the value on the page and tick, or say what is off.") if p)


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
    # #725 F7: ONE ROW PER PROBLEM. The printed value and the page are NOT in
    # the key: the same requirement on the same field with the same outcome is
    # one comment listing every tag (and each tag's own value and page when
    # they differ), not one row per tag.
    return (f.get("compliance_status"), text,
            _fold(f.get("crs_field_label") or f.get("matched_phrase") or f.get("contractor_section")),
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
    # A CONFIRMED FINDING LEADS ITS GROUP. A re-run keeps the engineer's
    # confirmed finding and writes a fresh machine proposal about the same
    # field beside it; both land in one row, and the row's "Comment By" and
    # text come from group[0]. The findings arrive `ORDER BY updated_at DESC`,
    # so the NEWER draft led and the row read "AI Review" - under the
    # engineer's permanent number - on every re-run done a second or more
    # after the confirmation (honesty audit entry 81). Stable sort: otherwise
    # the order the caller gave is kept.
    #
    # #725 F7: AND THE LEADER IS THE SAME ON EVERY RUN. A group now holds every
    # tag's finding, and the row's permanent number is keyed on its leader, so
    # the leader cannot depend on update order: confirmed first, then the
    # lowest page, tag and value.
    return [sorted(groups[k], key=_leader_order) for k in order]


def _leader_order(f: dict) -> tuple:
    page = f.get("contractor_page")
    return (not f.get("confirmed_by"), page if isinstance(page, int) else 10 ** 9,
            str(f.get("equipment_tag") or ""), _fold(f.get("contractor_evidence_text")))


#: Worst first. A row carries the worst severity of the findings it groups.
SEVERITY_ORDER = ("critical", "major", "minor", "observation")


def row_severity(group: list[dict]) -> str:
    """The worst severity in the group; "" when none is recorded."""
    found = {str(g.get("severity") or "").lower() for g in group}
    return next((s for s in SEVERITY_ORDER if s in found), "")


# --------------------------------------------------------------------------
# ORDER 139 PART 2 - one comment per datasheet field, a real order, no empty
# COMPANY Comments. CONTRACT STUBS (architect, docs/order-139-part2-spec.md).
# Builder A fills in the bodies; Builder B (crs_export, main, run_summary)
# and Builder C (the screen, through the run summary) code against these
# names and shapes now. Nothing calls the NotImplementedError stubs yet.
# --------------------------------------------------------------------------

#: What a finding is on the sheet, before grouping (spec section a). One
#: bucket per row-producing branch of `build_crs_rows`; None = not a row.
BUCKET_BREACH = "breach"          # NON_COMPLIANT against a standard
BUCKET_BLANK = "blank"            # MISSING_INFORMATION, paired with a field
BUCKET_NOT_FOUND = "not_found"    # MISSING_INFORMATION, no field paired
BUCKET_CHECK = "check"            # a datasheet self-check (kind B)
BUCKET_QUESTION = "question"      # NEEDS_ENGINEER_REVIEW (not a page note)
BUCKET_TICK = "tick"              # a safety-tier "meets" for an engineer's tick
BUCKET_CHAT = "chat"              # an engineer's comment filed from chat
BUCKET_AI = "ai"                  # an AI engineering check item (kind C)
BUCKET_WEB = "web"                # a public-web standards check item (kind D)
#: The buckets grouped ONE ROW PER DATASHEET FIELD (spec a). A finding of
#: these buckets with no field label keeps today's one-row-per-requirement key.
FIELD_GROUPED_BUCKETS = (BUCKET_BLANK, BUCKET_NOT_FOUND, BUCKET_QUESTION)

#: The rank of a CRS row, most important first (spec f). The sheet is sorted
#: by it, then datasheet page, then clause, then field - on screen and in the
#: file. `priority` (int) rides on every row; the words are printed in the
#: "Priority" column (it replaces the "Severity" column, which said "minor"
#: on 324 of 329 rows). Never "high"/"low": a rank is not a confidence.
PRIORITY_OUT_OF_LIMIT = 1
PRIORITY_MISSING_VALUE = 2
PRIORITY_ENGINEER_TO_CHECK = 3
PRIORITY_ENGINEERS_COMMENT = 4
PRIORITY_CARRIED_FORWARD = 5
PRIORITY_WORDS = {
    PRIORITY_OUT_OF_LIMIT: "Out of limit",
    PRIORITY_MISSING_VALUE: "Missing value",
    PRIORITY_ENGINEER_TO_CHECK: "Engineer to check",
    PRIORITY_ENGINEERS_COMMENT: "Engineer's comment",
    PRIORITY_CARRIED_FORWARD: "Carried forward",
}
#: The contractor's copy: a rank-3 row reaches it only once an engineer made
#: it theirs, and to the contractor it is a request to clarify, not an
#: internal to-do. Every other word is the same.
ISSUE_PRIORITY_WORDS = {**PRIORITY_WORDS, PRIORITY_ENGINEER_TO_CHECK: "Clarification"}

#: Spec e: COMPANY Comments of an UNCONFIRMED AI / web item. Plain words that
#: the row is a suggestion awaiting an engineer - never the draft itself,
#: which stays in "AI Review Comments" (owner order 2d/2f).
AI_UNCONFIRMED_COMMENT = ("AI suggestion awaiting an engineer's decision - its words are in "
                          "AI Review Comments. Not issued to the contractor until an engineer "
                          "confirms it.")
WEB_UNCONFIRMED_COMMENT = ("Web standards check suggestion awaiting an engineer's decision - its "
                           "words are in AI Review Comments. Not issued to the contractor until "
                           "an engineer confirms it.")

#: Spec c: a grouped row lists at most this many supporting clauses, then
#: "- and K more of these N (see Standard Reference)."
MAX_CLAUSE_LINES = 10
#: Spec c: each listed clause's own words are cut to this many characters.
CLAUSE_LINE_CHARS = 160


def priority_word(priority: int | None, copy: str = "internal") -> str:
    """The Priority column's word for a rank, in the words of the copy
    ("internal" or "issue"). "" for a row with no rank (a caller from before
    ranks existed) - never a guessed word."""
    words = ISSUE_PRIORITY_WORDS if copy == "issue" else PRIORITY_WORDS
    return words.get(priority, "") if isinstance(priority, int) else ""


def crs_bucket(finding: dict) -> str | None:
    """Which row-producing branch of `build_crs_rows` this ONE finding takes
    (a BUCKET_* constant), or None when it is never a row (rejected, a page
    note, NOT_IN_DOCUMENT_SCOPE, NOT_APPLICABLE, a plain COMPLIANT). Per
    finding only: the list-level rule (a datasheet check whose fact a breach
    or blank row already names is not a row) is `crs_groups`'s."""
    raise NotImplementedError("order 139 part 2: Builder A")


def crs_group_key(finding: dict) -> str | None:
    """The BASE grouping key of one finding (spec a), or None when it is not
    a row. Field-grouped buckets with a field label:
    "field:" + field_comment_key(bucket, label). Every other row-producing
    finding: "req:" + a digest of today's `_group_key` parts (bucket
    included), or "one:<finding id>" for a finding that is its own row (no
    requirement text, a safety tick, chat, AI, web). `crs_groups` may add an
    ":e<digest>" suffix when the findings of one base group carry different
    engineer wordings."""
    raise NotImplementedError("order 139 part 2: Builder A")


def field_comment_key(bucket: str, label: str) -> str:
    """Spec d: the PERMANENT-NUMBER key of a field-grouped row -
    `comment_key("field group", bucket, label)`. The field and what kind of
    row it is, never which clauses happen to raise it, which tags, or the
    leader: a re-run that adds or drops a clause keeps the number."""
    raise NotImplementedError("order 139 part 2: Builder A")


def finding_member_key(finding: dict) -> str:
    """Spec d: the per-requirement key a finding's comment had BEFORE order
    139 part 2 (`_subject_key`) - what an earlier per-clause row's number is
    stored under. A grouped row carries its findings' member keys
    (`member_keys`) so `main._crs_content` can find numbers an engineer
    already confirmed on the old per-clause rows."""
    return _subject_key(finding)


def row_priority(kind: str, compliance_status: str | None = None) -> int:
    """Spec f: the rank of a row from what it is. `kind` is a BUCKET_*
    constant for a finding row (a blank and a not-found share a row_kind but
    not a rank), or a ROW_KIND_* for a row with no finding
    (standard_not_cited 2, standard_not_applicable 3, carried_forward 5).
    `compliance_status` is read only for a datasheet check (NON_COMPLIANT 1,
    MISSING_INFORMATION 2, otherwise 3).

    A kind it does not know is refused (ValueError), never given a guessed
    rank; `ROW_KIND_MISSING_INFORMATION` is one of those on purpose - the
    caller must say whether the field was blank or not found."""
    if kind == BUCKET_CHECK:
        if compliance_status == "NON_COMPLIANT":
            return PRIORITY_OUT_OF_LIMIT
        if compliance_status == _MISSING_INFORMATION:
            return PRIORITY_MISSING_VALUE
        return PRIORITY_ENGINEER_TO_CHECK
    if kind not in _RANK_OF_KIND:
        raise ValueError(f"no CRS rank for row kind {kind!r}")
    return _RANK_OF_KIND[kind]


#: Spec f: the rank of every row kind that does not depend on its status. A
#: blank asks the contractor for a value (2); a value NOT FOUND is the
#: system's miss until an engineer says otherwise (honesty audit 50), so it
#: ranks with the engineer's questions (3), never with "missing value". An
#: engineer's chat comment is theirs - the system does not know how important
#: it is (4); a carried-forward row holds no kind to rank by (5).
_RANK_OF_KIND = {
    BUCKET_BREACH: PRIORITY_OUT_OF_LIMIT,
    ROW_KIND_NON_COMPLIANT: PRIORITY_OUT_OF_LIMIT,
    BUCKET_BLANK: PRIORITY_MISSING_VALUE,
    ROW_KIND_STANDARD_NOT_CITED: PRIORITY_MISSING_VALUE,
    BUCKET_NOT_FOUND: PRIORITY_ENGINEER_TO_CHECK,
    BUCKET_QUESTION: PRIORITY_ENGINEER_TO_CHECK,
    ROW_KIND_NEEDS_ENGINEER_REVIEW: PRIORITY_ENGINEER_TO_CHECK,
    BUCKET_TICK: PRIORITY_ENGINEER_TO_CHECK,
    BUCKET_AI: PRIORITY_ENGINEER_TO_CHECK,
    BUCKET_WEB: PRIORITY_ENGINEER_TO_CHECK,
    ROW_KIND_STANDARD_NOT_APPLICABLE: PRIORITY_ENGINEER_TO_CHECK,
    BUCKET_CHAT: PRIORITY_ENGINEERS_COMMENT,
    ROW_KIND_CARRIED_FORWARD: PRIORITY_CARRIED_FORWARD,
}


def finding_row_sort_key(priority: int, group: list[dict], key: str) -> tuple:
    """Spec f: where a FINDING row sits on the sheet - rank first, then the
    lowest datasheet page (none last), the leader's clause, the field as the
    row prints it, and the row's own key. Total: the order of two rows never
    depends on the rest of the list. `crs_groups` / the run summary order by
    the same key so the screen and the file cannot disagree."""
    return (priority, *_row_order(group), str(key or ""))


#: The finding loop's row kinds whose bucket is the kind itself (a
#: missing-information row is a blank or a not-found, read from the finding).
_FINDING_ROW_BUCKET = {
    ROW_KIND_NON_COMPLIANT: BUCKET_BREACH,
    ROW_KIND_DATASHEET_CHECK: BUCKET_CHECK,
    ROW_KIND_NEEDS_ENGINEER_REVIEW: BUCKET_QUESTION,
}


def _rank_row(row: dict, priority: int, group: list[dict]) -> tuple:
    """Spec f: put the finding row's rank on it; return its place on the sheet."""
    row["priority"] = priority
    return finding_row_sort_key(priority, group, row["comment_key"])


def standards_row_sort_key(priority: int, identifier: str, key: str) -> tuple:
    """Spec f: a required-vs-cited row (no finding, no page) sorts inside its
    rank after every finding row of that rank, by the standard's name."""
    return (priority, 10**9, (10**6,), _fold(identifier), str(key or ""))


def crs_groups(findings: list[dict]) -> list[dict]:
    """THE ONE GROUPING (spec a, b, f): the finding rows of the CRS, in sheet
    order. Each item: {"key": str (the row's group key, base + any edit
    suffix), "bucket": str, "row_kind": str, "priority": int, "findings":
    [finding dicts, leader first], "action": str | None (the row's first
    line when it lists two or more clauses, else None)}. `build_crs_rows`
    builds its finding rows from this, and the run summary sends each
    finding's key, rank, order and action to the screen from it - so the
    screen and the file cannot group or order differently."""
    raise NotImplementedError("order 139 part 2: Builder A")


def _clause_key(clause: object) -> tuple:
    return tuple(int(p) if p.isdigit() else 10 ** 6 for p in re.findall(r"\w+", str(clause or ""))) or (10 ** 6,)


def _row_order(group: list[dict]) -> tuple:
    """#725 F7: rows within a bucket by datasheet page, then clause."""
    pages = [g.get("contractor_page") for g in group if isinstance(g.get("contractor_page"), int)]
    return (min(pages) if pages else 10 ** 9, _clause_key(group[0].get("standard_clause")),
            _fold(_field_label(group[0])))


def _by(group: list[dict]) -> str:
    f = group[0]
    if f.get("engineer_comment"):
        who = f.get("confirmed_by_name") or f.get("confirmed_by") or "an engineer"
        return f"AI Review, edited and confirmed by {who}"
    if f.get("confirmed_by"):
        return f"AI Review, confirmed by {f.get('confirmed_by_name') or f['confirmed_by']}"
    return "AI Review"


def standards_check_rows(check: dict | None, submittal_name: str) -> list[dict]:
    """#754 F5b: the CRS rows of `applicability.standards_check` - one per
    required standard the contractor did not reference, one per cited
    standard that does not appear to apply. Machine drafts ("AI Review"),
    never confirmed here; a cited standard the library does not hold stays a
    Review note (`build_review_notes`), never a row and never met."""
    rows: list[dict] = []
    for r in (check or {}).get("required_not_cited") or []:
        ident = r["identifier"]
        rows.append({
            "finding_id": "", "document_name": submittal_name, "page_section": "",
            "comment": (f"Contractor did not reference {ident}; confirm compliance with "
                        f"{ident} (required because {r['reason']})."),
            "comment_by": "AI Review", "standard_reference": ident,
            "row_kind": ROW_KIND_STANDARD_NOT_CITED, "severity": "",
            "engineer_confirmed": False,
            "comment_key": comment_key("standard not cited", standard_ids.key(ident)),
        })
    for r in (check or {}).get("cited_not_applicable") or []:
        ident = r["identifier"]
        rows.append({
            "finding_id": "", "document_name": submittal_name, "page_section": "",
            "comment": (f"{ident} is cited but does not appear to apply ({r['reason']}); "
                        "confirm."),
            "comment_by": "AI Review", "standard_reference": ident,
            "row_kind": ROW_KIND_STANDARD_NOT_APPLICABLE, "severity": "",
            "engineer_confirmed": False,
            "comment_key": comment_key("standard not applicable", standard_ids.key(ident)),
        })
    # Order 139 part 2 (spec f): not referenced 2, not applicable 3.
    for row in rows:
        row["priority"] = row_priority(row["row_kind"])
    return rows


def build_crs_rows(findings: list[dict], missing_references: list[str],
                   submittal_name: str,
                   unread_pages: list[int] | None = None,
                   standards_check: dict | None = None) -> list[dict]:
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

    ORDER (order 139 part 2, spec f): BY RANK, most important first - out of
    limit (1), missing value (2), engineer to check (3), the engineer's own
    chat comments (4) - then by datasheet page, clause and field
    (`finding_row_sort_key`); the required-vs-cited rows sort inside their
    rank after its finding rows. Every row carries its `priority`; the
    Priority column prints its word. The kind of row no longer decides the
    order: a blank on p.1 comes before a datasheet check's missing value on
    p.3, both rank 2. Carried-forward rows (rank 5) are appended last by
    `main._crs_content`.

    Never rows: rejected findings; UNREAD_PAGES and PAGE_READER_ONLY
    questions and NOT_IN_DOCUMENT_SCOPE (all Review notes, B3/2f); a
    COMPLIANT result.
    """
    rows: list[dict] = []
    #: order 139 part 2: rows[i]'s place on the sheet (`finding_row_sort_key`)
    sort_keys: list[tuple] = []
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
              and (status(f) in ("NON_COMPLIANT", _MISSING_INFORMATION)
                   # rule_trust (#947): a check held because its rule is not
                   # proven is still a row - the engineer decides it.
                   or f.get("rule_said"))
              and not (f.get("fact_id") and f.get("fact_id") in covered)]
    for kind, bucket in ((ROW_KIND_NON_COMPLIANT, breaches),
                         (ROW_KIND_MISSING_INFORMATION, blanks),
                         (ROW_KIND_MISSING_INFORMATION, not_found),
                         (ROW_KIND_DATASHEET_CHECK, checks),
                         (ROW_KIND_NEEDS_ENGINEER_REVIEW, questions)):
        # Order 139 part 2: no per-bucket sort - the sheet's order is set
        # once, at the end, over every row kind (`finding_row_sort_key`).
        for group in _grouped(bucket):
            f = group[0]
            # Spec f: a blank and a not-found share `row_kind`, not a rank.
            rank_kind = _FINDING_ROW_BUCKET.get(kind) or (
                BUCKET_BLANK if paired(f) else BUCKET_NOT_FOUND
            )
            machine = _finding_text(f)  # 95 6b: kept as ai_comment
            if kind != ROW_KIND_DATASHEET_CHECK:
                machine = engineer_comment_text(group)
            text = f.get("engineer_comment") or machine
            rows.append({
                # THE FINDING'S OWN STORED ID, carried so `crs_export` can mint
                # a per-row reference that survives a re-export; never printed.
                "finding_id": f.get("id") or "",
                # #986: EVERY finding the row stands on. A decision on the row
                # is a decision on all of them; deciding only the first left
                # the row open with the next finding behind it.
                "finding_ids": [g["id"] for g in group if g.get("id")],
                "document_name": submittal_name,
                "page_section": _page_section(group),
                "comment": text,
                "ai_comment": machine,
                "edited": text.strip() != machine.strip(),
                "comment_by": _by(group),
                "standard_reference": "; ".join(dict.fromkeys(
                    r for r in (_standard_reference(g) for g in group) if r)),
                "row_kind": kind,
                "severity": row_severity(group),
                "engineer_confirmed": all(_confirmed(g) for g in group),
                # Never printed: what the permanent CRS number is keyed on.
                "comment_key": _subject_key(f),
                # R30: the chain behind the comment (internal copy only).
                "reasoning": reasoning_text(group),
                # rule_trust (#947): who stands behind the rule, in words.
                "rule_trust": trust_words(f),
            })
            rank = row_priority(rank_kind, f.get("compliance_status"))
            sort_keys.append(_rank_row(rows[-1], rank, group))

    # rule_trust (#947 step 8): SAFETY-TIER COMPLIANT, SHOWN FOR A TICK. The
    # rule decided "meets the standard" on its own; because the field is a
    # safety one, an engineer reads the clause and the value and ticks it
    # (the PF5 decision routes: accept = ticked, reject = something is off).
    # Internal copy only (`crs_export` drops the kind from the issue copy).
    for f in findings:
        if not f.get("show_for_engineer_tick") or status(f) != "COMPLIANT":
            continue
        rows.append({
            "finding_id": f.get("id") or "",
            "document_name": submittal_name,
            "page_section": _page_section([f]),
            "comment": safety_tick_text(f),
            "comment_by": _by([f]),
            "standard_reference": _standard_reference(f),
            "row_kind": ROW_KIND_SAFETY_TICK,
            "severity": "",
            "engineer_confirmed": _confirmed(f),
            "comment_key": comment_key("safety tick", _subject_key(f)),
            "reasoning": reasoning_text([f]),
            "rule_trust": trust_words(f),
        })
        sort_keys.append(_rank_row(rows[-1], row_priority(BUCKET_TICK), [f]))

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
            # The engineer's DISPLAY NAME, never their user id (audit
            # 2026-09-30); the id only when no name is on record.
            "comment_by": (f"{f.get('confirmed_by_name') or f.get('confirmed_by') or 'Engineer'}"
                           " (filed from chat)"),
            "standard_reference": "",
            "row_kind": ROW_KIND_ENGINEER_COMMENT,
            "severity": row_severity([f]),
            "engineer_confirmed": True,
            # An engineer's own free-text comment IS its subject.
            "comment_key": finding_comment_key(f),
        })
        sort_keys.append(_rank_row(rows[-1], row_priority(BUCKET_CHAT), [f]))

    # Owner order 2d/2f and 2d-2: AI engineering check (kind C) and public-web
    # standards check (kind D) items. Neither is ever a verdict - a question
    # for the contractor once an engineer has confirmed it, and until then a
    # draft in its own column that COMPANY Comments never holds.
    for f in findings:
        origin = f.get("origin")
        if origin not in (_AI_ORIGIN, _WEB_ORIGIN) or f.get("approval_status") == "rejected":
            continue
        text = f.get("engineer_comment") or _finding_text(f)
        if origin == _AI_ORIGIN:
            relates = _ai_relates_to(f)
            if relates and not f.get("engineer_comment"):
                text += f" (Relates to {relates}.)"
            # #559: from the model's memory of a standard not held. The label
            # stays on the row even once an engineer confirms raising it - the
            # source is still not held - unless the engineer rewrote it.
            if _ai_unverified(f) and not f.get("engineer_comment"):
                from .ai_engineering_check import UNVERIFIED_LABEL
                text = f"{UNVERIFIED_LABEL}. {text}"
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
        # Order 139 part 2 (spec e): COMPANY Comments is NEVER EMPTY. An
        # unconfirmed item's cell says, in plain words, that it is a suggestion
        # awaiting an engineer and where its words are - never the draft
        # itself, which stays in "AI Review Comments" (owner order 2d/2f).
        unconfirmed_comment = (
            AI_UNCONFIRMED_COMMENT if origin == _AI_ORIGIN else WEB_UNCONFIRMED_COMMENT
        )
        rows.append({
            "finding_id": f.get("id") or "",
            "document_name": submittal_name,
            "page_section": where,
            "comment": text if confirmed else unconfirmed_comment,
            "comment_by": (f"{confirmed_by_prefix}{f.get('confirmed_by_name') or f['confirmed_by']}"
                           if confirmed else unconfirmed_by),
            "ai_review_comment": "" if confirmed else text,
            "standard_reference": relates if origin == _AI_ORIGIN and not f.get("engineer_comment") else "",
            "row_kind": row_kind,
            "severity": row_severity([f]),
            "engineer_confirmed": confirmed,
            # The machine's finding text, not the engineer's edit of it, so
            # confirming or re-wording an AI/web item keeps its number.
            "comment_key": finding_comment_key(f),
            # R30: the chain behind the item (internal copy only).
            "reasoning": reasoning_text([f]),
        })
        rank = row_priority(BUCKET_AI if origin == _AI_ORIGIN else BUCKET_WEB)
        sort_keys.append(_rank_row(rows[-1], rank, [f]))

    # #754 F5b: the required-vs-cited result, one row per standard.
    rows.extend(standards_check_rows(standards_check, submittal_name))
    sort_keys.extend(
        standards_row_sort_key(r["priority"], r["standard_reference"], r["comment_key"])
        for r in rows[len(sort_keys) :]
    )

    # OWNER ORDER 2f: THE INTERNAL NOTES LEFT THIS SHEET. Requirements that
    # need another document, pages not yet read, values the page reader did
    # not find, and cited standards not in the library are the ENGINEER'S
    # to-do list - the "Review notes" sheet (`build_review_notes`), which the
    # contractor's copy does not carry.
    # Order 139 part 2 (spec f): THE SHEET'S ORDER IS ITS RANK. Every row
    # kind sorts on one key, so "out of limit" is never below 300 questions.
    return [rows[i] for i in sorted(range(len(rows)), key=sort_keys.__getitem__)]
