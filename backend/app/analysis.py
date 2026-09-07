"""The three engines joined to retrieval, the model and the access scope.

`synthesis.py` and `claims.py` are pure: they take evidence and a `generate`
callable and know nothing about SQLite, HTTP or Ollama. That is what let them
be developed and tested in isolation, and it is worth keeping - so everything
impure lives here, in one file, and the engines stay free of it.

WHAT AN EVIDENCE ITEM IS. `evidence_id` is
`sha256(document_id|page_start|page_end|section|exact_span)[:16]` and is
deliberately NOT a chunk id: chunk ids change when a document is re-chunked,
and a citation that moves when the chunker is retuned is not a citation. Two
identical spans on the same page of the same document are the same evidence,
which is the property a cross-document comparison needs.

WHY THE SPAN IS THE WHOLE PASSAGE. `exact_span` is what the reader is shown in
serif on a quote rule, and what every generated number is checked against. It
must be text that appears in the document verbatim, so it is the chunk's own
text and never a summary, a join or a reflow of it.

SCOPE. Every entry point takes an `AccessScope` and passes it to `search()`,
which filters before selection rather than after. Nothing here re-derives
authorisation, and nothing here accepts a document id from the caller that has
not been through `require_document`.
"""

from __future__ import annotations

import collections
import hashlib
import math
import re
import sqlite3

import httpx

from . import access, claims, market, search as search_mod, synthesis
from .config import settings
from .db import connect

#: What the plan asks for that this build does not produce. Named on the
#: result so a missing section is visible as missing rather than as an empty
#: one - the same rule the PDF follows on its first page.
NOT_IMPLEMENTED = [
    "conflict resolution across revisions (documents carry no revision or "
    "approval status)",
    "public market research (this machine is offline; the panel shows a "
    "labelled sample)",
    "analysis lifecycle and cancellation (there is no analyses table)",
]


def evidence_id(hit: dict) -> str:
    """Stable across re-chunking, because it is derived from what is quoted."""
    key = "|".join((
        str(hit.get("document_id") or ""),
        str(hit.get("page_start") or ""),
        str(hit.get("page_end") or ""),
        str(hit.get("section") or ""),
        str(hit.get("text") or ""),
    ))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def to_evidence(hit: dict) -> dict:
    """A retrieval hit as an evidence item.

    `exact_span` is the chunk's own text, unmodified.
    """
    return {
        "evidence_id": evidence_id(hit),
        "document_id": hit["document_id"],
        "filename": hit["filename"],
        "page_start": hit["page_start"],
        "page_end": hit["page_end"],
        "section": hit.get("section"),
        "exact_span": hit.get("text") or "",
        "text_source": hit.get("text_source") or "extracted",
        "ocr_min_conf": hit.get("ocr_min_conf"),
        "ocr_alphabet_violations": hit.get("ocr_alphabet_violations") or 0,
        "relevance_score": hit.get("rerank_score"),
        # WHICH SCALE, not just the number. A rerank score and an RRF score are
        # not comparable, and a bare figure would invite the comparison this
        # system forbids. None when nothing scored it - never 0.0, which sits
        # above the -3.0 floor and would read as credible.
        "relevance_score_type": "rerank" if hit.get("rerank_score") is not None else None,
    }


#: A filename or its stem, as a whole token. "doc17.pdf" and "doc17" both name
#: doc17.pdf; "17 mm" names nothing, because a bare number is a measurement and
#: the stem has to appear as written. Case-insensitive: nobody types NORSOK the
#: way the file is spelled.
def named_documents(question: str, filenames: list[str]) -> list[str]:
    """The corpus filenames the question mentions, in corpus order.

    Nothing in the system parsed document names out of a question before
    this (#82, R.2). Retrieval took a global top-k, so "compare doc17.pdf and
    doc20.pdf" could - and did - gather eight passages of which every doc20
    one ranked below the budget line.
    """
    q = question.lower()
    named: list[str] = []
    for filename in filenames:
        stem = filename.rsplit(".", 1)[0].lower()
        if len(stem) < 3:
            continue
        pattern = rf"(?<![\w.]){re.escape(stem)}(?:\.{re.escape(filename.rsplit('.', 1)[-1].lower())})?(?![\w.])"
        if re.search(pattern, q):
            named.append(filename)
    return named


def interleave_by_document(evidence: list[dict], names: list[str]) -> list[dict]:
    """Reorder so every NAMED document reaches the front before any repeats.

    The context budget keeps a PREFIX of this list and drops the rest, and the
    [S#] markers are positional - so the only safe place to fix "the second
    named document was cut entirely" is here, before the list is numbered.
    Round-robin across the named documents in the order the question named
    them, each document's passages in their original rank; then everything the
    question did not name, in rank order. Nothing is dropped and nothing is
    duplicated: an unnamed document may still be relevant, it just may not
    crowd out one the reader asked about.
    """
    if not names:
        return evidence
    buckets = {n: [e for e in evidence if e.get("filename") == n] for n in names}
    rest = [e for e in evidence if e.get("filename") not in buckets]
    out: list[dict] = []
    while any(buckets.values()):
        for n in names:
            if buckets[n]:
                out.append(buckets[n].pop(0))
    return out + rest


def _corpus_filenames(scope: access.AccessScope) -> list[str]:
    """Filenames the caller may read. A name the caller cannot see is not a
    name they can ask about, so the scope bounds the match as well."""
    ids = sorted(scope.allowed_document_ids)
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    return [r["filename"] for r in connect().execute(
        f"SELECT filename FROM documents WHERE id IN ({marks}) ORDER BY filename", ids)]


# ------------------------------------------------- named-document narrowing


def named_document_ids(
    scope: access.AccessScope, filenames: list[str]
) -> frozenset[str]:
    """The ids of these filenames, INTERSECTED with the caller's own scope.

    Naming a file in a question is a way of saying "look here", and it must
    never be a way of saying "look somewhere I am not allowed". So the scope
    bounds the lookup twice: `id IN (allowed)` inside the SQL, and an
    intersection with `allowed_document_ids` on the way out. Either alone
    would be correct; both are here because this is the one function in the
    analysis path that turns text the client wrote into a document id, and a
    single missed bound would make the question box an access-control
    surface. It is an intersection in both directions - there is no code path
    here that can produce an id the scope did not already contain.

    A filename that does not exist, or exists and is not granted, resolves to
    nothing and is simply not in the returned set. The caller then narrows to
    what survived, or - if nothing did - does not narrow at all.
    """
    ids = sorted(scope.allowed_document_ids)
    if not filenames or not ids:
        return frozenset()
    name_marks = ",".join("?" * len(filenames))
    id_marks = ",".join("?" * len(ids))
    try:
        rows = connect().execute(
            f"""SELECT id FROM documents
                WHERE filename IN ({name_marks}) AND id IN ({id_marks})""",
            [*filenames, *ids],
        ).fetchall()
    except sqlite3.Error:
        # A lookup that cannot run must not narrow anything: the fallback is
        # the caller's full authorised scope, which is what the question would
        # have been answered against had it named no documents at all. Failing
        # closed here would turn a database hiccup into an empty answer, and a
        # false refusal is the worse defect. It cannot fail OPEN, because the
        # only thing this function can do is shrink a set it never widens.
        return frozenset()
    return frozenset(r["id"] for r in rows) & scope.allowed_document_ids


def narrow_to_named(
    scope: access.AccessScope, filenames: list[str]
) -> tuple[frozenset[str], bool]:
    """`(ids to search, whether the narrowing applied)`.

    MEASURED (full corpus, keyword side): "compare design submittal
    percentages in doc13.pdf and doc16.pdf" at limit=24 was answered from a
    13-document candidate set, and a maths textbook won top-1 on the bare word
    "design". When the question names the documents, the other eleven are not
    competing evidence - they are noise the reader did not ask for.

    Three rules, in this order:
      * the question named nothing -> no narrowing;
      * some names resolved -> narrow to those, intersected with the scope;
      * nothing resolved (misspelt, absent, or not granted) -> no narrowing,
        because an empty answer is worse than a broad one.
    """
    if not filenames:
        return scope.allowed_document_ids, False
    named = named_document_ids(scope, filenames)
    if not named:
        return scope.allowed_document_ids, False
    return named, True


# ---------------------------------------------------------- per-document cap


#: How much deeper than the caller's limit the analysis path retrieves.
#:
#: The cap below can only redistribute slots among the passages retrieval
#: actually returned, so it needs a field wider than the number of slots or it
#: has nothing to promote INTO them. `search()` scores its whole pool and then
#: slices `pool[:limit]`, so asking for more of an already-scored pool costs no
#: extra keyword, dense or rerank work - it returns more of what it computed.
#: (On the reranked path the pool itself is bounded by
#: `settings.rerank_candidates`, so the effective depth is whichever is
#: smaller; this widens the field where there is a field to widen.)
ANALYSIS_OVERFETCH = 3

#: The screen sends `limit`: 8 for Quick, 24 for Comprehensive
#: (AnalysisModeScreen.tsx). Until now both ran the same single generation, and
#: the larger number bought the reader LESS.
#:
#: MEASURED, live: "do your deep analysis find all structural models from all
#: documents" in Comprehensive returned "the model reported the sources do not
#: support a summary", and the AI recommendation then correctly stayed silent
#: because it is gated on cited summary sentences. The SAME question had
#: answered minutes earlier on 9 passages. Qwen3.5:4b at num_ctx 4096 on a 15 W
#: CPU DECLINES rather than crashing when the prompt is too large, so the
#: failure arrives looking like a judgement about the evidence.
#:
#: `synthesis._fit` reserves prompt budget for the header of every source it is
#: handed - ~52 tokens each, because the tokenizer charges digits one at a time
#: - including the sources it is about to drop. Twenty-four headers reserve
#: ~1,250 tokens of a 3,846 token budget for passages the model never sees.
#:
#: So the modes are made to mean what they say. Quick is one pass over the top
#: QUICK_PASSAGES. Comprehensive is a map-reduce: every document that has a
#: passage gets its own summary, and the final call runs over those. No
#: frontend change - `limit` already carries the distinction.
QUICK_PASSAGES = 8

#: One document may supply at most a third of the candidate passages.
#:
#: MEASURED: "compare design submittal percentages in doc13.pdf and
#: doc16.pdf" at limit=24 gave doc16 EIGHTEEN of the 24 slots - pages 2, 19,
#: 21, 24, 29, 32, 35, 37 - and doc16 p.18, which carries the clause the
#: question was about ("a draft submission (usually at least a 50% design
#: submission)"), was not among them. One document ate the candidate set and
#: hid its own answer inside itself. Downstream, gap analysis saw doc13's
#: percentage clause and nothing from doc16, and truthfully reported that only
#: one document spoke to the facet - a compliance gap that does not exist.
#:
#: A third is chosen against that measurement: at limit=24 it is 8, less than
#: half of the 18 that caused the failure, and it leaves two thirds of the set
#: for everything else, so a two-document comparison cannot be reduced to a
#: monologue. It is deliberately not a half: a half would have permitted 12 of
#: 24, which is still one document holding the majority of the evidence a
#: cross-document comparison is built from.
#:
#: It is a SHARE, not a count, so it tracks whatever limit the route asks for.
PER_DOCUMENT_SHARE = 3

#: Below this, a share is not a useful quantity: at limit=8 a third is 2.67,
#: and a document that legitimately answers in three consecutive clauses would
#: lose one to arithmetic. Two is the floor only where the share is smaller.
MIN_PER_DOCUMENT = 2


def per_document_cap(limit: int) -> int:
    """The most passages any one document may supply at this limit."""
    return max(MIN_PER_DOCUMENT, math.ceil(max(limit, 1) / PER_DOCUMENT_SHARE))


def is_comprehensive(limit: int) -> bool:
    """Whether this request asked for more than one pass can honestly carry."""
    return limit > QUICK_PASSAGES


def contributing_documents(hits: list[dict]) -> int:
    """How many distinct documents put a passage in this field."""
    return len({str(h.get("document_id") or "") for h in hits})


def document_shares(hits: list[dict]) -> dict[str, int]:
    """How many passages each document supplied. Reported, so a share that
    exceeded the cap is visible rather than silent."""
    counts: collections.Counter[str] = collections.Counter(
        str(h.get("filename") or h.get("document_id") or "") for h in hits)
    return dict(counts)


def cap_per_document(hits: list[dict], limit: int) -> list[dict]:
    """At most `per_document_cap(limit)` passages per document.

    THE INVARIANT, precisely, because the first version of this got it wrong.

      (a) TOTAL. The result is never empty when `hits` is not, and never
          longer than `limit`. It is `min(limit, SUM over documents of
          min(cap, that document's passages))`.
      (b) SHARE. No document supplies more than `cap` - unless only ONE
          document contributed candidates at all, in which case the cap is
          LIFTED to `limit`, because a cap exists to stop one document
          crowding out another and there is no other.

      WHICH WINS. (b) wins. Where the cap and the requested total conflict,
      the result comes back SHORT rather than topped back up.

    WHY, MEASURED. The first version filled the leftover slots from the
    next-best passages of whatever remained, and since one document dominated
    the pool the fill handed the slots straight back to it: at limit=24 with
    cap=8, doc13 supplied 20 of 24 and doc16 supplied 4 - and on a question
    naming doc15 and doc16, doc16 supplied 15 of 16. The cap was reported in
    the metadata and enforced nowhere, which is the exact mechanism that hid
    doc16 p.18 in the first place. A cap that is topped back up is decoration.

    There is nothing to fill from. The first pass takes every document's best
    IN RANK ORDER, so a document under its cap has no passages left over: the
    only passages held back belong to documents already at the cap, and
    admitting those is precisely what (b) forbids. The one case where it is
    not forbidden - a single-document field - is handled by lifting the cap,
    which is honest about what it is doing and is recorded by the caller.
    """
    if not hits:
        return []
    cap = limit if contributing_documents(hits) < 2 else per_document_cap(limit)
    taken: collections.Counter[str] = collections.Counter()
    kept: list[dict] = []
    for hit in hits:
        document = str(hit.get("document_id") or "")
        if taken[document] < cap:
            taken[document] += 1
            kept.append(hit)
        if len(kept) == limit:
            break
    return kept


# ------------------------------------------------------- percentage intent


#: The question is about a proportion. "%" is included as a bare character
#: because that is how an engineer writes it in a question box.
_PERCENTAGE_QUESTION = re.compile(r"%|\bper\s?cent\b|\bpercent(?:s|age|ages)?\b", re.I)

#: A numeric percent AS IT APPEARS IN A DOCUMENT: "50%", "35 %", "50 per cent".
#: This is the marker the word "percentage" does not carry and the clause does.
_PERCENTAGE_IN_TEXT = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:%|per\s?cent\b|percent\b)", re.I)

#: Percent-bearing terms for the SUPPLEMENTARY retrieval call. Two-digit and
#: three-digit only: `keyword.build_match_query` keeps word tokens of two
#: characters or more, so "5%" would contribute nothing, and the FTS5
#: tokenizer does not index "%" itself - "50%" in a document is the token
#: "50". These are the round figures a design-submittal schedule is written
#: in; they are OR-ed into the query, never required.
_PERCENTAGE_TERMS = (
    "10", "15", "20", "25", "30", "35", "40", "45", "50",
    "60", "65", "70", "75", "80", "90", "95", "100", "percent",
)

#: Words that say nothing about what a question is ABOUT. Small and local on
#: purpose: `lexical.distinctive_terms` is the richer notion of this, and it
#: reads the acronym tables, which is a database dependency this filter does
#: not need and must not acquire.
_NOT_A_SUBJECT = frozenset("""
about across also and any are been between both but compare compared
comparison does each for from give have how into list many more most much
must only over said same shall should than that the their them then there
these this those used using what when where which while with your
""".split())


def percentage_intent(question: str) -> bool:
    """Is this question asking about a proportion?"""
    return bool(_PERCENTAGE_QUESTION.search(question))


def carries_percentage(text: str) -> bool:
    """Does this passage state a proportion AS A NUMBER?

    The predicate the word "percentage" does not satisfy and "a 50% design
    submission" does. Public because it is the claim both the widening below
    and its regression test are about.
    """
    return bool(_PERCENTAGE_IN_TEXT.search(text or ""))


def _subject_terms(text: str) -> frozenset[str]:
    """Lowercased content words of four letters or more.

    Digits are excluded from the token, which is why "doc13.pdf" yields
    nothing: a filename is a place to look, not a subject to match on.
    """
    return frozenset(
        w for w in re.findall(r"[a-z][a-z\-/]{3,}", text.lower())
        if w not in _NOT_A_SUBJECT
    )


#: How deep the recall pass reads. `settings.search_candidates` (30) is tuned
#: for a question whose words are in the passage; this pass is looking for a
#: NUMBER in a document of several hundred pages, and measured, the clause it
#: exists to find sits at bm25 rank 44 within its own document. Read past it.
PERCENTAGE_RECALL_CANDIDATES = 250


def percentage_recall(
    question: str,
    hits: list[dict],
    allowed_document_ids: frozenset[str],
    document_id: str | None,
    limit: int,
    *,
    targets: list[str | None] | None = None,
) -> list[dict]:
    """Extra percent-bearing candidates, appended behind everything retrieved.

    THE DEFECT. "compare design submittal percentages in doc13.pdf and
    doc16.pdf" has to be able to reach "a draft submission (usually at least a
    50% design submission)" - a clause that contains no form of the word
    "percentage" at all. The literal-word overlap that ranks it is absent, so
    on the measured run it never entered the kept set and gap analysis was told
    only one document spoke to the facet.

    WHY A SECOND CALL RATHER THAN A CHANGED QUERY. Rewriting the question -
    adding percent terms to the query the reranker and the primary ordering are
    built from - changes what the question MEANS: "submittal percentages"
    would start scoring against "50" and "100" as if the reader had asked
    about those numbers. The primary retrieval here is untouched, keeps its own
    ordering, and this is a strictly ADDITIVE second pass whose results arrive
    behind it. `keyword.py` is not modified: the widening is entirely in the
    argument this call passes.

    WHY IT CANNOT FLOOD THE SET. A supplementary hit is kept only if it
    satisfies all three of:
      * it is not already in the primary field;
      * its text carries a NUMERIC percent - which is the whole claim being
        made about it, so a passage without one has no business arriving on a
        query it was retrieved by number;
      * it shares a subject term with the question, the same standard the
        primary OR query applies. Without this, "35" would retrieve a chalking
        rating and a page number.
    """
    wanted = _subject_terms(question)
    seen = {evidence_id(h) for h in hits}
    per_document = per_document_cap(limit)
    widened = " ".join((question, *_PERCENTAGE_TERMS))
    added: list[dict] = []
    for target in (targets if targets is not None else [document_id]):
        # DEEP, LEXICAL, AND PER DOCUMENT. Every argument here was chosen
        # against a measurement on the real 13-document corpus, for the
        # clause "a draft submission (usually at least a 50% design
        # submission)" on doc16 p.18:
        #
        #   * WITHIN DOC16 ALONE it is bm25 rank 75 of 94 matches on the
        #     question, and rank 44 of 94 with the percent terms appended. The
        #     default candidate pool is `settings.search_candidates` = 30, so
        #     the clause was never RETRIEVED at all - it does not even appear
        #     in `shortlist_excluded`, because nothing ever shortlisted it.
        #     Hence `candidates`, deep.
        #   * rerank=False. Reranking re-imposes the `rerank_candidates` (16)
        #     shortlist cut by RRF order, which is the cut that hides the
        #     clause; and measured, the cross-encoder given a question with
        #     eighteen bare numbers appended ranked the clause out of the top
        #     six even when it was in the pool. This pass is asked for RECALL,
        #     and what decides admission is the filter below, not an ordering.
        #   * dense=False. It exists to find a NUMBER in the text; that is
        #     lexical work, and the embedder is the slow part of a search.
        #   * one call PER NAMED DOCUMENT. Measured on the same question, a
        #     single call over both documents returned 15 doc13 passages and
        #     1 doc16 passage: a 300-page document consumes the recall pass
        #     exactly as it consumes the primary one. Per document, doc16
        #     competes only with itself.
        supplementary = search_mod.search(
            widened,
            limit=PERCENTAGE_RECALL_CANDIDATES,
            candidates=PERCENTAGE_RECALL_CANDIDATES,
            document_id=target, rerank=False, dense=False,
            allowed_document_ids=allowed_document_ids,
        )
        admitted = 0
        for hit in supplementary.get("hits") or []:
            if admitted >= per_document:
                # No document may be admitted more than its own cap would
                # keep. Without this the front of the field would be a
                # hundred percent-bearing passages from one document, which is
                # the defect this whole file is about, arriving by a new road.
                break
            key = evidence_id(hit)
            if key in seen:
                continue
            text = str(hit.get("text") or "")
            if not carries_percentage(text):
                continue
            if wanted and not (wanted & _subject_terms(text)):
                continue
            seen.add(key)
            added.append(hit)
            admitted += 1
    return hits + added


def percentage_first(hits: list[dict]) -> list[dict]:
    """Passages carrying a numeric percent, before ones that do not.

    ORDERING, not a score - the same mechanism `search.promote_definitions`
    uses, and for the same reason: the claim is categorical (this passage
    states a proportion, that one does not) and expressing a categorical claim
    as a number tuned against one scale is how a rule comes to fire on every
    query and change no outcome.

    `sorted` is stable, so rank order survives inside both groups: a
    percent-bearing passage does not overtake a better percent-bearing one,
    and nothing is dropped. Applied only when the question asks about a
    proportion.
    """
    return sorted(
        hits,
        key=lambda h: not carries_percentage(str(h.get("text") or "")),
    )


#: More named documents than this and the recall pass stops issuing one call
#: per document. It falls back to a SINGLE unpinned call rather than reading
#: the first few: truncating the list would silently skip a document the
#: reader named, which is the defect this file exists to remove.
_MAX_RECALL_CALLS = 6


def _recall_targets(allowed: frozenset[str], narrowed: bool,
                    document_id: str | None) -> list[str | None]:
    """Which documents the recall pass reads, one call each.

    A caller-pinned document wins outright. Otherwise the named documents get
    a call each, so a 300-page document cannot consume the recall pass; and
    with nothing named there is one unpinned call, as before.
    """
    if document_id:
        return [document_id]
    if narrowed and 0 < len(allowed) <= _MAX_RECALL_CALLS:
        return sorted(allowed)
    return [None]


def gather(question: str, scope: access.AccessScope, *, limit: int = 8,
           document_id: str | None = None) -> tuple[list[dict], dict]:
    """Retrieve, and return evidence plus the raw search result.

    The raw result is kept because the coverage report and the per-document
    rows are built from the census and the eviction record, not from the hits -
    a document that contributed candidates and lost them all is invisible in
    the hits and visible in the census.

    FOUR THINGS HAPPEN HERE, in this order, and none of them changes shared
    retrieval: every one is either an argument passed to `search()` or a
    post-filter over what it returned. `search.py`, `keyword.py` and
    `passages.py` are shared with Chat and are untouched.

    1. NARROWING. If the question names documents the caller may read, only
       those are searched - the intersection of "named" and "authorised",
       never a union (see `narrow_to_named`). Measured: a maths textbook took
       top-1 on the bare word "design" for a question that named doc13.pdf and
       doc16.pdf.
    2. DEPTH. `limit * ANALYSIS_OVERFETCH` passages are requested, because the
       cap in (4) can only promote passages retrieval actually returned.
    3. PERCENTAGE INTENT. A question about percentages gets a second,
       additive retrieval pass for clauses whose percent is a NUMBER rather
       than the word, and percent-bearing passages are ordered first.
    4. THE PER-DOCUMENT CAP, applied after scoring and before the passage set
       is handed on, then trimmed to `limit`. Measured: doc16 supplied 18 of
       24 slots and hid its own answer, and the honest gap analysis downstream
       reported a compliance gap that does not exist.

    Then, as before, the evidence is interleaved so each named document is
    represented before the context budget cuts the tail. Measured before that
    (#82): 8 passages gathered for a doc17-vs-doc20 comparison, 2 kept by the
    budget, both from other documents; the model, shown no doc20 text,
    correctly refused.

    NOTHING HERE CAN EMPTY A NON-EMPTY RESULT. Narrowing stands down when no
    name resolves, the percentage pass only ever appends, and the cap returns
    exactly `min(limit, len(hits))` passages. The census in `result` is
    untouched - it reports what retrieval found; this decides what the model
    is shown, and records its own decisions alongside it.
    """
    names = named_documents(question, _corpus_filenames(scope))
    allowed, narrowed = narrow_to_named(scope, names)
    depth = max(limit, limit * ANALYSIS_OVERFETCH)

    result = search_mod.search(
        question, limit=depth, document_id=document_id,
        allowed_document_ids=allowed,
    )
    hits = list(result.get("hits") or [])

    wants_percentages = percentage_intent(question)
    added = 0
    if wants_percentages and hits:
        # Only when something was already found. On a question that retrieved
        # nothing, a percent-only second pass would be answering a question
        # nobody asked.
        widened = percentage_recall(
            question, hits, allowed, document_id, limit,
            targets=_recall_targets(allowed, narrowed, document_id))
        added = len(widened) - len(hits)
        hits = percentage_first(widened)

    hits = cap_per_document(hits, limit)

    # What was decided, next to what was found. A narrowing that did not apply
    # is recorded as not having applied rather than being indistinguishable
    # from one that did, and a cap that was LIFTED (a single-document field)
    # is recorded as lifted rather than looking like a cap that failed.
    cap = per_document_cap(limit)
    shares = document_shares(hits)
    result["analysis_named_documents"] = names
    result["analysis_named_scope_applied"] = narrowed
    result["analysis_per_document_cap"] = cap
    result["analysis_per_document_cap_lifted"] = bool(
        hits and max(shares.values()) > cap)
    result["analysis_document_shares"] = shares
    result["analysis_percentage_intent"] = wants_percentages
    result["analysis_percentage_candidates_added"] = added

    evidence = [to_evidence(h) for h in hits]
    return interleave_by_document(evidence, names), result


# ------------------------------------------------------------------- the model


def ollama_generate(system: str, prompt: str) -> synthesis.Generation:
    """The `Generate` protocol, backed by the local model.

    Injected rather than imported by the engines, which is what let them be
    tested without a model and what lets a caller here swap in a stub.
    """
    body = {
        "model": settings.answer_model,
        "system": system,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {
            "temperature": settings.temperature,
            "num_predict": settings.max_output_tokens,
            "num_ctx": settings.num_ctx,
            "num_thread": settings.num_thread,
            "num_batch": settings.num_batch,
        },
        "keep_alive": "30m",
    }
    with httpx.Client(timeout=180.0) as client:
        response = client.post(f"{settings.ollama_url}/api/generate", json=body)
        response.raise_for_status()
        return synthesis.Generation.from_ollama(response.json())


class ModelUnavailable(Exception):
    """The local model could not be reached. Not a crash, and not an answer."""


def _generate_or_refuse(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except httpx.HTTPError as exc:
        raise ModelUnavailable(type(exc).__name__) from exc


def _synthesise(question: str, evidence: list[dict], limit: int,
                generate) -> synthesis.Summary:
    """The one place the mode is decided, so the summary route and the
    recommendation route cannot drift into running different engines over the
    same question."""
    model = generate or ollama_generate
    if is_comprehensive(limit):
        return _generate_or_refuse(synthesis.map_reduce, question, evidence, model)
    # Quick is a PREFIX of the same ranked list, cut here rather than at
    # retrieval, so the evidence ledger the reader is shown and the passages
    # the model saw come from one gather.
    return _generate_or_refuse(
        synthesis.summarise, question, evidence[:QUICK_PASSAGES], model)


# ------------------------------------------------------------------ stage 3


def summary(question: str, scope: access.AccessScope, *, limit: int = 8,
            generate=None) -> dict:
    """Generated prose over the retrieved evidence, every sentence cited.

    Quick is ONE pass over the top `QUICK_PASSAGES`. Comprehensive is a
    map-reduce over every document that has a passage. See QUICK_PASSAGES for
    why the single pass could not be made to mean "more documents" simply by
    handing it more passages.
    """
    evidence, _ = gather(question, scope, limit=limit)
    result = _synthesise(question, evidence, limit, generate)
    return {
        "question": question,
        "evidence_ledger": evidence,
        **synthesis.summary_to_api(result),
        "not_implemented_sections": list(NOT_IMPLEMENTED),
    }


# ------------------------------------------------------------------ stage 6


def gaps(question: str, scope: access.AccessScope, *, limit: int = 8,
         baseline_document_id: str | None = None) -> dict:
    """Mechanical claim comparison. No model call, and no baseline invented.

    THE BASELINE MUST COME FROM THE USER. Choosing one here - the oldest
    document, the one with "standard" in its name - would be the system
    deciding which document is authoritative, which is an engineering
    judgement it has no basis for. With no baseline the applicability is
    `not_applicable` and the items are still returned, so the reader sees the
    comparison without being told which side is right.
    """
    evidence, _ = gather(question, scope, limit=limit)
    rows = claims.extract_claims(evidence)
    clusters = claims.cluster(rows, claims.question_terms(question))
    applicability = "applicable" if baseline_document_id else "not_applicable"
    baseline = None
    if baseline_document_id:
        baseline = {
            "kind": "document",
            "document_id": baseline_document_id,
            "section": None,
            "text": None,
        }
    return {
        "question": question,
        "evidence_ledger": evidence,
        "claim_clusters": claims.to_api(clusters),
        "gaps": {
            "applicability": applicability,
            "baseline": baseline,
            # Items are produced from the clusters, not invented: a facet with
            # no baseline to compare against is `insufficient_evidence`, never
            # `met`.
            "items": _gap_items(
                clusters,
                baseline_document_id,
                # Claim carries filename and exact_span, not document_id - it
                # is a claim about a sentence, not about a row in a table. The
                # mapping back to a document lives here, where the evidence is.
                {e["evidence_id"]: e["document_id"] for e in evidence},
            ),
        },
        "not_implemented_sections": list(NOT_IMPLEMENTED),
    }


#: Where each status sits when the list is ordered. A conflict is the thing a
#: reader most needs to see; "nothing to compare" is the thing they least need
#: and it was arriving first.
_STATUS_RANK = {
    "conflict": 0,
    "possible_gap": 1,
    "met": 2,
    "insufficient_evidence": 3,
    "not_applicable": 4,
}


#: Every label `claims.label_cluster` can return, and the gap status it earns
#: WHEN THE PROJECT DOCUMENTS SPOKE. Written as a table rather than an if/else
#: chain because the chain ended in `else: status = "possible_gap"`, and two
#: labels fell through it into a status that means the opposite of what they
#: say:
#:
#:   "addition"   one row carries a measurement or identifier the others lack;
#:                NOTHING IS CONTRADICTED. Measured live, that arrived on screen
#:                as "Possible gap - Retrieval found nothing addressing this"
#:                directly above its own note saying nothing is contradicted.
#:   "unresolved" the unit could not be normalised, so the values could not be
#:                COMPARED. Retrieval found plenty; it is the comparison that
#:                failed, which is what `insufficient_evidence` means.
#:
#: `addition` maps to `met` rather than to a sixth status, and that is a
#: deliberate reuse rather than a shortcut. `met` here already means "the
#: documents address this and nothing contradicts the baseline" - `agreement`
#: has always mapped to it on exactly that basis, and neither ever claimed a
#: requirement was formally satisfied. The card's caption for `met`, "Positive
#: matching evidence was found", is literally true of an addition row: there
#: are project evidence chips on it. A new status would be more precise by a
#: hair and would cost a contract change, a sixth concept in a five-concept
#: UI, and a broken `Record<GapItemStatus, ...>` in a file another agent is
#: editing right now.
#:
#: A label added to claims.py and not added here becomes
#: `insufficient_evidence` - which overstates nothing - and
#: test_the_label_to_status_mapping_is_exhaustive_and_honest fails, so the
#: omission is loud rather than silent.
STATUS_FOR_LABEL: dict[str, str] = {
    "possible_conflict": "conflict",
    "agreement": "met",
    "addition": "met",
    "unresolved": "insufficient_evidence",
}


def _gap_items(clusters, baseline_document_id: str | None,
               document_of: dict[str, str]) -> list[dict]:
    """Gap items, with the measured facets first and the singletons collapsed.

    THE FINDING WAS BURIED. "Minimum coating thickness shall be 125 µm" - the
    answer - arrived below nine items reading `insufficient_evidence`, each of
    them a facet only one document mentions and therefore nothing to compare.
    Nine rows of "nothing to compare" ahead of the answer is a list that
    hides its own conclusion.

    So: single-row clusters collapse into ONE entry, facets that carry a
    measurement sort above ones that do not, and citation ids are deduplicated
    (7a86abdc251ea774 appeared five times in a single item, which reads as
    five sources and is one).
    """
    items: list[dict] = []
    singletons: list = []
    for c in clusters:
        # A facet only one row speaks to cannot be COMPARED with anything -
        # but if that row carries a measurement it is still a FINDING, and
        # "Minimum coating thickness shall be 125 um" is the answer to the
        # question whether or not a second document repeats it. So only
        # unmeasured singletons collapse; measured ones sort to the top with
        # everything else.
        if (len(c.rows) == 1 and not baseline_document_id
                and not any(r.measurements for r in c.rows)):
            singletons.append(c)
            continue
        rows = list(c.rows)
        baseline_row = next(
            (r for r in rows
             if document_of.get(r.evidence_id) == baseline_document_id), None
        ) if baseline_document_id else None
        others = [r for r in rows if r is not baseline_row]
        if baseline_row is None:
            # NO BASELINE. "met" and "possible_gap" both mean "measured
            # against the authority", and there is no authority, so neither
            # can be assessed - `not_applicable` says that, and the flat
            # `insufficient_evidence` this used to emit said something else
            # and said it about every single row.
            #
            # A DISAGREEMENT is knowable without a baseline: two documents
            # stating different values contradict each other whoever is
            # right. That one keeps its status so it can lead the list.
            status = ("conflict" if c.label == "possible_conflict"
                      else "not_applicable")
        elif others:
            # THE PROJECT DOCUMENTS SPOKE. Whatever the label says about HOW
            # they agree, retrieval did not come back empty - so nothing here
            # may claim it did.
            status = STATUS_FOR_LABEL.get(c.label, "insufficient_evidence")
        else:
            # Only the baseline is in this cluster: no project document
            # addressed the facet at all. That is what `possible_gap` is for,
            # and it is the finding this panel exists to make - so a conflict
            # aside, it stands regardless of the label.
            status = "conflict" if c.label == "possible_conflict" else "possible_gap"
        items.append({
            "facet": c.facet or "(unnamed)",
            "status": status,
            "baseline_citation_id": baseline_row.evidence_id if baseline_row else None,
            "baseline_span": baseline_row.exact_span if baseline_row else "",
            # dict.fromkeys, not set: the same evidence id appeared five times
            # in one item, which reads as five sources and is one - and the
            # ORDER is the rank order retrieval produced, so it is kept.
            "project_citation_ids": list(dict.fromkeys(r.evidence_id for r in others)),
            "note": c.note,
            "_measured": any(r.measurements for r in c.rows),
            # How much of the QUESTION this facet is about. facet_key is
            # already (question terms ∩ claim terms), so this is the question's
            # own words rather than a similarity score invented here.
            "_shared": len([k for k in c.key
                            if not k.startswith(("dim:", "designator:"))]),
        })

    # Measured facets first; then the ones the question actually asked about;
    # then by how much the reader needs to see them.
    #
    # Alphabetical order put "coating (%)" above "coating thickness (µm)" on a
    # question about coating thickness - the answer arriving sixth in a list
    # of fourteen, which is the burial this ordering exists to prevent.
    items.sort(key=lambda i: (not i.pop("_measured"),
                              -i.pop("_shared"),
                              _STATUS_RANK.get(i["status"], 9),
                              i["facet"]))

    if singletons:
        # ONE entry for all of them, naming what they are rather than
        # repeating "insufficient_evidence" once per facet.
        facets = sorted({c.facet for c in singletons if c.facet})
        cited = list(dict.fromkeys(
            r.evidence_id for c in singletons for r in c.rows))
        items.append({
            "facet": f"stated once, nothing to compare ({len(singletons)})",
            "status": "insufficient_evidence",
            "baseline_citation_id": None,
            "baseline_span": "",
            "project_citation_ids": cited,
            "note": (
                "Only one document speaks to each of these, so there is "
                "nothing to compare them against: "
                + "; ".join(facets[:8])
                + ("; and others" if len(facets) > 8 else "")
            ),
        })
    return items


# ------------------------------------------------------- the advisory gate

#: The document layer produced nothing to advise on. Prefixed to the summary's
#: OWN refusal so the reader is told which of them happened - the model
#: declined, the model returned nothing, the evidence did not fit - rather than
#: being handed a second sentence that means "something went wrong".
REFUSAL_NO_DOCUMENT_LAYER = (
    "no recommendation: the document layer produced no cited sentence"
)

#: What the advice rests on when the summary produced nothing but the gap
#: analysis did. Rendered as the FIRST sentence of the recommendation and
#: carrying its citations, because advice built on a different footing than
#: last time, presented identically, is the reader being misled by omission.
#:
#: No digits in it, deliberately: a numeral here would be measured against the
#: cited spans by the same gate that measures the model's.
GAP_EVIDENCE_PREFACE = (
    "This advice rests on the gap analysis evidence cited here rather than on a "
    "documented summary, because no summary sentence survived the citation check."
)

#: A facet nothing could be compared against is not evidence that something is
#: there. Every other status - conflict, possible gap, met, insufficient
#: evidence - was reached because a document SPOKE, and the passage it spoke in
#: is cited on the item.
NOT_APPLICABLE = "not_applicable"

#: The generation ran and produced nothing that could be cited. Not the same
#: fact as "the document layer was silent", so not the same sentence.
REFUSAL_NO_ADVICE = (
    "no recommendation: the advisory generation produced no sentence a "
    "supplied source supported"
)


def advisory_refusal(summarised: synthesis.Summary) -> str | None:
    """Why the advisory layer has nothing to stand on, or None.

    The gate is on the SENTENCES, not on the refusal string: a summary with no
    finding has nothing cited in it whatever it says about itself, and a new
    refusal reason added to synthesis.py is gated on the day it is written
    rather than on the day someone remembers to add it to a list here.
    """
    if summarised.findings:
        return None
    why = summarised.refusal or "the summary produced no cited sentence"
    return f"{REFUSAL_NO_DOCUMENT_LAYER} ({why})"


def gap_evidence_ids(gap: dict) -> list[str]:
    """Evidence ids cited by gap items that found something, in item order.

    `not_applicable` means "there is no baseline to measure this against", so
    the facet is not a finding and its citations are not a footing for advice.
    Everything else on the list was reached because a document said something,
    and what it said is cited - so it is evidence a recommendation may rest on
    even when the summary generation produced nothing.
    """
    ids: list[str] = []
    for item in gap.get("gaps", {}).get("items", []):
        if item.get("status") == NOT_APPLICABLE:
            continue
        for eid in (item.get("baseline_citation_id"),
                    *item.get("project_citation_ids", [])):
            if eid and eid not in ids:
                ids.append(eid)
    return ids


# ------------------------------------------------------------------ stage 4


def recommendation(question: str, scope: access.AccessScope, *, limit: int = 8,
                   baseline_document_id: str | None = None,
                   generate=None) -> dict:
    """One advisory recommendation, with its confidence derived from checks.

    `high` is structurally unreachable - the same rule that forbids
    `coverage.complete === true`. Confidence comes from checks that FIRED,
    each named, so a reader can see why it is what it is rather than being
    handed a number.
    """
    evidence, raw = gather(question, scope, limit=limit)
    gap = gaps(question, scope, limit=limit,
               baseline_document_id=baseline_document_id)
    summarised = _synthesise(question, evidence, limit, generate)

    checks = synthesis.confidence_checks(
        gaps_applicability=gap["gaps"]["applicability"],
        document_statuses=[],
        cluster_labels=[c["label"] for c in gap["claim_clusters"]],
        evidence_text_sources=[e["text_source"] for e in evidence],
        # This build computes no coverage object for an analysis, and a
        # missing check must not read as a passing one.
        coverage_complete=None,
        summary_truncated=summarised.truncated,
        evidence_was_removed=bool(summarised.evidence_removed),
    )
    # THE GATE (#90), partially opened. Advice used to require cited summary
    # sentences and nothing else, so a summary the model declined took the
    # recommendation down with it even when the mechanical comparison - which
    # needs no model at all - had found conflicts and cited them. Two footings
    # are now allowed and they are not interchangeable:
    #
    #   * the summary stood: advise over the whole evidence ledger, as before;
    #   * the summary produced nothing but gap facets did: advise over THOSE
    #     facets' evidence only, and say so in the first sentence.
    #
    # What has NOT been weakened: with no cited summary sentence AND no gap
    # facet, nothing cited exists, the model is not called, and the reader is
    # told the document layer was silent and why.
    why = advisory_refusal(summarised)
    preface = None
    if why is None:
        rec_evidence = evidence
    else:
        cited = set(gap_evidence_ids(gap))
        rec_evidence = [e for e in evidence if e["evidence_id"] in cited]
        preface = GAP_EVIDENCE_PREFACE
    if not rec_evidence:
        return {
            "question": question,
            "evidence_ledger": evidence,
            "recommendation": None,
            "recommendation_refusal": why or REFUSAL_NO_DOCUMENT_LAYER,
            "public_market_findings": market.findings()["findings"],
            "not_implemented_sections": list(NOT_IMPLEMENTED),
        }

    rec = _generate_or_refuse(
        synthesis.recommend, question, rec_evidence, generate or ollama_generate,
        checks=checks, basis="documents_only", preface=preface)
    return {
        "question": question,
        "evidence_ledger": evidence,
        "recommendation": synthesis.recommendation_to_api(rec),
        # Null recommendation, named reason. A card that renders nothing and a
        # card that was refused look identical, and mean opposite things.
        "recommendation_refusal": (
            None if rec is not None
            else why or REFUSAL_NO_ADVICE
        ),
        "public_market_findings": market.findings()["findings"],
        "not_implemented_sections": list(NOT_IMPLEMENTED),
    }
