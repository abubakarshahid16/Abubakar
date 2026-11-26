"""THE FORM'S OWN CITATIONS FIRST (the owner's technical-query faults of 26 Nov 2026, fault 4; lead-4: builder A).

A technical query's form usually names where its subject is set: "Schedule C, clause 4.2". The evidence search used to search all the
contracts on the question box's words only, so a question with stray words found twenty passages of no use. Now, BEFORE the general
search, the part and clause the form itself cites are looked up:

  1. WHAT THE FORM CITES, read by code: the Schedules the form names (the contract code's own part reading, `contract_checks.parts`: a
     Schedule, no higher part), and the clause numbers it gives ("clause 4.2", "section 7", "article 12.1", "para 3"). A clause on the
     same line as a Schedule belongs to it. A clause on a line of its own belongs to the form's Schedule when the form names exactly ONE.
  2. WHICH CONTRACT THAT IS: the contract the caller may read whose own first heading lines say it IS that Schedule
     (`contract_checks.package_part`, page 1 only, as for a contract review's reference papers). Exactly one, or it is said: "not held"
     or "held more than once". Never a likeness of names, never a model.
  3. THE CLAUSE: the first page of that contract where a line BEGINS with the clause number (a heading, not a mention). The passage
     listed is that page's own text from the heading on (at most PASSAGE_CHARS, ending at a line end): verbatim, so it is checked on
     its page like any passage. No clause named: that contract is searched FIRST (the same local search), its best passages listed first.

The general search then runs as before; a passage already listed is not listed twice. The coverage says what was looked up first and
what was found. Nothing here leaves the machine; read access only narrows (only the contracts the caller may read are looked at).
"""

from __future__ import annotations

import re

from . import contract_checks as CC
from .db import connect

#: A clause the form names: "clause 4.2", "Clause No. 7", "section 7.2.1", "article 12", "para 3.1", "sub-clause 2.3".
CLAUSE = re.compile(
    r"\b(?:sub-?clause|clause|section|article|para(?:graph)?)\s*(?:no\.?\s*)?(\d{1,3}(?:\.\d{1,3}){0,4})\b",
    re.IGNORECASE,
)
#: The most of a contract page listed for a cited clause, from its heading on.
PASSAGE_CHARS = 1500
#: How many passages of a cited contract with no clause named are listed first.
CITED_PART_HITS = 3


Part = tuple[
    tuple[str, str], tuple[str, str] | None
]  # (label, the higher part it belongs to), as `contract_checks.parts`


def _line_parts(line: str) -> list[Part]:
    """The deepest parts a line names. A lower part with no higher part of its own belongs to the nearest higher part named BEFORE it
    on the line ("Schedule B - Attachment V" is Attachment V of Schedule B); a part that has a lower part of its own after it on the
    line is not cited by itself."""
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


def cited(texts: list[str]) -> list[tuple[Part, str | None]]:
    """(part, clause or None) pairs the form names, in order of first mention, each once. A clause belongs to a part only when the
    SAME line names that part and no standard: measured on the stored queries (26 Nov 2026), a form's clause numbers on other lines,
    or beside a standard's name, were clauses of company standards or of another part, never of the form's."""
    from .standard_ids import cited_standards

    pages = [(i + 1, str(t or "")) for i, t in enumerate(texts)]
    pairs: list[tuple[Part, str | None]] = []
    for _p, line in CC.lines_of(pages):
        clauses = [] if cited_standards(line) else CLAUSE.findall(line)
        for part in _line_parts(line):
            pairs += [(part, c) for c in clauses] or [(part, None)]
    out: list[tuple[Part, str | None]] = []
    for pair in pairs:
        if pair not in out:
            out.append(pair)
    named = {p for p, c in out if c}
    return [
        (p, c) for p, c in out if c or p not in named
    ]  # a part named with a clause needs no clause-less entry


def _page_one(conn, document_id: str) -> str:
    row = conn.execute(
        "SELECT COALESCE(NULLIF(p.text, ''), o.text, '') FROM pages p LEFT JOIN page_ocr o"
        " ON o.document_id = p.document_id AND o.page_no = p.page_no WHERE p.document_id = ? AND p.page_no = 1",
        (document_id,),
    ).fetchone()
    return str(row[0] or "") if row else ""


def which(contracts: list[str], part: Part) -> list[str]:
    """The readable contract that IS this part by its own page-1 heading (a part cited with no higher part matches it under any);
    of several, the main one as a contract review chooses its reference papers (`references.pick`: the main schedule over its
    attachments, then the highest recorded revision), else all."""
    from .aim_review import references

    key, parent = part
    with connect() as conn:
        out = [d for d in contracts
               if any(k == key and (parent is None or p == parent) for k, p in CC.package_part([(1, _page_one(conn, d))]))]  # fmt: skip
        return references.pick(conn, out) if len(out) > 1 else out


def clause_passage(pages: dict[int, str], clause: str) -> tuple[int, str] | None:
    """(page, the page's own text from the clause heading on) for the first page where a line BEGINS with the clause number."""
    head = re.compile(
        rf"(?mi)^[ \t]*(?:(?:sub-?clause|clause|section|article)\s+)?{re.escape(clause)}(?:\.(?!\d))?(?=[ \t]|$)"
    )
    for p, text in sorted(pages.items()):
        m = head.search(text or "")
        if not m:
            continue
        part = text[m.start() : m.start() + PASSAGE_CHARS]
        if len(text) > m.start() + PASSAGE_CHARS and "\n" in part:
            part = part[: part.rfind("\n")]
        return p, part.strip()
    return None


def lookup(
    texts: list[str], contracts: list[str], search_one
) -> tuple[list[dict], list[str]]:
    """(passages listed first, one plain line per citation). `search_one(document_id)` is the general search of ONE contract (its
    hits), used for a cited Schedule with no clause named."""
    from . import agent_review_standards

    hits: list[dict] = []
    said: list[str] = []
    for part, clause in cited(texts):
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
        if clause:
            with connect() as conn:
                pages = dict(agent_review_standards.read_book(conn, doc).pages)
            found = clause_passage(pages, clause)
            if found is None:
                said.append(f"{where}: the clause was not found in that contract")
                continue
            page, text = found
            hits.append({"document_id": doc, "page_start": page, "page_end": page, "text": text, "locator": f"{name}, clause {clause}",
                         "rerank_score": None, "score": None, "cited": True})  # fmt: skip
            said.append(f"{where}: found on page {page}")
            continue
        own = [
            dict(h, cited=True)
            for h in (search_one(doc) or [])[:CITED_PART_HITS]
            if (h.get("text") or "").strip()
        ]
        hits += own
        said.append(
            f"{where}: searched first ({len(own)} passage{'s' if len(own) != 1 else ''})"
        )
    return hits, said
