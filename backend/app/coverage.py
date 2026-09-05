"""Which documents the question was about, and which of them the answer used.

Report-only. Nothing here changes retrieval, reranking, ordering or the
passages an answer is built from; it describes what already happened.

The question this exists to answer is not "did the system miss a document".
Gold question Q4 was measured on 2026-09-05 and the system did not miss
anything: the second document's correct section was retrieved, shortlisted,
reranked to +2.104 against a -3.0 floor, and placed fifth of sixteen - above
four candidates from the document that *was* cited. It lost to `limit=3`.

That is the fact this module reports: **a credible passage existed in another
document and the answer did not include it.** Smaller and truer than a miss,
and actionable in a way a miss is not.

Two rules that are not negotiable, and each has a test rather than a comment.

1. `complete: True` is never emitted. Term incidence is a presence test, and
   `docs/gold-questions.md` opens by saying presence is not relevance -
   demonstrated since with `contractor`, which appears in two documents and is
   a real requirement in one and the phrase "the Federal Government and their
   contractors" in the other. A completeness guarantee derived from word counts
   would be a stronger claim than the evidence supports. The field is `False`
   or `None`.

2. This module may call `keyword.term_occurrences(term, doc_id)` and must
   NEVER call `lexical.assess` with a document_id it derived itself. The
   absolute presence gate inside `assess` (`lexical.py:233-251`) is already
   parameterised by document, so one careless loop turns "does not appear
   anywhere in the indexed documents" into "does not appear in this document" -
   and that refusal text is user-visible and says *anywhere*. The gate runs
   exactly once, before any per-document reasoning, on the scope the request
   already had, and its verdict is final.

It does not scale. Cost is terms x documents FTS COUNT(*) queries: tens of
milliseconds at twelve documents, off the rerank path. At a thousand it is the
whole latency budget and needs a term-to-document posting aggregate instead.
Noted, not built.
"""

from __future__ import annotations

from typing import Literal

from . import keyword, lexical

#: What the completeness verdict rests on.
#:
#: `term_incidence` is deliberately absent, and that is a finding rather than
#: an omission. The design specified it; measured on the twelve-document corpus
#: it made **all twelve documents "expected" on Q4**, because "contain" is an
#: ordinary English verb that appears in every one of them. Q2 and Q6 fail the
#: same way on "cost" and "form". Every cutoff that would fix it - a document
#: spread limit, a two-term minimum - is a new constant on a new scale with one
#: question of evidence, which is the practice `scores.py` exists to stop. So
#: the incidence table is still reported per document, and no expectation is
#: computed from it.
#:
#: What completeness rests on instead needs no constant: a document with a
#: passage above the credibility floor that the answer did not use. That is a
#: measured fact about this query, not an inference from word counts.
CoverageBasis = Literal[
    "credible_uncited",       # a credible passage existed and was not used
    "single_document_scope",  # the reader's own filter was in force
    "none",                   # no completeness claim is being made
]

#: A passage from this document reached the reader, or it did not and this is
#: why. Ordered most-favourable first: the first status that fits is the one
#: reported, so a document that is cited is never also reported as a gap.
DocumentCoverageStatus = Literal[
    "answered",               # a passage from this document is in the answer
    "supporting",             # offered alongside the answer, not part of it
    "credible_not_cited",     # cleared the credibility floor, answer took others
    "retrieved_not_credible", # reached the rerank batch, scored below the floor
    "expected_not_shortlisted",  # contributed candidates, none reached the shortlist
    "expected_not_retrieved",    # carries a distinguishing term, contributed nothing
    "searched_no_match",         # in scope, and keyword and dense found nothing
]

#: Ordering is the classification rule, not decoration.
_STATUS_ORDER: tuple[str, ...] = (
    "answered",
    "supporting",
    "credible_not_cited",
    "retrieved_not_credible",
    "expected_not_shortlisted",
    "expected_not_retrieved",
    "searched_no_match",
)

#: The statuses that mean the reader saw evidence from this document.
CITED = ("answered", "supporting")

_REASONS = {
    "answered": None,
    "supporting": "Offered as a supporting passage rather than the answer.",
    "credible_not_cited": (
        "A passage from this document cleared the credibility floor but the "
        "answer takes only its highest-ranked passages."
    ),
    "retrieved_not_credible": (
        "Passages were found and scored, and none was a credible match for "
        "this question."
    ),
    "expected_not_shortlisted": (
        "This document contributed candidates and none of them reached the "
        "scoring stage, so no credibility judgement was made about it."
    ),
    "expected_not_retrieved": (
        "This document contains a distinguishing term from the question and "
        "keyword and vector retrieval returned nothing from it."
    ),
    "searched_no_match": "Searched, and nothing in it matched the question.",
}


def distinguishing_terms(question: str) -> list[str]:
    """Question terms specific enough that their absence means something.

    The same corpus-frequency rule `lexical.distinguishing_uncovered_terms`
    uses, at corpus scope and without its compound-question precondition: that
    function returns `[]` for a single-subject question, which is the right
    answer for choosing a second passage and the wrong one for asking which
    documents a question is about.

    `distinctive_terms` is reused rather than reimplemented so that a
    multi-word expansion the corpus defines keeps counting as one term.
    """
    indexed = keyword.indexed_count()
    if not indexed:
        return []
    cutoff = (
        max(1, int(indexed * lexical.COMMON_TERM_FRACTION))
        if indexed >= lexical.MIN_CORPUS_FOR_COMMONNESS
        # too small a corpus to judge commonness, so nothing counts as common
        else indexed
    )
    out: list[str] = []
    for term in distinctive_terms_of(question):
        occurrences = keyword.term_occurrences(term)
        # -1 is a term FTS cannot parse and tells us nothing either way; it is
        # not the same as 0, and neither is treated as distinguishing.
        if 0 < occurrences <= cutoff:
            out.append(term)
    return out


def distinctive_terms_of(question: str) -> list[str]:
    """Indirection with a purpose: no document_id is ever threaded through.

    `lexical.distinctive_terms` accepts one, and passing a per-document id here
    would make the term list itself depend on which document was being
    examined. The terms are a property of the question.
    """
    return lexical.distinctive_terms(question)


def _incidence(terms: list[str], document_ids: list[str]) -> dict[str, list[str]]:
    """Which of these terms appear in each document, memoised per call."""
    table: dict[str, list[str]] = {doc_id: [] for doc_id in document_ids}
    for term in terms:
        for doc_id in document_ids:
            if keyword.term_occurrences(term, doc_id) > 0:
                table[doc_id].append(term)
    return table


def _classify(
    doc_id: str,
    *,
    answered_ids: frozenset[str],
    supporting_ids: frozenset[str],
    census: dict,
    displaced: frozenset[str],
    min_rerank_score: float,
) -> str:
    if doc_id in answered_ids:
        return "answered"
    if doc_id in supporting_ids:
        return "supporting"

    row = census.get(doc_id) or {}
    best = row.get("best_rerank_score")
    if best is not None:
        return (
            "credible_not_cited" if best >= min_rerank_score
            else "retrieved_not_credible"
        )
    if doc_id in displaced or row.get("shortlisted"):
        return "expected_not_shortlisted"
    return "expected_not_retrieved"


def document_incidence(
    question: str,
    allowed_document_ids: frozenset[str],
    document_id: str | None = None,
    *,
    answered_ids: frozenset[str] = frozenset(),
    supporting_ids: frozenset[str] = frozenset(),
    census: dict | None = None,
    shortlist_excluded: list[dict] | None = None,
    min_rerank_score: float,
    reranked: bool = True,
    filenames: dict[str, str] | None = None,
) -> dict:
    """The coverage report for one answered question.

    Called after the answer is built, for `extract` and `generated` only. A
    refusal gets no coverage report at all: an incidence table under a refusal
    invites the reader to read it as evidence the corpus could have answered
    after all.

    Every row comes from `allowed_document_ids` and nothing else. There is no
    `out_of_scope` status, deliberately - a row saying "expected, out of scope"
    would leak the existence of a document the caller may not be allowed to
    know about, the precise failure `keyword.py:230-237` argues against.
    """
    if not reranked:
        # Every status below "supporting" turns on the credibility floor, and
        # without a rerank pass nothing was scored against it. Reporting
        # "not credible" - or "credible" - would be a verdict from a test that
        # did not run. The degraded mode is already visible to the reader as
        # `reranked: false` on the answer itself.
        return {
            "basis": "none",
            "expected_documents": None,
            "found_documents": None,
            "searched_documents": len(allowed_document_ids),
            "complete": None,
            "documents": [],
            "note": (
                "No coverage report: passages were ranked without the "
                "cross-encoder, so no document was scored for credibility."
            ),
        }

    census = census or {}
    # ANY eviction reason, not only the shortlist cut. A candidate lost to
    # near-duplicate merging also contributed and also never reached scoring;
    # reporting that as "expected, not retrieved" would be false, and it is
    # the same conflation that made recording only the cut insufficient.
    displaced = frozenset(
        e["document_id"] for e in (shortlist_excluded or [])
        if e.get("document_id")
    )
    filenames = filenames or {}
    ids = sorted(allowed_document_ids)

    if document_id is not None:
        # The reader's own filter is in force. There is no cross-document
        # expectation to form and reporting one would second-guess a choice
        # they made on screen.
        return {
            "basis": "single_document_scope",
            "expected_documents": 1,
            "found_documents": 1 if document_id in answered_ids else 0,
            "searched_documents": 1,
            "complete": None,
            "documents": [],
            "note": (
                "One document was searched because the question was asked "
                "against it."
            ),
        }

    # The incidence table is still reported per document: knowing that a
    # document carries "eradicate" is useful to a reader deciding what to open
    # next. It is the aggregate COUNT of "expected" documents that measurement
    # showed to be meaningless, so nothing is computed from it.
    terms = distinguishing_terms(question)
    table = _incidence(terms, ids) if terms else {doc_id: [] for doc_id in ids}

    rows: list[dict] = []
    for doc_id in ids:
        carries = table.get(doc_id) or []
        row_census = census.get(doc_id) or {}
        status = _classify(
            doc_id,
            answered_ids=answered_ids,
            supporting_ids=supporting_ids,
            census=census,
            displaced=displaced,
            min_rerank_score=min_rerank_score,
        )
        if status == "expected_not_retrieved" and not carries:
            status = "searched_no_match"
        rows.append({
            "document_id": doc_id,
            "filename": filenames.get(doc_id, doc_id),
            "status": status,
            "expected": bool(carries),
            "distinguishing_terms": carries,
            "candidates": int(row_census.get("candidates") or 0),
            "shortlisted": int(row_census.get("shortlisted") or 0),
            "best_rerank_score": row_census.get("best_rerank_score"),
            "reason": _REASONS.get(status),
        })

    rows.sort(key=lambda r: (_STATUS_ORDER.index(r["status"]), r["filename"]))

    # The documents this query actually produced credible evidence from, and
    # which of them the answer used. Both come from rerank scores against the
    # absolute floor - measured facts about this query, not inferences from
    # word counts.
    credible = [
        row for row in rows
        if row["status"] in CITED or row["status"] == "credible_not_cited"
    ]
    uncited = [row for row in credible if row["status"] == "credible_not_cited"]

    # `complete` is False only when a credible passage went unused, and null
    # in every other case. NEVER True - see the module docstring.
    #
    # The null case reports no counts at all. "2 of 2" would read as a
    # completeness guarantee by arithmetic, arriving at the claim the previous
    # paragraph refuses to make directly. A null must render as NOTHING: no
    # tick, no green. Rendering it as a checkmark converts "I did not check"
    # into "I checked and it is fine", which is where a coverage feature most
    # easily becomes a lie.
    if not uncited:
        return {
            "basis": "none",
            "expected_documents": None,
            "found_documents": None,
            "searched_documents": len(ids),
            "complete": None,
            "documents": rows,
            "note": (
                "No completeness claim: every document that produced a "
                "credible passage for this question was used in the answer. "
                "That is not a guarantee the answer is complete."
            ),
        }

    return {
        "basis": "credible_uncited",
        "expected_documents": len(credible),
        "found_documents": len(credible) - len(uncited),
        "searched_documents": len(ids),
        "complete": False,
        "documents": rows,
        "note": (
            "This answer did not use every credible passage available. The "
            "answer takes its highest-ranked passages only, so a passage that "
            "cleared the credibility floor in another document can be left "
            "out. Documents marked credible_not_cited are worth reading."
        ),
    }
