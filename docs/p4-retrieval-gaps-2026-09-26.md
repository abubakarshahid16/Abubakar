# P4 — remaining retrieval gaps, measured (2026-09-26)

Frozen B6 benchmark (72 answerable questions + 8 unanswerable, AI-authored,
relative only), fresh re-ingest of the 9 real standards on the current code,
cloud container (4 vCPU, no GPU). Aggregates only.

## Where retrieval stands

r@1 / r@5 / MRR **0.653 / 0.903 / 0.755**; reworded r@5 0.833; own-words r@5
0.972; **7 misses**; p95 2.37 s. Unchanged since B6B.

## Why the 7 misses miss

| Question | Correct passage | Rank of the correct passage (top 50) |
|---|---|---|
| reworded | prose, <= 292 tokens | 12 |
| reworded | prose, <= 275 tokens | not in top 50 |
| reworded | prose, <= 294 tokens | not in top 50 |
| reworded | prose, <= 276 tokens | not in top 50 |
| exact wording | prose, <= 331 tokens | not in top 50 |
| reworded | prose, <= 265 tokens | 1 at measurement time (benchmark-run variance) |
| reworded | prose, <= 72 tokens | not in top 50 |

* **No miss is a long clause or a table.** Every correct passage is prose
  under the 512-token embedding limit - nothing was truncated.
* **5 of 7 are not in the top 50 at all**: the reworded question shares
  neither the words (keyword) nor enough meaning (dense) with the clause. That
  is the vocabulary gap query expansion / multi-query exist for - and both
  need a language model to write the variants. A hand-written synonym list
  would be tuned to these 72 questions, which the finish-mode rules forbid.
* The result limit is not a lever: 0 of 72 questions change their top-5 rank
  between limit 5 and limit 50 (the rerank pool is fixed at 16 candidates).

## Is vector search the bottleneck? (ANN / vector DB)

| Stage | median | max |
|---|---|---|
| keyword (FTS5) | 0.9 ms | 1.6 ms |
| dense (e5, exact) | 48 ms | 86 ms |
| rerank (cross-encoder) | 1723 ms | 1982 ms |

No. The reranker is ~97 % of search time; an ANN index would save at most
~50 ms. **Not added.**

## Decision

No retrieval change in this session: none is justified by a measured failure
that this environment can fix. **Pending owner laptop (Ollama):** E5 query
expansion / multi-query on the frozen set, kept only if it improves r@5
without hurting citations, permissions, own-words recall or latency.
