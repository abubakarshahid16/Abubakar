"""A CITED CLAUSE IS READ IN EVERY HELD CONTRACT PART (order 14, goal G6: "evidence from every held contract part with clause and page";
lead-4, 26 Nov 2026, the queries/CFC fault 4 with builder A).

A query that cites a clause ("clause 4.2.1", "Article 9.3", "section 7.1 of Schedule B") is about THAT clause. The wide search finds
passages by meaning and keeps a fair share per part, so a part that holds the cited clause can rank below the cut and the engineer never
sees it. Here code looks the clause number up in the clause headings of the contract parts the caller may read (the stored page text, the
same heading reader the locator uses), and returns, for each part that holds it, the clause's own text with its clause and page:
- a citation that names its part ("Schedule B", "Appendix 2", "the Agreement") is looked up in the parts whose file name names it, and in
  every part when none does;
- a citation that names no part is looked up in EVERY part; when more than CITED_PARTS_LISTED parts hold that number (each part numbers
  its own clauses), the ones that best fit the question by the local reranker are listed and the rest are counted;
- a clause of a named STANDARD ("SAES-X-123 section 4.2") is not a contract clause and is not looked up here.
The parts that do not hold it are counted, never silent: "Clause 4.2.1 (cited): found in 3 of 20 contract parts."

Builder A's reader of the form's own cited clause gives its references to the same `in_every_part` (through `search_all(cited=...)`).
Each found passage carries the local reranker's own score against the question (None when the reranker is not available), and a listed
one is never held back by the listing's cut. Nothing leaves the machine; read access only narrows (the parts are the caller's readable
contracts)."""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

#: A cited clause: after its word ("clause 4.2", "Art. 9", "section 7.1.2", "§ 3.4"), or a bare number of three levels or more ("4.2.1").
#: A bare "1.5" is a value ("1.5 bar"), never a citation.
_AFTER_WORD = re.compile(
    r"(?:\b(?:clauses?|cl\.|articles?|art\.|sections?|sec\.|paragraphs?|para\.)|§)\s*(\d+(?:\.\d+)*)(?!\w)", re.I
)
_THREE_LEVELS = re.compile(r"(?<![\w.])(\d+\.\d+\.\d+(?:\.\d+)*)(?!\w|\.\d)")  # a full stop after it ends the sentence
#: A standard's designation just before a citation ("SAES-X-123 section", "ISO 12944 clause", "API 610 4.2.1"): the clause is the
#: standard's, not the contract's.
_STANDARD_BEFORE = re.compile(r"\b[A-Z]{2,6}(?:[- ][A-Z0-9]{1,3})?[- ]?\d{2,5}(?:[-:]\d+)*\W{0,3}(?:\w+\W{1,3})?$")
_STANDARD_AFTER = re.compile(r"^\W{0,3}(?:of|in)\s+(?:the\s+)?[A-Z]{2,6}(?:[- ][A-Z0-9]{1,3})?[- ]?\d{2,5}\b")
#: The contract part a citation names, near it ("Schedule B", "Appendix 2", "Attachment 3", "the Agreement").
_PART = re.compile(r"\b(schedule|appendix|annex|attachment|exhibit)\s+([A-Z]{1,2}|\d{1,2})\b|\b(agreement)\b", re.I)
NEAR = 40
#: At most this many cited clauses are looked up for one query (a form lists one or two; a pasted list of many is not a citation).
MAX_CITED = 5
#: A citation that names no part, held by more parts than this: the best-fitting ones are listed, the rest counted.
CITED_PARTS_LISTED = 3
#: A heading's leading number: "4.2.1 Title", "Clause 7 Title", "Article 9.3 Title".
_HEADING_NUMBER = re.compile(r"^(?:[A-Za-z]+\s+)?(\d+(?:\.\d+)*)\b")
#: A contents line: a title running into leader dots or ending in a page number ("4.2.1 Painting ........ 12").
_CONTENTS = re.compile(r"(?:\.{3,}|\s{2,})\s*\d+\s*$|\s\d{1,3}\s*$")
#: The longest clause text kept as one passage; a longer clause is cut at a line, and the cut is said (`shortened`), never silent.
MAX_CLAUSE_CHARS = 1500


def _part_near(before: str, after: str) -> str | None:
    """The part a citation names: the nearest part word in the text just after it ("4.2 of Schedule B"), else just before it."""
    for text, nearest in ((after, 0), (before, -1)):
        found = list(_PART.finditer(text))
        if found:
            m = found[nearest]
            return "agreement" if m.group(3) else f"{m.group(1).lower()} {m.group(2).upper()}"
    return None


def cited_refs(text: str) -> list[dict]:
    """`[{"clause": "4.2.1", "part": "schedule B" | None}]`: the contract clauses a text cites, in its order, each once, at most MAX_CITED.
    A clause of a named standard is left out."""
    text = " ".join((text or "").split())
    found = [(m.start(), m.end(), m.group(1)) for m in _AFTER_WORD.finditer(text)]
    found += [(m.start(), m.end(), m.group(1)) for m in _THREE_LEVELS.finditer(text)]
    out: list[dict] = []
    found.sort(key=lambda f: (f[0], -f[1]))
    found = [f for n, f in enumerate(found) if not any(o[0] <= f[0] and f[1] <= o[1] for o in found[:n])]  # "clause 4.2.1" holds "4.2.1"
    for n, (start, end, number) in enumerate(found):
        # the words near a citation stop at its neighbours: a part named for one citation is never another's
        since = found[n - 1][1] if n else 0
        until = found[n + 1][0] if n + 1 < len(found) else len(text)
        before, after = text[max(since, start - NEAR) : start], text[end : min(until, end + NEAR)]
        if _STANDARD_BEFORE.search(before) or _STANDARD_AFTER.search(after):
            continue
        ref = {"clause": number.rstrip("."), "part": _part_near(before, after)}
        if not any(r["clause"] == ref["clause"] for r in out):
            out.append(ref)
    return out[:MAX_CITED]


def cited_numbers(text: str) -> list[str]:
    """The contract clause numbers a text cites (`cited_refs` without the part)."""
    return [r["clause"] for r in cited_refs(text)]


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


def names_part(filename: str, part: str) -> bool:
    """True when a contract part's file name names `part` ("schedule B" in "Invented Schedule B - Scope.pdf", not in "Schedule BB")."""
    word, _, ident = part.partition(" ")
    if not ident:
        return re.search(rf"\b{word}\b", filename or "", re.I) is not None
    return re.search(rf"\b{word}[\s_-]*{re.escape(ident)}(?![A-Za-z0-9])", filename or "", re.I) is not None


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
    """One sentence per cited clause: in how many of the parts looked in it was found, how many of those are listed, how many could not be read."""
    out = []
    for c in cited:
        named = f" of {c['part'][:1].upper()}{c['part'][1:]}" if c.get("part") else ""
        where = f"parts named {c['part'][:1].upper()}{c['part'][1:]}" if c.get("looked_in") == "named" else "contract parts"
        line = f"Clause {c['clause']}{named} (cited): found in {c['found_in']} of {c['of']} {where}."
        if c.get("looked_in") == "every" and c.get("part"):
            line += " No held part is named so; every part was looked in."
        if c.get("not_listed"):
            line += f" The {c['found_in'] - c['not_listed']} that best fit the question are listed; {c['not_listed']} more are not listed."
        if c["failed"]:
            line += f" {c['failed']} could not be read."
        if c["shortened"]:
            line += f" {c['shortened']} long clause text(s) are shown up to {MAX_CLAUSE_CHARS:,} characters; the page holds the rest."
        out.append(line)
    return " ".join(out)


def _ref(r) -> dict:
    return {"clause": r, "part": None} if isinstance(r, str) else {"clause": r["clause"], "part": r.get("part")}


def in_every_part(refs: list, contracts: list[str], question: str) -> dict:
    """`{"hits": [...passages of the parts holding each cited clause...], "cited": [...counts per clause...]}`. `refs` are clause numbers or
    `cited_refs` entries. A part that cannot be read is counted as not read, never as "not held", and never stops the others."""
    from .db import connect

    refs = [_ref(r) for r in refs]
    if not refs or not contracts:
        return {"hits": [], "cited": [{**r, "found_in": 0, "of": len(contracts), "failed": 0, "shortened": 0, "not_listed": 0} for r in refs]}
    hits: list[dict] = []
    cited: list[dict] = []
    with connect() as conn:
        names = {r["id"]: r["filename"] for r in conn.execute(
            f"SELECT id, filename FROM documents WHERE id IN ({','.join('?' for _ in contracts)})", tuple(contracts)
        ).fetchall()}  # fmt: skip
        pages: dict[str, list | None] = {}
        for ref in refs:
            named = [d for d in contracts if ref["part"] and names_part(names.get(d, ""), ref["part"])]
            parts = named or contracts
            c = {**ref, "found_in": 0, "of": len(parts), "failed": 0, "shortened": 0, "not_listed": 0}
            c["looked_in"] = "named" if named else "every"
            found_here: list[dict] = []
            for document_id in parts:
                if document_id not in pages:
                    try:
                        pages[document_id] = _part_pages(conn, document_id)
                    except Exception as exc:  # noqa: BLE001 - counted as not read in the coverage line
                        log.warning("technical query: a contract part could not be read for a cited clause (%s)", type(exc).__name__)
                        pages[document_id] = None
                if pages[document_id] is None:
                    c["failed"] += 1
                    continue
                found = find_clause(pages[document_id], ref["clause"])
                if not found:
                    continue
                c["found_in"] += 1
                c["shortened"] += 1 if found["shortened"] else 0
                found_here.append(
                    {"document_id": document_id, "page_start": found["page"], "page_end": found["page"], "text": found["text"],
                     "locator": found["heading"], "cited": ref["clause"]}
                )  # fmt: skip
            _scored(question, found_here)
            if not named and len(found_here) > CITED_PARTS_LISTED:
                found_here.sort(key=lambda h: (h["rerank_score"] is None, -(h["rerank_score"] or 0.0)))
                c["not_listed"] = len(found_here) - CITED_PARTS_LISTED
                found_here = found_here[:CITED_PARTS_LISTED]
            hits += found_here
            cited.append(c)
    return {"hits": hits, "cited": cited}
