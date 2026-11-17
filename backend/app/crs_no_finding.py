"""A POINT THAT CARRIES NO FINDING OF ITS OWN is never part of a comment to the contractor (order 14, W-D6, W-D7, W-D11; 17 Nov 2026).

A senior engineer's read of the live datasheet sheets found comments that ask nothing: a "Book missing" row, a line whose reader was
given no rule text, a check that read the value compliant and only waits for a tick, a rule whose "text" is a contents entry or a
reference list, a rule that names another company's form the paper is not on. Each one is a POINT (it stays on the sheet Evidence, it
is counted on the first sheet, and every one is listed on the sheet "Not a comment" with what it is); none of them is a comment, and
none of them is folded into a comment's count or Note (`crs_comments` keys it apart: `kind_of`).

  kind_of(point)   what a point with no finding is called, or None (it carries a finding, or an engineer kept or edited it).
  mark(conn, points)   sets, once per listing, the two flags only the database can decide (`_not_a_requirement`: where the rule's text
                   sits in its book, `rule_text_place`; `_form_not_held`: the rule names a form the paper is not on and the library does
                   not hold) and gives those points their honest action words. Only a point whose rule book the caller may read is
                   looked at (rule 5): the words name no book the caller may not read.

General (CLAUDE.md rule 13): stored codes and positions, the library's own chunk kinds and identifiers; no layout or spelling of any
paper. Honesty (rule 4): a value that is open or not stated is never set apart as nothing to change; a firm verdict is never set apart.
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
KIND_CODE_READ_MET = "Code read it met, not confirmed: engineer to tick"
KIND_NOT_A_REQUIREMENT = (
    "Not a requirement: the rule's text is a contents or reference-list entry"
)
KIND_FORM_NOT_HELD = "Form not held: checked against the field list only"
KINDS = (
    KIND_BOOK_NOT_HELD,
    KIND_NO_RULE_TEXT,
    KIND_CODE_READ_MET,
    KIND_NOT_A_REQUIREMENT,
    KIND_FORM_NOT_HELD,
)

NOT_A_REQUIREMENT_ACTION = (
    "Nothing to ask: the rule's text is {place} in its rule book, not a requirement."
)
FORM_NOT_HELD_ACTION = (
    "Form not held: the rule names form {forms}; this paper is not on it and the library does not hold it, so the paper was checked "
    "against the equipment's field list only. Whether that form is required is a project-basis question for the engineer."
)
#: The ONE sentence `untrusted_value.hold_results` writes when it holds a decided check on an untrusted reading (its own words, never
#: the paper's): "... The check read <STATUS>; engineer to confirm." A test runs that writer and this reader together, so they never drift.
#: The AI line sources that ask a rule of a book ("rule") or an item of a checklist ("skill"); a coverage line is "group".
ASKED = ("rule", "skill")
_CHECK_READ = re.compile(r"\bThe check read ([A-Z_]+); engineer to confirm\.")
_COMPLIANT = "COMPLIANT"
_HELD = "NEEDS_ENGINEER_REVIEW"
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


def check_read(finding: dict) -> str | None:
    """What a held datasheet check had read before it was held (`rule_said`, else `untrusted_value`'s own sentence), or None."""
    said = finding.get("rule_said")
    if said:
        return str(said)
    for text in (finding.get("finding"), finding.get("ai_rationale")):
        if m := _CHECK_READ.search(str(text or "")):
            return m.group(1)
    return None


def code_read_met(point: dict) -> bool:
    """A rule-check datasheet check that READ the value compliant and was held only because the reading is in doubt or the rule is
    not yet approved: the engineer ticks it. A value the sheet marks as not final (deferred, "By Contractor") stays a question."""
    from .blank_markers import defers_value
    from .hold_reason import DEFERRED_MARKER

    f = point.get("_finding") or {}
    if point.get("rank") != 4 or (
        f.get("origin") != "datasheet_check"
        and (point.get("_row") or {}).get("row_kind") != "datasheet_check"
    ):
        return False
    if (
        f.get("compliance_status") != _HELD
        or f.get("hold_reason_code") == DEFERRED_MARKER
    ):
        return False
    if defers_value(f.get("contractor_evidence_text")):
        return False
    return check_read(f) == _COMPLIANT


def kind_of(point: dict) -> str | None:
    """What a point that carries NO finding of its own is called (one of `KINDS`, or a "does not apply" point's own kind); None for a
    point that carries a finding. A firm verdict (not met), a met point and an engineer's own point are never set apart here (a met
    point is set apart by its field, `crs_comments`)."""
    if _decided_finding(point):
        return None
    if point.get("tile") == "does_not_apply":
        return point.get("other_kind") or words.KIND_NOT_APPLICABLE
    if point.get("rank") not in (3, 4):
        return None
    if point.get("_book_missing"):
        return KIND_BOOK_NOT_HELD
    if point.get("_not_a_requirement"):
        return KIND_NOT_A_REQUIREMENT
    if point.get("_form_not_held"):
        return KIND_FORM_NOT_HELD
    if point.get("rank") == 4 and no_rule_text(point):
        return KIND_NO_RULE_TEXT
    if code_read_met(point):
        return KIND_CODE_READ_MET
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


def _library_holds(conn, forms: list[str]) -> bool:
    names = [_fold_id(r[0]) for r in conn.execute("SELECT filename FROM documents")]
    return any(_fold_id(f) in n for f in forms for n in names)


def form_not_held(conn, point: dict, paper_id, cache: dict) -> list[str]:
    """W-D11: the forms a point's rule puts the paper on, when the paper carries none of them and the library holds none: the paper
    is in another format, so asserting a form mismatch would be a claim nobody checked. [] otherwise."""
    forms = [f for t in _rule_texts(point) for f in forms_named(t)]
    if (
        not forms
        or not paper_id
        or _paper_carries(conn, paper_id, forms, cache)
        or _library_holds(conn, forms)
    ):
        return []
    return list(dict.fromkeys(forms))


def mark(conn, points: list[dict], paper_id) -> None:
    """Set `_not_a_requirement` and `_form_not_held` on the points the database shows to be such, and give them their honest action
    words (the rule check's or the AI's ask stays in the record, never on the row). In place; reads only."""
    cache: dict = {}
    for p in points:
        if _decided_finding(p) or p.get("rank") not in (3, 4) or p.get("_book_missing"):
            continue
        if place := place_of(conn, p):
            p["_not_a_requirement"] = place
            p["action"], p["action_source"] = (
                NOT_A_REQUIREMENT_ACTION.format(place=place),
                "check",
            )
        elif forms := form_not_held(conn, p, paper_id, cache):
            p["_form_not_held"] = forms
            p["action"], p["action_source"] = (
                FORM_NOT_HELD_ACTION.format(forms=", ".join(forms)),
                "check",
            )
