"""Order 4c (2 Nov): the CRS fields of a procedure or other non-datasheet kind.

Seen on a procedure review: the sheet named an equipment type the document does not
have, its page cells stayed empty beside a quote, and its Item No carried a
document-id fragment. Behind `settings.procedure_crs_fields_enabled`; off, every
function here hands back what it was given. Read only: no model, no write.

1. EQUIPMENT. A document whose kind is known and is not a datasheet has no
   equipment type ON THE CRS. `document_classification.equipment_type` keeps its
   value on purpose: the subject gates of the review still read it, and blanking
   it sent 236 requirements to "needs another document" on a saved procedure run
   (`kind_rules.for_run`). An undecided or guessed kind stays as it was.
2. PAGE. A row's page cell comes from the page its quote verifies on, with the one
   verifier AI quotes pass (`clause_review.verify_quote`). A quote verified nowhere,
   or on several pages with none stated, gives no page, never a guess.
3. NUMBER. Where the document states its number on its cover or title block, that
   number is a suggestion, printed marked (`crs_numbers.no_number_label`) and never
   stored. Two different numbers there: no suggestion, no choosing between them.
"""

from __future__ import annotations

import re

from . import classification, crs_numbers, document_kind, kind_rules
from .clause_review import page_texts, verify_quote
from .config import settings
from .crs_draft_lanes import CLAUSE_ORIGIN
from .db import connect
from .procedure_text import FOUND

#: How many of the first page's non-empty lines count as its cover, besides the
#: title block lines (`classification.title_block_lines`).
COVER_LINES = 40
MAX_NUMBER_CHARS = 60
_EQUIPMENT_METHODS = frozenset({"equipment_type", "governing_standard"})
#: The words a stored selection reason uses when it names the type it read.
_NAMES_A_TYPE = re.compile(r"read from (?:the submittal's|its)\b|\bgoverns an? ", re.I)
METHOD_NOT_FOR_KIND = "not by equipment type"
REASON_NOT_FOR_KIND = (
    "Chosen by an equipment reading when this run was made; this document is a "
    "{kind} and has no equipment type. Engineer to check whether it applies."
)
_PAGE_LEAD = re.compile(r"^p\.\s*\d[\d,\s\-]*(?:\s-\s)?")
_FOUND_QUOTE = re.compile(rf'^{FOUND}: found on page (\d+): "(.+?)" - ', re.S)
_LABELLED = re.compile(document_kind._NUMBER_LABEL.pattern + r"[\s:.|#-]*(\S*)", re.I)


def no_equipment(document_id: str | None) -> bool:
    """True when this document's CRS must carry no equipment type."""
    return settings.procedure_crs_fields_enabled and kind_rules.not_a_datasheet(
        document_id
    )


def standards_sheet(rows: list[dict], document_id: str) -> list[dict]:
    """The "Applicable standards" rows. A standard the stored run chose by equipment
    stays listed (it was used), with words that name no type."""
    if not no_equipment(document_id):
        return rows
    kind = kind_rules._lookup(document_id)[0]
    return [
        {
            **row,
            "method": METHOD_NOT_FOR_KIND,
            "reason": REASON_NOT_FOR_KIND.format(kind=kind),
        }
        if row.get("method") in _EQUIPMENT_METHODS
        or _NAMES_A_TYPE.search(str(row.get("reason") or ""))
        else row
        for row in rows
    ]


# ------------------------------------------------------------------ page cell


def _finding_quote(finding: dict) -> tuple[str, int | None] | None:
    """(quote, the page it names) a finding stands on; None for a value row, whose
    evidence text is a field's value and not a quote."""
    match = _FOUND_QUOTE.match(finding.get("ai_rationale") or "")
    if match:
        return match.group(2), int(match.group(1))
    if finding.get("origin") == CLAUSE_ORIGIN and finding.get(
        "contractor_evidence_text"
    ):
        return finding["contractor_evidence_text"], finding.get("contractor_page")
    return None


def verified_page(quote: str, stated: int | None, texts: dict[int, str]) -> int | None:
    """The page the quote is proved on: the stated page when it holds it, else the
    ONE page that does. None when no page does or several do."""
    if stated in texts and verify_quote(quote, texts[stated]):
        return stated
    hits = [page for page, text in texts.items() if verify_quote(quote, text)]
    return hits[0] if len(hits) == 1 else None


def _page_words(pages: list[int]) -> str:
    return "p." + ", ".join(str(p) for p in pages)


def fill_pages(rows: list[dict], findings: list[dict], document_id: str) -> None:
    """Set each quoted row's page cell, in place, from where its quotes verify. A row
    with no quote is left alone. A row whose quotes verify nowhere loses a printed
    page: it was not proved."""
    if not settings.procedure_crs_fields_enabled:
        return
    by_id = {f.get("id"): f for f in findings}
    texts: dict[int, str] | None = None
    for row in rows:
        ids = row.get("finding_ids") or [row.get("finding_id")]
        quotes = [q for q in (_finding_quote(by_id.get(i) or {}) for i in ids) if q]
        if row.get("quote"):
            quotes.append((row["quote"], None))
        if not quotes:
            continue
        if texts is None:
            texts = page_texts(document_id)
        pages = sorted(
            {p for q, stated in quotes if (p := verified_page(q, stated, texts))}
        )
        rest = _PAGE_LEAD.sub("", str(row.get("page_section") or ""))
        lead = _page_words(pages) if pages else ""
        row["page_section"] = f"{lead} - {rest}" if lead and rest else lead or rest


# --------------------------------------------------------- the document number


def _number_like(value: str) -> bool:
    """A document number carries a digit and a separator (`_document_number_hits`)."""
    return (
        0 < len(value) <= MAX_NUMBER_CHARS
        and bool(re.search(r"\d", value))
        and bool(re.search(r"[-/]", value))
        and not classification._is_placeholder(value)
    )


def _cover_lines(pages: list[dict]) -> list[tuple[int, str]]:
    ordered = sorted(pages, key=lambda p: p["page_no"])
    first = [ln.strip() for ln in (ordered[0].get("text") or "").splitlines()]
    cover = [(ordered[0]["page_no"], ln) for ln in first if ln][:COVER_LINES]
    block = [(p, ln.strip()) for p, ln in classification.title_block_lines(ordered)]
    return list(dict.fromkeys(cover + block))


def _numbers_in(lines: list[tuple[int, str]]) -> list[tuple[str, int, str]]:
    """(number, page, the line(s) it was read from) on labelled or whole-number lines."""
    out = []
    for index, (page, line) in enumerate(lines):
        labelled = _LABELLED.search(line)
        if labelled:
            value, quote = labelled.group(1).strip("|:;,. "), line
            if not value and index + 1 < len(lines):
                value = lines[index + 1][1].strip("|:;,. ")
                quote = f"{line} {lines[index + 1][1]}"
            if _number_like(value):
                out.append((value, page, quote))
        elif document_kind._BARE_NUMBER.fullmatch(line) and _number_like(line):
            out.append((line, page, line))
    return out


def read_number(pages: list[dict]) -> dict | None:
    """{"number", "page", "quote"}: the one number the cover states. Pure over page
    rows. None when it states none, or two different ones."""
    if not pages:
        return None
    metadata = classification.suggest_submittal_metadata(pages)
    if "document_number" in metadata.conflicts:
        return None
    found = metadata.found.get("document_number")
    if found is not None:
        return {"number": found.value, "page": found.page, "quote": found.quote}
    numbers = _numbers_in(_cover_lines(pages))
    if len({classification._identity(n) for n, _p, _q in numbers}) != 1:
        return None
    number, page, quote = numbers[0]
    return {"number": number, "page": page, "quote": quote}


def suggested_number(document_id: str) -> dict | None:
    pages = [
        dict(r)
        for r in connect().execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
            (document_id,),
        )
    ]
    return read_number(pages)


def number_notes(document_id: str, scope_key: str, label: str) -> list[dict]:
    """The Review note that says what the Item No label is. None for a real number."""
    if not settings.procedure_crs_fields_enabled or not scope_key.startswith("doc:"):
        return []
    if label == crs_numbers.NO_NUMBER_LABEL:
        note = "Item numbers: no document number"
        detail = (
            f"{label} is not a document number: no number was found on this document's "
            "cover or title block, so its items are numbered in a sequence of their own. "
            "Recording the document number prints it instead."
        )
    elif label.endswith(crs_numbers.SUGGESTED_SUFFIX):
        found = suggested_number(document_id) or {}
        note = "Item numbers: document number suggested"
        detail = (
            f"A guess until an engineer records the document number: read from page "
            f'{found.get("page")}: "{found.get("quote")}".'
        )
    else:
        return []
    return [{"note": note, "standard": "", "count": None, "detail": detail}]


def other_document(quoted_label: str, reply: dict, document_id: str) -> bool:
    """NO-NUMBER is not unique to one document, so a reply quoting it must also name
    this document (the sheet's Document Name column), or it is not matched."""
    if (
        not settings.procedure_crs_fields_enabled
        or quoted_label != crs_numbers.NO_NUMBER_LABEL
    ):
        return False
    row = (
        connect()
        .execute("SELECT filename FROM documents WHERE id = ?", (document_id,))
        .fetchone()
    )
    name = reply.get("document_name") or ""
    return (
        row is None or name.strip().lower() != (row["filename"] or "").strip().lower()
    )
