"""A CITED CLAUSE IS READ IN EVERY HELD CONTRACT PART (order 14, goal G6: "evidence from every held contract part with clause and page";
lead-4, 26 Nov 2026, the queries/CFC fault 4 with builder A).

A query that cites a clause ("clause 4.2.1", "Article 9.3", "section 7.1") is about THAT clause. The wide search finds passages by meaning
and keeps a fair share per part, so a part that holds the cited clause can rank below the cut and the engineer never sees it. Here code looks
the clause number up in the clause headings of EVERY contract part the caller may read (the stored page text, the same heading reader the
locator uses), and returns, for each part that holds it, the clause's own text with its clause and page. The parts that do not hold it are
counted, never silent: "Clause 4.2.1 (cited): found in 3 of 20 contract parts."

Which clause numbers a query cites: `cited_numbers(text)` (a dotted number of three levels, or one after a word such as clause, article,
section). Builder A's reader of the form's own cited clause gives its numbers to the same `in_every_part`. Each found passage is scored by the
local reranker against the question (its own honest score, None when the reranker is not available), and it is never held back by the
listing's cut. Nothing leaves the machine; read access only narrows (the parts are the caller's readable contracts)."""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

#: A cited clause: after its word ("clause 4.2", "Art. 9", "section 7.1.2", "§ 3.4"), or a bare number of three levels or more ("4.2.1").
#: A bare "1.5" is a value ("1.5 bar"), never a citation.
_AFTER_WORD = re.compile(
    r"(?:\b(?:clauses?|cl\.|articles?|art\.|sections?|sec\.|paragraphs?|para\.)|§)\s*(\d+(?:\.\d+)*)(?!\w)", re.I
)
_THREE_LEVELS = re.compile(r"(?<![\w.])(\d+\.\d+\.\d+(?:\.\d+)*)(?![\w.])")
#: At most this many cited clauses are looked up for one query (a form lists one or two; a pasted list of many is not a citation).
MAX_CITED = 5
#: A heading's leading number: "4.2.1 Title", "Clause 7 Title", "Article 9.3 Title".
_HEADING_NUMBER = re.compile(r"^(?:[A-Za-z]+\s+)?(\d+(?:\.\d+)*)\b")
#: A contents line: a title running into leader dots or ending in a page number ("4.2.1 Painting ........ 12").
_CONTENTS = re.compile(r"(?:\.{3,}|\s{2,})\s*\d+\s*$|\s\d{1,3}\s*$")
#: The longest clause text kept as one passage; a longer clause is cut at a line, and the cut is said (`shortened`), never silent.
MAX_CLAUSE_CHARS = 1500


def cited_numbers(text: str) -> list[str]:
    """The clause numbers a text cites, in the order it cites them, each once, at most MAX_CITED."""
    found: list[tuple[int, str]] = [(m.start(), m.group(1)) for m in _AFTER_WORD.finditer(text or "")]
    found += [(m.start(), m.group(1)) for m in _THREE_LEVELS.finditer(text or "")]
    out: list[str] = []
    for _at, number in sorted(found):
        number = number.rstrip(".")
        if number not in out:
            out.append(number)
    return out[:MAX_CITED]


def _number_of(heading: str) -> str | None:
    if heading.startswith("Item "):
        return None  # a list item, not the clause itself
    m = _HEADING_NUMBER.match(heading)
    return m.group(1) if m else None


def find_clause(pages: list[tuple[int, str]], number: str) -> dict | None:
    """The clause `number` in one part's pages: `{"page", "heading", "text", "shortened"}` from its heading line to the next heading on that
    page, verbatim lines. A contents line, or a heading with no text under it, is not the clause; of several, the one with the most text.
    None when the part does not hold it."""
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
            found = {"page": page_no, "heading": heading, "text": "\n".join(kept), "shortened": len(kept) < len(body), "size": len("\n".join(body))}
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
    """Each hit's own reranker score against the question, in place (None when the reranker is not available)."""
    from . import reranker

    try:
        scores = dict(reranker.rerank(question, [(str(n), h["text"]) for n, h in enumerate(hits)]))
    except Exception as exc:  # noqa: BLE001 - the passages stay listed, unscored; the type is logged
        log.warning("technical query: cited clauses could not be scored (%s)", type(exc).__name__)
        scores = {}
    for n, hit in enumerate(hits):
        hit["rerank_score"] = scores.get(str(n))
        hit["score"] = hit["rerank_score"]


def coverage_line(cited: list[dict]) -> str:
    """One sentence per cited clause: in how many of the searched parts it was found (and how many could not be read)."""
    out = []
    for c in cited:
        line = f"Clause {c['clause']} (cited): found in {c['found_in']} of {c['of']} contract parts."
        if c["failed"]:
            line += f" {c['failed']} could not be read."
        if c["shortened"]:
            line += f" {c['shortened']} long clause text(s) are shown up to {MAX_CLAUSE_CHARS:,} characters; the page holds the rest."
        out.append(line)
    return " ".join(out)


def in_every_part(numbers: list[str], contracts: list[str], question: str) -> dict:
    """`{"hits": [...one passage per part holding each cited clause...], "cited": [...counts per clause...]}`. A part that cannot be read
    is counted as not read, never as "not held", and never stops the others."""
    from .db import connect

    hits: list[dict] = []
    cited = [{"clause": n, "found_in": 0, "of": len(contracts), "failed": 0, "shortened": 0} for n in numbers]
    if not numbers or not contracts:
        return {"hits": [], "cited": cited}
    with connect() as conn:
        for document_id in contracts:
            try:
                pages = _part_pages(conn, document_id)
            except Exception as exc:  # noqa: BLE001 - counted as not read in the coverage line
                log.warning("technical query: a contract part could not be read for a cited clause (%s)", type(exc).__name__)
                for c in cited:
                    c["failed"] += 1
                continue
            for c in cited:
                found = find_clause(pages, c["clause"])
                if not found:
                    continue
                c["found_in"] += 1
                c["shortened"] += 1 if found["shortened"] else 0
                hits.append(
                    {
                        "document_id": document_id,
                        "page_start": found["page"],
                        "page_end": found["page"],
                        "text": found["text"],
                        "locator": found["heading"],
                        "cited": c["clause"],
                    }
                )
    _scored(question, hits)
    return {"hits": hits, "cited": cited}
