"""Evidence for a technical query from EVERY contract the caller may read (order 14, F3).

Before, one keyword search over all documents kept five passages, so most contracts were never looked at. Now each CONTRACT_DOCUMENT the
caller may read is searched on its own, with the dense search and the reranker, and the best passages of each are kept. The result states
its own coverage ("searched 19 of 20 contracts, hits in 6"), stored with the query and shown: a contract that could not be searched is
counted as not searched, never as "no hit". Nothing here leaves the machine (the search is local). Read access only narrows: a contract the
caller may not read is not searched and not counted.
"""

from __future__ import annotations

import logging
from typing import Any

from .db import connect

log = logging.getLogger(__name__)

#: Measured 26 Nov 2026 (10 answered questions): a wide candidate pool, a wide reranker shortlist and the cut AFTER the reranker found the right
#: page for 8 of 10, against 7 of 10 for 16 candidates reranked and 2 kept. Rank-1 and top-3 did not change.
WIDE_CANDIDATES = 60
WIDE_SHORTLIST = 40
PER_CONTRACT = 8
#: FAIR SHARE (lead-4 score of 26 Nov 2026: 8 of 12 right pages; all 4 misses were parts never listed, while one part filled up to 8 of 14
#: places): every searched part's best passage is listed, no part holds more than PER_PART_LISTED, and the list holds up to MAX_PASSAGES.
PER_PART_LISTED = 3
MAX_PASSAGES = 30
#: How many passages the engineer sees: the best LISTED of the fair-share pool, in the reranker's order (lead-4's score of run 4: the
#: right page was at rank 1 in 8 of 9 hits and rank 2 in the ninth; 30 was more to read than the hits need).
LISTED = 12
#: A passage scoring more than SCORE_FLOOR below the best (the reranker's own score) is not listed once MIN_LISTED are (lead-4's measure
#: on evidence run 14: the right passage was rank 1 or 2 for every answerable question; at 4 below, 144 listed passages become 70, every hit
#: kept, with margin for an answer that ranks lower; lead-4's decision of 26 Nov 2026).
SCORE_FLOOR = 4.0
MIN_LISTED = 3
ROLE = "CONTRACT_DOCUMENT"


def contract_ids(allowed: frozenset[str]) -> list[str]:
    """The contract documents among `allowed` (ids the caller may read), in a stable order."""
    ids = sorted(str(d) for d in allowed if d)
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT document_id FROM document_classification WHERE document_role = ? AND document_id IN ({marks}) ORDER BY document_id",
            (ROLE, *ids),
        ).fetchall()
    return [r["document_id"] for r in rows]


#: The held standards are searched TOGETHER (one search over all of them; the owner, 26 Nov 2026: technical-query evidence includes
#: company standards and the standards we hold): at most this many of their passages join the fair-share pool.
STANDARD_HITS = 12


def standard_entries(allowed: frozenset[str]) -> list[dict]:
    """The held standards among `allowed` (ids the caller may read): the general review's own definition of a rule book
    (`aim_review.library.usable`: a company standard by its recorded role, or an unroled public standard), as library entries."""
    from .aim_review import library as L

    ids = frozenset(str(d) for d in allowed if d)
    if not ids:
        return []
    with connect() as conn:
        return sorted(
            (e for e in L.library(conn, within=ids) if L.usable(e)),
            key=lambda e: e["id"],
        )


def standard_ids(allowed: frozenset[str]) -> frozenset[str]:
    """The held standards among `allowed` (a company standard by role, or an unroled public standard; never a contract, a submittal or
    any other document): the ids a Claude query draft may also send (owner, 26 Nov 2026 23:00 PKT; CLAUDE.md rule 1)."""
    return frozenset(e["id"] for e in standard_entries(allowed))


def standards_line(of: int, hits_in: int, failed: bool) -> str:
    if of == 0:
        return " No held standard that you may read: none was searched."
    if failed:
        return f" The {of} held standards you may read could not be searched."
    return (
        f" Searched the {of} held standards you may read together, hits in {hits_in}."
    )


#: What a passage's source is, said on each evidence row (the owner, 26 Nov 2026: "Show which source each passage comes from").
SOURCE_CONTRACT, SOURCE_COMPANY, SOURCE_STANDARD, SOURCE_OTHER = (
    "contract document",
    "company standard",
    "standard",
    "document",
)


def source_of(conn, document_id: str) -> tuple[str, str]:
    """(kind, name) of an evidence row's document, by its recorded role and its own number or file name (read at display time; a
    viewer sees only rows of documents they may read)."""
    from .aim_review import library as L

    entry = next(iter(L.library(conn, within=frozenset({str(document_id)}))), None)
    if entry is None:
        return SOURCE_OTHER, ""
    role = str(entry.get("document_role") or "")
    kind = SOURCE_CONTRACT if role == ROLE else SOURCE_COMPANY if role == "COMPANY_STANDARD" else SOURCE_STANDARD if L.usable(entry) else SOURCE_OTHER  # fmt: skip
    return kind, str(entry.get("title") or L.identifier_of(entry) or "")


def coverage_line(searched: int, of: int, hits_in: int, failed: int = 0) -> str:
    if of == 0:
        return "No contract document that you may read is held: nothing was searched."
    line = f"Searched {searched} of {of} contracts, hits in {hits_in}."
    if failed:
        line += f" {failed} could not be searched."
    return line


def _standard_parts(
    question: str, standard_ids: list[str]
) -> tuple[bool, list[list[dict]]]:
    """(failed, the held standards' passages grouped by standard): ONE search over every held standard the caller may read."""
    from . import search

    if not standard_ids:
        return False, []
    try:
        res = search.search(question, limit=STANDARD_HITS, rerank=True, dense=True, allowed_document_ids=frozenset(standard_ids),
                            candidates=WIDE_CANDIDATES, rerank_candidates=WIDE_SHORTLIST)  # fmt: skip
    except Exception as exc:  # noqa: BLE001 - said in the coverage line; the contracts' passages stand
        log.warning(
            "technical query: the held standards could not be searched (%s)",
            type(exc).__name__,
        )
        return True, []
    by_doc: dict[str, list[dict]] = {}
    for h in res.get("hits") or []:
        if (h.get("text") or "").strip() and h.get("document_id") in set(standard_ids):
            by_doc.setdefault(h["document_id"], []).append(h)
    return False, list(by_doc.values())


def _one(question: str, document_id: str) -> list[dict]:
    """The general search of ONE contract (dense + rerank), its PER_CONTRACT best passages with text."""
    from . import search

    res = search.search(
        question,
        limit=PER_CONTRACT,
        document_id=document_id,
        rerank=True,
        dense=True,
        allowed_document_ids=frozenset({document_id}),
        candidates=WIDE_CANDIDATES,
        rerank_candidates=WIDE_SHORTLIST,
    )
    return [h for h in (res.get("hits") or []) if (h.get("text") or "").strip()][
        :PER_CONTRACT
    ]


def search_all(
    question: str,
    allowed: frozenset[str],
    progress=None,
    cited_from: list[str] | None = None,
) -> dict[str, Any]:
    """`{"hits": [...best passages...], "coverage": {...}}`. FIRST, what the attached form itself cites (`cited_from`: the form's page
    texts; `technical_query_cited.cited_first`, builders A and C): the cited part's clause, a cited part searched first, a clause with no
    part from every part that holds it. THEN one search per contract (dense + rerank), PER_CONTRACT passages each, `fair_share` (every
    part's best, at most PER_PART_LISTED of a part, MAX_PASSAGES in all); a searched passage on the same page of the same part as one
    listed first is not listed twice. A search that fails is counted, logged by type, and never stops the others. No form: as before."""
    from . import technical_query_cited

    contracts = contract_ids(allowed)
    standards = standard_entries(frozenset(allowed) - frozenset(contracts))
    first: dict = {"hits": [], "said": [], "cited": []}
    if cited_from:
        try:
            first = technical_query_cited.cited_first(
                cited_from,
                contracts,
                question,
                lambda doc: _one(question, doc),
                standards,
            )
        except Exception as exc:  # noqa: BLE001 - the form's citations are a first look; the general search still runs
            log.warning(
                "technical query: the form's citations could not be looked up (%s)",
                type(exc).__name__,
            )
            first = {
                "hits": [],
                "said": ["the form's citations could not be looked up"],
                "cited": [],
            }
    per_part: list[list[dict]] = []
    searched = failed = hits_in = 0
    for n, document_id in enumerate(contracts, 1):
        if progress:
            progress(
                n - 1, len(contracts), f"searching contract {n} of {len(contracts)}"
            )
        try:
            found = _one(question, document_id)
        except Exception as exc:  # noqa: BLE001 - counted as not searched and said in the coverage line; the other contracts go on
            log.warning(
                "technical query: a contract could not be searched (%s)",
                type(exc).__name__,
            )
            failed += 1
            continue
        searched += 1
        hits_in += 1 if found else 0
        per_part.append(found)
    std_failed, std_parts = _standard_parts(question, [e["id"] for e in standards])
    per_part += std_parts
    taken = {(h["document_id"], h["page_start"]) for h in first["hits"]}
    hits = first["hits"] + [
        h
        for h in fair_share(per_part)
        if (h.get("document_id"), h.get("page_start")) not in taken
    ]
    line = coverage_line(searched, len(contracts), hits_in, failed) + standards_line(
        len(standards), len(std_parts), std_failed
    )
    said = first["said"]
    coverage = {
        "searched": searched,
        "of": len(contracts),
        "hits_in": hits_in,
        "failed": failed,
        "line": line
        + (
            " Looked up first, as the form cites them: " + "; ".join(said) + "."
            if said
            else ""
        ),
        "cited": first["cited"],
        "cited_first": said,
    }
    return {"hits": hits, "coverage": coverage}


def _score(hit: dict) -> float:
    """The RERANKER's own score (the search's `score` adds boosts and penalties on top of it); a passage with none ranks by its score."""
    return float(
        hit["rerank_score"]
        if hit.get("rerank_score") is not None
        else (hit.get("score") or 0.0)
    )


def fair_share(per_part: list[list[dict]]) -> list[dict]:
    """The listed passages from each part's own hits: the best passage of EVERY part first (no part is crowded out), then the next best
    overall while a part holds fewer than PER_PART_LISTED, at most MAX_PASSAGES; listed in the reranker's order."""
    ranked = [sorted(found, key=_score, reverse=True) for found in per_part if found]
    chosen = sorted((found[0] for found in ranked), key=_score, reverse=True)[
        :MAX_PASSAGES
    ]
    held = {}
    for hit in chosen:
        held[hit.get("document_id")] = held.get(hit.get("document_id"), 0) + 1
    for hit in sorted(
        (h for found in ranked for h in found[1:]), key=_score, reverse=True
    ):
        if len(chosen) >= MAX_PASSAGES:
            break
        part = hit.get("document_id")
        if held.get(part, 0) < PER_PART_LISTED:
            chosen.append(hit)
            held[part] = held.get(part, 0) + 1
    return sorted(chosen, key=_score, reverse=True)


def below_floor(hits: list[dict], listed: int, hit: dict) -> bool:
    """True when `hit` scores more than SCORE_FLOOR below the best of `hits` (sorted best first) and MIN_LISTED are already listed."""
    return (
        bool(hits)
        and listed >= MIN_LISTED
        and _score(hit) < _score(hits[0]) - SCORE_FLOOR
    )


def _searched(hits: list[dict], listed: int) -> tuple[list[dict], int]:
    """The searched passages (a cited clause's passage set apart) and how many of `listed` were searched ones (the cited come first)."""
    searched = [h for h in hits if not h.get("cited")]
    return searched, max(0, listed - (len(hits) - len(searched)))


def held_back(hits: list[dict], listed: int, hit: dict) -> bool:
    """True when `hit` is not listed: a cited clause's passage never; a searched one past LISTED searched passages, or below the floor."""
    if hit.get("cited"):
        return False
    searched, n = _searched(hits, listed)
    return n >= LISTED or below_floor(searched, n, hit)


def floor_note(hits: list[dict], listed: int) -> str:
    """The sentence that says how many found passages the floor left out (counted, never silent); "" when none."""
    hits, listed = _searched(hits, listed)
    pool = hits[:MAX_PASSAGES]
    left = sum(
        1
        for n, hit in enumerate(pool)
        if n >= listed and below_floor(pool, max(listed, MIN_LISTED), hit)
    )
    return (
        f" {left} more found passage(s) scored more than {SCORE_FLOOR:g} below the best and are not listed."
        if left
        else ""
    )
