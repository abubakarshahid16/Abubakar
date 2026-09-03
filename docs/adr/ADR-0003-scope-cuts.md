# ADR-0003 — Scope cuts for the prototype cut

- **Status:** Accepted
- **Date:** 2026-09-04

## Context

- The P0 backlog in EXECUTION.md §13 sums to **20.5 h optimistic / 40 h upper** against the plan's own effort guide.
- Available time to the 3:00 PM AST cut was **~17 h wall clock** at project start, spanning a full night.
- Cuts were therefore agreed up front rather than discovered at T−90 minutes.

## Cuts applied

| Cut | Detail | Reversal path |
|---|---|---|
| **OCR** | Detect and flag scanned pages only. No OCR implementation. | Tesseract `eng+ara` behind the existing detection heuristic |
| **ANN index** | Brute-force vector search only. At prototype scale it is faster *and* exact. | LanceDB `IVF_HNSW_SQ` above a measured threshold (~100k vectors) |
| **Retrieval profiles** | One profile only. Fast and Quality dropped. | Re-add as config once latency is understood |
| **System view** | Four UI views: Documents, Chat, Ingestion, Dashboard. History folded into Chat. | Separate view later |
| **Playwright** | Manual, evidenced acceptance testing. | Add post-prototype |
| **mypy blocking** | Runs in CI, reports, does not block merge. | Flip to blocking when the type surface stabilises |
| **Offline installer packaging** | See ADR-0002 — the premise was wrong. | n/a, permanently removed |
| **GitHub Project board** | Token lacks `project` scope; low value pre-deadline. | `gh auth refresh -s project` |

## Cut then REVERSED

- **Reranker.** Originally cut. **Reinstated as mandatory** by ADR-0001 — a small local CPU cross-encoder is what makes the no-LLM Tier 1 path trustworthy, and it removes ~90 s of prompt evaluation per query. It pays for itself many times over.

## Never cut

- Page-level citations
- Insufficient-evidence refusals
- Streaming upload
- Crash resume from the last completed page batch
- Honest status labels — a partially processed document is never shown as `ready`

## Deviations from the plan's stated stack

- **Python 3.12.10**, not the specified 3.11. All selected libraries support 3.12. Recorded rather than spending deadline time on an interpreter change.
- **Free disk ~45 GB** on the working volume — does not accommodate the full 1.2 M-page corpus. Prototype scale only.
