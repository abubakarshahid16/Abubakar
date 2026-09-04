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

#: A passage whose heading names a DIFFERENT member of the designator the
#: question asked about is not merely less relevant - it is about something
#: else. Quoting coating system 4's film thickness for a question about system
#: 1 reads perfectly plausible and is simply false, so it is pushed below every
#: passage that does not contradict the question. Expressed as a fraction of
#: the observed score spread, so it works on the rerank scale and the RRF scale
#: alike.
CONFLICT_PENALTY = 1.0

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
    #: designators this passage names that the question did NOT ask for
    conflicts: list[str] = field(default_factory=list)
    boost: float = 0.0
    penalty: float = 0.0
    rerank_score: float | None = None

    @property
    def searchable_text(self) -> str:
        """Heading plus body. What the passage actually is, for matching and
        reranking - the heading carries the clause number and designator."""
        return self.section + "\n" + self.text if self.section else self.text

    @property
    def score(self) -> float:
        """Final ordering score. Rerank wins when available."""
        if self.rerank_score is not None:
            return self.rerank_score - self.penalty
        return self.rrf + self.boost - self.penalty

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
            "penalty": round(self.penalty, 6),
            "conflicts": self.conflicts,
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


def find_designators(text: str) -> list[str]:
    return keyword.find_designators(text)


def apply_identifier_boost(question: str, candidates: list[Candidate]) -> None:
    """Reward chunks that literally contain the question's identifiers.

    A question about `API 610` is about API 610. Semantic similarity will
    happily rank a passage about vibration limits generally above the one that
    names the standard, which is the wrong answer for an engineering lookup.

    Designators are treated the same way and matter more, because getting one
    wrong is not a missing answer but a confidently wrong one: quoting coating
    system 4's film thickness in answer to a question about system 1 reads
    perfectly plausible and is simply false.
    """
    wanted: dict[str, list[str]] = {}
    for ident in find_identifiers(question):
        wanted[ident.lower()] = [ident.lower()]
    for designator in keyword.find_designators(question):
        wanted[designator.lower()] = [
            v.lower() for v in keyword.designator_variants(designator)
        ]
    if not wanted:
        return

    top_rrf = max((c.rrf for c in candidates), default=0.0) or 1.0
    wanted_designators = keyword.find_designators(question)
    for c in candidates:
        # The section heading is part of the passage's identity, and in a
        # specification it is where the designator usually lives: annex A.1's
        # body never says "system 1", its heading does. Matching the body
        # alone ranked system 4's table first for a question about system 1 -
        # a confidently wrong answer, not a missing one.
        lowered = c.searchable_text.lower()
        hits = sorted(
            key for key, spellings in wanted.items()
            if any(v in lowered for v in spellings)
        )
        if hits:
            c.identifier_hits = hits
            c.boost = IDENTIFIER_BOOST * top_rrf * (len(hits) / len(wanted))

        # Which member does the HEADING declare? In a specification the clause
        # heading is the authoritative scope of the passage; a mention in the
        # body is usually a cross-reference. Annex A.4's text really does say
        # "Coating system no. 1 may be used on other deck areas", so matching
        # body text alone cannot tell A.1 from A.4 - and getting that wrong
        # quotes system 4's film thickness as system 1's.
        heading = c.section or ""
        for want in wanted_designators:
            word, _, value = want.partition(" ")
            declared = {
                m.group(2).upper()
                for m in keyword.DESIGNATOR.finditer(heading)
                if m.group(1).lower() == word
            }
            if not declared:
                continue
            if value.upper() in declared:
                c.identifier_hits = sorted(set(c.identifier_hits) | {want})
                c.boost = max(c.boost, IDENTIFIER_BOOST * top_rrf * 2)
            else:
                c.conflicts = sorted(f"{word} {v}" for v in declared)


def _apply_conflict_penalty(candidates: list[Candidate], reranked: bool = False) -> None:
    """Push contradicting passages below every non-contradicting one.

    Scaled to the spread of whatever scores are in play, because the RRF scale
    (~0.03) and the cross-encoder scale (~1-8) differ by two orders of
    magnitude - a boost tuned for one is numerically invisible on the other,
    which is exactly how a passage about coating system 4 stayed top for a
    question about system 1.
    """
    if not any(c.conflicts for c in candidates):
        return
    scores = [
        c.rerank_score if (reranked and c.rerank_score is not None) else c.rrf
        for c in candidates
    ]
    scores = [s for s in scores if s is not None and s != float("-inf")]
    spread = (max(scores) - min(scores)) if len(scores) > 1 else 1.0
    step = max(spread, 1e-6) * CONFLICT_PENALTY
    for c in candidates:
        c.penalty = step if c.conflicts else 0.0


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
        # two annex tables can share almost all their body text and differ
        # only by heading, so dedup must see the heading too
        tokens = _tokens(c.searchable_text)
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


#: Trailing punctuation an engineer types without thinking. It carries no
#: meaning and the cross-encoder is measurably hostile to it: on the NORSOK
#: corpus the identical question scored +1.44 as "what is ndft", +0.18 as
#: "what is ndft?" and -0.14 as "what is ndft ??" - and the last of those fell
#: below the credibility threshold and refused a question the document
#: answers, in 3.2 Abbreviations, with "NDFT nominal dry film thickness".
#:
#: The fix belongs here, at the input, and NOT in the threshold. Loosening the
#: gate to admit a -0.14 would admit every genuinely unrelated passage too.
_TRAILING_PUNCTUATION = re.compile(r"[\s?!.,;:]+$")


def normalise_question(question: str) -> str:
    """The question as the scorers should see it: no trailing punctuation
    noise, no repeated whitespace. Case is deliberately left alone - the
    cross-encoder is uncased (measured: 1.437 vs 1.426 for the same question
    in either case), and identifiers like CA6NM read better as written."""
    return _TRAILING_PUNCTUATION.sub("", " ".join(question.split()))


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

    # Everything that scores sees the normalised question. The original is
    # kept for the response, so the reader is always shown what they typed.
    asked = question
    question = normalise_question(question)

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
    _apply_conflict_penalty(pool)
    pool = deduplicate(pool)
    pool.sort(key=lambda c: -c.score)

    reranked = False
    if rerank and pool:
        from . import reranker

        t = Timer()
        shortlist = pool[: settings.rerank_candidates]
        # rerank on heading + body, so the cross-encoder can see which coating
        # system, clause or annex a passage belongs to
        scored = reranker.rerank(
            question, [(c.chunk_id, c.searchable_text) for c in shortlist]
        )
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
            _apply_conflict_penalty(pool, reranked=True)
            pool.sort(key=lambda c: -c.score)

    return {
        "query": asked,
        "mode": "hybrid" if dense_hits else "keyword_only",
        "reranked": reranked,
        "keyword_candidates": len(keyword_hits),
        "dense_candidates": len(dense_hits),
        "total": len(pool),
        "seconds": timer.seconds(),
        "timings": timings,
        "hits": [c.to_dict() for c in pool[:limit]],
    }
