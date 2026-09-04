"""Small-to-big: search small, show big.

The chunk size that retrieves well is not the chunk size that reads well.
Three hundred tokens is about right for a cross-encoder and about half a
clause for a reader, and NORSOK showed exactly what that costs. Clause A.1 is
a table of film thicknesses followed by its notes, split across two chunks.
Retrieval correctly found A.1 and returned the notes chunk, so the answer
quoted "Chalking rating 1 or better should be preferred" and left the actual
thickness figures in the chunk next door.

The right passage was being found and then cut off just before the useful
part. That is a boundary problem, not a retrieval problem, so nothing here
touches retrieval: the hit is still whatever the reranker chose. Only what
the reader is shown grows, outward from the hit, through its parent block and
then its neighbours, within a character budget.

Expansion never crosses into a different section. A passage labelled A.1 that
contains A.2's text would be a worse defect than the one this fixes.
"""

from __future__ import annotations

from .config import settings
from .db import connect

#: Sentinel so a chunk with no parent (a pre-migration row) still expands by
#: adjacency rather than silently refusing to.
_NO_PARENT = "\x00none"


def _rows_for(document_id: str) -> list[dict]:
    return [
        dict(r)
        for r in connect().execute(
            """SELECT id, ordinal, page_start, page_end, section, parent_id,
                      kind, text, text_source, ocr_min_conf,
                      ocr_alphabet_violations, ocr_alphabet_sample
               FROM chunks
               WHERE document_id = ? AND retrievable = 1
               ORDER BY ordinal""",
            (document_id,),
        )
    ]


def expand_passage(
    chunk_id: str, document_id: str, budget: int | None = None
) -> dict:
    """The hit chunk grown to its readable extent.

    Returns the joined text, the page span it actually covers, the section,
    how many chunks were joined, and where the hit chunk sits inside the
    joined text - so a caller can still point at the passage that matched.
    """
    budget = budget or settings.answer_context_chars
    rows = _rows_for(document_id)
    index = next((i for i, r in enumerate(rows) if r["id"] == chunk_id), None)
    if index is None:
        return {}

    hit = rows[index]
    section = hit["section"]
    parent = hit["parent_id"] or _NO_PARENT

    def joinable(row: dict) -> bool:
        # Same clause, always. A passage labelled A.1 must not contain A.2.
        return row["section"] == section

    # The parent block first: this is the whole point, and it is what puts
    # A.1's thickness table back together with A.1's notes.
    lo = hi = index
    while lo - 1 >= 0 and (rows[lo - 1]["parent_id"] or _NO_PARENT) == parent \
            and joinable(rows[lo - 1]):
        lo -= 1
    while hi + 1 < len(rows) and (rows[hi + 1]["parent_id"] or _NO_PARENT) == parent \
            and joinable(rows[hi + 1]):
        hi += 1

    def size(lo: int, hi: int) -> int:
        return sum(len(rows[i]["text"]) for i in range(lo, hi + 1)) + 2 * (hi - lo)

    # A parent larger than the budget is trimmed back towards the hit rather
    # than truncated mid-word: the chunk that matched is never dropped.
    while size(lo, hi) > budget and (lo < index or hi > index):
        if hi - index >= index - lo and hi > index:
            hi -= 1
        elif lo < index:
            lo += 1
        else:
            break

    # Then neighbours, alternating outward, while there is budget left. These
    # may sit in a different parent block but must still be the same clause.
    grew = True
    while grew:
        grew = False
        for nxt, step in ((hi + 1, 1), (lo - 1, -1)):
            if not 0 <= nxt < len(rows) or not joinable(rows[nxt]):
                continue
            new_lo, new_hi = (lo, nxt) if step == 1 else (nxt, hi)
            if size(new_lo, new_hi) <= budget:
                lo, hi = new_lo, new_hi
                grew = True

    parts = [rows[i]["text"] for i in range(lo, hi + 1)]
    text = "\n\n".join(parts)
    offset = sum(len(p) + 2 for p in parts[: index - lo])

    return {
        "text": text,
        "page_start": min(rows[i]["page_start"] for i in range(lo, hi + 1)),
        "page_end": max(rows[i]["page_end"] for i in range(lo, hi + 1)),
        "section": section,
        # A quoted TABLE cannot be reflowed as prose: column pairing is
        # positional, so wrapping it destroys the only structure it has. The
        # UI needs to know which it is holding.
        "kind": hit["kind"],
        "chunks_joined": hi - lo + 1,
        # Provenance over the JOINED passage, not just the matched chunk. The
        # reader is shown the whole expanded block, so if any part of it was
        # recognised the whole thing must say so - the same rule that makes a
        # chunk spanning a recognised page recognised. See ADR-0006.
        "text_source": (
            "recognised"
            if any(rows[i]["text_source"] == "recognised" for i in range(lo, hi + 1))
            else "extracted"
        ),
        "ocr_min_conf": min(
            (rows[i]["ocr_min_conf"] for i in range(lo, hi + 1)
             if rows[i]["ocr_min_conf"] is not None), default=None),
        "ocr_alphabet_violations": sum(
            (rows[i]["ocr_alphabet_violations"] or 0) for i in range(lo, hi + 1)),
        "ocr_alphabet_sample": "".join(sorted({
            c for i in range(lo, hi + 1)
            for c in (rows[i]["ocr_alphabet_sample"] or "")})) or None,
        # where the chunk that actually matched sits inside the joined text
        "match_span": [offset, offset + len(hit["text"])],
    }
