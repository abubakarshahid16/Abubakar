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


def coverage_line(searched: int, of: int, hits_in: int, failed: int = 0) -> str:
    if of == 0:
        return "No contract document that you may read is held: nothing was searched."
    line = f"Searched {searched} of {of} contracts, hits in {hits_in}."
    if failed:
        line += f" {failed} could not be searched."
    return line


def search_all(question: str, allowed: frozenset[str], progress=None) -> dict[str, Any]:
    """`{"hits": [...best passages...], "coverage": {...}}`. One search per contract (dense + rerank), PER_CONTRACT passages each, then
    `fair_share` (every part's best, at most PER_PART_LISTED of a part, MAX_PASSAGES in all). A search that fails is counted, logged by type, and never stops the others."""
    from . import search

    contracts = contract_ids(allowed)
    hits: list[dict] = []
    per_part: list[list[dict]] = []
    searched = failed = hits_in = 0
    for n, document_id in enumerate(contracts, 1):
        if progress:
            progress(
                n - 1, len(contracts), f"searching contract {n} of {len(contracts)}"
            )
        try:
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
            found = [
                h for h in (res.get("hits") or []) if (h.get("text") or "").strip()
            ][:PER_CONTRACT]
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
    hits = fair_share(per_part)
    coverage = {
        "searched": searched,
        "of": len(contracts),
        "hits_in": hits_in,
        "failed": failed,
        "line": coverage_line(searched, len(contracts), hits_in, failed),
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
