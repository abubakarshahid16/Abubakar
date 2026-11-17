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
KIND_FORM_NOT_HELD = "Form not held: checked against the field list only"
KINDS = (
    KIND_BOOK_NOT_HELD,
    KIND_NO_RULE_TEXT,
    KIND_NOT_A_REQUIREMENT,
    KIND_FORM_NOT_HELD,
)

NOT_A_REQUIREMENT_ACTION = (
    "Nothing to ask: the rule's text is {place} in its rule book, not a requirement."
)
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
        or point.get("rank") != 4
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


def kind_of(point: dict) -> str | None:
    """What a point that carries NO finding of its own is called (one of `KINDS`, or a "does not apply" point's own kind); None for a
    point that carries a finding. A firm verdict (not met), a met point and an engineer's own point are never set apart here (a met
    point is set apart by its field, `crs_comments`)."""
    if _decided_finding(point):
        return None
    if point.get("tile") == "does_not_apply":
        return point.get("other_kind") or words.KIND_NOT_APPLICABLE
    if point.get("rank") not in (3, 4) or open_request(
        point
    ):  # the point's own record decides FIRST
        return None
    if point.get("_book_missing"):
        return KIND_BOOK_NOT_HELD
    if point.get("_not_a_requirement"):
        return KIND_NOT_A_REQUIREMENT
    if point.get("_form_not_held"):
        return KIND_FORM_NOT_HELD
    if point.get("rank") == 4 and no_rule_text(point):
        return KIND_NO_RULE_TEXT
    return None


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
    """W-D7: the point's rule text is a contents entry or a reference-list entry (`rule_text_place.not_a_requirement`), or None."""
    texts = _rule_texts(point)
    if not texts:
        return None
    line, f = _line(point), point.get("_finding") or {}
    if not line and f.get("requirement_id"):
        return rule_text_place.place_of_requirement(conn, f["requirement_id"])
    book = line.get("standard_document_id") or point.get("_book_doc")
    return rule_text_place.not_a_requirement(
        texts[0], conn=conn, book_id=book, page=_book_page(line)
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


def mark(conn, points: list[dict], paper_id, readable=frozenset()) -> None:
    """Set `_not_a_requirement` and `_form_not_held` on the points the database shows to be such, and give them their honest action
    words; a book-missing point whose own record is an open request says its own ask. `readable`: the documents the caller may read
    (rule 5). In place; reads only."""
    cache: dict = {}
    for p in points:
        if _decided_finding(p) or p.get("rank") not in (3, 4):
            continue
        if open_request(p):
            if p.get("_book_missing"):
                _own_ask(p)
            continue
        if p.get("_book_missing"):
            continue
        if place := place_of(conn, p):
            p["_not_a_requirement"] = place
            p["action"], p["action_source"] = (
                NOT_A_REQUIREMENT_ACTION.format(place=place),
                "check",
            )
        elif forms := form_not_held(conn, p, paper_id, cache, readable):
            if form_only(_rule_texts(p)):
                p["_form_not_held"] = forms
                p["action"], p["action_source"] = (
                    FORM_NOT_HELD_ACTION.format(forms=", ".join(forms)),
                    "check",
                )
            else:
                p["_form_note"] = forms
                p["action"] = (
                    f"{_clean(p.get('action'))} {FORM_NOTE.format(forms=', '.join(forms))}".strip()
                )
