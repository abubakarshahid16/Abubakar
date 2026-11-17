"""What a point of the RULE CHECK holds, in words for the one CRS and the page (owner order 16 Nov 2026: "the one CRS carries each point's own
content"). One home, pure, no I/O, no model.

Every value comes from the stored finding and its CRS row, or the function says plainly that nothing is recorded; nothing is invented.
HONESTY: a quote counts as "verified" only when code verified it (the caller passes the verified text separately); a stored value
that code did not verify is shown as stored, with "not verified by code"; "not mentioned" is never "compliant".

The kinds of rule-check point (`row_kind`): datasheet_check, clause_review, playbook_check, ai_engineering_check, needs_engineer_review,
standard_not_cited, standard_not_applicable, safety_tick, missing_information, engineer_comment.
"""

from __future__ import annotations

import re

PLACEHOLDER = "AI suggestion awaiting an engineer's decision"
NOTHING = "nothing recorded for this point"
NOT_VERIFIED = "not verified by code"
NO_RULE_CITED = "no rule book cited: a field check"
UNREADABLE_BOOK = "not shown: not a rule book you may read, or not linked to a held one (not named)"
AI_SUGGESTION = "the AI's suggestion (internal; not issued to the contractor until an engineer confirms it)"

#: "Checked by": which part of the review raised the point.
CHECKED_BY = {
    "datasheet_check": "Rule check: datasheet checklist",
    "safety_tick": "Rule check: datasheet checklist (safety field)",
    "clause_review": "Rule check: clause review (AI)",
    "playbook_check": "Rule check: playbook check",
    "ai_engineering_check": "Rule check: AI engineering check",
    "needs_engineer_review": "Rule check: standards comparison",
    "missing_information": "Rule check: standards comparison",
    "standard_not_cited": "Rule check: cited standards",
    "standard_not_applicable": "Rule check: cited standards",
    "engineer_comment": "Engineer",
}
AI_REVIEW_BY = "AI reviewer"

#: Why the point is a question or a finding, by kind: what was compared, or why it is left to the engineer. Plain words; nothing here is
#: a verdict.
REASON = {
    "datasheet_check": "A value of the datasheet was checked against an entry of the datasheet checklist; it could not be settled, so an engineer decides.",
    "safety_tick": "A safety field of the datasheet: the engineer ticks it once the value is checked.",
    "clause_review": "The AI read the clause against the paper and could not settle it, so an engineer decides.",
    "playbook_check": "A check of the paper against its playbook; an engineer reads it.",
    "ai_engineering_check": "The AI engineering check raised this point for an engineer to decide.",
    "needs_engineer_review": "A requirement of a cited standard could not be compared with the paper by code, so an engineer decides.",
    "missing_information": "The paper does not give the value this requirement needs.",
    "standard_not_cited": "The paper does not cite this standard.",
    "standard_not_applicable": "A cited standard that does not apply to this kind of equipment.",
}
CODE_REASON = {
    "procedure_text_found": "The standard's wording was found in the procedure text, but code could not compare it.",
    "quantity_kind_unsure": "The kind of quantity (for example pressure or temperature) was not sure, so the numbers were not compared.",
}
STATUS_WORDS = {
    "NON_COMPLIANT": "recorded as not meeting the requirement",
    "MISSING_INFORMATION": "no value found for this requirement",
    "NEEDS_ENGINEER_REVIEW": "left to the engineer",
    "NOT_IN_DOCUMENT_SCOPE": "needs another document",
    "NOT_APPLICABLE": "does not apply",
    "COMPLIANT": "recorded as meeting the requirement",
}

_PAGE_LABEL = re.compile(r"^(?:p\.?|pp\.?|page)\s*\d[\d,\s\-]*$", re.I)


def clean(value) -> str:
    return " ".join(str(value or "").split())


def is_placeholder(text) -> bool:
    t = clean(text).lower()
    return t.startswith(PLACEHOLDER.lower()) or ("awaiting an engineer" in t and "ai review comments" in t)


def _head(text: str, words: int = 9) -> str:
    parts = clean(text).split()
    return " ".join(parts[:words]) + ("…" if len(parts) > words else "")  # FTU-1: the one cut mark (`crs_completeness.CUT_MARK`)


HIDDEN_FIELD = "a requirement not shown: its rule book is not one you may read, or the point is not linked to a held rule book"


def field_of(section_tail: str, row: dict, finding: dict | None, allow_rule: bool = True) -> str:
    """The point's field: the sheet's own field label; when the row has none (or only a placeholder or a page label), the finding's
    section or phrase; for a clause point with no field, its clause and subject. Never a placeholder and never a page label."""
    f = finding or {}
    tail = clean(section_tail)
    # The row's section tail (`page_section`, built by `crs_mapping._page_section` from `_field_label`) is the paper's own label when the
    # sheet printed one, BUT `_field_label` falls back to the matched phrase and, for a field not found on the sheet, to the CLAUSE'S OWN
    # subject (`requirement_limit.subject`, crs_mapping.py: "NOT FOUND ON THE SHEET: the clause's own subject names the field"). So it can
    # hold requirement wording and is used only when the rule content is visible.
    if allow_rule and tail and not is_placeholder(tail) and not _PAGE_LABEL.match(tail):
        return tail
    # a hidden point keeps the paper's own labels only: the field the datasheet read (`submittal_facts.field_name`) and the finding's
    # contractor section; the matched phrase comes from the requirement
    fact_label = (f.get("_fact") or {}).get("field_name")
    for cand in (None if allow_rule else fact_label, (f.get("matched_phrase") if allow_rule else None), f.get("contractor_section")):
        c = clean(cand)
        if c and not _PAGE_LABEL.match(c) and not is_placeholder(c):
            return c
    if not allow_rule:  # the rule book is not the viewer's to read: nothing derived from it, not even its reference or clause number
        return HIDDEN_FIELD
    ref, clause = clean(row.get("standard_reference")), clean(f.get("standard_clause"))
    # a clause point is named by its reference and clause number (the book's own sentence belongs in "What the rule requires")
    where = f"{ref} clause {clause}".strip() if clause and clause.lower() not in ref.lower() else ref
    if where:
        return where
    comment = clean(row.get("comment"))
    return _head(comment, 7) if comment and not is_placeholder(comment) else ""


def paper_value(finding: dict | None) -> tuple[str, int | None]:
    """The stored value or contractor quote of the finding, and its page ("" when nothing is stored). NOT proof: the caller says whether
    code verified it."""
    f = finding or {}
    fact = f.get("_fact") or {}  # the datasheet value the check read (`submittal_facts`), attached by the caller
    text = clean(f.get("contractor_evidence_text"))
    if not text and clean(fact.get("field_value")):
        text = clean(f"{fact.get('field_name') or ''}: {fact.get('field_value')} {fact.get('unit') or ''}").lstrip(": ")
    page = f.get("contractor_page") or fact.get("page")
    page = page if isinstance(page, int) and not isinstance(page, bool) and page >= 1 else None
    return text, page


def says_no_value(kind: str | None, finding: dict | None) -> bool:
    """The rule-check point's OWN record says the paper gives no value: its kind or its stored status (never free words)."""
    return kind == "missing_information" or str((finding or {}).get("compliance_status") or "") == "MISSING_INFORMATION"


def rule_text(finding: dict | None) -> str:
    """The stored text of the requirement or checklist entry ("" when none)."""
    f = finding or {}
    return clean(f.get("requirement_source_text") or f.get("requirement"))


def rule_ref(row: dict, finding: dict | None) -> dict:
    """Where the rule comes from, as stored: the standard's reference, its clause and its page. The reference is the cited standard's
    name as the row holds it; a held book the caller may not read is named by the caller's rule 5 check, not here."""
    f = finding or {}
    page = f.get("standard_page")
    page = page if isinstance(page, int) and not isinstance(page, bool) and page >= 1 else None
    name, clause = clean(row.get("standard_reference")), clean(f.get("standard_clause"))
    if clause and clause.lower() in name.lower():  # the stored reference already says the clause: said once
        clause = ""
    return {"name": name, "clause": clause, "page": page}


HIDDEN_ACTION = "Engineer to check this point: its rule book is not one you may read, or the point is not linked to a held rule book (not named)."


def action_of(row: dict, finding: dict | None, scrub=clean, own_only: bool = False, comment_only: bool = False) -> tuple[str, str]:
    """(the words of the action, where they come from): the row's own comment; when that is the placeholder, the real words of the AI's
    suggestion that the placeholder points to (the row's AI-review comment, else the finding's required action or its text). source is
    "check" (the check's own comment), "ai_suggestion" (internal only) or ""."""
    if own_only:  # a hidden point: the fixed sentence only. The check's comment, the AI's and the finding's words can all quote the book
        return HIDDEN_ACTION, "hidden"
    comment = clean(row.get("comment"))
    if comment and not is_placeholder(comment) and (got := scrub(comment)):
        return got, "check"
    if comment_only:  # the app's own checklist text for a restricted viewer: no AI or finding words (they can carry a book's wording)
        return HIDDEN_ACTION, "hidden"
    f = finding or {}
    for cand in (row.get("ai_review_comment"), f.get("required_action"), f.get("finding"), f.get("ai_rationale")):
        c = clean(cand)
        if c and not is_placeholder(c) and (got := scrub(c)):
            return got, "ai_suggestion"
    return "", ""


def checked_by(kind: str | None) -> str:
    return CHECKED_BY.get(kind or "", "Rule check")


def reason_words(kind: str | None, finding: dict | None) -> str:
    """The reason in plain words, per kind, from the kind, the stored reason code and the stored status; never the source label."""
    f = finding or {}
    code = CODE_REASON.get(str(f.get("reason_code") or ""))
    base = code or REASON.get(kind or "", "")
    status = STATUS_WORDS.get(str(f.get("compliance_status") or ""))
    if base and status and kind in ("datasheet_check", "needs_engineer_review", "missing_information", "clause_review"):
        return f"{base} Status on record: {status}."
    return base


# ------------------------------------------------------------------------------------------------ W-H4, W-H5: not a requirement to check

#: The other kind (rank 8, "Does not apply" tile) of a rule-check point that is not a requirement of the paper (order 14, W-H4/W-H5):
#: kept as a point (counted on the page, a row of the sheet Evidence, listed with its reason), never a comment or a question.
NOT_A_REQUIREMENT = "Not a requirement to check"
_NUMBER = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?\s+)?")
#: A rule book's section TITLE (the whole title, its clause number aside) that holds no requirement on a paper: its scope or
#: purpose, its terms, its conflicts and deviations, its exceptions. "Scope of supply" or "Deviation alarms" are not whole titles.
_HOUSEKEEPING = re.compile(
    r"(?:(?:purpose\s+(?:and|&)\s+)?scope(?:\s+(?:and|&)\s+purpose)?|purpose|applicability"
    r"|terms?(?:\s*(?:,|and|&)\s*(?:abbreviations?|acronyms?|symbols?))*"
    r"|conflicts?(?:\s+(?:and|&)\s+deviations?)?|deviations?(?:\s+(?:and|&)\s+(?:waivers?|exceptions?))?|exceptions?|waivers?)\s*:?",
    re.IGNORECASE,
)
_OBLIGES = re.compile(r"\b(?:shall|must|is required|are required|is to be|are to be)\b", re.IGNORECASE)
_KIND_OF_TITLE = (
    (re.compile(r"(?:purpose\s+(?:and|&)\s+)?scope|purpose|applicability", re.I), "the rule book's scope statement"),
    (re.compile(r"terms?\b", re.I), "a definition of the rule book's terms"),
    (re.compile(r"conflicts?|deviations?|exceptions?|waivers?", re.I), "the rule book's own conflicts and deviations rule"),
)


def not_a_requirement(text: str | None, section: str | None) -> str:
    """W-H4 (order 14): why a stored rule is not a requirement to check against a paper, or "". From the stored clause's own heading
    (the section title the book prints: scope, terms or definitions, conflicts and deviations, references) or from its own sentence
    (it only defines a word, `requirement_quality.is_defining_sentence`). General: no word list of any one book; a definition sits in
    the book, never on the paper."""
    from . import requirement_quality as rq

    title, sentence = " ".join(str(section or "").split()), str(text or "")
    defines = rq.is_defining_sentence(sentence)
    # in a section of terms or definitions, a sentence that still OBLIGES something ("X must be independent", "the drawing shall be
    # scaled") stays a requirement: only a sentence that defines a word or obliges nothing is set apart (no real requirement is lost)
    obliges = bool(_OBLIGES.search(sentence)) and not defines
    if title:
        bare = _NUMBER.sub("", title, count=1)
        terms = rq.is_definitions_heading(title) or (_HOUSEKEEPING.fullmatch(bare) and _KIND_OF_TITLE[1][0].match(bare))
        if terms:
            return "" if obliges else f'a definition in the rule book\'s section "{title}", not a requirement'
        if rq.is_references_heading(title):
            return f'a reference list of the rule book (section "{title}"), not a requirement'
        if _HOUSEKEEPING.fullmatch(bare):
            what = next(w for rx, w in _KIND_OF_TITLE if rx.match(bare))
            return f'{what} (section "{title}"), not a requirement on the paper'
    if defines:
        return "its own sentence only defines a word: a definition, not a requirement"
    return ""


#: W-H5 (order 14): the reason of the AI check's own note on the paper that no rule asks (see `ai_note_on_paper`).
AI_NOTE_REASON = (
    "An AI engineering note on the paper's own values, not a rule's question: it names no clause, and the rule book it names ({book}) "
    "is not held. Engineer to decide whether to raise it."
)


def ai_note_on_paper(kind: str | None, finding: dict | None, clause_named: bool) -> bool:
    """W-H5 (order 14): the rule check's AI step wrote this point about a value of the paper's OWN table or sheet (its row label is the
    paper's), naming no clause of a rule, from a rule book we do not hold. No rule asks it, so it is never worded as that book's
    question ("Book missing ... cannot be checked until the book is held", with a bare number as its evidence): it is the AI's own
    note, in its own words, its value shown with the paper's label."""
    f = finding or {}
    if kind not in ("ai_engineering_check", "web_standard_check") or clause_named or _clean_text(f.get("standard_clause")):
        return False
    return bool(_clean_text(f.get("contractor_section")))


def _clean_text(value) -> str:
    return " ".join(str(value or "").split())
