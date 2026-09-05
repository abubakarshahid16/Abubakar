# Design — multi-document coverage reporting

Written against the real code, not from general RAG practice. Every claim below
carries a file:line, and where the design is uncertain it says so rather than
sounding confident.

## What happens today, in code

`answer.answer()` calls `search_mod.search()` once (`answer.py:374`). `search()`
builds one global candidate pool from `keyword.search` + `dense_search`
(`search.py:598-611`), fuses ranks (`search.py:613`), reranks a single shortlist
of `settings.rerank_candidates = 16` (`search.py:661-666`), and then **discards
everything outside it**: `pool = shortlist` (`search.py:684`). Tier 1 takes
`hits[0]` and at most one `_second_passage` (`answer.py:423-427`).

Nothing in that path is document-aware except the access mask.

On the measured Q4 case — evidence in doc17 and doc19, only doc19 returned —
doc17 was never excluded. It either lost the global RRF race or made the pool
and fell outside the 16 slots. **Either way it left no record.**

That shortlist truncation at `search.py:661` is the one place in this system
where candidates are dropped with no recorded reason. It is an invariant-5 gap
and it is cheaper to close than any retrieval work.

## The decision signal, and why the existing machinery does not generalise

`lexical.is_compound_question` (`lexical.py:111-113`) is a regex for
`and|as well as|along with|plus`. It answers "does this question ask for two
things", which is syntactic and says nothing about *where* the things live.
Q4 fires — but so does "what is the check frequency and the relative humidity
limit", which `lexical.py:96-99` correctly identifies as a **single-document**
two-clause question. A signal that cannot separate two clauses in one document
from two documents is not a multi-document signal.

`lexical.distinguishing_uncovered_terms` (`lexical.py:297-327`) is the right
primitive at the wrong scope. It already computes distinctive terms minus those
in the passage, filtered by corpus frequency. Two things stop it generalising:
it returns `[]` for non-compound questions (line 308), and its `document_id`
feeds a corpus-wide or single-document count, never a per-document
*distribution*.

`answer._second_passage` (`answer.py:188-268`) must **not** be generalised to
documents. It filters already-retrieved hits rather than retrieving, its
diversity axis is the section string (`answer.py:216-217`), and its
`separation` comparison (`answer.py:226-228`) is computed against one rerank
field — which makes it correct today and an invariant-3 violation the moment a
candidate arrives from a different batch.

**The signal to use: per-document term incidence.**
`keyword.term_occurrences(term, document_id)` (`keyword.py:289-311`) already
takes a document and already returns `-1` for unparseable, distinct from `0`
for absent — the three-way distinction invariant 6 needs.

Cost is `terms x documents` FTS `COUNT(*)` queries: tens of milliseconds at 8
documents, memoised per request, off the rerank path. **It does not scale** —
at 1,200 documents it is the whole latency budget and needs a term-to-document
posting aggregate instead. Noted, not built.

## The score-scale constraint, stated precisely

The constraint is sharper than "RrfScore is not RerankScore". The cross-encoder's
int8 activation scales are computed per tensor over the whole batch, so **two
scores are comparable only if they came from the same forward pass** — measured
at up to 0.494 of drift from padding width alone, against a
`MIN_RERANK_SCORE = -3.0` floor whose calibration gap is 3.5 points.

`reranker.rerank` (`reranker.py:112-142`) chunks at `settings.rerank_batch = 32`;
with 16 candidates every current call is a single pass. **That property is
load-bearing and currently accidental. Make it explicit.**

Rule: one rerank batch per query, always. Ranking across documents is decided
inside that one batch or it is not decided at all.

### Not to be done

- Rerank per document and compare the winners. Two quantisation regimes.
- Normalise or z-score per document. That does not make batches comparable; it
  makes the incomparability invisible.
- Carry a rerank score across passes. A passage not in the final batch has
  `rerank_score = None`, never 0.0 — 0.0 sits above the -3.0 floor and reads as
  credible.
- Apply `MIN_RERANK_SCORE` per document. The floor is absolute, calibrated on
  one population.
- Widen `answer(limit=3)` for Tier 2. Three expanded sources at
  `generated_context_chars = 1200` already have to fit `num_ctx`, and
  `answer.py:448-450` says overflow silently truncates the evidence.

## Response shape — additive, defaulted, three-state

```python
DocumentCoverageStatus = Literal[
    "answered",                  # a passage from this doc is in answer_passages
    "supporting",                # in `supporting`, not in the answer
    "retrieved_not_credible",    # reached the rerank batch, below MIN_RERANK_SCORE
    "expected_not_retrieved",    # carries a distinguishing term, contributed nothing
    "expected_not_shortlisted",  # contributed candidates, displaced before rerank
    "searched_no_match",         # in scope, keyword+dense returned nothing
]

class DocumentCoverage(BaseModel):
    document_id: str
    filename: str
    status: DocumentCoverageStatus
    expected: bool
    distinguishing_terms: list[str] = []
    candidates: int                     # reached the RRF pool. 0 is a real 0.
    shortlisted: int
    best_rerank_score: float | None = None   # null unless scored IN the final batch
    reason: str | None = None

class Coverage(BaseModel):
    basis: Literal["term_incidence", "single_document_scope", "none"]
    expected_documents: int | None      # null when basis == "none" - never 0
    found_documents: int | None
    searched_documents: int
    complete: bool | None = None
    documents: list[DocumentCoverage] = []
    note: str | None = None
```

On `AnswerResult`: `coverage: Coverage | None = None`.

**`out_of_scope` is deliberately absent from the enum.** Every coverage row must
come from `allowed_document_ids` and nothing else. A row saying "expected, out of
scope" leaks the existence of a document the caller may not know exists — the
precise failure `keyword.py:230-237` argues against.

### The two gotchas that will silently swallow this field

1. **`contracts/types.ts` is hand-written** — "source of truth for the UI", no
   codegen, no test catching drift. The TypeScript goes in the same commit.
2. **`chat._PAYLOAD_KEYS` (`chat.py:412-417`) is an explicit allow-list.** Its
   own comment says it is explicit so a future field cannot silently start being
   persisted — which means a new field is silently *not* persisted. Without
   `"coverage"` added there, reopening a conversation shows a complete-looking
   answer with the partial-coverage warning gone. That is worse than not
   shipping the field.

### Consumers checked

| Consumer | Safe? |
|---|---|
| `AnswerCard.tsx:41,57` | Never enumerates keys. Safe |
| `eval/run_eval.py:232,296,346` | Uses `.get`. Safe |
| `eval/reachability.py` | Runs with `rerank=False` — any shortlist change **must** be a no-op on that path, or the sweep's meaning changes |
| `eval/coverage.py` | A different, older meaning of "coverage" — pages reachable through a retrievable chunk. Do not conflate |

## Reporting — the distinction that matters

| Claim | `basis` | `expected_documents` | `complete` |
|---|---|---|---|
| "1 of the 2 that matter" | `term_incidence` | 2 | `false` |
| "searched 8, 1 was relevant" | `none` | `null` | `null` |
| reader's own filter in effect | `single_document_scope` | 1 | — |

`basis: "none"` whenever no expectation could be formed — no distinguishing term
with a usable distribution, or `keyword.indexed_count()` below
`MIN_CORPUS_FOR_COMMONNESS = 20` (`lexical.py:86`), where "common in the corpus"
is not a meaningful idea. Then `expected_documents` and `complete` are **null,
not 0 and not true**.

In the UI:
- `complete === false` names the gap and the document.
- `complete === null` **says nothing about completeness.** No tick, no green.
  A null rendered as a checkmark converts "I did not check" into "I checked and
  it is fine". That is where a coverage feature most easily becomes a lie.

## Never emit `complete: true`

Term incidence is a presence test. `docs/gold-questions.md` says in its own
preamble that presence is not relevance. If both expected documents are cited,
emitting `complete: true` would be a coverage guarantee derived from word
counts — a stronger claim than the evidence supports, and an invariant-7 break
by construction.

The field is `false` or `null`. If the eval harness needs a positive, name it
`no_uncited_expected_documents` and let it mean exactly that.

## Known false positives, unresolved

**Q1.** `zero trust` appears once in doc19 and that chunk is explicitly labelled
NOT relevant in the gold set. If it clears the frequency cutoff, Q1 — a clean
pass today — starts reporting `complete: false`. Not dangerous, but it trains
the reader to ignore the warning, which makes the Q4 warning worthless too.

**Q4.** `containment` also appears in book4 and doc02 in a physical-process
sense. Term incidence cannot see word sense, so Q4 may name four expected
documents where two matter. This alone may make the raw signal unusable and
push toward "report the incidence table, do not compute an expectation".

Mitigations exist — require two distinguishing terms, or a chunk-count floor —
but both are new constants on a new scale with n=1 of evidence, which is the
practice `scores.py` exists to stop. **Set the constant from the five gold
questions or ship with no constant and a `note` saying the expectation is
presence-based.** Do not guess it.

## The invariant most likely to break, and the test that prevents it

`lexical.assess` (`lexical.py:173`) threads `document_id` into
`keyword.indexed_count` (line 192) and `keyword.term_occurrences` (line 217).
The `named_absent` rule at `lexical.py:233-251` — the absolute presence gate —
is therefore **already parameterised by document**, and today is only ever called
with the caller's own `document_id` (`answer.py:396`).

The moment coverage code iterates documents and calls `lexical.assess` inside
that loop, "does not appear anywhere in the indexed documents" (line 237)
silently becomes "does not appear in this document", and the user-visible
refusal message, which says *anywhere*, becomes false.

**Rule, enforced by a test rather than a comment:** the coverage layer may call
`keyword.term_occurrences(term, doc_id)` for incidence, and may **never** call
`lexical.assess` with a document_id it derived itself. The gate runs exactly
once, before any per-document reasoning, on the scope the request already had
(`answer.py:395-406`), and its verdict is final. A refused question has
`coverage: null` — computing an incidence table for it would invite the reader
to read it as evidence the corpus can answer after all.

Second form: `_second_passage` calls `lexical.assess(..., document_id)` at
`answer.py:264` where `document_id` is the *request's* filter, not the hit's.
That is correct today. Do not "fix" it to `hit["document_id"]`.

## Latency budget — 15 W CPU, no GPU

| Step | Cost |
|---|---|
| Term incidence, 8 docs | Tens of ms |
| Diverse shortlist (RRF-scale selection only) | **Zero** — same 16 passages, same one pass |
| Second retrieval + re-rank of the union | Roughly doubles the rerank component. Gate it behind the expectation firing; if the fired case exceeds ~3.5s it is a Tier 2 feature |

Tier 1 median is ~2.1s and `limitations.md` records that the last +650 ms was
paid deliberately and bought 9/10 to 10/10. Any addition here is measured
against that precedent or it is not made.

## The smallest honest version — about 90 minutes

Report-only. No retrieval change, no rerank change, no second pass. Zero effect
on latency, on the -3.0 calibration, or on `run_phrasings.py`.

1. **`search()` records the shortlist eviction** — `search.py:661` returns
   `"shortlist_excluded": [{chunk_id, document_id, rrf, reason}]`. ~15 min.
   This closes the one silent-drop hole in the pipeline and is worth shipping
   alone even if the rest is abandoned.
2. **`backend/app/coverage.py`, one function** —
   `document_incidence(question, allowed_document_ids, document_id=None)`,
   called from `answer()` after the answer is built, only for `extract` and
   `generated`. Reuse `lexical.distinctive_terms`; do not reimplement. ~40 min.
3. **`basis: "term_incidence"`, `complete` false or null, never true**, with a
   `note` saying the expectation is presence-based. ~5 min.
4. **Schema + contract + `_PAYLOAD_KEYS`, one commit.** ~15 min.
5. **Run the five gold questions, record the Q4 row.** ~15 min.

### What it produces, measurably

Q4 goes from "doc19 only, silently" to "doc19 cited; NIST SP 800-53r5 also
carries *eradication* and *containment* and supplied N candidates — this answer
is partial."

The before/after is **not** "1 of 2 to 2 of 2". It is **"1 of 2, undetected" to
"1 of 2, detected and reported"** — which is the honest claim, and the one
`docs/gold-questions.md` actually asks for: *the coverage report must say so
rather than presenting a partial answer as whole.*

### What it does not claim

It does not improve retrieval. It does not find doc17. It supports no
completeness guarantee. **Anyone describing it as multi-document *synthesis* is
overstating it** — it is multi-document *coverage reporting*.

### What comes second

The document-diverse shortlist, alone: reserve slots for other documents by RRF
mass before the 16-slot cut, `rerank=False` path untouched, single batch
preserved. Re-measure on `run_eval.py` and `run_phrasings.py` before claiming
anything — `limitations.md` records that `rerank_candidates` 20 to 16 was
deliberate and that 12 degraded non-monotonically, so changing composition
demands the same evidence changing size did.

A second retrieval pass comes last, or never: the `shortlist_excluded` telemetry
from step 1 answers for free whether doc17 was ever in the pool.

> **It did, and the answer invalidates this section.** Step 1 is built and
> measured (2026-09-05). doc17's best candidate is **rank 7 of 52 by RRF, one
> of four doc17 candidates inside the 16-slot shortlist, and rank 5 of 16 after
> the rerank at +2.104** - its *3.8 INCIDENT RESPONSE* section on p179. It is
> not displaced by the cut; it is simply below the three passages the answer
> takes. A document-diverse shortlist reserves slots for a document that is
> **already in the shortlist**, so it would change nothing here. Whatever comes
> second has to be derived from this measurement, not from the assumption it
> replaces. Full figures in `docs/gold-questions.md`, under Q4.

### Step 1, as built

Wider than specified, deliberately. The brief calls the shortlist cut "the one
silent-drop hole"; it is not. `deduplicate()` discarded near-identical
candidates silently, and the pool builder silently skipped chunks whose row had
gone or had been marked non-retrievable. Recording only the cut would have left
two unaccounted losses in the same pipeline and could have answered the doc17
question wrongly - a candidate lost to dedup would have looked like a candidate
that never existed. All five reasons are recorded under one stable slug
vocabulary (`search.EVICTION_REASONS`).

The record is taken **before** the reranker runs but is only kept if the
reranker returns scores, because a reranker that returns nothing leaves the
pool whole and those candidates were never dropped. There is a test for that
specific lie, and it fails against the naive implementation.

`shortlist_excluded` is not on the HTTP surface: `schemas.SearchResult` does
not carry it, so `/api/search` is byte-identical and `contracts/types.ts` is
untouched. It is internal telemetry for the coverage layer in step 2.
