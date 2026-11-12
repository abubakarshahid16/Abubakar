"""Does the paper have any stored text for the AI reviewer to read? (order 13, C2; owner 12 Nov 2026, point 12)

A paper that reaches the reviewer with nothing to read must never be "asked 0 rules" in silence. This module looks at what the
library holds for the paper (page rows, page text, search chunks) and says, in one plain sentence, what is missing:

  state "no text"        no page of the paper holds any stored text (no pages, or only blank / scanned pages with nothing
                         recognised). The run STOPS before any rule is chosen and before any AI call.
  state "not indexed"    pages have text but the paper has no stored search chunks, so no rule book can be chosen for it.
                         The run STOPS the same way.
  state "still reading"  the library is still reading the paper in (its status is not ready yet): the run STOPS and says to wait.
  state "partly readable"  some pages have text, some have none: the review RUNS, and the pages with no text are listed.
  state "readable"       every page has text.

Words and numbers only: page numbers and counts, never a page's text. General (rule 13): no layout, no paper kind.
"""

from __future__ import annotations

from dataclasses import dataclass, field

NO_TEXT = "no_paper_text"
NOT_INDEXED = "paper_text_not_indexed"
STILL_READING = "paper_still_reading"
NO_RULE = "no_rule_asked"
#: the stop codes of this module (the first word of the run's stop reason, before the colon).
STOP_CODES = (NO_TEXT, NOT_INDEXED, STILL_READING, NO_RULE)
#: the document states that mean the library is still reading the paper in (`states.py`).
IN_PROGRESS = ("queued", "extracting", "chunking", "indexing_keyword")

ADVICE = "Check its status on the Documents screen (waiting for recognition, failed, no searchable content) or upload a readable copy, then review again."
SENTENCE_NO_TEXT = (
    "This paper has no readable text in the library. "
    + ADVICE
    + " The AI review asked no rule."
)
SENTENCE_NOT_INDEXED = (
    "This paper's text is stored but not indexed for search, so the AI review could not choose rule books for it. "
    + ADVICE.replace(" or upload a readable copy", "")
    + " The AI review asked no rule."
)
SENTENCE_STILL_READING = "This paper is still being read in: try again when its status is ready. The AI review asked no rule."
#: the one table of causes for a plan that ends with nothing to ask (code -> sentence; numbers filled in by `empty_plan_sentence`).
SENTENCE_NO_ROWS = (
    "The AI review asked no rule: 0 stored rules came from the rule books selected for this paper "
    "(no rule book was selected, or the selected books hold no rules for it)."
)
SENTENCE_ALL_LEFT_OUT = "The AI review asked no rule: {looked} stored rules were looked at and 0 fit this paper ({reasons})."
SENTENCE_NO_CAUSE = "The AI review asked no rule and the plan recorded no further cause: 0 rules and 0 checklist items were left to ask."
#: the longest page list written into the sentence (the full list is always in `pages_not_read`).
MAX_PAGES_IN_SENTENCE = 20

_STATE_CODE = {
    "no text": NO_TEXT,
    "not indexed": NOT_INDEXED,
    "still reading": STILL_READING,
}


@dataclass(frozen=True)
class PaperText:
    state: str  # "readable" | "partly readable" | "no text" | "not indexed" | "still reading"
    pages_total: int | None
    pages_not_read: list[int] = field(default_factory=list)
    sentence: str | None = None

    @property
    def stop_code(self) -> str | None:
        return _STATE_CODE.get(self.state)

    @property
    def stop(self) -> str | None:
        """The run's stop reason ("<code>: <sentence>"), or None when the review may run."""
        code = self.stop_code
        return f"{code}: {self.sentence}" if code else None

    def stops_run(self, general: bool) -> bool:
        """True when the run must stop before any rule is chosen. A general review (a procedure, a contract) chooses no rule book
        from the search chunks and reads the page text itself, so only "no text" and "still reading" stop it; "not indexed"
        stops the rule review."""
        return self.stop_code is not None and not (
            general and self.state == "not indexed"
        )

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "pages_total": self.pages_total,
            "pages_not_read": list(self.pages_not_read),
            "sentence": self.sentence,
        }


def partly_sentence(pages: list[int], total: int) -> str:
    """True whether or not any rule was asked: it says only which pages of this paper have no readable text."""
    shown = ", ".join(str(p) for p in pages[:MAX_PAGES_IN_SENTENCE])
    more = len(pages) - MAX_PAGES_IN_SENTENCE
    tail = f" and {more} more" if more > 0 else ""
    return (
        f"{len(pages)} of {total} pages of this paper have no readable text (page{'' if len(pages) == 1 else 's'} "
        f"{shown}{tail})."
    )


def read(conn, paper: str) -> PaperText:
    """The state of the paper's stored text. Read only."""
    row = conn.execute(
        "SELECT page_count, status FROM documents WHERE id = ?", (paper,)
    ).fetchone()
    declared = row[0] if row and isinstance(row[0], int) and row[0] > 0 else 0
    reading = bool(row) and str(row[1] or "") in IN_PROGRESS
    stored = {
        int(r[0]): bool((r[1] or "").strip())
        for r in conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ?", (paper,)
        )
    }
    total = max(declared, max(stored, default=0))
    with_text = sorted(n for n, has in stored.items() if has)
    not_read = [n for n in range(1, total + 1) if not stored.get(n)]
    chunked = conn.execute(
        "SELECT 1 FROM chunks WHERE document_id = ? AND TRIM(COALESCE(text, '')) <> '' LIMIT 1",
        (paper,),
    ).fetchone()
    if reading and (not with_text or chunked is None):
        return PaperText(
            "still reading", total or None, not_read, SENTENCE_STILL_READING
        )
    if not with_text:
        return PaperText("no text", total or None, not_read, SENTENCE_NO_TEXT)
    if chunked is None:
        return PaperText("not indexed", total, not_read, SENTENCE_NOT_INDEXED)
    if not_read:
        return PaperText(
            "partly readable", total, not_read, partly_sentence(not_read, total)
        )
    return PaperText("readable", total, [], None)


def read_step(conn, submittal: str, scope, run_id: str) -> PaperText:
    """The paper's text state FIRST; the read step (which can call a reader) runs only when the paper is not already known to
    hold no text. A paper with no text, or still being read in, makes no call of any kind. A read step that found nothing on
    a paper that holds text but no chunks is said as the stop; a stored file that is absent, or nothing read on a paper that
    holds text and chunks, stays a loud failure as before."""
    from . import nothing_read

    text = read(conn, submittal)
    if text.state in ("no text", "still reading"):
        return text
    try:
        nothing_read.read_phase(submittal, scope, run_id)
    except nothing_read.StoredFileAbsent:
        raise
    except nothing_read.NothingRead:
        if text.stop is None:
            raise
    return read(conn, submittal)


def record(conn, run_id: str, text: PaperText) -> None:
    """Write the paper's text state into the run row (both the rule review and the general review): one function."""
    import json

    with conn:
        conn.execute(
            "UPDATE agent_review_run SET equipment_json = json_set(COALESCE(NULLIF(equipment_json, ''), '{}'),"
            " '$.paper_text', json(?)) WHERE run_id = ?",
            (json.dumps(text.as_dict()), run_id),
        )


def empty_plan_sentence(plan: dict, left_out_words: dict | None = None) -> str:
    """WHY a finished plan holds nothing to ask (0 items). One function, one table of sentences, each literally true of what
    the plan knows; never empty, so a run is never "0 rules" with no words."""
    block = plan.get("block") or {}
    rows = (block.get("candidates") or {}).get("rows")
    counts = {
        k: v
        for k, v in (block.get("counts") or {}).items()
        if isinstance(v, int) and v > 0
    }
    looked = sum(counts.values())
    if rows == 0:
        return SENTENCE_NO_ROWS
    if looked > 0:
        words = left_out_words or {}
        reasons = ", ".join(
            f"{words.get(k, k)}: {v}" for k, v in sorted(counts.items())
        )
        return SENTENCE_ALL_LEFT_OUT.format(looked=looked, reasons=reasons)
    return SENTENCE_NO_CAUSE


def ensure_stop(plan: dict, left_out_words: dict | None = None) -> dict:
    """A plan with no item always carries a stop with its sentence (kept as it is when it already has one)."""
    if not plan.get("items") and not plan.get("stop"):
        plan["stop"] = f"{NO_RULE}: {empty_plan_sentence(plan, left_out_words)}"
    return plan
