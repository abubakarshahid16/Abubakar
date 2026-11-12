"""Does the paper have any stored text for the AI reviewer to read? (order 13, C2; owner 12 Nov 2026, point 12)

A paper that reaches the reviewer with nothing to read must never be "asked 0 rules" in silence. This module looks at what the
library holds for the paper (page rows, page text, search chunks) and says, in one plain sentence, what is missing:

  state "no text"        no page of the paper holds any stored text (no pages, or only blank / scanned pages with nothing
                         recognised). The run STOPS before any rule is chosen and before any AI call.
  state "not indexed"    pages have text but the paper has no stored search chunks, so no rule book can be chosen for it.
                         The run STOPS the same way.
  state "partly readable"  some pages have text, some have none: the review RUNS, and the pages with no text are listed.
  state "readable"       every page has text.

Words and numbers only: page numbers and counts, never a page's text. General (rule 13): no layout, no paper kind.
"""

from __future__ import annotations

from dataclasses import dataclass, field

NO_TEXT = "no_paper_text"
NOT_INDEXED = "paper_text_not_indexed"
#: the stop codes of this module (the first word of the run's stop reason, before the colon).
STOP_CODES = (NO_TEXT, NOT_INDEXED)

SENTENCE_NO_TEXT = (
    "This paper has no readable text in the library: re-read it, then review again. "
    "No rule was asked and nothing was sent to the AI."
)
SENTENCE_NOT_INDEXED = (
    "This paper's text is stored but not indexed for search, so no rule book can be chosen for it: "
    "re-read it, then review again. No rule was asked and nothing was sent to the AI."
)
#: the longest page list written into the sentence (the full list is always in `pages_not_read`).
MAX_PAGES_IN_SENTENCE = 20


@dataclass(frozen=True)
class PaperText:
    state: str  # "readable" | "partly readable" | "no text" | "not indexed"
    pages_total: int | None
    pages_not_read: list[int] = field(default_factory=list)
    sentence: str | None = None

    @property
    def stop_code(self) -> str | None:
        return {"no text": NO_TEXT, "not indexed": NOT_INDEXED}.get(self.state)

    @property
    def stop(self) -> str | None:
        """The run's stop reason ("<code>: <sentence>"), or None when the review may run."""
        code = self.stop_code
        return f"{code}: {self.sentence}" if code else None

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "pages_total": self.pages_total,
            "pages_not_read": list(self.pages_not_read),
            "sentence": self.sentence,
        }


def partly_sentence(pages: list[int], total: int) -> str:
    shown = ", ".join(str(p) for p in pages[:MAX_PAGES_IN_SENTENCE])
    more = len(pages) - MAX_PAGES_IN_SENTENCE
    tail = f" and {more} more" if more > 0 else ""
    return (
        f"{len(pages)} of {total} pages have no stored text and were not read (page{'' if len(pages) == 1 else 's'} "
        f"{shown}{tail}). The rules were asked against the other pages only."
    )


def read(conn, paper: str) -> PaperText:
    """The state of the paper's stored text. Read only."""
    row = conn.execute(
        "SELECT page_count FROM documents WHERE id = ?", (paper,)
    ).fetchone()
    declared = row[0] if row and isinstance(row[0], int) and row[0] > 0 else 0
    stored = {
        int(r[0]): bool((r[1] or "").strip())
        for r in conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ?", (paper,)
        )
    }
    total = max(declared, max(stored, default=0))
    with_text = sorted(n for n, has in stored.items() if has)
    if not with_text:
        return PaperText(
            "no text", total or None, list(range(1, total + 1)), SENTENCE_NO_TEXT
        )
    chunked = conn.execute(
        "SELECT 1 FROM chunks WHERE document_id = ? AND TRIM(COALESCE(text, '')) <> '' LIMIT 1",
        (paper,),
    ).fetchone()
    not_read = [n for n in range(1, total + 1) if not stored.get(n)]
    if chunked is None:
        return PaperText("not indexed", total, not_read, SENTENCE_NOT_INDEXED)
    if not_read:
        return PaperText(
            "partly readable", total, not_read, partly_sentence(not_read, total)
        )
    return PaperText("readable", total, [], None)
