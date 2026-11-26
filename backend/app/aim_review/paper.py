"""THE one input of the general review: a paper's page texts, for the paper as the app stored it (its row in `documents`, its
`pages` and `page_ocr`), never from a folder. Nothing about the paper's kind is learnt here.

READING ORDER. Ingestion stores `get_text("text")`, which follows the PDF's content stream. A PDF whose fields were filled in or
edited after it was made has the added text at the END of the stream: the label "Set pressure psig" sits mid-page with its value
missing and the value stands alone at the bottom, so the judge reads the value as blank or left open. A person reads the page in
visual order. So each page is read again from the app's own stored upload in visual order (`get_text("text", sort=True)`, under
`pdf_guard`), for any PDF. A page falls back to the stored `pages.text`, then the page's recognised text (`page_ocr`), when the
file is not a PDF, is a Word document (no printed pages), cannot be found or opened, or the sorted page has no text (a scanned
page). The judge AND the quote check read the same `Paper.pages`; `Paper.sources` says where each page came from (no text).

A long paper is judged by page windows: the deterministic split of `kind_review_table.windows` (the one walk,
`agent_general_review.window_pages`), with the kind's `window_tokens` and `overlap_pages`; a kind with no window size uses
DEFAULT_WINDOW_TOKENS. A paper that fits is ONE window, the whole paper, exactly as the measured experiment judged it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .budget import cap

log = logging.getLogger(__name__)

DEFAULT_WINDOW_TOKENS = 60_000
DEFAULT_OVERLAP_PAGES = 1

#: Where a page's text came from (`Paper.sources`): the stored PDF in visual order, the stored text, the recognised text.
FROM_PDF, FROM_STORED, FROM_OCR = "pdf_visual_order", "stored_text", "recognised_text"
#: A page Claude transcribed from its picture (`picture_stage`, the upload's picture reading; such a page is stored as recognised text): the page held no text and local recognition found none.
FROM_PICTURE = "claude_picture_reading"


@dataclass
class Paper:
    paper_id: str  # the library document the text comes from (it is what the gate is told the prompts carry)
    pages: dict[int, str]
    sources: dict[int, str] = field(
        default_factory=dict
    )  # page -> FROM_PDF | FROM_STORED | FROM_OCR
    file_note: str = (
        ""  # why the stored file was not read (a code word), "" when it was
    )
    unread: list = field(
        default_factory=list
    )  # [{"where": "page 7", "why": code}]: pages with no text and no picture reading (`unread`)
    unread_checked: bool = False  # True only when the unread pages were really worked out (a check that failed or a missing file is not "none")

    def source_note(self) -> str:
        """Counts only, never text: "pages: 4 pdf_visual_order, 1 recognised_text" (+ why the file was not read)."""
        counts: dict[str, int] = {}
        for src in self.sources.values():
            counts[src] = counts.get(src, 0) + 1
        note = "pages: " + ", ".join(
            f"{counts[k]} {k}"
            for k in (FROM_PDF, FROM_STORED, FROM_OCR, FROM_PICTURE)
            if k in counts
        )
        return note + (f"; file not read: {self.file_note}" if self.file_note else "")

    def text_with_markers(self, only: list[int] | None = None) -> str:
        """The pages as the model reads them: a page printed in two halves side by side (`layout.halves`) as its left half,
        then its right half, under the same page number; any other page as it is. The quote check reads `pages` as stored."""
        keep = set(only) if only is not None else None
        return "\n".join(
            _marked(n, t)
            for n, t in sorted(self.pages.items())
            if keep is None or n in keep
        )

    @property
    def chars(self) -> int:
        return sum(len(t) for t in self.pages.values())


def _marked(n: int, text: str) -> str:
    from .layout import halves, with_pairs

    two = halves(text)
    if two is None:
        return f"=== PAGE {n} ===\n{with_pairs(text)}"
    left, right = (with_pairs(x) for x in two)
    return (
        f"=== PAGE {n} (left half) ===\n{left}\n=== PAGE {n} (right half) ===\n{right}"
    )


def load_paper(conn, paper_id: str, data_dir=None) -> Paper:
    """The paper's pages: each page of the stored PDF in visual reading order, else the stored text
    (`agent_review_standards.read_book`: `pages.text`, else the page's recognised text). An empty dict when nothing is stored
    or readable: the caller stops with a code, never a guess. `data_dir` is where relative stored paths live (default: the
    app's `settings.data_dir`)."""
    from app import agent_review_standards

    book = agent_review_standards.read_book(conn, str(paper_id))
    scanned = set(book.ocr)
    pages = dict(book.pages)
    sources = {n: (FROM_OCR if n in scanned else FROM_STORED) for n in pages}
    visual, note = _visual_pages(conn, str(paper_id), data_dir)
    for n, text in visual.items():
        # A scanned page keeps its recognised text: the few characters a scan's text layer may hold (a stamp) are not the page.
        if text.strip() and n not in scanned:
            pages[n], sources[n] = text, FROM_PDF
    return Paper(paper_id=str(paper_id), pages=pages, sources=sources, file_note=note)


def _visual_pages(conn, paper_id: str, data_dir) -> tuple[dict[int, str], str]:
    """({page: text in visual order}, "") from the stored PDF; ({}, code word) when there is no PDF to read. Never raises."""
    from app import agent_review_pages, pdf_guard

    try:
        ref = agent_review_pages.document_ref(conn, paper_id)
        if (ref.get("pagination") or "") == "flow":
            return {}, "no_printed_pages"
        if data_dir is None:
            from app.config import settings

            data_dir = settings.data_dir
        path = agent_review_pages.pdf_path(ref, data_dir)
        with path.open("rb") as fh:
            if not fh.read(1024).lstrip().startswith(b"%PDF"):
                return {}, "not_a_pdf"
        out: dict[int, str] = {}
        with pdf_guard.opened(str(path)) as pdf:
            for i in range(pdf.page_count):
                with (
                    pdf_guard.held()
                ):  # one short read per page: page images are not frozen meanwhile
                    out[i + 1] = _tidy(
                        pdf.load_page(i).get_text("text", sort=True) or ""
                    )
        return out, ""
    except agent_review_pages.PageImageUnavailable as exc:
        return {}, str(exc)
    except Exception as exc:  # noqa: BLE001 - a file that cannot be read falls back to the stored text; logged by class only
        log.info(
            "general review: stored file of %s not read (%s)",
            paper_id,
            type(exc).__name__,
        )
        return {}, f"unreadable:{type(exc).__name__}"


def _tidy(text: str) -> str:
    """Trailing spaces off each line and runs of blank lines down to one (the sorted reading leaves gaps); words untouched."""
    lines = [ln.rstrip() for ln in text.splitlines()]
    out: list[str] = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip("\n")


def windows(paper: Paper, kind: str | None) -> list[list[int]]:
    """The page windows the judge reads: one window (every page) when the paper fits."""
    from app import agent_general_review, kind_review_table

    try:
        limit, overlap = kind_review_table.window_settings(_table_kind(kind))
    except (KeyError, ValueError, TypeError):
        limit, overlap = 0, 0
    if limit <= 0:
        limit, overlap = DEFAULT_WINDOW_TOKENS, DEFAULT_OVERLAP_PAGES
    limit = cap(int(limit), "window_tokens")  # smaller on the local model (`budget`)
    return agent_general_review.window_pages(paper.pages, int(limit), int(overlap))


def _table_kind(kind: str | None) -> str:
    """The method's kind in the kind table's spelling ("test record" -> "test_record"); unknown for none."""
    return str(kind or "unknown").strip().lower().replace(" ", "_")
