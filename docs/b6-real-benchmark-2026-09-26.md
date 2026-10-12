# B6 core retrieval — real-standards benchmark, 2026-09-26

**Aggregate numbers only.** No standard name, question, passage, page number or
score-per-query appears here (CLAUDE.md rules 1 and 3). The question set and the
scratch database lived only in an owner-approved cloud session and were deleted
with it.

## Setup

| Item | Value |
|---|---|
| Corpus | 9 of the owner's company standards (242 pages, 842 retrievable chunks, 842 vectors) |
| Models | the REAL staged models: multilingual-e5-small (qint8 ONNX) and ms-marco-MiniLM-L-6-v2 reranker (quantized ONNX) |
| Code | `feat/b6-core-retrieval` merged with `main` (B4 + B5), hybrid search + rerank, top 5 |
| Questions | 36 real requirement clauses × 2 phrasings = **72 positives**; **8 negatives** (topics the 9 standards do not answer) |
| Kinds | **exact** = the clause's own key terms; **paraphrase** = the same question in plain words sharing few content words |
| Hit rule | the returned chunk is in the right document AND its page range covers the answer page |
| Machine | a cloud container — **not** the 16 GB target laptop, so latency is indicative only |

## Recall by stage

| Queries | Stage | recall@1 | recall@5 | MRR |
|---|---|---|---|---|
| exact (36) | keyword (FTS5) only | 0.667 | 0.833 | 0.741 |
| exact (36) | dense (e5) only | 0.667 | 0.889 | 0.766 |
| exact (36) | **hybrid + rerank** | **0.750** | **0.972** | **0.861** |
| paraphrase (36) | keyword only | 0.222 | 0.444 | 0.306 |
| paraphrase (36) | dense only | 0.361 | 0.722 | 0.499 |
| paraphrase (36) | **hybrid + rerank** | **0.417** | **0.778** | **0.552** |
| **all (72)** | **hybrid + rerank** | **0.583** | **0.875** | **0.706** |

Each stage earns its place: fusion + rerank beats either side alone on both kinds.
The synthetic CI benchmark (recall@1 0.94) overstates real performance — the real
figure is 0.58 at rank 1 and 0.88 in the top 5.

**Misses in the top 5: 9 of 72** — 8 paraphrases, 1 exact phrasing (a generic
"references" clause whose words appear in every standard).

## Unanswerable questions (negatives)

| Measure | Value |
|---|---|
| Negatives flagged `low_confidence` | **0 of 8** |
| Positives flagged `low_confidence` | 1 of 72 |
| Negatives' top rerank scores | −9.30 … **+1.02** |
| Correct passages' rerank scores (63 found in top 10) | −6.70 … high positive |
| Correct passages below the −9.5 noise floor | **0** |

**Finding — no score threshold is set, on purpose.** The worst negative (+1.02)
retrieved a clause on the same *subject* that does not answer the question; the
cross-encoder scores topical overlap, not "this answers it". 20 of the 72
positives' top scores are below that negative. The two populations overlap, so
any threshold high enough to refuse most negatives would refuse right answers.
This matches what `search.RELEVANCE_FLOOR`'s own comment already states from the
earlier 35-question measurement; the −9.5 noise floor itself held (no correct
passage below it). "The corpus does not answer this" therefore cannot rest on the
retrieval score; it needs an answer-level check (B8's verdict gate), with its own
labelled evaluation — not a guessed threshold.

## Latency (cloud container, 80 queries, hybrid + rerank)

p50 **2.17 s**, p95 **2.45 s**. The same code measured p50 0.57–0.81 s on the
3-document synthetic corpus in CI; re-measure on the target laptop before quoting.

## Stage mutations (`scripts/mutations/search.py`, `test_b6_core_retrieval.py`)

| Id | Deleted | Result |
|---|---|---|
| M790 | dense retrieval | detected |
| M791 | RRF keyword-rank weighting | detected |
| M792 | RRF dense contribution | detected (first NOT detected — a direct RRF arithmetic test was added) |
| M793 | reranker skipped | detected |
| M794 | reranker scores inverted | detected |
| M795 | dense permission mask | detected |
| M796 | keyword permission clause | detected |

7/7, each by an assertion failure (an earlier run "detected" all seven by
fixture errors because the session lacked OCR models — that run was discarded).
