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

#: The shortest shared boundary text treated as chunk OVERLAP rather than
#: coincidence. The chunker carries whole trailing sentences forward
#: (`chunk_overlap_tokens`, ~60 tokens), so a real overlap is a sentence or
#: more; twenty characters is well under one sentence and far longer than a
#: shared word or number.
MIN_OVERLAP_CHARS = 20


def boundary_overlap(previous: str, following: str) -> int:
    """How many leading characters of `following` repeat the end of `previous`.

    The chunker starts each prose chunk with the last sentences of the one
    before it, so joining neighbours as they are stored repeats those
    sentences - up to ~20% of a Tier 2 source's budget spent on text the
    reader has just read (retrieval audit R11). Measured on the text itself,
    so no stored offset is needed and nothing is re-indexed.

    Returns 0 unless the shared text is at least MIN_OVERLAP_CHARS long and
    ends on a word boundary in `following`: a coincidental repeat of a few
    characters, or one ending mid-word, is not overlap and is left alone.
    Longest overlap wins, including `following` lying wholly inside the end of
    `previous` (a strict continuation adds nothing new).
    """
    if len(previous) < MIN_OVERLAP_CHARS or len(following) < MIN_OVERLAP_CHARS:
        return 0
    probe = following[:MIN_OVERLAP_CHARS]
    start = previous.find(probe)
    while start != -1:
        length = len(previous) - start
        if length <= len(following) and following.startswith(previous[start:]):
            if length == len(following) or not following[length].isalnum() \
                    or not following[length - 1].isalnum():
                return length
        start = previous.find(probe, start + 1)
    return 0


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

    # Overlap with the row before, per row, measured once. A joined passage
    # carries each shared boundary ONCE (see boundary_overlap), so both the
    # budget and the text below count what the reader is actually shown.
    overlap_memo: dict[int, int] = {}

    def overlap(i: int) -> int:
        if i not in overlap_memo:
            overlap_memo[i] = boundary_overlap(rows[i - 1]["text"], rows[i]["text"])
        return overlap_memo[i]

    def size(lo: int, hi: int) -> int:
        total = len(rows[lo]["text"])
        for i in range(lo + 1, hi + 1):
            shared = overlap(i)
            total += len(rows[i]["text"]) - shared + (0 if shared else 2)
        return total

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

    # Joined with a blank line, except across an overlap: there the repeated
    # sentences are written once and the next chunk continues straight on,
    # so every chunk - the matched one included - is still one contiguous
    # span of the joined text.
    text = rows[lo]["text"]
    offset = 0
    for i in range(lo + 1, hi + 1):
        shared = overlap(i)
        if shared:
            start = len(text) - shared
            text += rows[i]["text"][shared:]
        else:
            text += "\n\n"
            start = len(text)
            text += rows[i]["text"]
        if i == index:
            offset = start

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
