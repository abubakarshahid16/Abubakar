"""A draft written from passages an ENGINEER verified (lead-4, 26 Nov 2026; order 14 technical queries).

The answer lane (`answer.answer`) searches the library and then gates: when no candidate fits the question well enough it refuses
before any model is asked. That gate is right for a chat question nobody has checked. It is wrong for a technical query whose engineer
has already verified the passages that answer it: in the 12-question test it refused 3 answerable questions (25 %) before any model
call. So, while `given` is open:

- retrieval returns exactly the verified passages (no search), in the engineer's order;
- the fit checks never refuse: a weak word fit is recorded on the answer as `fit` ("weak fit") and the draft is asked (the engineer's
  verification stands in for the semantic relevance score);
- when the model says the passages do not hold the answer, the draft says "Not found in the chosen papers" and names what was searched,
  in place of a refusal.

No model, no network here: this module only shapes what the answer lane sees and how its "not found" is said.
"""

from __future__ import annotations

import contextlib
import contextvars

#: The verified passages of the draft being written now (None: the ordinary search and gates).
_GIVEN: contextvars.ContextVar[list[dict] | None] = contextvars.ContextVar(
    "verified_passages", default=None
)

WEAK_FIT = "weak fit"
#: The fusion score a verified passage carries: an engineer's verification stands in for the search's relevance score, so the semantic
#: check (`answer._is_semantically_credible`) never refuses it; a weak word fit is still flagged by `relax`.
ENGINEER_VERIFIED = 1.0
NOT_FOUND = "Not found in the chosen papers"


def active() -> bool:
    """True while a draft is written from verified passages."""
    return _GIVEN.get() is not None


@contextlib.contextmanager
def given(hits: list[dict]):
    """Within this block the answer lane drafts from `hits` (from `hits_from_evidence`) and its gates only flag."""
    token = _GIVEN.set(list(hits))
    try:
        yield
    finally:
        _GIVEN.reset(token)


def search_or_given(search):
    """`search` itself, or, while `given` is open, a search that returns exactly the verified passages."""
    hits = _GIVEN.get()
    if hits is None:
        return search

    def verified(*_args, **_kwargs) -> dict:
        return {"hits": [dict(h) for h in hits], "mode": "verified passages", "reranked": False, "timings": {},
                "total": len(hits), "seconds": 0.0, "shortlist_excluded": []}  # fmt: skip

    return verified


def relax(base: dict, verdict: dict) -> None:
    """While `given` is open, the lexical gate's refusal becomes a "weak fit" flag on the answer and the draft is asked (the verdict is
    marked passed in place); otherwise nothing changes. Returns None so a caller can write `relax(...) or question`."""
    if active() and not verdict.get("ok"):
        base["fit"] = {"flag": WEAK_FIT, "reason": verdict.get("reason")}
        verdict["ok"] = True


def hits_from_evidence(conn, evidence: list[dict]) -> list[dict]:
    """Search-shaped hits made from verified evidence rows (the passage text is the verified quote, on its own pages)."""
    names: dict[str, str] = {}
    out = []
    for n, e in enumerate(evidence, 1):
        doc = e["document_id"]
        if doc not in names:
            row = conn.execute(
                "SELECT filename FROM documents WHERE id = ?", (doc,)
            ).fetchone()
            names[doc] = (row[0] if row else None) or doc
        out.append({
            "chunk_id": f"evidence:{e['id']}", "document_id": doc, "filename": names[doc], "section": e.get("locator") or "",
            "page_start": e.get("page_start"), "page_end": e.get("page_end"), "locator": e.get("locator"),
            "text": e["exact_quote"], "score": float(len(evidence) - n + 1), "rrf": ENGINEER_VERIFIED, "rerank_score": None,
            "identifier_hits": [], "text_source": "extracted",
        })  # fmt: skip
    return out


def searched_words(hits: list[dict]) -> str:
    """'<file> page 4; <file> pages 7-8': what a not-found draft searched, in the engineer's order, each document once with its pages."""
    by_doc: dict[str, list[str]] = {}
    for h in hits:
        lo, hi = h.get("page_start"), h.get("page_end")
        where = f"page {lo}" if hi is None or lo == hi else f"pages {lo}-{hi}"
        pages = by_doc.setdefault(
            str(h.get("filename") or h.get("document_id") or ""), []
        )
        if where not in pages:
            pages.append(where)
    return "; ".join(f"{doc} {', '.join(pages)}" for doc, pages in by_doc.items())


def answer(question: str, *, evidence: list[dict], **kwargs) -> dict:
    """`answer.answer(question, **kwargs)` drafted from the verified `evidence` inside `allowed_document_ids` (the documents the engine
    may read). A model that finds the answer is not in them gives a draft that says so ("Not found in the chosen papers. Searched: ..."),
    with no citation, the model's reason as an open point, and the model that was asked."""
    from . import answer as answer_mod
    from .db import connect

    allowed = kwargs.get("allowed_document_ids") or frozenset()
    with connect() as conn:
        hits = hits_from_evidence(
            conn, [e for e in evidence if e["document_id"] in allowed]
        )
    with given(hits):
        result = answer_mod.answer(question, **kwargs)
    # "not found" only when the MODEL read the passages and said so; a refusal made before any model was asked (the front-matter
    # gate) stays a refusal with its own words (review of update 12, N4)
    answered = "generation_ms" in (result.get("timings") or {})
    if (
        result.get("answer_type") == "insufficient_evidence"
        and result.get("absence_kind") == "not_found"
        and answered
    ):
        reason = (
            result.get("reason")
            or "the model reported the passages do not contain the answer"
        )
        # the model that answered, as it reported itself (never the configured name): a Claude draft that fell back to the local
        # model keeps its "Claude did not write this draft" note (review of update 12, N3)
        return {**result, "answer_type": "generated", "answer": f"{NOT_FOUND}. Searched: {searched_words(hits)}.", "cited": [],
                "passages": [], "not_found": True, "reason": reason, "model": result.get("model") or "not reported"}  # fmt: skip
    return result
