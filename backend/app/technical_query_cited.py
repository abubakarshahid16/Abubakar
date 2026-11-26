"""WHAT THE FORM CITES, LOOKED UP FIRST (the owner's technical-query faults of 26 Nov 2026, fault 4; one module of builders A and C,
lead-4's decision: A's reader and part choice as the base, C's clause finder and every-part lookup inside it).

A technical query's form names where its subject is set ("REF.1 ... Schedule B - Attachment V, Rev 6, Section 7.2"). The evidence search
used to search every contract on the question box's words only. Now, BEFORE that search, what the form itself cites is looked up:

  1. WHERE THE FORM CITES (A): only the form's REFERENCE lines: a references block (`technical_query_questions._REFERENCES`, the
     form reader's own label, up to the next blank line) and numbered reference entries ("REF.1", "Ref 2"). Measured on the 31 stored
     forms (26 Nov 2026): the reference lines held the real citations; the rest of a form held its procedure text ("in accordance with
     sub clause N of Schedule A ...", 20 citations, none of them about the query's subject) and clause numbers of company standards.
  2. WHAT IS CITED (A): the parts each reference line names (the contract code's own part reading, `contract_checks.parts`; a lower part
     belongs to the higher part named before it on the line, "Schedule B - Attachment V" is Attachment V of Schedule B), and the clause
     numbers on THAT line. A line that names a standard gives no clause (it is the standard's).
  3. WHICH CONTRACT (A): the readable contract whose own page-1 heading says it IS that part (`contract_checks.package_part`); of several,
     the main one as a contract review chooses its reference papers (`references.pick`); still tied, or none: said, never guessed.
  4. THE CLAUSE (C): `find_clause`: from the clause's heading line (the locator's own heading reader) to the next heading on that page,
     verbatim, a contents line or a bare heading never; a long clause is cut at a line and the cut is said. Not found in the named
     part: said. A clause of a named part is never looked up in another part (each part numbers its own clauses).
  5. A CLAUSE WITH NO PART on a reference line (C): looked up in EVERY readable part, and listed only where its heading carries the
     reference's own title (A, measured: on the stored forms the part-less sections were sections of non-contract documents, and the
     contracts' clauses of that number were other clauses); more than CITED_PARTS_LISTED: the best fits by the local reranker listed,
     the rest counted. No title on the line: not looked up. A named part with no clause: that contract is searched first.
Every passage listed first is never held back by the listing's cut (`technical_query_contracts.held_back`); the coverage says what
was looked up and found, in how many parts, and what was not held. Nothing leaves the machine; read access only narrows.
"""

from __future__ import annotations

import logging
import re

from . import contract_checks as CC
from .db import connect

log = logging.getLogger(__name__)

# ------------------------------------------------------------------ 1-2 what the form cites (builder A)

#: A clause on a reference line: "clause 4.2", "Clause No. 7", "section 7.2.1", "article 12", "para 3.1", "sub-clause 2.3".
CLAUSE = re.compile(
    r"\b(?:sub-?clause|clause|section|article|para(?:graph)?)\s*(?:no\.?\s*)?(\d{1,3}(?:\.\d{1,3}){0,4})\b",
    re.IGNORECASE,
)
#: A numbered reference entry of a form: "REF.1 ...", "Ref 2: ...", also inside a table cell ("| REF.1 ...").
_REF_ENTRY = re.compile(r"(?:^|\|)\s*ref\.?\s*\d{1,2}\b", re.IGNORECASE)
#: At most this many citations are looked up for one query (a form lists one or two; a pasted list of many is not a citation).
MAX_CITED = 5

Part = tuple[
    tuple[str, str], tuple[str, str] | None
]  # (label, the higher part it belongs to), as `contract_checks.parts`


def reference_lines(texts: list[str]) -> list[str]:
    """The form's reference lines: a references block (the form reader's label, up to the next blank line) and numbered entries."""
    from .technical_query_questions import _REFERENCES

    out: list[str] = []
    for text in texts:
        block = False
        for line in str(text or "").splitlines():
            if _REFERENCES.match(line):
                block = True
                continue
            if block and not line.strip():
                block = False
                continue
            if (block or _REF_ENTRY.search(line)) and line.strip():
                out.append(line.strip())
    return out


def _line_parts(line: str) -> list[Part]:
    """The deepest parts a line names; a lower part with no higher part of its own belongs to the nearest higher part named BEFORE it."""
    found = CC.parts(line)
    out: list[Part] = []
    for i, ((key, parent), _at) in enumerate(found):
        depth = CC.DEPTH.get(key[0], 9)
        if parent is None:
            higher = [k for (k, _p), _a in found[:i] if CC.DEPTH.get(k[0], 9) < depth]
            parent = higher[-1] if higher else None
        out.append((key, parent))
    parents = {p for _k, p in out if p}
    return [(k, p) for k, p in out if k not in parents]


def cited(texts: list[str]) -> list[tuple[Part | None, str | None]]:
    """(part or None, clause or None) for each citation of the form's REFERENCE lines, in order, each once, at most MAX_CITED. A clause
    belongs to a part on the same line; a line naming a standard gives no clause; a clause on a line naming no part has no part."""
    from .standard_ids import cited_standards

    pairs: list[tuple[Part | None, str | None]] = []
    for line in reference_lines(texts):
        clauses = [] if cited_standards(line) else CLAUSE.findall(line)
        parts = _line_parts(line)
        for part in parts:
            pairs += [(part, c) for c in clauses] or [(part, None)]
        if not parts:
            pairs += [(None, c) for c in clauses]
    out: list[tuple[Part | None, str | None]] = []
    for pair in pairs:
        if pair not in out:
            out.append(pair)
    named = {p for p, c in out if c and p}
    return [(p, c) for p, c in out if c or p not in named][
        :MAX_CITED
    ]  # a part named with a clause needs no clause-less entry


_WORD = re.compile(r"[^\W\d_]{3,}")


def title_words(line: str, clause: str) -> set[str]:
    """The title a reference line gives after a clause number ("Section 7.2 Process Design" -> {process, design}), folded, at most six
    words; none when the number ends the line."""
    m = re.search(rf"(?<![\d.]){re.escape(clause)}(?![\d])", line)
    after = line[m.end() :] if m else ""
    return {w.lower() for w in _WORD.findall(after)[:6]}


def titles(texts: list[str]) -> dict[str, set[str]]:
    """{clause with no part: the title words its reference line gives} (`title_words`)."""
    from .standard_ids import cited_standards

    out: dict[str, set[str]] = {}
    for line in reference_lines(texts):
        if cited_standards(line) or _line_parts(line):
            continue
        for clause in CLAUSE.findall(line):
            out.setdefault(clause, title_words(line, clause))
    return out


# ------------------------------------------------------------------ 3 which contract (builder A)


def _page_one(conn, document_id: str) -> str:
    row = conn.execute(
        "SELECT COALESCE(NULLIF(p.text, ''), o.text, '') FROM pages p LEFT JOIN page_ocr o"
        " ON o.document_id = p.document_id AND o.page_no = p.page_no WHERE p.document_id = ? AND p.page_no = 1",
        (document_id,),
    ).fetchone()
    return str(row[0] or "") if row else ""


def which(contracts: list[str], part: Part) -> list[str]:
    """The readable contract that IS this part by its own page-1 heading (a part cited with no higher part matches it under any); of
    several, the main one (`references.pick`: the main schedule over its attachments, then the highest recorded revision), else all."""
    from .aim_review import references

    key, parent = part
    with connect() as conn:
        out = [d for d in contracts
               if any(k == key and (parent is None or p == parent) for k, p in CC.package_part([(1, _page_one(conn, d))]))]  # fmt: skip
        return references.pick(conn, out) if len(out) > 1 else out


# ------------------------------------------------------------------ 4 the clause in a part (builder C)

#: A heading's leading number: "4.2.1 Title", "Clause 7 Title", "Article 9.3 Title".
_HEADING_NUMBER = re.compile(r"^(?:[A-Za-z]+\s+)?(\d+(?:\.\d+)*)\b")
#: A contents line: a title running into leader dots or ending in a page number ("4.2.1 Painting ........ 12").
_CONTENTS = re.compile(r"(?:\.{3,}|\s{2,})\s*\d+\s*$|\s\d{1,3}\s*$")
#: The longest clause text kept as one passage; a longer clause is cut at a line, and the cut is said (`shortened`), never silent.
MAX_CLAUSE_CHARS = 1500
#: A clause with no part, held by more parts than this: the best-fitting ones are listed, the rest counted.
CITED_PARTS_LISTED = 3


def _number_of(heading: str) -> str | None:
    if heading.startswith("Item "):
        return None  # a list item, not the clause itself
    m = _HEADING_NUMBER.match(heading)
    return m.group(1) if m else None


def find_clause(pages: list[tuple[int, str]], number: str) -> dict | None:
    """The clause `number` in one part's pages: `{"page", "heading", "text", "shortened"}` from its heading line to the next heading on
    that page, verbatim lines. A contents line, or a heading with no text under it, is not the clause; of several, the one with the most
    text. None when the part does not hold it."""
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
            found = {"page": page_no, "heading": heading, "text": "\n".join(kept), "shortened": len(kept) < len(body), "size": len("\n".join(body))}  # fmt: skip
            if best is None or found["size"] > best["size"]:
                best = found
    return best


def _part_pages(conn, document_id: str) -> list[tuple[int, str]]:
    rows = conn.execute(
        "SELECT p.page_no,p.text AS native,p.needs_ocr,o.text AS ocr_text FROM pages p LEFT JOIN page_ocr o "
        "ON o.document_id=p.document_id AND o.page_no=p.page_no WHERE p.document_id=? ORDER BY p.page_no",
        (document_id,),
    ).fetchall()
    return [
        (r["page_no"], (r["ocr_text"] or "") if r["needs_ocr"] else (r["native"] or ""))
        for r in rows
    ]


def _scored(question: str, hits: list[dict]) -> None:
    """Each hit's own reranker score against the question, in place (None when the reranker is not available)."""
    from . import reranker

    if not hits:
        return
    try:
        scores = dict(
            reranker.rerank(question, [(str(n), h["text"]) for n, h in enumerate(hits)])
        )
    except Exception as exc:  # noqa: BLE001 - the passages stay listed, unscored; the type is logged
        log.warning(
            "technical query: cited clauses could not be scored (%s)",
            type(exc).__name__,
        )
        scores = {}
    for n, hit in enumerate(hits):
        hit["rerank_score"] = scores.get(str(n))
        hit["score"] = hit["rerank_score"]


# ------------------------------------------------------------------ 5 a clause with no part: every part (builder C)


def same_title(heading: str, words: set[str]) -> bool:
    """The heading names the reference's own title: at least two of its title words (all of them when it gives fewer than two)."""
    have = {w.lower() for w in _WORD.findall(heading)}
    return bool(words) and len(have & words) >= min(2, len(words))


def in_every_part(
    clause: str, contracts: list[str], question: str, words: set[str] | None = None
) -> tuple[list[dict], dict]:
    """(passages of the parts holding `clause` under the reference's own title, its counts). Every readable part is looked in; a part
    whose clause of that number has ANOTHER title is not the cited clause (measured on the stored forms, 26 Nov 2026: a part-less
    "Section 13" or "Section 7.2" named a section of a non-contract document, and the contracts' clauses of that number were other
    clauses), so it is counted apart and never listed. No title (`words` empty): nothing is looked up. More than CITED_PARTS_LISTED
    holding it: the best fits by the reranker listed, the rest counted. A part that cannot be read is counted as not read."""
    c = {
        "clause": clause,
        "found_in": 0,
        "of": len(contracts),
        "failed": 0,
        "shortened": 0,
        "not_listed": 0,
        "other_title": 0,
    }
    if not words:
        return [], c
    found_here: list[dict] = []
    with connect() as conn:
        for document_id in contracts:
            try:
                pages = _part_pages(conn, document_id)
            except Exception as exc:  # noqa: BLE001 - counted as not read in the coverage line
                log.warning(
                    "technical query: a contract part could not be read for a cited clause (%s)",
                    type(exc).__name__,
                )
                c["failed"] += 1
                continue
            found = find_clause(pages, clause)
            if not found:
                continue
            if not same_title(found["heading"], words):
                c["other_title"] += 1
                continue
            c["found_in"] += 1
            c["shortened"] += 1 if found["shortened"] else 0
            found_here.append({"document_id": document_id, "page_start": found["page"], "page_end": found["page"], "text": found["text"],
                               "locator": found["heading"], "cited": clause})  # fmt: skip
    _scored(question, found_here)
    if len(found_here) > CITED_PARTS_LISTED:
        found_here.sort(
            key=lambda h: (
                h.get("rerank_score") is None,
                -(h.get("rerank_score") or 0.0),
            )
        )
        c["not_listed"] = len(found_here) - CITED_PARTS_LISTED
        found_here = found_here[:CITED_PARTS_LISTED]
    return found_here, c


def _every_part_line(c: dict, titled: bool = True) -> str:
    if not titled:
        return f"clause {c['clause']} (no part named, no title): not looked up; it names no contract part"
    line = f"clause {c['clause']} (no part named): found under its title in {c['found_in']} of {c['of']} contract parts"
    if c.get("other_title"):
        line += f"; {c['other_title']} hold a clause of that number with another title (not listed)"
    if c.get("not_listed"):
        line += f", the {c['found_in'] - c['not_listed']} that best fit the question listed, {c['not_listed']} more not listed"
    if c["failed"]:
        line += f", {c['failed']} could not be read"
    return line


# ------------------------------------------------------------------ the step (builders A and C)


def cited_first(
    texts: list[str], contracts: list[str], question: str, search_one
) -> dict:
    """`{"hits": [...passages listed first...], "said": [...one plain line per citation...], "cited": [...counts...]}`.
    `search_one(document_id)` is the general search of ONE contract, for a cited part with no clause."""
    hits: list[dict] = []
    said: list[str] = []
    counts: list[dict] = []
    named_titles = titles(texts)
    for part, clause in cited(texts):
        if part is None:
            words = named_titles.get(str(clause)) or set()
            found, c = in_every_part(str(clause), contracts, question, words)
            hits += found
            counts.append(c)
            said.append(_every_part_line(c, bool(words)))
            continue
        name = CC._name(part)
        where = f"{name} clause {clause}" if clause else name
        docs = which(contracts, part)
        if not docs:
            said.append(f"{where}: not held among the contracts you may read")
            continue
        if len(docs) > 1:
            said.append(f"{where}: held more than once, not chosen")
            continue
        doc = docs[0]
        if not clause:
            own = [
                dict(h, cited=True)
                for h in (search_one(doc) or [])[:CITED_PARTS_LISTED]
                if (h.get("text") or "").strip()
            ]
            hits += own
            said.append(
                f"{where}: searched first ({len(own)} passage{'s' if len(own) != 1 else ''})"
            )
            continue
        with connect() as conn:
            found = find_clause(_part_pages(conn, doc), clause)
        if found is None:
            said.append(f"{where}: the clause was not found in that contract")
            continue
        hit = {"document_id": doc, "page_start": found["page"], "page_end": found["page"], "text": found["text"],
               "locator": f"{name}, {found['heading']}", "cited": clause}  # fmt: skip
        _scored(question, [hit])
        hits.append(hit)
        said.append(f"{where}: found on page {found['page']}" + (" (shown in part; the page holds the rest)" if found["shortened"] else ""))  # fmt: skip
    return {"hits": hits, "said": said, "cited": counts}
