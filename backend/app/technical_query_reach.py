"""How far a technical query's evidence search reaches into ONE contract (lead 4, 26 Nov 2026: for 3 of 10 answered questions no passage from the
right contract page was among the proposed ones). Three ideas, each behind its own letter of `TECHNICAL_QUERY_REACH`, so each can be measured alone:

  b  MORE CANDIDATES. The contract is searched with a wide candidate pool and the reranker reads a wide shortlist; the cut to the few kept comes
     AFTER the reranker (it was 16 fused candidates reranked, then 2 kept).
  c  HEADINGS. The contract's own headings (the heading chain of each chunk) are searched as well as its body text: a chunk whose heading holds at
     least half of the question's key terms is a candidate even when its body words never matched the way the contractor asked.
  a  OWN WORDS. The question is widened with words from the contract's OWN headings that hold a question term and from its defined terms
     ("Works" means ...), by code, no model, no outside thesaurus. The wider question is a second search of the same contract.

Whatever the ideas bring in is scored by the reranker against the ORIGINAL question, so every score is on one scale and the wider question
never ranks a passage by its own wording. With no letter set, nothing here runs and the search is exactly what it was.
"""

from __future__ import annotations

import logging
import re

from . import technical_query_match as M

log = logging.getLogger(__name__)

IDEAS = frozenset("abc")
WIDE_CANDIDATES = 60
WIDE_SHORTLIST = 40
WIDE_KEEP = 8
HEADING_CANDIDATES = 8
EXPAND_PER_HEADING = 4
EXPAND_TOTAL = 8
DEFINITION = re.compile(
    r"[\"“]([A-Z][A-Za-z0-9 /-]{2,40})[\"”]\s+(?:means|shall mean|has the meaning)\s+([^.\n]{5,200})"
)


def ideas() -> frozenset[str]:
    """The letters the owner's setting turns on (unknown letters ignored)."""
    from .config import settings

    return frozenset(str(settings.technical_query_reach or "").lower()) & IDEAS


def _terms(text: str) -> list[str]:
    return M.key_terms(text)


def heading_candidates(
    conn, document_id: str, question: str, limit: int = HEADING_CANDIDATES
) -> list[dict]:
    """Chunks of the contract whose heading chain holds at least half of the question's key terms (the most terms first), as passage dicts."""
    terms = _terms(question)
    if not terms:
        return []
    need = M.required(len(terms))
    out = []
    for r in conn.execute(
        "SELECT id, filename, section, context, page_start, page_end, text FROM chunks WHERE document_id = ? AND retrievable = 1 "
        "AND (section IS NOT NULL OR context IS NOT NULL)",
        (document_id,),
    ):
        heading = f"{r['context'] or ''} {r['section'] or ''}"
        held = M.score(terms, heading)["count"]
        if held >= need:
            out.append((held, r))
    out.sort(key=lambda t: (-t[0], t[1]["page_start"]))
    return [
        {"chunk_id": r["id"], "document_id": document_id, "filename": r["filename"], "section": r["section"], "context": r["context"],
         "page_start": r["page_start"], "page_end": r["page_end"], "text": r["text"], "via": "heading"}
        for _held, r in out[:limit]
    ]  # fmt: skip


def own_words(conn, document_id: str, question: str) -> list[str]:
    """Words from the contract's OWN headings that hold a question term, and from its defined terms that a question term names: the words a
    contractor's question may be worded with in THIS contract. Never a word the question already has; at most EXPAND_TOTAL."""
    terms = set(_terms(question))
    have = {M.stem(w) for w in M.WORD.findall(question or "")}
    extra: list[str] = []

    def take(words) -> None:
        for w in words:
            s = M.stem(w)
            if (
                s
                and s not in terms
                and s not in have
                and s not in extra
                and len(extra) < EXPAND_TOTAL
            ):
                extra.append(s)

    seen_headings: set[str] = set()
    for r in conn.execute(
        "SELECT DISTINCT section, context FROM chunks WHERE document_id = ? AND retrievable = 1",
        (document_id,),
    ):
        heading = " ".join(f"{r['context'] or ''} {r['section'] or ''}".split())
        if not heading or heading in seen_headings:
            continue
        seen_headings.add(heading)
        words = _terms(heading)
        if terms & set(words):
            take(
                words[:EXPAND_PER_HEADING] if len(words) > EXPAND_PER_HEADING else words
            )
    for r in conn.execute(
        "SELECT text FROM chunks WHERE document_id = ? AND retrievable = 1 AND text LIKE '%means%' LIMIT 400",
        (document_id,),
    ):
        for term, meaning in DEFINITION.findall(r["text"] or ""):
            if terms & set(_terms(term)):
                take(_terms(meaning)[:6])
    return extra


def _key(hit: dict) -> tuple:
    return (
        hit.get("document_id"),
        hit.get("page_start"),
        " ".join(str(hit.get("text") or "").split())[:120],
    )


def search_contract(
    question: str, document_id: str, per_contract: int, *, search_fn, rerank_fn=None
) -> list[dict]:
    """The passages of ONE contract for the question: `per_contract` of them, best reranker score first. With no idea switched on it is the
    plain search it always was (`search_fn(question, limit=per_contract, ...)`)."""
    from .db import connect

    chosen = ideas()
    allowed = frozenset({document_id})
    if not chosen:
        res = search_fn(
            question,
            limit=per_contract,
            document_id=document_id,
            rerank=True,
            dense=True,
            allowed_document_ids=allowed,
        )
        return [h for h in (res.get("hits") or []) if (h.get("text") or "").strip()][
            :per_contract
        ]
    keep = max(per_contract, WIDE_KEEP) if "b" in chosen else per_contract
    wide = (
        {"candidates": WIDE_CANDIDATES, "rerank_candidates": WIDE_SHORTLIST}
        if "b" in chosen
        else {}
    )
    base = search_fn(
        question,
        limit=keep,
        document_id=document_id,
        rerank=True,
        dense=True,
        allowed_document_ids=allowed,
        **wide,
    )
    merged: dict[tuple, dict] = {
        _key(h): h for h in (base.get("hits") or []) if (h.get("text") or "").strip()
    }
    added: dict[tuple, dict] = {}
    conn = connect()
    if "a" in chosen:
        words = own_words(conn, document_id, question)
        if words:
            more = search_fn(f"{question} {' '.join(words)}", limit=keep, document_id=document_id, rerank=True, dense=True,
                             allowed_document_ids=allowed, **wide)  # fmt: skip
            for h in more.get("hits") or []:
                if (h.get("text") or "").strip() and _key(h) not in merged:
                    added[_key(h)] = {**h, "via": "own_words"}
    if "c" in chosen:
        for h in heading_candidates(conn, document_id, question):
            if _key(h) not in merged and _key(h) not in added:
                added[_key(h)] = h
    if added:  # everything the extra ideas brought in is scored against the ORIGINAL question, so all scores share one scale
        if rerank_fn is None:
            from . import reranker

            rerank_fn = reranker.rerank
        items = list(added.items())
        got = dict(
            rerank_fn(
                question,
                [
                    (str(i), f"{h.get('section') or ''}\n{h['text']}".strip())
                    for i, (_k, h) in enumerate(items)
                ],
            )
        )
        for i, (k, h) in enumerate(items):
            if str(i) in got:
                h = {
                    **h,
                    "rerank_score": float(got[str(i)]),
                    "score": float(got[str(i)]),
                }
            merged[k] = h
    hits = sorted(
        merged.values(),
        key=lambda h: float(
            h["rerank_score"]
            if h.get("rerank_score") is not None
            else (h.get("score") or 0.0)
        ),
        reverse=True,
    )
    return hits[:keep]
