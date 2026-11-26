"""Chat with SEVERAL selected papers (owner's own use, planner 25 Nov 2026 23:35, note A): ten attached papers could not all be
read or answered, because one search returned 6 passages for all of them and a turn allowed 6 tool calls.

By code, no model:
  * `selected_block`: the first message lists every selected paper (title, status, pages) and asks for ONE pass PER PAPER, so
    Claude opens each of them; a paper still being read is named as such and is not opened.
  * `tool_cap`: a turn on N selected papers allows at least N + 2 tool calls (at most `MAX_TOOL_CALLS`).
  * `coverage`: the line under the answer, "read 8 of 10; 2 still processing", from what the turn's tools actually returned
    (a paper counts as read only when a tool brought back its text), never from the model's words.
  * `review_offer`: "review / check these" offers the real Review engine for each selected paper (the comment sheet), never a
    chat summary in its place.
Only the papers the caller selected AND may read are ever named (rule 5: the caller's selection narrows, never widens). No
document text is read or kept here: titles, statuses and counts.
"""

from __future__ import annotations

import re

from .db import connect

#: The largest selection this pass covers in one turn, and the most tool calls one turn may make.
MAX_PAPERS = 20
MAX_TOOL_CALLS = 24
#: A selection this size or more gets the per-paper pass.
MIN_PAPERS = 2

_REVIEW_WORDS = re.compile(
    r"\b(?:review|check|assess|evaluate|audit)\b(?!\s+(?:of|the\s+summary))",
    re.IGNORECASE,
)


def _rows(ids) -> list[dict]:
    ids = sorted({str(i) for i in ids})
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    rows = (
        connect()
        .execute(
            f"SELECT id, filename, status, page_count FROM documents WHERE id IN ({marks}) ORDER BY filename",
            ids,
        )
        .fetchall()
    )
    return [dict(r) for r in rows]


def _processing(status: str) -> bool:
    from . import states

    return status not in states.TERMINAL_STATES | {states.PARTIALLY_SEARCHABLE}


def applies(selected) -> bool:
    return MIN_PAPERS <= len(selected or ()) <= MAX_PAPERS


def tool_cap(base: int, selected) -> int:
    """The tool calls one turn may make: the setting, or N + 2 for N selected papers (one read each, two spare)."""
    if not applies(selected):
        return int(base)
    return min(MAX_TOOL_CALLS, max(int(base), len(selected) + 2))


def selected_block(selected) -> str:
    """The part of the first message that names the selected papers. Empty for fewer than `MIN_PAPERS`."""
    if not applies(selected):
        return ""
    lines = []
    for r in _rows(selected):
        state = (
            "still being read in: do not open it"
            if _processing(str(r["status"] or ""))
            else "ready"
        )
        pages = f"{r['page_count']} pages" if r.get("page_count") else "pages not known"
        lines.append(f"- {r['id']}: {r['filename']} ({pages}; {state})")
    return (
        f"THE READER SELECTED {len(lines)} PAPERS. Answer from EVERY ready paper, one pass per paper: open each with "
        "read_document (or search_documents with its id), note what it says with pages, then answer from all of them. "
        "Say which paper each point comes from.\n" + "\n".join(lines)
    )


def coverage(selected, read_ids) -> dict | None:
    """{"selected", "read", "processing", "not_read": [ids], "sentence"} for N selected papers (the answer's `paper_coverage`);
    None for fewer than two."""
    if not applies(selected):
        return None
    rows = _rows(selected)
    processing = [r["id"] for r in rows if _processing(str(r["status"] or ""))]
    read = [
        r["id"] for r in rows if r["id"] in set(read_ids) and r["id"] not in processing
    ]
    not_read = [
        r["id"] for r in rows if r["id"] not in read and r["id"] not in processing
    ]
    sentence = f"Read {len(read)} of {len(rows)} selected papers"
    if processing:
        sentence += f"; {len(processing)} still processing"
    if not_read:
        sentence += f"; {len(not_read)} not opened in this answer"
    return {
        "selected": len(rows),
        "read": len(read),
        "processing": len(processing),
        "not_read": not_read,
        "sentence": sentence + ".",
    }


REVIEW_WORDS = (
    "To review these papers against the standards, use Review on each one: the Review engine writes the comment sheet. "
    "A chat answer is no review."
)


def review_offer(question: str, selected) -> list[dict]:
    """The papers to offer the real Review for, when the question asks to review or check the selected papers."""
    if not selected or not _REVIEW_WORDS.search(question or ""):
        return []
    return [
        {"document_id": r["id"], "title": r["filename"], "status": r["status"]}
        for r in _rows(selected)
    ]


def attach(result: dict, question: str, selected, sources: list[dict]) -> dict:
    """The finished answer with its coverage line and, for "review these", the offer of the real Review (both by code)."""
    read_ids = {
        str(src.get("document_id")) for src in sources or [] if src.get("document_id")
    }
    cov = coverage(selected, read_ids)
    offer = review_offer(question, selected) if applies(selected) else []
    if cov is None and not offer:
        return result
    notices = list(result.get("notices") or [])
    if cov is not None:
        result["paper_coverage"] = cov
        notices.append(cov["sentence"])
    if offer:
        result["review_offer"] = offer
        notices.append(REVIEW_WORDS)
    result["notices"] = notices
    return result
