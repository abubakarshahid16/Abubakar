"""S5, the editor of the general review's comment sheet (order 14): ONE call per paper after the judge, which may only take a
sent line off the sheet; code checks every move. Moved out of `steps` unchanged, then K2 (the lead, 18 Nov 2026): a line that
claims something is missing, limited or "only" may be answered by a quote from ANY page of the paper, under code's checks."""

from __future__ import annotations

import logging
import re

from . import EDITED, PROVISIONAL_FAILS
from . import prompts as P
from .engine import StepFailed
from .steps import NOT_ON_ANY_PAGE, _dumps, paper_block
from .verify import find_page, norm, quote_in

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ S5: the editor (it may only take a comment off the sheet)

EDIT_MAX_TOKENS = 4000
REPEATS, CONTRADICTED = "repeats", "paper_states_otherwise"


def s5_edit(model, paper, lines: list[dict], lead: str, kind: str | None = None) -> int:
    """ONE call per paper after S4 (the lead, 18 Nov 2026): the editor sees the SENT lines only (n = the line's number, field,
    page, comment, quote) and the paper, and may only take a line off the comment sheet. Code checks every move
    (`_edit_reason`): a repeat names a real, sent line about the same place; a contradiction is only for a line that claims a
    thing is not stated, with a paper quote on its page that holds its field and a value. A code-proven failure is never offered. A moved line keeps its label and gets "edited: <reason>" (never sent, still in All points).
    Nothing is added, rewritten or relabelled. A failed call moves nothing. Returns the number of lines moved."""
    from . import sendable
    from .engine import to_line

    sent = {n: d for n, d in enumerate(lines, 1) if sendable(to_line(n, d))}
    # a line code compared and found failing is code's decision: never offered to the editor, never movable (light check E1)
    offered = {n: d for n, d in sent.items() if not _code_failed(d)}
    if not offered:
        return 0
    shown = [
        {"n": n, "field": d.get("field") or "", "page": d.get("page"), "comment": d.get("comment") or "", "quote": d.get("quote") or ""}
        for n, d in offered.items()
    ]  # fmt: skip
    carries = {paper.paper_id} | {
        str(d["book_document_id"])
        for d in offered.values()
        if d.get("book_document_id")
    }
    try:
        out = model.ask(
            step="aim_edit",
            model=lead,
            system="",
            cached=paper_block(paper),
            prompt=P.EDIT_TASK % {"comments": "\n".join(_dumps(x) for x in shown)},
            carries=carries,
            max_tokens=EDIT_MAX_TOKENS,
        )
    except StepFailed as exc:  # the editor only removes repeats: without it every judged line stays as judged
        log.info(
            "general review: the editor step moved nothing (%s)",
            str(exc).split(" ", 2)[:2],
        )
        return 0
    moves = (out or {}).get("moves") if isinstance(out, dict) else None
    moved = 0
    for mv in moves if isinstance(moves, list) else []:
        n = mv.get("n") if isinstance(mv, dict) else None
        why = (
            _edit_reason(mv, n, offered, sent, paper, kind)
            if isinstance(n, int) and n in offered
            else None
        )
        if why:
            d = offered.pop(n)
            sent.pop(n)
            d["code"] = "; ".join(x for x in (d.get("code"), f"{EDITED}: {why}") if x)
            moved += 1
    return moved


def _code_failed(d: dict) -> bool:
    """Code compared this line and it FAILED (a rule compare, a provisional figure, a paper compare)."""
    cmp_ = d.get("code_compare")
    parts = {x.strip() for x in str(d.get("code") or "").split(";")}
    return (
        isinstance(cmp_, dict) and cmp_.get("result") == "fail"
    ) or PROVISIONAL_FAILS in parts


#: What a line's own words say when its claim is "not stated / missing" (read by code from the line, never from the editor).
_SAYS_MISSING = re.compile(
    r"\b(?:not\s+(?:stated|given|shown|provided|specified|indicated|found|listed|mentioned|filled)"
    r"|(?:is|are|was|left)\s+(?:blank|empty|missing)|missing|absent|no\s+(?:value|entry|figure|data)\b"
    r"|does\s+not\s+(?:state|show|give|specify|list|mention)|do(?:es)?\s+not\s+appear)",
    re.IGNORECASE,
)


def _claims_missing(d: dict) -> bool:
    """The line's own claim is that something is not stated: a Question or an AI opinion whose code note is "not on any page" or
    "no paper quote", or whose comment says so."""
    if d.get("label") not in ("Question", "AI opinion"):
        return False
    code = str(d.get("code") or "")
    return (
        NOT_ON_ANY_PAGE in code
        or "no paper quote" in code
        or bool(_SAYS_MISSING.search(str(d.get("comment") or "")))
    )


#: K2: a line's own words claim an ABSENCE or a LIMITATION ("only defined for", "limited to", "not covered", "missing for",
#: "no provision"): read by code from the line, never from the editor.
_CLAIMS_ABSENCE = re.compile(
    r"\b(?:only|limited\s+to|not\s+(?:covered|addressed|included|defined|described)|missing\s+for|no\s+provision"
    r"|does\s+not\s+(?:cover|address|include|define|describe))\b",
    re.IGNORECASE,
)
#: A quote from another page must be this long (folded) to answer a claim of absence.
MIN_ANY_PAGE_QUOTE = 40
#: Words too common to tie a quote to a line's field or topic.
_COMMON = frozenset(
    [
        "about",
        "after",
        "also",
        "been",
        "before",
        "being",
        "between",
        "both",
        "each",
        "from",
        "have",
        "into",
        "more",
        "must",
        "none",
        "only",
        "other",
        "over",
        "shall",
        "should",
        "such",
        "than",
        "that",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "under",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "will",
        "with",
        "within",
        "without",
        "would",
        "paper",
        "item",
        "items",
        "value",
        "values",
        "stated",
        "state",
        "page",
    ]
)


def _content_words(text) -> set[str]:
    return {
        w
        for w in re.findall(r"[a-z0-9]+", norm(str(text or "")))
        if len(w) >= 4 and w not in _COMMON
    }


def _claims_absence(d: dict) -> bool:
    """The line claims something is missing, not covered, limited or "only" (a Question or an AI opinion), by its own words."""
    return _claims_missing(d) or (
        d.get("label") in ("Question", "AI opinion")
        and bool(_CLAIMS_ABSENCE.search(str(d.get("comment") or "")))
    )


def _label_printed(d: dict, paper) -> bool:
    """The line's field label is printed on the paper (a datasheet): then the strict E1 rule holds (its own page, label + value)."""
    label = norm(str(d.get("field") or ""))
    return len(label) >= 4 and any(label in norm(t) for t in paper.pages.values())


def _answered_elsewhere(d: dict, quote: str, paper, hint) -> int | None:
    """K2: the page of a quote that answers the line's claim from ANY page: at least MIN_ANY_PAGE_QUOTE characters, sharing at
    least two content words with the line's field or topic, and found on a page of the paper by code. Else None."""
    if len(norm(quote)) < MIN_ANY_PAGE_QUOTE:
        return None
    tied = _content_words(f"{d.get('field') or ''} {d.get('topic') or ''}")
    if len(tied & _content_words(quote)) < 2:
        return None
    return find_page(quote, paper.pages, hint if isinstance(hint, int) else None)


def _states_value(quote: str, field: str) -> bool:
    """The quote holds the line's field label (folded) followed by a value: not empty, not a blank or deferral form."""
    from app import blank_markers

    label, q = norm(field), norm(quote)
    at = q.find(label) if label else -1
    if at < 0:
        return False
    value = q[at + len(label) :].lstrip(" :=-")
    if not re.search(r"[a-z0-9]", value):
        return False
    blank, _marker = blank_markers.classify(value)
    return not (blank or blank_markers.is_whole_deferral(value, value_field=True))


def _same_place(a: dict, b: dict) -> bool:
    """Two lines about the same place: the same page AND the same verified quote or the same compared value."""
    if a.get("page") is None or a.get("page") != b.get("page"):
        return False
    qa, qb = norm(a.get("quote") or ""), norm(b.get("quote") or "")
    if qa and qa == qb:
        return True
    ca, cb = a.get("code_compare"), b.get("code_compare")
    return (
        isinstance(ca, dict)
        and isinstance(cb, dict)
        and ca.get("paper") is not None
        and ca.get("paper") == cb.get("paper")
    )


def _edit_reason(
    mv: dict, n: int, offered: dict, sent: dict, paper, kind: str | None = None
) -> str | None:
    """Code's check of one move of an OFFERED line (never a code-proven failure): the reason words, or None (refused: the line
    stays sent). "repeats": line `of` is real, sent, not this line, and about the same place (`_same_place`). "paper states
    otherwise": `_contradicted` (a datasheet: the strict E1 rule on the line's own page; any other kind: K2, a claim of absence
    answered by a checked quote from ANY page)."""
    d = offered[n]
    if mv.get("reason") == REPEATS:
        m = mv.get("of")
        if not isinstance(m, int) or m == n or m not in sent:
            return None
        return f"repeats line {m}" if _same_place(d, sent[m]) else None
    if mv.get("reason") == CONTRADICTED:
        return _contradicted(d, str(mv.get("quote") or ""), mv.get("page"), paper, kind)
    return None


def _contradicted(
    d: dict, quote: str, named_page, paper, kind: str | None = None
) -> str | None:
    """'Paper states otherwise', checked by code. Never for a line code compared (any result). A line whose field label is
    printed on the paper (a datasheet) keeps the strict E1 rule: it claims "not stated", the quote is on ITS page and holds its
    label with a value. Any other line (a procedure) may be answered from ANY page when it claims an absence or a limitation
    (`_claims_absence`) and the quote passes `_answered_elsewhere` (K2)."""
    if isinstance(d.get("code_compare"), dict):
        return None
    # a datasheet keeps the strict E1 rule (by the paper's kind; with no kind known, by its field label printed on the paper)
    if (kind == "datasheet") if kind else _label_printed(d, paper):
        page = d.get("page") if d.get("page") is not None else named_page
        if not _claims_missing(d) or not isinstance(page, int):
            return None
        if not quote_in(quote, paper.pages.get(page, "")) or not _states_value(
            quote, str(d.get("field") or "")
        ):
            return None
    else:
        page = (
            _answered_elsewhere(d, quote, paper, named_page)
            if _claims_absence(d)
            else None
        )
        if page is None:
            return None
    return f'paper states otherwise (page {page}: "{quote[:200]}")'
