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
  * nothing  -> MISSING_INFORMATION: "no passage found; contractor to show where".
  * NEVER COMPLIANT from a text match. No model is called (the AI clause
    review is #1477).

SWITCH: `settings.procedure_path_enabled`, OFF by default.
"""

from __future__ import annotations

import re

from .config import settings
from .db import connect

PROCEDURE_KINDS = frozenset({"procedure", "specification"})
#: Evidence types a procedure IS (so its own text answers them). A certificate,
#: drawing, report, calculation or record is another document: never here (#163).
OWN_TEXT_EVIDENCE = frozenset({"procedure", "plan"})

FOUND = "procedure_text_found"
NOT_FOUND = "procedure_text_not_found"

_STOP = frozenset(
    "shall should must will would could may might can be been being is are was were have has had "
    "the and for with that this these those from into onto upon than then them they their there "
    "such any all each every other which where when while whose also only not nor but are its "
    "per via use used using ensure ensured provide provided make made need needed required "
    "requirement requirements accordance applicable".split())
_WORD = re.compile(r"[a-z][a-z0-9\-]{3,}")
_SENTENCE_END = re.compile(r"(?<=[.;:!?])\s+|\n+")
#: A passage must carry at least this share of the requirement's key words,
#: and at least two of them (one when the requirement has only one).
MIN_SHARE = 0.6
MAX_QUOTE = 400


def _stem(word: str) -> str:
    for suffix in ("ing", "es", "ed", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def key_words(text: str | None) -> frozenset[str]:
    return frozenset(
        _stem(w) for w in _WORD.findall((text or "").lower()) if w not in _STOP)


def document_kind(document_id: str) -> str | None:
    """`document_classification.document_kind` when #1474's column exists, else None."""
    conn = connect()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(document_classification)")}
    if "document_kind" not in cols:
        return None
    row = conn.execute(
        "SELECT document_kind FROM document_classification WHERE document_id = ?",
        (document_id,)).fetchone()
    return ((row[0] or "").lower() or None) if row else None


def is_procedure_submittal(document_id: str | None) -> bool:
    """True when the switch is on and the submittal is a procedure.

    The column is read when it exists; until then an explicit id list
    (`procedure_path_document_ids`) says so. NEVER guessed from the text."""
    if not settings.procedure_path_enabled or not document_id:
        return False
    listed = {x.strip() for x in settings.procedure_path_document_ids.split(",") if x.strip()}
    return document_id in listed or document_kind(document_id) in PROCEDURE_KINDS


def load_pages(document_id: str) -> list[tuple[int, str]]:
    return [(r["page_no"], r["text"] or "") for r in connect().execute(
        "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
        (document_id,))]


def find_passage(requirement_text: str | None, pages: list[tuple[int, str]]) -> dict | None:
    """The best passage of `pages` for the requirement, or None.

    {page, quote}: `quote` is a slice of that page's stored text (verified)."""
    wanted = key_words(requirement_text)
    if not wanted:
        return None
    need = max(1, min(2, len(wanted)))
    best: tuple[float, int, int, str] | None = None
    for page_no, text in pages:
        for part in _SENTENCE_END.split(text):
            hit = len(wanted & key_words(part))
            share = hit / len(wanted)
            if hit >= need and share >= MIN_SHARE and (best is None or (share, hit) > best[:2]):
                best = (share, hit, page_no, part.strip()[:MAX_QUOTE])
    if best is None:
        return None
    page_no, quote = best[2], best[3]
    if quote not in dict(pages)[page_no]:  # code, not the search, vouches for the quote
        return None
    return {"page": page_no, "quote": quote}


def verdict(requirement: dict, pages: list[tuple[int, str]]) -> dict:
    """The row for a procedure requirement: an engineer's, or a blank. Never COMPLIANT."""
    text = requirement.get("source_text") or requirement.get("requirement_text")
    found = find_passage(text, pages)
    base = {"limit": None, "observed": None, "exception_applied": None}
    if found is None:
        return {**base, "status": "MISSING_INFORMATION", "rationale": (
            f"{NOT_FOUND}: no passage of this procedure was found for the requirement; "
            f"contractor to show where it is addressed")}
    quote = " ".join(found["quote"].split())
    return {**base, "status": "NEEDS_ENGINEER_REVIEW", "rationale": (
        f"{FOUND}: found on page {found['page']}: \"{quote}\" - this is the closest passage by its "
        f"words, not a finding that the requirement is met; engineer to confirm")}
