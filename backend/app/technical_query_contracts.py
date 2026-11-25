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

PER_CONTRACT = 2
MAX_PASSAGES = 20
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
    """`{"hits": [...best passages...], "coverage": {...}}`. One search per contract (dense + rerank), PER_CONTRACT passages each, the best
    MAX_PASSAGES overall by score. A search that fails is counted, logged by type, and never stops the others."""
    from . import search, technical_query_reach

    chosen = technical_query_reach.ideas()
    per_contract = technical_query_reach.WIDE_KEEP if "b" in chosen else PER_CONTRACT
    contracts = contract_ids(allowed)
    hits: list[dict] = []
    searched = failed = hits_in = 0
    for n, document_id in enumerate(contracts, 1):
        if progress:
            progress(
                n - 1, len(contracts), f"searching contract {n} of {len(contracts)}"
            )
        try:
            found = technical_query_reach.search_contract(
                question, document_id, per_contract, search_fn=search.search
            )
        except Exception as exc:  # noqa: BLE001 - counted as not searched and said in the coverage line; the other contracts go on
            log.warning(
                "technical query: a contract could not be searched (%s)",
                type(exc).__name__,
            )
            failed += 1
            continue
        searched += 1
        hits_in += 1 if found else 0
        hits.extend(found)
    # ranked by the RERANKER's own score (the search's `score` adds boosts and penalties on top of it); a passage with none ranks by its score
    hits.sort(
        key=lambda h: float(
            h["rerank_score"]
            if h.get("rerank_score") is not None
            else (h.get("score") or 0.0)
        ),
        reverse=True,
    )
    coverage = {
        "searched": searched,
        "of": len(contracts),
        "hits_in": hits_in,
        "failed": failed,
        "line": coverage_line(searched, len(contracts), hits_in, failed),
        "reach": "".join(
            sorted(chosen)
        ),  # which reach ideas were on for this search ("" = the plain search)
    }
    return {"hits": hits[:MAX_PASSAGES], "coverage": coverage}
