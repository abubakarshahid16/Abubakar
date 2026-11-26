"""THE SAME CLAUSE NUMBER IN THE OTHER HELD CONTRACT PARTS (order 14, goal G6: "evidence from every held contract part with clause and
page"; lead-4, 26 Nov 2026, the queries/CFC fault 4 with builder A).

Builder A's `technical_query_cited.lookup` reads the clause the form cites in the part the form names and lists it first. When that cannot
be settled (the named part is not held among the caller's contracts, or the clause is not found in it), A's lookup asks `every_part`: the
clause headings of EVERY other contract part the caller may read are searched for the same number, and each part that has it gives its
clause's own text with heading and page.

These are NOT the cited clause. Each contract part numbers its own clauses, so "4.2" in another part is a different clause with the same
number (A's measure on the stored forms). Every passage is marked `same_number_other_part` and its line says so. When more than
OTHER_PARTS_LISTED parts have the number, it is too common to point anywhere: no passage is listed, only the count (measured on the 31
stored forms, 26 Nov 2026, counts only: of 22 citations A's lookup cannot settle, 19 have the number in no other part and 3 in 4, 8 and 10
other parts, so nothing of a different clause is listed on them). A contents line, or a heading with no text under it, is not a clause. A long clause is cut at a line and the cut is said. Nothing
leaves the machine; read access only narrows (the parts are the caller's readable contracts)."""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

#: More parts than this with the same number: the number is too common to point anywhere, so none is listed, only counted.
OTHER_PARTS_LISTED = 3
#: A heading's leading number: "4.2.1 Title", "Clause 7 Title", "Article 9.3 Title".
_HEADING_NUMBER = re.compile(r"^(?:[A-Za-z]+\s+)?(\d+(?:\.\d+)*)\b")
#: A contents line: a title running into leader dots or ending in a page number ("4.2.1 Painting ........ 12").
_CONTENTS = re.compile(r"(?:\.{3,}|\s{2,})\s*\d+\s*$|\s\d{1,3}\s*$")
#: The longest clause text kept as one passage; a longer clause is cut at a line, and the cut is said, never silent.
MAX_CLAUSE_CHARS = 1500


def _number_of(heading: str) -> str | None:
    if heading.startswith("Item "):
        return None  # a list item, not a clause
    m = _HEADING_NUMBER.match(heading)
    return m.group(1) if m else None


def find_clause(pages: list[tuple[int, str]], number: str) -> dict | None:
    """The clause `number` in one part's pages: `{"page", "heading", "text", "shortened"}` from its heading line to the next heading on that
    page, verbatim lines. A contents line, or a heading with no text under it, is not the clause; of several, the one with the most text.
    None when the part has no such clause."""
    from .technical_query_match import _headings

    best: dict | None = None
    for page_no, text in pages:
        lines = (text or "").splitlines()
        heads = _headings(lines)
        for n, (i, heading) in enumerate(heads):
            if _number_of(heading) != number or _CONTENTS.search(lines[i].rstrip()):
                continue
            end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
            body = [line for line in lines[i:end] if line.strip()]
            if len(body) < 2:
                continue  # a heading alone (or a heading with its title on the next line and nothing more)
            kept, size = [], 0
            for line in body:
                if kept and size + len(line) > MAX_CLAUSE_CHARS:
                    break
                kept.append(line)
                size += len(line) + 1
            whole = "\n".join(body)
            found = {"page": page_no, "heading": heading, "text": "\n".join(kept), "shortened": len(kept) < len(body), "size": len(whole)}
            if best is None or found["size"] > best["size"]:
                best = found
    return best


def _part_pages(conn, document_id: str) -> list[tuple[int, str]]:
    rows = conn.execute(
        "SELECT p.page_no,p.text AS native,p.needs_ocr,o.text AS ocr_text FROM pages p LEFT JOIN page_ocr o "
        "ON o.document_id=p.document_id AND o.page_no=p.page_no WHERE p.document_id=? ORDER BY p.page_no",
        (document_id,),
    ).fetchall()
    return [(r["page_no"], (r["ocr_text"] or "") if r["needs_ocr"] else (r["native"] or "")) for r in rows]


def _scored(question: str, hits: list[dict]) -> None:
    """Each hit's own reranker score against the question, in place (None when the reranker is not available or there is no question)."""
    scores: dict[str, float] = {}
    if question and hits:
        from . import reranker

        try:
            scores = dict(reranker.rerank(question, [(str(n), h["text"]) for n, h in enumerate(hits)]))
        except Exception as exc:  # noqa: BLE001 - the passages stay, unscored; the type is logged
            log.warning("technical query: same-number clauses could not be scored (%s)", type(exc).__name__)
    for n, hit in enumerate(hits):
        hit["rerank_score"] = scores.get(str(n))
        hit["score"] = hit["rerank_score"]


def line(clause: str, found_in: int, of: int, listed: int, failed: int, shortened: int) -> str:
    """The plain sentence beside the passages: how many other parts have the number, that each is a different clause, what is listed."""
    if of == 0:
        return f"Clause {clause}: no other contract part that you may read is held, so no other part was looked in."
    if found_in == 0:
        said = f"Clause {clause}: no other contract part (of {of} looked in) has a clause with this number."
    else:
        said = (
            f"Clause {clause}: {found_in} of {of} other contract parts have a clause with the same number. Each part numbers its own "
            "clauses, so each is a different clause, shown for reference only."
        )
        if listed < found_in:
            said += " So many parts use this number that none is listed."
    if failed:
        said += f" {failed} could not be read."
    if shortened:
        said += f" {shortened} long clause text(s) are shown up to {MAX_CLAUSE_CHARS:,} characters; the page holds the rest."
    return said


def every_part(clause: str, contracts: list[str], question: str = "", exclude: frozenset[str] = frozenset()) -> tuple[list[dict], str]:
    """(passages, line) for clause `clause` in every contract part of `contracts` (the caller's readable ones) other than `exclude` (the
    part the form names, already looked in). Hits are shaped like search hits: document_id, page_start, page_end, text (verbatim),
    locator, rerank_score, and `same_number_other_part: True`. A part that cannot be read is counted, never "not found"."""
    from .db import connect

    parts = [d for d in contracts if d not in exclude]
    clause = (clause or "").strip().rstrip(".")
    hits: list[dict] = []
    failed = 0
    if clause and parts:
        with connect() as conn:
            for document_id in parts:
                try:
                    pages = _part_pages(conn, document_id)
                except Exception as exc:  # noqa: BLE001 - counted as not read in the line
                    log.warning("technical query: a contract part could not be read for a clause number (%s)", type(exc).__name__)
                    failed += 1
                    continue
                found = find_clause(pages, clause)
                if not found:
                    continue
                hits.append(
                    {"document_id": document_id, "page_start": found["page"], "page_end": found["page"], "text": found["text"],
                     "locator": found["heading"], "same_number_other_part": True, "shortened": found["shortened"]}
                )  # fmt: skip
    _scored(question, hits)
    found_in = len(hits)
    if found_in > OTHER_PARTS_LISTED:
        hits = []  # too common a number to be the cited clause: counted, never listed
    shortened = sum(1 for h in hits if h["shortened"])  # of the listed ones
    return hits, line(clause, found_in, len(parts), len(hits), failed, shortened)
