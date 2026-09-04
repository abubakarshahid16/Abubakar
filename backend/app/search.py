"""Hybrid retrieval: FTS5 + dense vectors, fused with RRF, then reranked.

Design constraints that shaped this:

* It must work with NO vectors at all. A document is answerable seconds after
  upload, long before embedding finishes, so dense retrieval is an upgrade
  rather than a dependency. Every stage degrades to keyword-only cleanly.
* Lexical matching is what gets identifiers right. `API 610`, clause `5.3.2`,
  `ASTM A216 WCB` - embeddings blur these, BM25 does not. Exact identifier
  matches are boosted explicitly rather than hoped for.
* Brute-force cosine over stored vectors, no ANN index. At this scale it is
  both faster and exact, and an approximate index would add a recall question
  nobody has asked for.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

import numpy as np

from . import keyword
from .db import connect
from .config import settings
from .embedder import EMBEDDING_DIM, Embedder, EmbedderConfig
from .rates import Timer

#: RRF damping. 60 is the value from the original paper and behaves well when
#: one of the two lists is empty, which is the normal case before embedding.
RRF_K = 60

#: How much an exact identifier match is worth, as a fraction of the top RRF
#: score. Deliberately additive rather than multiplicative so it cannot
#: dominate a result that matches nothing else.
IDENTIFIER_BOOST = 0.5

#: Two chunks whose texts share this proportion of tokens are near-duplicates.
DUPLICATE_OVERLAP = 0.85

_TOKEN = re.compile(r"[\w.\-/]+")


@dataclass
class Candidate:
    chunk_id: str
    document_id: str
    filename: str
    section: str | None
    page_start: int
    page_end: int
    text: str
    keyword_rank: int | None = None
    dense_rank: int | None = None
    bm25: float | None = None
    cosine: float | None = None
    rrf: float = 0.0
    identifier_hits: list[str] = field(default_factory=list)
    boost: float = 0.0
    rerank_score: float | None = None

    @property
    def score(self) -> float:
        """Final ordering score. Rerank wins when available."""
        if self.rerank_score is not None:
            return self.rerank_score
        return self.rrf + self.boost

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "filename": self.filename,
            "section": self.section,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "text": self.text,
            "score": round(self.score, 6),
            "rrf": round(self.rrf, 6),
            "boost": round(self.boost, 6),
            "rerank_score": None if self.rerank_score is None else round(self.rerank_score, 6),
            "bm25": None if self.bm25 is None else round(self.bm25, 4),
            "cosine": None if self.cosine is None else round(self.cosine, 6),
            "keyword_rank": self.keyword_rank,
            "dense_rank": self.dense_rank,
            "identifier_hits": self.identifier_hits,
        }


# --------------------------------------------------------------- dense side


def _load_vectors(document_id: str | None = None) -> tuple[list[str], np.ndarray]:
    """All stored vectors for retrievable chunks, as one matrix.

    Joined against `chunks` so a vector orphaned by a re-chunk can never be
    retrieved, and filtered on `retrievable` so an excluded chunk cannot come
    back through the dense path even if it slipped past the index.
    """
    conn = connect()
    sql = """SELECT v.chunk_id, v.vector FROM chunk_vectors v
             JOIN chunks c ON c.id = v.chunk_id
             WHERE c.retrievable = 1"""
    params: list[object] = []
    if document_id:
        sql += " AND v.document_id = ?"
        params.append(document_id)
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return [], np.zeros((0, EMBEDDING_DIM), dtype=np.float32)

    ids = [r["chunk_id"] for r in rows]
    matrix = np.frombuffer(b"".join(r["vector"] for r in rows), dtype=np.float32)
    matrix = matrix.reshape(len(ids), EMBEDDING_DIM)
    return ids, matrix


def dense_search(question: str, limit: int = 30, document_id: str | None = None) -> list[dict]:
    """Brute-force cosine. Returns [] when nothing is embedded yet."""
    ids, matrix = _load_vectors(document_id)
    if not ids:
        return []

    query_vec = Embedder.instance(EmbedderConfig()).embed_queries([question])[0]
    # both sides are unit length, so the dot product IS the cosine
    scores = matrix @ query_vec
    top = np.argsort(-scores)[:limit]
    return [{"chunk_id": ids[i], "cosine": float(scores[i])} for i in top]


# ---------------------------------------------------------------- fusion


def rrf_fuse(
    keyword_hits: list[dict],
    dense_hits: list[dict],
    k: int = RRF_K,
) -> dict[str, dict]:
    """Reciprocal Rank Fusion.

    BM25 scores and cosine similarities are not comparable - different scales,
    different signs, different distributions. RRF discards the magnitudes and
    fuses the RANKS, which is what makes a hybrid of the two meaningful.
    """
    fused: dict[str, dict] = {}
    for rank, hit in enumerate(keyword_hits, start=1):
        entry = fused.setdefault(hit["chunk_id"], {"rrf": 0.0})
        entry["rrf"] += 1.0 / (k + rank)
        entry["keyword_rank"] = rank
        entry["bm25"] = hit.get("bm25")
    for rank, hit in enumerate(dense_hits, start=1):
        entry = fused.setdefault(hit["chunk_id"], {"rrf": 0.0})
        entry["rrf"] += 1.0 / (k + rank)
        entry["dense_rank"] = rank
        entry["cosine"] = hit.get("cosine")
    return fused


def find_identifiers(text: str) -> list[str]:
    return keyword.IDENTIFIER.findall(text)


def apply_identifier_boost(question: str, candidates: list[Candidate]) -> None:
    """Reward chunks that literally contain the identifiers in the question.

    A question about `API 610` is about API 610. Semantic similarity will
    happily rank a passage about vibration limits generally above the one that
    names the standard, which is the wrong answer for an engineering lookup.
    """
    wanted = {i.lower() for i in find_identifiers(question)}
    if not wanted:
        return
    top_rrf = max((c.rrf for c in candidates), default=0.0) or 1.0
    for c in candidates:
        lowered = c.text.lower()
        hits = sorted({w for w in wanted if w in lowered})
        if hits:
            c.identifier_hits = hits
            c.boost = IDENTIFIER_BOOST * top_rrf * (len(hits) / len(wanted))


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


def deduplicate(candidates: list[Candidate]) -> list[Candidate]:
    """Drop near-identical chunks, keeping the better-scoring one.

    Overlapping chunks legitimately share text, so an exact-match check is not
    enough; this compares token overlap against the shorter of the two.
    """
    kept: list[Candidate] = []
    kept_tokens: list[set[str]] = []
    for c in sorted(candidates, key=lambda x: -x.score):
        tokens = _tokens(c.text)
        if not tokens:
            continue
        duplicate = False
        for existing in kept_tokens:
            shorter = min(len(tokens), len(existing)) or 1
            if len(tokens & existing) / shorter >= DUPLICATE_OVERLAP:
                duplicate = True
                break
        if not duplicate:
            kept.append(c)
            kept_tokens.append(tokens)
    return kept


# ----------------------------------------------------------------- lookup


def _hydrate(chunk_ids: list[str]) -> dict[str, sqlite3.Row]:
    if not chunk_ids:
        return {}
    conn = connect()
    marks = ",".join("?" * len(chunk_ids))
    rows = conn.execute(
        f"""SELECT id, document_id, filename, section, page_start, page_end,
                   text, retrievable
            FROM chunks WHERE id IN ({marks})""",
        chunk_ids,
    ).fetchall()
    return {r["id"]: r for r in rows}


# ------------------------------------------------------------------ search


def search(
    question: str,
    limit: int = 10,
    candidates: int | None = None,
    document_id: str | None = None,
    rerank: bool = True,
    dense: bool = True,
) -> dict:
    """Hybrid retrieval end to end.

    Returns the ordered passages plus how they were found, so a result can
    always be explained: which side retrieved it, at what rank, and what the
    rerank thought.
    """
    timer = Timer()
    timings: dict[str, float] = {}
    candidates = candidates or settings.search_candidates

    t = Timer()
    keyword_hits = keyword.search(question, limit=candidates, document_id=document_id)
    timings["keyword_ms"] = round(t.elapsed * 1000, 2)

    dense_hits: list[dict] = []
    if dense:
        t = Timer()
        dense_hits = dense_search(question, limit=candidates, document_id=document_id)
        timings["dense_ms"] = round(t.elapsed * 1000, 2)

    fused = rrf_fuse(keyword_hits, dense_hits)
    rows = _hydrate(list(fused))

    pool: list[Candidate] = []
    for chunk_id, meta in fused.items():
        row = rows.get(chunk_id)
        # a chunk that has since been excluded or re-chunked must not surface
        if row is None or not row["retrievable"]:
            continue
        pool.append(
            Candidate(
                chunk_id=chunk_id,
                document_id=row["document_id"],
                filename=row["filename"],
                section=row["section"],
                page_start=row["page_start"],
                page_end=row["page_end"],
                text=row["text"],
                keyword_rank=meta.get("keyword_rank"),
                dense_rank=meta.get("dense_rank"),
                bm25=meta.get("bm25"),
                cosine=meta.get("cosine"),
                rrf=meta["rrf"],
            )
        )

    apply_identifier_boost(question, pool)
    pool = deduplicate(pool)
    pool.sort(key=lambda c: -c.score)

    reranked = False
    if rerank and pool:
        from . import reranker

        t = Timer()
        shortlist = pool[: settings.rerank_candidates]
        scored = reranker.rerank(question, [(c.chunk_id, c.text) for c in shortlist])
        timings["rerank_ms"] = round(t.elapsed * 1000, 2)
        if scored:
            reranked = True
            by_id = dict(scored)
            for c in shortlist:
                # the identifier boost still applies on top of the rerank,
                # so a semantically plausible passage that omits the
                # identifier cannot displace the one that names it
                c.rerank_score = by_id.get(c.chunk_id, float("-inf")) + c.boost

            # Only the shortlist was reranked, and the two scales are not
            # comparable: an unrelated passage scores about -11 from the
            # cross-encoder while an unreranked candidate keeps a raw RRF of
            # about 0.012. Mixing them let a leftover candidate outrank every
            # properly scored one - and because its RRF sat just above the
            # fallback threshold, an unanswerable question returned a
            # confident-looking passage instead of refusing.
            pool = shortlist
            pool.sort(key=lambda c: -c.score)

    return {
        "query": question,
        "mode": "hybrid" if dense_hits else "keyword_only",
        "reranked": reranked,
        "keyword_candidates": len(keyword_hits),
        "dense_candidates": len(dense_hits),
        "total": len(pool),
        "seconds": timer.seconds(),
        "timings": timings,
        "hits": [c.to_dict() for c in pool[:limit]],
    }
