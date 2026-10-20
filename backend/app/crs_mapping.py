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
questions, and questions with no datasheet field or page behind them (#139),
stay off the sheet as Review notes (owner order 2f), each note
counting its own boundary. The comment is written in an engineer's voice
(`engineer_comment_text`), Page/Section is the DATASHEET's page and field,
the standard and clause ride in `standard_reference`, and every row carries
`engineer_confirmed` - the issue-to-contractor copy prints only those.
`row_kind` rides on every row (never printed) so `crs_export` can fill each
kind its own colour without re-deciding what the sheet says.
"""

import hashlib
import re

from . import (
    crs_ai_drafts,
    crs_blank_fields,
    crs_item_series,
    method_notes,
    severity_rule,
    standard_ids,
)

# isort: split
from . import paragraph_ids

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


_page_list = crs_blank_fields.page_list


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


def _no_datasheet_field(finding: dict) -> bool:
    """#139: a standard's question with NO datasheet field behind it - no
    value read and no datasheet page (a tie between fields, a pairing step that
    did not run). It is the standard's sentence, not a reading of the sheet,
    so it is the engineer's to-do (a Review note), never a CRS line - unless
    an engineer has confirmed it, which makes it their comment, or it is a
    verdict held for an unproven rule (`rule_said`, #947), which is the
    engineer's decision on that rule."""
    return (
        finding.get("compliance_status") == "NEEDS_ENGINEER_REVIEW"
        and finding.get("origin")
        not in (_DATASHEET_ORIGIN, _AI_ORIGIN, _WEB_ORIGIN, "chat")
        and not (finding.get("fact_id") or finding.get("contractor_page"))
        and not _unread(finding)
        and not _page_reader_only(finding)
        and not _confirmed(finding)
        and not finding.get("rule_said")
    )


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
    """The permanent-number key of the ROW one finding lands on - the same
    key `build_crs_rows` gives that row. One home for every shape (a
    requirement comment, a field-grouped row, a chat comment, an AI/web check
    item). Order 139 part 2: a finding of a field-grouped row returns the
    FIELD's key (`field_comment_key`), never its own clause's; the key its
    comment had before that is `finding_member_key`."""
    origin = f.get("origin")
    if f.get("crs_key"):
        return f["crs_key"]
    if origin == "chat":
        return comment_key(
            "chat", f.get("engineer_comment") or f.get("finding"),
            f.get("contractor_page"), f.get("contractor_section"))
    if origin in (_AI_ORIGIN, _WEB_ORIGIN):
        return comment_key(
            origin, f.get("finding"), f.get("required_action"),
            f.get("contractor_page"), f.get("contractor_section"))
    key = _group_key(f)
    if key[0] == "field":
        return field_comment_key(key[1], key[2])
    return comment_key(*key) if key[0] == "blanks" else _subject_key(f)


def rejected_comment_keys(findings: list[dict]) -> set[str]:
    """The comment keys of the findings an engineer rejected - the row key
    each lands on AND its own per-requirement key (`finding_member_key`,
    order 139 part 2), so a number an earlier per-clause row of it holds is
    withdrawn too. A rejected comment is never issued: `main._crs_content`
    never carries these forward and `main._mint_crs_numbers` withdraws their
    numbers (less any key a row still on the sheet holds)."""
    rejected = [f for f in findings if _rejected(f)]
    return {finding_comment_key(f) for f in rejected} | {
        finding_member_key(f) for f in rejected
    }


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
        crs_item_series.own_label(f) or f.get("matched_phrase") or f.get("contractor_section"),
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
#: #139: a requirement left for an engineer with no datasheet field behind it
#: (`_no_datasheet_field`). It was a CRS line with an empty Page/Section - a
#: standard's sentence printed as if it were a comment on the sheet.
NOTE_FIELD_NOT_IDENTIFIED = "Datasheet field not identified - engineer to check"
#: How many of a note's clause references are listed before "and N more".
_NOTE_REFERENCES = 6
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
    notes.extend(_field_not_identified_notes(findings))
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


def _field_not_identified_notes(findings: list[dict]) -> list[dict]:
    """#139: the questions with no datasheet field behind them, one note per
    standard with its count and the clauses (`_no_datasheet_field`)."""
    unplaced: dict[str, list[str]] = {}
    for f in findings:
        if not _rejected(f) and _no_datasheet_field(f):
            std = f.get("standard_name") or f.get("standard_document_id") or ""
            unplaced.setdefault(str(std), []).append(_standard_reference(f))
    notes: list[dict] = []
    for name in sorted(unplaced):
        refs = list(dict.fromkeys(r for r in unplaced[name] if r))
        n = len(unplaced[name])
        listed = "; ".join(refs[:_NOTE_REFERENCES]) + (
            f"; and {len(refs) - _NOTE_REFERENCES} more"
            if len(refs) > _NOTE_REFERENCES
            else ""
        )
        notes.append(
            {
                "note": NOTE_FIELD_NOT_IDENTIFIED,
                "standard": name,
                "count": n,
                "detail": (
                    f"{n} of this run's findings from {name or 'this standard'} "
                    "were left for an engineer with no datasheet field and no "
                    "datasheet page behind them"
                    + (f" ({listed})" if listed else "")
                    + ". They are not comments on the datasheet; find the "
                    "field, or decide that the requirement does not apply."
                ),
            }
        )
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
    page = finding.get("standard_page")
    return std + paragraph_ids.cited(finding) + (f" (p.{page})" if page else "")


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
        bits.extend(method_notes.why_bits(f.get("ai_rationale")))
        if bits:
            lines.append(". ".join(bits))
    return "\n".join(dict.fromkeys(lines))


def _page_section(group: list[dict]) -> str:
    """The DATASHEET's page and field: "p.1 - Corrosion allowance (V-2001)".
    Never the standard's file name - that is the Standard Reference column."""
    f = group[0]
    pages = sorted({g.get("contractor_page") for g in group if g.get("contractor_page")})
    field = _field_label(f) + crs_item_series.items_suffix(group)
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


def _requirement_words(finding: dict, cut: int = 220) -> str:
    """ "requires <subject> not less than 3 mm" - ONLY for a verdict the
    arithmetic made (COMPLIANT / NON_COMPLIANT), where the parsed limit is the
    one that was compared. Everywhere else the clause's own sentence is
    quoted: a blank field or an engineer's question must not restate a limit
    the parser may have got wrong ("30 %" read from "30 % of rated flow").
    `cut`: where the quoted sentence is cut (a grouped row's clause list
    cuts each at `CLAUSE_LINE_CHARS`)."""
    limit = finding.get("requirement_limit") or {}
    subject = " ".join(str(limit.get("subject") or "").split())
    clean_subject = subject and len(subject) <= 70 and " shall " not in f" {subject.lower()} "
    if (limit.get("operator") in _OP_WORDS and limit.get("raw_value") not in (None, "")
            and clean_subject
            and finding.get("compliance_status") in ("NON_COMPLIANT", "COMPLIANT")):
        unit = f" {limit['raw_unit']}" if limit.get("raw_unit") else ""
        return (f"requires {subject[0].lower() + subject[1:]} "
                f"{_OP_WORDS[limit['operator']]} {limit['raw_value']}{unit}.")
    sentence = _clause_sentence(finding, cut)
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
    text = " ".join(method_notes.reason_of(finding).split())
    return re.sub(r"^(?:[a-z_]+|[A-Z][A-Z_]+):\s*", "", text)


def _action(finding: dict, field: str) -> str:
    status = finding.get("compliance_status")
    what = field or "the value"
    if status == "NON_COMPLIANT":
        return (f"Contractor to revise {what} to meet the requirement, or submit a "
                "deviation request with justification for Company approval.")
    if status == _MISSING_INFORMATION:
        if finding.get("fact_id") or finding.get("contractor_page"):
            return crs_blank_fields.provide_words(finding, field)
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
    field = _field_label(f) + crs_item_series.items_suffix(group)
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
        # value and page, never the first tag's value printed for all. Once
        # each (order 139 part 2: a field row holds one finding per clause
        # AND tag, and a tag's value is said once).
        per_tag = "; ".join(dict.fromkeys(
            f"{crs_item_series.item_name(g)} {_provided(g)}"
            + (f" (p.{g['contractor_page']})" if g.get("contractor_page") else "")
            for g in sorted(group, key=crs_item_series.in_series_order)))
        said = f"Datasheet {field or 'value'}: {per_tag}."
    else:
        said = f"Datasheet {where} {_provided(f)}." if where else f"The datasheet {_provided(f)}."
    clause_lines = _supporting_clause_lines(group)
    if clause_lines:
        # ORDER 139 PART 2 (spec c): ONE COMMENT PER DATASHEET FIELD. A field
        # row asking two or more things says what to do once, what the sheet
        # says once, then every clause behind it (capped, with the count).
        return "\n".join([group_action(group), said, *clause_lines])
    return f"{lead} {said} {_action(crs_blank_fields.action_leader(group), field)}"


def _clauses(group: list[dict]) -> dict[tuple, list[dict]]:
    """The group's findings by distinct (standard, clause), in group order.
    A finding naming neither is not a clause."""
    out: dict[tuple, list[dict]] = {}
    for g in group:
        key = (
            str(g.get("standard_document_id") or ""),
            str(g.get("standard_clause") or ""),
        )
        if key != ("", ""):
            out.setdefault(key, []).append(g)
    return out


def clause_count(group: list[dict]) -> int:
    """Spec c: how many distinct (standard, clause) a row's findings cite -
    the boundary of its "Supporting clauses (n)" line."""
    return len(_clauses(group))


def _cut(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split()).rstrip(".")
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + " ..."
    return text


def _is_field_row(group: list[dict]) -> bool:
    return _group_key(group[0])[0] == "field"


def _point_words(g: dict, question: bool) -> str:
    """What one finding of a field row asks, in the clause line's words: an
    engineer's question's reason, else the requirement's own sentence."""
    if question:
        return _cut(_reason_words(g), CLAUSE_LINE_CHARS) + "."
    return _requirement_words(g, CLAUSE_LINE_CHARS)


def point_count(group: list[dict]) -> int:
    """Rule 4: how many DIFFERENT things a row's findings ask - each distinct
    requirement sentence, and on an engineer's question each distinct reason
    too. A row asking two things never prints only the first one's words:
    deciding the row decides every finding behind it (#986)."""
    question = _bucket_of(group[0]) == BUCKET_QUESTION
    return len(
        {
            (
                str(g.get("standard_document_id") or ""),
                str(g.get("standard_clause") or ""),
                _fold(g.get("requirement_source_text")),
                _point_words(g, question) if question else "",
            )
            for g in group
        }
    )


def group_action(group: list[dict]) -> str | None:
    """Spec c: the first line of a FIELD row asking two or more things (two
    clauses, or two requirements or reasons of one clause) - the action once,
    for the field ("Contractor to complete the field 'Corrosion allowance' (left blank)."). None for any
    other row, whose one sentence already says everything it asks."""
    if not _is_field_row(group) or point_count(group) < 2:
        return None
    f = group[0]
    field = _field_label(f)
    if _bucket_of(f) == BUCKET_QUESTION:
        return f"Engineer to check {field}."
    return _action(crs_blank_fields.action_leader(group), field)


def _supporting_clause_lines(group: list[dict]) -> list[str]:
    """Spec c: "Supporting clauses (n):" and one line per distinct clause of a
    field row asking two or more things ("- <ref>: <words>"), ordered by
    clause then reference; a clause behind several requirements or reasons
    says each of them (rule 4: nothing a decision covers is hidden). At most
    MAX_CLAUSE_LINES, then "- and k more of these n (see Standard
    Reference)". [] for any other row."""
    if group_action(group) is None:
        return []
    question = _bucket_of(group[0]) == BUCKET_QUESTION
    entries = []
    for members in _clauses(group).values():
        g = members[0]
        ref = _standard_reference(g) or "Requirement"
        words = " ".join(dict.fromkeys(_point_words(m, question) for m in members))
        entries.append(
            (_clause_key(g.get("standard_clause")), ref, f"- {ref}: {words}")
        )
    entries.sort(key=lambda e: (e[0], e[1]))
    n = len(entries)
    lines = [f"Supporting clauses ({n}):", *(e[2] for e in entries[:MAX_CLAUSE_LINES])]
    if n > MAX_CLAUSE_LINES:
        lines.append(
            f"- and {n - MAX_CLAUSE_LINES} more of these {n} (see Standard Reference)."
        )
    return lines


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
    """THE BASE GROUPING KEY of one finding (order 139 part 2, spec a).

    ONE ROW PER DATASHEET FIELD for a value left blank, a value not found and
    an engineer's question (`FIELD_GROUPED_BUCKETS`): ("field", bucket, the
    field as the row prints it, folded). One blank field cited by 29 clauses
    was 29 rows; it is one comment listing the 29 clauses. The bucket is IN
    the key: a blank and a not-found of the same field stay two rows - their
    actions differ, and merging them would ask the contractor for a value the
    system only failed to find (honesty audit 50).

    Every other row-producing finding (a breach, a datasheet check, a field-
    grouped finding with no field label): ONE ROW PER FIELD ISSUE, as before
    - the same requirement wording, status and field, whichever tags carry it
    and whichever standards state it. A finding with no requirement text, a
    safety tick, a chat comment and an AI/web item is its own row ("one").
    An engineer's wording splits a group in `_grouped`, list-level."""
    text = _fold(f.get("requirement_source_text"))
    bucket = _bucket_of(f)
    if crs_blank_fields.is_unrequired_blank(f):
        return ("blanks", crs_blank_fields.ROW_KEY)
    if not text or bucket in _ONE_ROW_BUCKETS:
        return ("one", str(f.get("id") or id(f)))
    label = _fold(_field_label(f)) if bucket in FIELD_GROUPED_BUCKETS else ""
    if label:
        return ("field", bucket, label)
    # #725 F7: ONE ROW PER PROBLEM. The printed value and the page are NOT in
    # the key: the same requirement on the same field with the same outcome is
    # one comment listing every tag (and each tag's own value and page when
    # they differ), not one row per tag.
    return ("req", bucket, f.get("compliance_status"), text,
            _fold(f.get("crs_field_label") or f.get("matched_phrase") or f.get("contractor_section")),
            f.get("origin") == _DATASHEET_ORIGIN)


def _grouped(ordered: list[dict]) -> list[list[dict]]:
    keys = _final_keys(ordered)
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for f in ordered:
        key = keys[id(f)]
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
    # lowest page, tag and value - and (order 139 part 2: a field row holds
    # many clauses) the lowest clause, the requirement's words and the id.
    return [sorted(groups[k], key=_leader_order) for k in order]


def _leader_order(f: dict) -> tuple:
    page = f.get("contractor_page")
    return (
        not f.get("confirmed_by"),
        page if isinstance(page, int) else 10**9,
        str(f.get("equipment_tag") or ""),
        _fold(f.get("contractor_evidence_text")),
        _clause_key(f.get("standard_clause")),
        _fold(f.get("requirement_source_text")),
        str(f.get("id") or ""),
    )


def _key_text(key: tuple) -> str:
    """A `_group_key` tuple as the string key the run summary sends."""
    if key[0] in ("one", "blanks"):
        return f"{key[0]}:{key[1]}"
    if key[0] == "field":
        return "field:" + field_comment_key(key[1], key[2])
    return "req:" + comment_key("requirement group", *key[1:])


def _final_keys(ordered: list[dict]) -> dict[int, str]:
    """{id(finding): its group key} over one list: the base key, plus - when
    the findings of one base group carry two or more DIFFERENT engineer
    wordings - ":e<digest of the wording>" (spec a rule 5). The screen edits
    a whole row and writes its words on every finding of it, so one wording
    keeps the row whole; an engineer's words are never merged with different
    words. (It used to make every edited finding a row of its own, which
    would re-split a 29-finding row the moment it was edited.)"""
    base = {id(f): _key_text(_group_key(f)) for f in ordered}
    wordings: dict[str, set[str]] = {}
    for f in ordered:
        wordings.setdefault(base[id(f)], set()).add(_fold(f.get("engineer_comment")))
    return {
        id(f): base[id(f)]
        + (
            ":e" + comment_key("edit", f.get("engineer_comment"))[:12]
            if len(wordings[base[id(f)]]) > 1
            else ""
        )
        for f in ordered
    }


#: Worst first. A row carries the worst severity of the findings it groups.
SEVERITY_ORDER = severity_rule.ORDER


def row_severity(group: list[dict]) -> str:
    """The worst severity in the group; "" when none is recorded."""
    found = {severity_rule.effective_severity(g) for g in group}
    return next((s for s in SEVERITY_ORDER if s in found), "")


# --------------------------------------------------------------------------
# ORDER 139 PART 2 - one comment per datasheet field, a real order, no empty
# COMPANY Comments (docs/order-139-part2-spec.md). The grouping (sections a-d)
# is `crs_groups`; `main._crs_content` and the run summary read it, so the
# file and the screen group alike.
# --------------------------------------------------------------------------

#: What a finding is on the sheet, before grouping (spec section a). One
#: bucket per row-producing branch of `build_crs_rows`; None = not a row.
BUCKET_BREACH = "breach"  # NON_COMPLIANT against a standard
BUCKET_BLANK = "blank"  # MISSING_INFORMATION, paired with a field
BUCKET_NOT_FOUND = "not_found"  # MISSING_INFORMATION, no field paired
BUCKET_CHECK = "check"  # a datasheet self-check (kind B)
BUCKET_QUESTION = "question"  # NEEDS_ENGINEER_REVIEW (not a page note)
BUCKET_TICK = "tick"  # a safety-tier "meets" for an engineer's tick
BUCKET_CHAT = "chat"  # an engineer's comment filed from chat
BUCKET_AI = "ai"  # an AI engineering check item (kind C)
BUCKET_WEB = "web"  # a public-web standards check item (kind D)
#: The buckets grouped ONE ROW PER DATASHEET FIELD (spec a). A finding of
#: these buckets with no field label keeps today's one-row-per-requirement key.
FIELD_GROUPED_BUCKETS = (BUCKET_BLANK, BUCKET_NOT_FOUND, BUCKET_QUESTION)

#: The rank of a CRS row, most important first (spec f). The sheet is sorted
#: by it, then datasheet page, clause and field (`_sheet_order`), and the words
#: print in the "Priority" column in place of "Severity". Never "high"/"low": a
#: rank is not a confidence.
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
AI_UNCONFIRMED_COMMENT = (
    "AI suggestion awaiting an engineer's decision - its words are in "
    "AI Review Comments. Not issued to the contractor until an engineer "
    "confirms it."
)
WEB_UNCONFIRMED_COMMENT = (
    "Web standards check suggestion awaiting an engineer's decision - its "
    "words are in AI Review Comments. Not issued to the contractor until "
    "an engineer confirms it."
)

#: The two waiting sentences. They are text ONLY beside the draft they point
#: to (a row's "AI Review Comments"); anywhere else - a carried-forward
#: snapshot, a row whose draft is gone - they say nothing true.
WAITING_COMMENTS = frozenset({AI_UNCONFIRMED_COMMENT, WEB_UNCONFIRMED_COMMENT})


def row_has_no_text(row: dict) -> bool:
    """Spec e, one home (rule 8): a CRS row with no comment text a contractor
    could be sent - an empty comment, or a waiting sentence with no draft
    beside it. `crs_export` never issues such a row and `crs_issue` blocks
    the issue on a confirmed one."""
    text = str(row.get("comment") or "").strip()
    if not text:
        return True
    draft = str(row.get("ai_review_comment") or "").strip()
    return text in WAITING_COMMENTS and not draft


def row_has_no_issuable_text(row: dict) -> bool:
    """`row_has_no_text` for a row that is about to be ISSUED (1b): a waiting
    sentence is never text a contractor is sent, draft beside it or not - the
    draft is the machine's, and an issued number's row can carry both."""
    return row_has_no_text(row) or (
        str(row.get("comment") or "").strip() in WAITING_COMMENTS
    )


def carry_issued_wording(row: dict, snapshot: dict, names_of=None) -> None:
    """1b: AN ISSUED NUMBER KEEPS THE ENGINEER'S WORDS. A later run raises the
    same AI/web item again as an unconfirmed draft (the row holds
    `ai_review_comment`, its COMPANY Comments is the waiting sentence), but
    its key already holds an issued number, so the row is the engineer's
    comment. It then carries what that number last said - the snapshot - on
    both copies; the draft stays in AI Review Comments, internal only. A
    snapshot with no words (a number saved empty or as a waiting sentence by
    an older build) leaves the row EMPTY, so it is counted and blocks the
    issue instead of printing "not issued" beside an issued number. A row
    without a draft already holds its own words and is left alone.

    The byline is the snapshot's, never the draft's ("AI - engineer to
    confirm"): blank when none was kept or no words were, and a raw user id
    in an older byline is shown as that user's display name (`names_of`: ids
    -> {id: name}), as every carried byline is (audit 2026-09-30)."""
    if not str(row.get("ai_review_comment") or "").strip():
        return
    words = str(snapshot.get("comment") or "").strip()
    if words in WAITING_COMMENTS:
        words = ""
    row["comment"] = words
    by = str(snapshot.get("comment_by") or "").strip() if words else ""
    person = byline_person(by)
    names = names_of({person}) if person and names_of else {}
    row["comment_by"] = resolve_byline(by, names)


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
    return None if _rejected(finding) else _bucket_of(finding)


def _bucket_of(f: dict) -> str | None:
    """`crs_bucket` without the rejection: what the finding WOULD be, so a
    rejected finding's comment key is the key of the row it would land on."""
    origin = f.get("origin")
    status = f.get("compliance_status")
    if f.get("crs_skip"):
        return None
    if origin == "chat":
        return BUCKET_CHAT
    if origin == _AI_ORIGIN:
        return BUCKET_AI
    if origin == _WEB_ORIGIN:
        return BUCKET_WEB
    if origin == _DATASHEET_ORIGIN:
        # rule_trust (#947): a check held because its rule is not proven is
        # still a row - the engineer decides it.
        if status in ("NON_COMPLIANT", _MISSING_INFORMATION) or f.get("rule_said"):
            return BUCKET_CHECK
    elif status == "NON_COMPLIANT":
        return BUCKET_BREACH
    elif status == _MISSING_INFORMATION:
        return (
            BUCKET_BLANK
            if (f.get("fact_id") or f.get("contractor_page"))
            else BUCKET_NOT_FOUND
        )
    elif status == "NEEDS_ENGINEER_REVIEW":
        # B3 / 2f: unread-page and page-reader questions are Review notes.
        # #1177 (#139): so is a standard's question with no datasheet field and
        # no page behind it (`_no_datasheet_field`): one note per standard,
        # never a CRS line. Decided HERE, in the one place that says what is a
        # row, so the file and the screen's `crs_note` agree.
        if (
            not _unread(f)
            and not _page_reader_only(f)
            and not _no_datasheet_field(f)
        ):
            return BUCKET_QUESTION
        return None
    if f.get("show_for_engineer_tick") and status == "COMPLIANT":
        return BUCKET_TICK
    return None


#: Buckets whose every finding is a row of its own.
_ONE_ROW_BUCKETS = (BUCKET_TICK, BUCKET_CHAT, BUCKET_AI, BUCKET_WEB)
#: Buckets built as a requirement comment (`engineer_comment_text`).
_REQUIREMENT_BUCKETS = (
    BUCKET_BREACH,
    BUCKET_BLANK,
    BUCKET_NOT_FOUND,
    BUCKET_CHECK,
    BUCKET_QUESTION,
)
_BUCKET_ROW_KIND = {
    BUCKET_BREACH: ROW_KIND_NON_COMPLIANT,
    BUCKET_BLANK: ROW_KIND_MISSING_INFORMATION,
    BUCKET_NOT_FOUND: ROW_KIND_MISSING_INFORMATION,
    BUCKET_CHECK: ROW_KIND_DATASHEET_CHECK,
    BUCKET_QUESTION: ROW_KIND_NEEDS_ENGINEER_REVIEW,
    BUCKET_TICK: ROW_KIND_SAFETY_TICK,
    BUCKET_CHAT: ROW_KIND_ENGINEER_COMMENT,
    BUCKET_AI: ROW_KIND_AI_ENGINEERING_CHECK,
    BUCKET_WEB: ROW_KIND_WEB_STANDARD_CHECK,
}


def crs_group_key(finding: dict) -> str | None:
    """The BASE grouping key of one finding (spec a), or None when it is not
    a row. Field-grouped buckets with a field label:
    "field:" + field_comment_key(bucket, label). Every other row-producing
    finding: "req:" + a digest of today's `_group_key` parts (bucket
    included), or "one:<finding id>" for a finding that is its own row (no
    requirement text, a safety tick, chat, AI, web). `crs_groups` may add an
    ":e<digest>" suffix when the findings of one base group carry different
    engineer wordings."""
    if crs_bucket(finding) is None:
        return None
    return _key_text(_group_key(finding))


def field_comment_key(bucket: str, label: str) -> str:
    """Spec d: the PERMANENT-NUMBER key of a field-grouped row -
    `comment_key("field group", bucket, label)`. The field and what kind of
    row it is, never which clauses happen to raise it, which tags, or the
    leader: a re-run that adds or drops a clause keeps the number."""
    return comment_key("field group", bucket, label)


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
    suffix), "bucket": str, "row_kind": str, "findings": [finding dicts,
    leader first], "action": str | None (the row's first line when it asks
    two or more things, else None)}. `build_crs_rows` builds its finding
    rows from this, and the run summary sends each finding's key, order and
    action to the screen from the rows built from it - so the screen and the
    file cannot group or order differently.

    Rejected findings are not rows; a datasheet check about a fact a breach
    or blank row already names is that row, not a second one."""
    crs_item_series.merge(findings)
    crs_ai_drafts.merge(findings)
    findings = [f for f in findings if not _rejected(f)]
    by: dict[str, list[dict]] = {}
    for f in findings:
        bucket = _bucket_of(f)
        if bucket is not None:
            by.setdefault(bucket, []).append(f)
    breaches = by.get(BUCKET_BREACH, [])
    blanks = by.get(BUCKET_BLANK, [])
    not_found = by.get(BUCKET_NOT_FOUND, [])
    questions = by.get(BUCKET_QUESTION, [])
    # A datasheet check about a fact a standard's row already names is that row.
    covered = {f.get("fact_id") for f in breaches + blanks if f.get("fact_id")}
    checks = [
        f
        for f in by.get(BUCKET_CHECK, [])
        if not (f.get("fact_id") and f.get("fact_id") in covered)
    ]
    items: list[dict] = []
    for kind, bucket in (
        (ROW_KIND_NON_COMPLIANT, breaches),
        (ROW_KIND_MISSING_INFORMATION, blanks),
        (ROW_KIND_MISSING_INFORMATION, not_found),
        (ROW_KIND_DATASHEET_CHECK, checks),
        (ROW_KIND_NEEDS_ENGINEER_REVIEW, questions),
    ):
        keys = _final_keys(bucket)
        ckeys = _split_comment_keys(_grouped(bucket), keys)
        # The order is set once, over every row kind, by `_sheet_order`.
        for group in _grouped(bucket):
            items.append(
                {
                    "key": keys[id(group[0])],
                    "comment_key": ckeys[keys[id(group[0])]],
                    "bucket": _bucket_of(group[0]),
                    "row_kind": kind,
                    "findings": group,
                    "action": group_action(group),
                }
            )
    # Then, one row each: the safety ticks, the engineer's chat comments, and
    # the AI / web check items (those two in the order given).
    for wanted in ((BUCKET_TICK,), (BUCKET_CHAT,), (BUCKET_AI, BUCKET_WEB)):
        for f in findings:
            bucket = _bucket_of(f)
            if bucket in wanted:
                items.append(
                    {
                        "key": _key_text(_group_key(f)),
                        "bucket": bucket,
                        "row_kind": _BUCKET_ROW_KIND[bucket],
                        "findings": [f],
                        "action": None,
                    }
                )
    return _sheet_order(items)


def _split_comment_keys(
    groups: list[list[dict]], keys: dict[int, str]
) -> dict[str, str]:
    """{group key: the permanent-number key of its row}, over one bucket.

    Normally a row's key is its leader's (`finding_comment_key`). When the
    findings of ONE base group carry different engineer wordings, `_final_keys`
    splits it into several rows, and a field group's rows would all share the
    field's key - one number for two rows, and which row held it would depend
    on where each lands on the sheet. So one of them keeps the key and each
    other gets its own, made from that key and its wording's digest - the
    same ":e<digest>" the group key carries, so it depends on nothing but the
    wording and is the same on every run.

    The row that keeps the key is the one an engineer made theirs (every
    finding confirmed), then the larger, then the lower wording digest: an
    edited row that a re-run finds beside a fresh draft of the same field
    keeps the number it was issued under."""
    cohorts: dict[tuple[str, str], list[list[dict]]] = {}
    for group in groups:
        lead = group[0]
        cohorts.setdefault(
            (_key_text(_group_key(lead)), finding_comment_key(lead)), []
        ).append(group)
    out: dict[str, str] = {}
    for (_base, natural), cohort in cohorts.items():
        anchor = min(
            cohort,
            key=lambda g: (
                not all(_confirmed(f) for f in g),
                -len(g),
                keys[id(g[0])],
            ),
        )
        for group in cohort:
            group_key = keys[id(group[0])]
            out[group_key] = (
                natural
                if group is anchor
                else comment_key(
                    "wording split", natural, group_key.rsplit(":e", 1)[-1]
                )
            )
    return out


def _sheet_order(items: list[dict]) -> list[dict]:
    """The order of the finding rows (spec f): each item gets its rank
    (`priority`) and its place (`sort_key`), and the list is sorted by it -
    out of limit first, then missing values, then the engineer's questions,
    each by datasheet page, clause and field. `build_crs_rows` reads the same
    two values off the item, so the file's rows and the screen's `crs_order`
    (read from the rows built from this) keep one order."""
    for item in items:
        group = item["findings"]
        item["priority"] = row_priority(item["bucket"], group[0].get("compliance_status"))
        item["sort_key"] = finding_row_sort_key(item["priority"], group, item["key"])
    return sorted(items, key=lambda item: item["sort_key"])


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


def _one_row_findings(items: list[dict], *buckets: str) -> list[dict]:
    """The findings of the one-finding rows of these buckets, in order."""
    return [item["findings"][0] for item in items if item["bucket"] in buckets]


def build_crs_rows(findings: list[dict], missing_references: list[str],
                   submittal_name: str,
                   unread_pages: list[int] | None = None,
                   standards_check: dict | None = None) -> list[dict]:
    """The CRS rows for one run - ONE ROW PER FIELD ISSUE, and (order 139
    part 2) ONE COMMENT PER DATASHEET FIELD for a value left blank, not found
    or for an engineer to check: the finding rows are `crs_groups`, built
    here in its order.

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
    questions, questions with no datasheet field behind them (#139) and
    NOT_IN_DOCUMENT_SCOPE (all Review notes, B3/2f); a COMPLIANT result.
    """
    rows: list[dict] = []
    #: order 139 part 2: rows[i]'s place on the sheet (`finding_row_sort_key`)
    sort_keys: list[tuple] = []
    status = lambda f: f.get("compliance_status")  # noqa: E731
    # ORDER 139 PART 2: THE ONE GROUPING (`crs_groups`, which also leaves
    # rejected findings out) - the run summary sends the same groups and
    # order to the screen.
    items = crs_groups(findings)
    for item in items:
        if item["bucket"] in _REQUIREMENT_BUCKETS:
            group, kind = item["findings"], item["row_kind"]
            f = group[0]
            machine = _finding_text(f)  # 95 6b: kept as ai_comment
            if kind != ROW_KIND_DATASHEET_CHECK or crs_blank_fields.is_row(group):
                machine = crs_blank_fields.comment_or(group, engineer_comment_text)
            text = f.get("engineer_comment") or machine
            rows.append(
                {
                    # THE FINDING'S OWN STORED ID, carried so `crs_export` can mint
                    # a per-row reference that survives a re-export; never printed.
                    "finding_id": f.get("id") or "",
                    # #986: EVERY finding the row stands on. A decision on the row
                    # is a decision on all of them; deciding only the first left
                    # the row open with the next finding behind it.
                    "finding_ids": [g["id"] for g in group if g.get("id")],
                    "document_name": submittal_name,
                    "page_section": crs_blank_fields.section_or(group, _page_section),
                    "comment": text,
                    "ai_comment": machine,
                    "edited": text.strip() != machine.strip(),
                    "comment_by": _by(group),
                    "standard_reference": "; ".join(
                        dict.fromkeys(
                            r for r in (_standard_reference(g) for g in group) if r
                        )
                    ),
                    "row_kind": kind,
                    "severity": row_severity(group),
                    "engineer_confirmed": all(_confirmed(g) for g in group),
                    # Never printed: what the permanent CRS number is keyed on.
                    # A field row (order 139 part 2) is keyed on the FIELD, never
                    # on whichever clause leads it, so a re-run that adds a
                    # clause keeps its number.
                    "comment_key": item["comment_key"],
                    # Never printed (spec d): every finding's own per-requirement
                    # key, so the numbers earlier per-clause rows hold are found.
                    "member_keys": crs_item_series.member_keys(group),
                    # Never printed: the group key the run summary sends the
                    # screen, and the row's first line when it asks two or more
                    # things.
                    "crs_group": item["key"],
                    "crs_action": item["action"],
                    # R30: the chain behind the comment (internal copy only).
                    "reasoning": reasoning_text(group),
                    # rule_trust (#947): who stands behind the rule, in words.
                    "rule_trust": trust_words(f),
                }
            )
            # A row that is not a field row also holds its OWN key (a row split
            # off by wording has one no finding has), so `main` never takes it
            # for a field row replacing clauses.
            if _group_key(f)[0] != "field":
                rows[-1]["member_keys"] = sorted(
                    {*rows[-1]["member_keys"], item["comment_key"]}
                )
            # Spec f: the rank, and the SAME sort key `crs_groups` orders by, so the
            # file's rows and the screen's `crs_order` cannot disagree.
            rows[-1]["priority"] = item["priority"]
            sort_keys.append(item["sort_key"])

    # rule_trust (#947 step 8): SAFETY-TIER COMPLIANT, SHOWN FOR A TICK. The
    # rule decided "meets the standard" on its own; because the field is a
    # safety one, an engineer reads the clause and the value and ticks it
    # (the PF5 decision routes: accept = ticked, reject = something is off).
    # Internal copy only (`crs_export` drops the kind from the issue copy).
    for f in _one_row_findings(items, BUCKET_TICK):
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
            "crs_group": _key_text(_group_key(f)),
            "reasoning": reasoning_text([f]),
            "rule_trust": trust_words(f),
        })
        sort_keys.append(_rank_row(rows[-1], row_priority(BUCKET_TICK), [f]))

    # An engineer's own comments, filed from chat: individual comments to the
    # contractor, the engineer's rather than the machine's.
    for f in _one_row_findings(items, BUCKET_CHAT):
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
            "crs_group": _key_text(_group_key(f)),
        })
        sort_keys.append(_rank_row(rows[-1], row_priority(BUCKET_CHAT), [f]))

    # Owner order 2d/2f, 2d-2: AI (kind C) and web (kind D) check items - never
    # a verdict; a draft in its own column until an engineer confirms it.
    for f in _one_row_findings(items, BUCKET_AI, BUCKET_WEB):
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
        # HONESTY (2026-09-27): "Comment By" says whose draft it is, never blank.
        unconfirmed_by = _AI_UNCONFIRMED_BY if origin == _AI_ORIGIN else _WEB_UNCONFIRMED_BY
        row_kind = ROW_KIND_AI_ENGINEERING_CHECK if origin == _AI_ORIGIN else ROW_KIND_WEB_STANDARD_CHECK
        # Spec e: COMPANY Comments is never empty; an unconfirmed item's cell
        # says it awaits an engineer, the draft stays in "AI Review Comments".
        unconfirmed_comment = (
            AI_UNCONFIRMED_COMMENT if origin == _AI_ORIGIN else WEB_UNCONFIRMED_COMMENT
        )
        rows.append(
            {
                "finding_id": f.get("id") or "",
                "document_name": submittal_name,
                "page_section": where,
                "comment": text if confirmed else unconfirmed_comment,
                "comment_by": (
                    f"{confirmed_by_prefix}{f.get('confirmed_by_name') or f['confirmed_by']}"
                    if confirmed
                    else unconfirmed_by
                ),
                "ai_review_comment": "" if confirmed else text,
                "standard_reference": relates
                if origin == _AI_ORIGIN and not f.get("engineer_comment")
                else "",
                "row_kind": row_kind,
                "severity": row_severity([f]),
                "engineer_confirmed": confirmed,
                "engineer_worded": bool(f.get("engineer_comment")),
                # The machine's finding text, not the engineer's edit of it, so
                # confirming or re-wording an AI/web item keeps its number.
                "comment_key": finding_comment_key(f),
                "crs_group": _key_text(_group_key(f)),
                # R30: the chain behind the item (internal copy only).
                "reasoning": reasoning_text([f]),
            }
        )
        rows[-1].update(crs_ai_drafts.row_extras(f))
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
