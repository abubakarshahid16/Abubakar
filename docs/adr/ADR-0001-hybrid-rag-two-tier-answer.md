# ADR-0001 — Hybrid RAG with a two-tier answer path

- **Status:** Accepted
- **Date:** 2026-09-04
- **Supersedes:** the single-path answer design in EXECUTION.md §5 and the retrieval-profile table in §5

## Context

- Target hardware is a Lenovo IdeaPad Flex 7i — Intel i7-1255U (2 P-cores + 8 E-cores, 15 W), 16 GB RAM, no usable GPU offload.
- **This laptop is the production machine, not a development stand-in.** There is no faster environment later. Every measurement here is a production measurement.
- Benchmarking the plan's intended answer path on this hardware produced an unusable result — see `docs/benchmarks.md`.

## Measured evidence (not projections)

| Measurement | Value |
|---|---|
| Prompt eval, Ollama defaults | 20.7 tok/s |
| Prompt eval, tuned (`num_thread=12`, `num_batch=2048`) | 27.9 tok/s |
| Generation | 6–9 tok/s |
| **End-to-end: 3,767-token context → 53-token answer** | **195 s** |
| GPU offload | none — `ollama ps` reports `100% CPU` |

- Prompt evaluation is ~80% of total latency and **is** time-to-first-token, so streaming cannot conceal it.
- The plan's Balanced profile (7 chunks × 400 tokens ≈ 3,000–3,800 tokens) costs ~137 s per answer even tuned.

## Decision

**Two-tier answer path.**

**Tier 1 — default, no LLM.**
- Hybrid retrieval (dense + FTS5) → RRF → **cross-encoder rerank** → return the top passage verbatim.
- Returns document name, page number, section, and the answer span highlighted.
- Target: **1–2 s**.
- Rationale: most questions against engineering documentation are clause and value lookups. The exact quoted clause is a *better* answer than a paraphrase — it is auditable, and it cannot hallucinate.
- **Tier 1 output is quoted source text and must never be rendered as generated prose.**

**Tier 2 — explicit or auto-routed, calls the LLM.**
- Triggered by an explicit "Explain" / "Synthesise" action, or automatically when a question requires combining documents.
- Context budget: **2 chunks × 250 tokens**, not 7 × 400. To be validated against the client's real questions before locking.
- Answer capped at **60–100 tokens** — concise cited answers suit engineering documents, and generation is only 6–9 tok/s.

**The UI must always show which tier answered.**

## Supporting decisions

- **Reranker is mandatory.** This reverses the earlier cut. A small local CPU cross-encoder over the RRF candidates costs 1–2 s and removes ~90 s of prompt evaluation by making Tier 1 trustworthy enough to be the default.
- **`num_ctx` capped near 1536**, set from measurement. The plan's 8K cap is unusable on this CPU.
- **Tuned runtime settings retained:** `num_thread=12`, `num_batch=2048` (+35% prompt eval, measured).
- **System prompt capped under 250 tokens** including citation-format instructions. At 27.9 tok/s, every ~28 tokens costs one second. Its exact token count must be reported and tracked.
- **System prompt cached** via Ollama context reuse / `keep_alive` so it is not re-evaluated per turn.
- **Chunk boundaries never split mid-sentence.**
- **Ingestion pauses during the demo** — CPU contention would invalidate every latency number.
- **Answer model is a config value.** Default `qwen3.5:4b`. `qwen3.5:2b` to be benchmarked on identical context using the client's real questions. Floor is 2b; quality is not negotiable and the model will not be shrunk below it to buy speed.
  - Available sizes: 0.8b (1.0 GB), 2b (2.7 GB), 4b (3.4 GB), then 9b+. **`qwen3.5:1.7b` does not exist.**

## Rejected alternatives

- **Shrink the model to ~1.7B** — rejected: the tag does not exist, and trading answer quality for latency is not acceptable for engineering documentation.
- **Keep the single LLM path with a smaller context** — rejected: still ~57 s, still not demonstrable.
- **Wait for faster hardware** — impossible; this laptop is production.
- **Stream to hide latency** — rejected as a fix: the bottleneck is time-to-first-token. Retained only as a UX mitigation on Tier 2.

## Open items

- Intel iGPU acceleration via IPEX-LLM is to be attempted **after** the CPU baseline works end to end, under a hard 90-minute timebox. Prompt eval is compute-bound, which is what an iGPU helps. Expected 2–3× if it works. Numbers reported either way; if not working at 90 minutes, stay on CPU.
- Final configuration will be chosen from a measured latency table (Tier 1; Tier 2 CPU at 4b and 2b; Tier 2 iGPU if it works), not from projections.

## Consequences

- Tier 1 carries the demo. Tier 2 is the exception, not the default.
- The reranker becomes a critical-path component rather than an optional enhancement.
- Retrieval quality matters *more* than before: with no LLM to paper over a bad passage, Tier 1 is only as good as its top-ranked result.
