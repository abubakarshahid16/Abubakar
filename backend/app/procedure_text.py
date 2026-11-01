"""#1476 THE PROCEDURE PATH: the document is the evidence.

A procedure submittal was reviewed as if it were an equipment datasheet, so its
procedure-type requirements were sent to "needs another document" (274 HAZOP
rows). Here, for a submittal whose kind is a procedure (or specification), the
requirement is looked up in the submittal's OWN stored page text.

What code may say, and no more:

  * found    -> NEEDS_ENGINEER_REVIEW: "found on page n: <quote>; engineer to
                confirm". The quote is cut from the stored page text and checked
                to be a real substring of it. Finding the subject's words is not
                proof the procedure MEETS the requirement.
  * nothing  -> NEEDS_ENGINEER_REVIEW: "a keyword search found no passage; engineer to
                check". Never MISSING_INFORMATION: a keyword search that finds
                nothing says what it searched, not that the document lacks it.
  * NEVER COMPLIANT from a text match. No model is called (the AI clause
    review is #1477).

SWITCH: `settings.procedure_path_enabled`, OFF by default.
"""

from __future__ import annotations

import contextvars
import re
from contextlib import contextmanager

from . import field_links, requirements_3b
from .config import settings
from .db import connect

PROCEDURE_KINDS = frozenset({"procedure", "specification"})
#: Evidence types a procedure IS (so its own text answers them). A certificate,
#: drawing, report, calculation or record is another document: never here (#163).
OWN_TEXT_EVIDENCE = frozenset({"procedure", "plan"})

FOUND = "procedure_text_found"
NOT_FOUND = "procedure_text_not_found"
TOO_SHORT = "procedure_text_too_short"

_STOP_TEXT = (
    "shall should must will would could may might can be been being is are was were have has had "
    "the and for with that this these those from into onto upon than then them they their there "
    "such any all each every other which where when while whose also only not nor but are its "
    "per via use used using ensure ensured provide provided make made need needed required "
    "requirement requirements accordance applicable maximum minimum material materials "
    "design service section clause general"
)
_STOP = frozenset(_STOP_TEXT.split())
_WORD = re.compile(r"[a-z][a-z0-9\-]{3,}")
_SENTENCE_END = re.compile(r"(?<=[.;:!?])\s+|\n+")
#: A passage must carry at least this share of the requirement's key words,
#: and at least MIN_HITS of them (all, when the requirement has fewer).
MIN_SHARE = 0.6
MIN_HITS = 3
MAX_QUOTE = 400


def _stem(word: str) -> str:
    for suffix in ("ing", "es", "ed", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def key_words(text: str | None) -> frozenset[str]:
    return frozenset(
        _stem(w) for w in _WORD.findall((text or "").lower()) if w not in _STOP
    )


def document_kind(document_id: str) -> str | None:
    """The router's kind (`document_kinds`, #1474/#1488): a confirmed kind, or a
    suggestion. `needs_engineer`, no row or no kind = None: no procedure path."""
    row = (
        connect()
        .execute(
            "SELECT kind, state FROM document_kinds WHERE document_id = ?",
            (document_id,),
        )
        .fetchone()
    )
    if row is None or row["state"] == "needs_engineer":
        return None
    return (row["kind"] or "").lower() or None


def is_procedure_submittal(document_id: str | None) -> bool:
    """True when the switch is on and the router says procedure or specification."""
    if not settings.procedure_path_enabled or not document_id:
        return False
    return document_kind(document_id) in PROCEDURE_KINDS


def load_pages(document_id: str) -> list[tuple[int, str]]:
    return [
        (r["page_no"], r["text"] or "")
        for r in connect().execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
            (document_id,),
        )
    ]


def find_passage(
    requirement_text: str | None, pages: list[tuple[int, str]]
) -> dict | None:
    """The best passage of `pages` for the requirement, or None.

    {page, quote}: `quote` is a slice of that page's stored text (verified)."""
    wanted = key_words(requirement_text)
    if not wanted:
        return None
    need = max(1, min(MIN_HITS, len(wanted)))
    best: tuple[float, int, int, str] | None = None
    for page_no, text in pages:
        for part in _SENTENCE_END.split(text):
            hit = len(wanted & key_words(part))
            share = hit / len(wanted)
            if (
                hit >= need
                and share >= MIN_SHARE
                and (best is None or (share, hit) > best[:2])
            ):
                best = (share, hit, page_no, part.strip()[:MAX_QUOTE])
    if best is None:
        return None
    page_no, quote = best[2], best[3]
    if quote not in dict(pages)[page_no]:  # code, not the search, vouches for the quote
        return None
    return {"page": page_no, "quote": quote}


#: The pages of the procedure under review, set only for the length of one
#: `run_comparison` (`reading`). None = not a procedure review: nothing is routed,
#: so every other caller of `comparison.compare` (rules, chat) is unchanged.
_PAGES: contextvars.ContextVar[list[tuple[int, str]] | None] = contextvars.ContextVar(
    "procedure_pages", default=None
)


@contextmanager
def using(pages: list[tuple[int, str]] | None):
    token = _PAGES.set(pages)
    try:
        yield
    finally:
        _PAGES.reset(token)


@contextmanager
def reading(review_run_id: str):
    """Pages of the run's submittal when it is a procedure (switch on), else None."""
    row = (
        connect()
        .execute(
            "SELECT submittal_document_id FROM review_runs WHERE id = ?",
            (review_run_id,),
        )
        .fetchone()
    )
    doc = row[0] if row else None
    with using(load_pages(doc) if is_procedure_submittal(doc) else None):
        yield


def route(requirement: dict, fact: dict | None) -> dict | None:
    """The procedure path's verdict for a requirement, or None (the usual path).

    Two cases that used to be sent to "needs another document": a demand for a
    procedure/plan (a procedure is its own evidence), and an unmatched statement
    (B9 R1) except one that only asks to be stated. A certificate, drawing or
    report demand is never routed here (#163)."""
    pages = _PAGES.get()
    if pages is None:
        return None
    evidence = requirement.get("required_evidence_type")
    own = evidence in OWN_TEXT_EVIDENCE
    text = requirement.get("source_text") or requirement.get("requirement_text")
    statement = (
        fact is None
        and evidence in (None, requirements_3b.DATA_SHEET_EVIDENCE)
        and requirement.get("requirement_type") == requirements_3b.STATEMENT
        and not field_links.asks_only_to_be_stated(text)
    )
    return verdict(requirement, pages) if own or statement else None


def verdict(requirement: dict, pages: list[tuple[int, str]]) -> dict:
    """The row for a procedure requirement: an engineer's, or a blank. Never COMPLIANT."""
    text = requirement.get("source_text") or requirement.get("requirement_text")
    if len(key_words(text)) < MIN_HITS:
        return {
            "limit": None,
            "observed": None,
            "exception_applied": None,
            "status": "NEEDS_ENGINEER_REVIEW",
            "rationale": f"{TOO_SHORT}: the requirement has too few distinguishing words to search this procedure for; engineer to check it",
        }
    found = find_passage(text, pages)
    base = {"limit": None, "observed": None, "exception_applied": None}
    if found is None:
        return {
            **base,
            "status": "NEEDS_ENGINEER_REVIEW",
            "rationale": (
                f"{NOT_FOUND}: a keyword search of the document's pages found no passage "
                f"for this requirement; engineer to check (the document may state it in other words)"
            ),
        }
    quote = " ".join(found["quote"].split())
    return {
        **base,
        "status": "NEEDS_ENGINEER_REVIEW",
        "rationale": (
            f'{FOUND}: found on page {found["page"]}: "{quote}" - this is the closest passage by its '
            f"words, not a finding that the requirement is met; engineer to confirm"
        ),
    }
