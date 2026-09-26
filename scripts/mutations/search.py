"""Mutations of `backend/app/search.py` and the keyword scope clause - the B6
core-retrieval stages, each deleted in turn so `test_b6_core_retrieval.py`
must fail. Needs the staged models (the tests ingest a synthetic corpus)."""

from __future__ import annotations

from ._base import APP, Mutation

_S = APP / "search.py"
_T = "tests/test_b6_core_retrieval.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M790", phase=67, description="B6: dense retrieval disabled - hybrid search is keyword-only",
        path=_S,
        anchor="    if dense:\n        t = Timer()\n        dense_hits = dense_search(\n",
        replacement="    if False:\n        t = Timer()\n        dense_hits = dense_search(\n",
        target=_T, keyword="dense or fusion",
    ),
    Mutation(
        id="M791", phase=67, description="B6: RRF broken - a worse keyword rank scores higher",
        path=_S,
        anchor='        entry["rrf"] += 1.0 / (k + rank)\n        entry["keyword_rank"] = rank\n',
        replacement='        entry["rrf"] += rank / k\n        entry["keyword_rank"] = rank\n',
        target=_T, keyword="fusion",
    ),
    Mutation(
        id="M792", phase=67, description="B6: RRF broken - the dense side contributes nothing to the fused score",
        path=_S,
        anchor='        entry["rrf"] += 1.0 / (k + rank)\n        entry["dense_rank"] = rank\n',
        replacement='        entry["rrf"] += 0.0\n        entry["dense_rank"] = rank\n',
        target=_T, keyword="fusion",
    ),
    Mutation(
        id="M793", phase=67, description="B6: reranker skipped even when asked for",
        path=_S,
        anchor="    if rerank and pool:\n",
        replacement="    if False and pool:\n",
        target=_T, keyword="cross_encoder or recall",
    ),
    Mutation(
        id="M794", phase=67, description="B6: reranker broken - its scores are inverted",
        path=_S,
        anchor='                c.rerank_score = by_id.get(c.chunk_id, float("-inf")) + c.boost\n',
        replacement='                c.rerank_score = -by_id.get(c.chunk_id, float("inf")) + c.boost\n',
        target=_T, keyword="cross_encoder or recall",
    ),
    Mutation(
        id="M795", phase=67, description="B6: dense permission mask removed - every chunk is in scope",
        path=_S,
        anchor="        [owner.get(cid) in allowed_document_ids for cid in ids], dtype=bool\n",
        replacement="        [True for cid in ids], dtype=bool\n",
        target=_T, keyword="grants or mask", tags=("access",),
    ),
    Mutation(
        id="M796", phase=67, description="B6: keyword permission clause removed - FTS5 searches every document",
        path=APP / "keyword.py",
        anchor='    where += f" AND document_id IN ({marks})"\n    params.extend(sorted(allowed_document_ids))\n',
        replacement="",
        target=_T, keyword="grants", tags=("access",),
    ),
)
