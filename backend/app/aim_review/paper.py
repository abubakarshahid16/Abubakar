"""THE one input of the general review: a paper is its stored page texts, read from the database (`pages`, and for a page with no
text layer its recognised text in `page_ocr`), never from a folder. Nothing about the paper's kind is learnt here.

A long paper is judged by page windows: the deterministic split of `kind_review_table.windows` (the one walk,
`agent_general_review.window_pages`), with the kind's `window_tokens` and `overlap_pages`; a kind with no window size uses
DEFAULT_WINDOW_TOKENS. A paper that fits is ONE window, the whole paper, exactly as the measured experiment judged it.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_WINDOW_TOKENS = 60_000
DEFAULT_OVERLAP_PAGES = 1


@dataclass
class Paper:
    paper_id: str  # the library document the text comes from (it is what the gate is told the prompts carry)
    pages: dict[int, str]

    def text_with_markers(self, only: list[int] | None = None) -> str:
        keep = set(only) if only is not None else None
        return "\n".join(
            f"=== PAGE {n} ===\n{t}"
            for n, t in sorted(self.pages.items())
            if keep is None or n in keep
        )

    @property
    def chars(self) -> int:
        return sum(len(t) for t in self.pages.values())


def load_paper(conn, paper_id: str) -> Paper:
    """The paper's stored pages (`agent_review_standards.read_book`: `pages.text`, else the page's recognised text). An empty
    dict when nothing is stored: the caller stops with a code, never a guess."""
    from app import agent_review_standards

    book = agent_review_standards.read_book(conn, str(paper_id))
    return Paper(paper_id=str(paper_id), pages=dict(book.pages))


def windows(paper: Paper, kind: str | None) -> list[list[int]]:
    """The page windows the judge reads: one window (every page) when the paper fits."""
    from app import agent_general_review, kind_review_table

    try:
        limit, overlap = kind_review_table.window_settings(_table_kind(kind))
    except (KeyError, ValueError, TypeError):
        limit, overlap = 0, 0
    if limit <= 0:
        limit, overlap = DEFAULT_WINDOW_TOKENS, DEFAULT_OVERLAP_PAGES
    return agent_general_review.window_pages(paper.pages, int(limit), int(overlap))


def _table_kind(kind: str | None) -> str:
    """The method's kind in the kind table's spelling ("test record" -> "test_record"); unknown for none."""
    return str(kind or "unknown").strip().lower().replace(" ", "_")
