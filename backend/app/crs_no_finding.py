"""A POINT THAT CARRIES NO FINDING OF ITS OWN is never part of a comment to the contractor (order 14, W-D6, W-D7, W-D11; 17 Nov 2026).

A senior engineer's read of the live datasheet sheets found comments that ask nothing: a "Book missing" row, a line whose reader was
given no rule text, a rule whose "text" is a contents entry or a reference list, a rule that names ONLY another company's form the paper
is not on. THE POINT'S OWN RECORD DECIDES FIRST (lead, review of PR #1889: a real finding hidden is worse than noise): a point whose own
record is an open request to the contractor (information missing, a placeholder to fill, a value to provide, two values that conflict, an
engineering check's own ask) stays a comment whatever the state of its rule book, and a book-missing one says its own ask first. Each one is a POINT (it stays on the sheet Evidence, it
is counted on the first sheet, and every one is listed on the sheet "Not a comment" with what it is); none of them is a comment, and
none of them is folded into a comment's count or Note (`crs_comments` keys it apart: `kind_of`).

  kind_of(point)   what a point with no finding is called, or None (it carries a finding, or an engineer kept or edited it).
  mark(conn, points)   sets, once per listing, the two flags only the database can decide (`_not_a_requirement`: where the rule's text
                   sits in its book, `rule_text_place`; `_form_not_held`: the rule names a form the paper is not on and the library does
                   not hold) and gives those points their honest action words. Only a point whose rule book the caller may read is
                   looked at (rule 5): the words name no book the caller may not read.

General (CLAUDE.md rule 13): stored codes and positions, the library's own chunk kinds and identifiers; no layout or spelling of any
paper. Honesty (rule 4): a value that is open or not stated is never set apart as nothing to change; a firm verdict is never set apart;
a held check (a reading in conflict, a rule not yet proven) is never set apart: only code comparing a trusted reading makes a Met.
No model, no network; reads only.
"""

from __future__ import annotations

import re

from . import crs_ai_words as words
from . import review_point_decisions as decisions_mod
from . import rule_text_place

KIND_BOOK_NOT_HELD = (
    words.KIND_NOT_HELD
)  # "Not checked: rule book not held": the book is on the sheet "Rule books not held"
KIND_NO_RULE_TEXT = "Not checked: no rule text was given to the reader"
KIND_NOT_A_REQUIREMENT = (
    "Not a requirement: the rule's text is a contents or reference-list entry"
)
KIND_FORM_NOT_HELD = "Form not held: checked against the field list only"  # a comment's action, never a set-apart kind
KIND_AI_THINKS_MET = (
    "AI thinks met, engineer to confirm"  # one reader's view, labelled AI
)
KINDS = (
    KIND_BOOK_NOT_HELD,
    KIND_NO_RULE_TEXT,
    KIND_AI_THINKS_MET,
)

NOT_A_REQUIREMENT_NOTE = "(The rule's text is {place} in its rule book, not a requirement: an engineer decides whether anything is asked.)"
FORM_NOT_HELD_ACTION = (
    "Form not held: the rule names form {forms}; this paper is not on it and no document you may read holds it, so the paper was "
    "checked against the equipment's field list only. Whether that form is required is a project-basis question for the engineer."
)
#: A rule that ALSO holds another requirement stays a comment for it; the form part is noted after its action.
FORM_NOTE = (
    "(Form not held: the rule also names form {forms}; this paper is not on it and no document you may read holds it, so that part "
    "was checked against the field list only.)"
)
#: A book-missing point whose own record asks the contractor something: its own ask first, then the book.
OWN_ASK_BOOK = "{ask} ({missing}: not checked against it.)"
#: The record of an open request to the contractor (`open_request`): the stored compliance status, the hold codes of two conflicting
#: values, and the rule check's engineering-check kind (its own record is an ask addressed to the contractor).
_OPEN_STATUS = frozenset({"MISSING_INFORMATION"})
_OPEN_KINDS = frozenset({"ai_engineering_check"})
#: Rule-check kinds whose record is itself an ask (to the contractor or the engineer): never set apart.
_ASK_KINDS = frozenset(
    {
        "ai_engineering_check",
        "standard_not_cited",
        "missing_information",
        "datasheet_check",
        "playbook_check",
        "safety_tick",
        "engineer_comment",
        "needs_engineer_review",
    }
)
#: THE CLOSED LISTS (lead, last review of PR #1889): a kind, row kind or reason code not named here keeps the point a comment.
#: (f) the "does not apply" kinds a point may be set apart with.
ALLOWED_OTHER_KINDS = frozenset(words.OTHER_KINDS)
#: (a) the rule-check row kinds whose book-missing row, with an empty record, asks nothing.
ALLOWED_BOOK_ROW_KINDS = frozenset({"clause_review", "standard_not_applicable"})
#: (b) the AI reason codes of a line its reader could not decide for want of rule text.
ALLOWED_NO_TEXT_CODES = frozenset(
    {"", "unclear_clause", "needs_drawing_or_calc", "other"}
)
#: AI reason codes that are a concern about the paper (a value absent, silent, deferred, not met).
_CONCERN_CODES = frozenset(
    {"not_met", "absent", "sheet_silent", "value_deferred", "not_stated"}
)
#: The AI line sources that ask a rule of a book ("rule") or an item of a checklist ("skill"); a coverage line is "group".
ASKED = ("rule", "skill")
_SENTENCE = re.compile(r"(?<=[.;])[\"\u201d\u2019)]?\s+(?=[A-Z(\"\u201c])")
#: A rule that puts the paper's data ON a named form or data sheet: "shall be listed on forms X-1234", "specified on the Data Sheet(s)
#: X-1, X-2". Submitting a form ("submit a completed Form X-12") is a separate deliverable, not the paper's format: not matched.
_ON_FORM = re.compile(
    r"\b(?:listed|specified|shown|given|entered|recorded|stated|provided|presented)\s+on\s+(?:the\s+)?(?:applicable\s+|approved\s+)?"
    r"(?:forms?|data\s*sheets?|datasheets?)(?:\s*\(s\))?\b(?P<rest>[^.;:]{0,160})",
    re.IGNORECASE,
)
_FORM_ID = re.compile(r"\b[A-Z]{1,4}-\d{3,5}(?:-[A-Z0-9]{1,4})*\b")


def _clean(text) -> str:
    return " ".join(str(text or "").split())


def _line(point: dict) -> dict:
    line = point.get("_line")
    return line if isinstance(line, dict) else {}


def _decided_finding(point: dict) -> bool:
    """An engineer kept or edited the point, or added it: it is the engineer's finding, never set apart."""
    from . import review_points as rp

    state = (point.get("decision") or {}).get("state")
    return point.get("source") == rp.SOURCE_ADDED or state in (
        decisions_mod.KEEP,
        decisions_mod.EDIT,
    )


def no_rule_text(point: dict) -> bool:
    """An AI line its reader could not decide because no rule text was given (no requirement, no clause quote): nothing was checked.
    A line on a rule book the caller may not read is not looked at (its words are already left out for that caller)."""
    from . import review_points as rp

    line = _line(point)
    # only a line that ASKED a rule or a checklist item (a general review's note asks none: it never had rule text to be given)
    if (
        point.get("source") != rp.SOURCE_AI_REVIEW
        or line.get("source") not in ASKED
        or line.get("general")
    ):
        return False
    if point.get("_book_doc") and not point.get("rule_book"):
        return False  # a book the caller may not read
    return (
        line.get("ai_verdict") in (None, "", "Query")
        and not _clean(line.get("requirement"))
        and not _clean(line.get("clause_quote"))
    )


def open_request(point: dict) -> bool:
    """Is the point's OWN record an open request to the contractor? Information missing (a placeholder to fill, a value to provide), two
    values that conflict on the sheet, or the engineering check's own ask. Read from stored codes, never from the words."""
    from .hold_reason import APPLICABILITY_SEVERAL_VALUES, FIELD_SEVERAL_VALUES

    f, row = point.get("_finding") or {}, point.get("_row") or {}
    return (
        f.get("compliance_status") in _OPEN_STATUS
        or f.get("hold_reason_code")
        in (FIELD_SEVERAL_VALUES, APPLICABILITY_SEVERAL_VALUES)
        or row.get("row_kind") in _OPEN_KINDS
    )


def record_asks(point: dict) -> bool:
    """Does a RULE-CHECK point's own record hold an ask or a code concern? Any stored status, any required action, any open request, or
    a kind that is itself an ask (a check that needs no book, a standard not cited, an engineering check)."""
    f, row = point.get("_finding") or {}, point.get("_row") or {}
    return bool(
        open_request(point)
        or _clean(f.get("compliance_status"))
        or _clean(f.get("reason_code")).upper()
        not in ("", "COMPLIANT", "NOT_APPLICABLE")
        or _clean(f.get("required_action"))
        or row.get("row_kind") in _ASK_KINDS
        or f.get("origin") == "datasheet_check"
    )


def ai_concern(line: dict) -> bool:
    """Does an AI line hold a concern or an ask? Its reader said Fail or not met, the value is absent, silent or deferred, or it wrote ANY
    words to the contractor on a line it did not judge met (the reader's own words are never read for "no action": an ask hidden is worse
    than a line of noise)."""
    codes = {str(line.get("reason_code") or ""), str(line.get("reason_code_ai") or "")}
    met = line.get("ai_verdict") == "Pass" or "met" in codes
    return bool(
        line.get("ai_verdict") == "Fail"
        or codes & _CONCERN_CODES
        or (_clean(line.get("comment")) and not met)
    )


def kind_of(point: dict) -> str | None:
    """THE CLOSED ALLOW-LIST (lead, last review of PR #1889): what a point that carries nothing to ask is called, or None (it stays a
    comment). Only: (a) a book-missing rule-check point whose own record holds no ask and no code concern; (b) an AI line given no rule
    text that holds no ask or concern; (f) a "does not apply / not reviewed / rule not yet approved" point with no AI concern. Coverage
    notes are keyed apart (`crs_comments.key_of`); met points are named by `met_kind` on their field. Everything else stays a comment:
    any AI Fail, not met or absent (rule approved or not), any ask in the record, any check that needs no book."""
    from . import review_points as rp

    if _decided_finding(point) or point.get("rank") in (1, 2, 3):
        return None
    line = _line(point)
    if line and (line.get("general") or ai_concern(line)):
        return None
    if point.get("tile") == "does_not_apply":
        kind = point.get("other_kind") or words.KIND_NOT_APPLICABLE
        if kind not in ALLOWED_OTHER_KINDS or (
            point.get("source") == rp.SOURCE_RULE_CHECK
            and not line
            and record_asks(point)
        ):
            return None
        return kind
    if point.get("rank") != 4:
        return None
    row_kind = (point.get("_row") or {}).get("row_kind")
    if (
        point.get("_book_missing")
        and point.get("source") == rp.SOURCE_RULE_CHECK
        and row_kind in ALLOWED_BOOK_ROW_KINDS
        and not record_asks(point)
    ):
        return KIND_BOOK_NOT_HELD
    codes = {str(line.get("reason_code") or ""), str(line.get("reason_code_ai") or "")}
    if no_rule_text(point) and codes <= ALLOWED_NO_TEXT_CODES:
        return KIND_NO_RULE_TEXT
    return None


def met_kind(point: dict, tick_only: bool, guard_objected: bool) -> str:
    """What a met point is called apart from a comment: proven by code, or two readers whose quotes code verified, is "checked, nothing
    to change"; a one-reader AI "met" (or two readers without verified quotes) is the AI's view, labelled so; a met code could not
    confirm, or one the pass guard objected to, is the engineer's to tick."""
    if tick_only or guard_objected:
        return words.KIND_MET_NOT_CONFIRMED
    checks = _line(point).get("quotes_checked")
    verified = (
        isinstance(checks, dict)
        and checks.get("paper") is True
        and checks.get("clause") is True
    )
    if point.get("rank") == 7 or (point.get("rank") == 6 and verified):
        return words.KIND_NOTHING_TO_CHANGE
    return KIND_AI_THINKS_MET


# ------------------------------------------------------------------------------------------------ the database's two flags


def _rule_texts(point: dict) -> list[str]:
    """The rule's own words a point carries (the book's quote or the stored rule), only when the caller may read the book."""
    if not point.get("rule_book"):
        return []
    line, f = _line(point), point.get("_finding") or {}
    texts = (
        (line.get("clause_quote"), line.get("requirement"))
        if line
        else (f.get("requirement_source_text"), f.get("requirement"))
    )
    return [t for t in (_clean(x) for x in texts) if t]


def _book_page(line: dict):
    where = line.get("clause_book")
    page = (
        (where.get("page") if isinstance(where, dict) else None)
        or line.get("rule_page")
        or line.get("clause_page")
    )
    try:
        return int(page) if page not in (None, "") else None
    except (TypeError, ValueError):
        return None


def place_of(conn, point: dict) -> str | None:
    """W-D7: the point's rule text is a contents entry or a reference-list entry (`rule_text_place`), or None. EVERY text of the point
    is read (the book's quote AND the stored requirement): a requirement word in any of them and it is a requirement."""
    texts = _rule_texts(point)
    if not texts or any(rule_text_place.is_requirement_text(t) for t in texts):
        return None
    line, f = _line(point), point.get("_finding") or {}
    if not line and f.get("requirement_id"):
        return rule_text_place.place_of_requirement(conn, f["requirement_id"])
    book = line.get("standard_document_id") or point.get("_book_doc")
    return next(
        (
            pl
            for t in texts
            if (
                pl := rule_text_place.not_a_requirement(
                    t, conn=conn, book_id=book, page=_book_page(line)
                )
            )
        ),
        None,
    )


def forms_named(text) -> list[str]:
    """The form or data-sheet identifiers a rule puts the paper's data on (`_ON_FORM`), in order, each once."""
    out: list[str] = []
    for m in _ON_FORM.finditer(str(text or "")):
        out += [i for i in _FORM_ID.findall(m.group("rest")) if i not in out]
    return out


def form_only(texts: list[str]) -> bool:
    """Every sentence of the rule that holds a requirement word puts the paper on a form: the rule asks nothing else."""
    sentences = [x for t in texts for x in _SENTENCE.split(t) if x.strip()]
    asks = [
        x
        for x in sentences
        if rule_text_place.is_requirement_text(x) or _ON_FORM.search(x)
    ]
    return bool(asks) and all(_ON_FORM.search(x) for x in asks)


def _fold_id(text) -> str:
    return re.sub(r"[^0-9a-z]+", "", str(text or "").lower())


def _paper_carries(conn, paper_id, forms: list[str], cache: dict) -> bool:
    if paper_id not in cache:
        cache[paper_id] = _fold_id(
            " ".join(
                r[0]
                for r in conn.execute(
                    "SELECT text FROM chunks WHERE document_id = ?", (paper_id,)
                )
            )
        )
    return any(_fold_id(f) in cache[paper_id] for f in forms)


def _library_holds(conn, forms: list[str], readable) -> bool:
    """A document the caller may read (rule 5: only those are looked at) holds one of the forms by its file name."""
    names = [
        _fold_id(r[1])
        for r in conn.execute("SELECT id, filename FROM documents")
        if r[0] in (readable or ())
    ]
    return any(_fold_id(f) in n for f in forms for n in names)


def form_not_held(
    conn, point: dict, paper_id, cache: dict, readable=frozenset()
) -> list[str]:
    """W-D11: the forms a point's rule puts the paper on, when the paper carries none of them and the library holds none: the paper
    is in another format, so asserting a form mismatch would be a claim nobody checked. [] otherwise."""
    forms = [f for t in _rule_texts(point) for f in forms_named(t)]
    if (
        not forms
        or not paper_id
        or _paper_carries(conn, paper_id, forms, cache)
        or _library_holds(conn, forms, readable)
    ):
        return []
    return list(dict.fromkeys(forms))


def _own_ask(point: dict) -> None:
    """A book-missing point whose own record asks the contractor something says that ask first (its row's own words), then the book."""
    from . import review_points_content as content

    ask, source = content.action_of(point.get("_row") or {}, point.get("_finding"))
    if ask:
        point["action"] = OWN_ASK_BOOK.format(
            ask=ask.rstrip(". "),
            missing=point.get("_book_missing_words") or "Book missing",
        )
        point["action_source"] = source


def _note(point: dict, words_: str) -> None:
    point["action"] = f"{_clean(point.get('action'))} {words_}".strip()


def mark(conn, points: list[dict], paper_id, readable=frozenset()) -> None:
    """The database's facts about a point's rule, said on its row and never hiding it (every such point stays a comment): a book-missing
    point whose own record is an open request says its own ask first; a rule whose text is a contents or reference-list entry is noted;
    a FORM-ONLY rule naming a form the paper is not on and no readable document holds says "Form not held" instead of asserting a
    mismatch, and a rule that also asks something else keeps its ask with the form noted. `readable`: the documents the caller may read
    (rule 5). In place; reads only."""
    cache: dict = {}
    for p in points:
        if _decided_finding(p) or p.get("rank") not in (3, 4, 8):
            continue
        if p.get("_book_missing"):
            if open_request(p):
                _own_ask(p)
            continue
        if place := place_of(conn, p):
            p["_not_a_requirement"] = place
            _note(p, NOT_A_REQUIREMENT_NOTE.format(place=place))
        if forms := form_not_held(conn, p, paper_id, cache, readable):
            if form_only(_rule_texts(p)):
                p["_form_not_held"] = forms
                p["action"], p["action_source"] = (
                    FORM_NOT_HELD_ACTION.format(forms=", ".join(forms)),
                    "check",
                )
            else:
                p["_form_note"] = forms
                _note(p, FORM_NOTE.format(forms=", ".join(forms)))
