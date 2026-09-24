# ADR-0022 — Retrieval and evaluation methodology against the Microsoft RAG guides

- **Status:** Accepted (research stage 1)
- **Date:** 2026-09-24
- **Decision:** Retrieval architecture — **ADOPT (keep as is; no new
  infrastructure).** Evaluation methodology — **ADOPT** three additions to the
  existing harnesses. LLM query rewriting / HyDE — **REJECT** for now.

## Sources read

- *RAG information-retrieval phase* (Azure Architecture Center). Recommends:
  retrieve broadly, merge lexical + vector with RRF (c ≈ 60), rerank with a
  cross-encoder, truncate to top N; benchmark relevance **and** latency on your
  own test queries; evaluate with precision@K, recall@K, MRR; **test negative
  queries too** (metrics should approach 0 where the corpus cannot answer).
- *RAG solution design and evaluation guide*. Evaluate each phase
  (chunking, enrichment, embedding, retrieval, generation) separately with
  representative test media and queries; record hyperparameters with results.
- Azure is used here as an **architecture reference only**. No client
  document, chunk, query or score is sent to any cloud service (ADR-0002).

## What the code already does

`backend/app/search.py`: SQLite FTS5 + dense (384-dim e5-small ONNX, vectors
as SQLite BLOBs, brute-force over a numpy memmap in
`backend/app/vectorcache.py` — **not LanceDB**, despite `lancedb` being pinned
in `backend/requirements.txt`), fused by `rrf_fuse`, then cross-encoder
reranked. That is the guide's recommended four-step pipeline, already built.
`standards.search_requirements` reuses it; comparison-time requirement
retrieval (`submittal_review.list_standard_requirements`) is an exhaustive SQL
fetch per applicable standard — exact, so it has no recall loss to fix.

## The existing weakness

- `scripts/eval_retrieval.py` scores recall@5, recall@10, MRR on
  `gold/R1-SAMPLE-30.csv`: **30 cases, not engineer-labelled** (the script
  says so), local-only (gitignored), **no negative cases, no precision@K**.
- `scripts/eval_extraction.py` covers datasheet extraction only; nothing
  measures chunking or requirement extraction per phase (see ADR-0021).
- Dense search is brute force. ADR-0003 already names the ANN trigger
  (~100 k vectors). The 2 M-page plan crosses it.

## Evaluation data needed / additions adopted

1. Negative retrieval cases (queries the corpus cannot answer) in the
   retrieval tripwire, reported separately from positives, as the guide says.
2. precision@K alongside recall@K and MRR, same single ranking per case.
3. A larger, engineer-labelled case set drawn from more than one standard;
   until labelled, results stay "sample, not engineer-verified".

## Measured benefit on our data

Current retrieval numbers are whatever the tripwire last recorded on 30
cases. The proposed additions are measurement, so "benefit" is coverage of
the evaluation, not a retrieval gain. **No retrieval gain is claimed.**

## Cost on the stated hardware (estimate)

- Eval additions: negligible compute.
- At ~2 M pages and the ~1.6 chunks/page seen on the 1,400-page capacity test
  (`docs/benchmarks.md`), ~3.2 M vectors x 384 x 4 B ≈ **~4.9 GB** memmap;
  embedding at the measured 9.22 chunks/s ≈ **~4 days** of CPU (both
  estimates; engineering documents may chunk more densely).
- Query rewriting / HyDE needs an LLM call per query on a CPU-only laptop where
  generation is already the latency floor, and it makes retrieval depend on a
  non-reproducible model output.

## Reason for the decision

The implemented pipeline matches the guide; the gap is the evaluation, not the
architecture. The ANN question is **DEFERRED** to a measured query-latency
threshold on a scaled corpus, not decided on vector count alone.
