# Nabaa — Private Document Intelligence Prototype

Local hybrid-RAG prototype for petroleum engineering documentation.
Ask questions against your own PDFs and get answers that cite the exact page they came from — or an honest "insufficient indexed evidence" when they can't.

> **Status: in development.** Nothing in this README is a measured performance claim.
> Benchmarks are recorded in `docs/benchmarks.md` only after they are actually run on this hardware.

---

## The one rule

**Client document content never leaves this machine.**

| Allowed | Forbidden |
|---|---|
| Downloading model weights, pip/npm packages | Sending document text, chunks, questions, or answers to any external service |
| GitHub, CI, reading documentation | Hosted inference APIs |
| Any network use that does not carry document content | Cloud OCR |
| | Cloud/hosted vector databases |

All inference — embedding and generation — runs locally on CPU.
After model download completes, `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` are set so no library can phone home with document content.

This is **not** an air-gapped system. It is a **locally-inferencing** system on a networked machine.

---

## Architecture

```
PDF ──▶ stream + SHA-256 ──▶ page batches ──▶ PyMuPDF text ──▶ structure-aware chunks
                                     │                                    │
                                     │                                    ├──▶ ONNX int8 E5 ──▶ LanceDB (brute-force)
                                     │                                    └──▶ SQLite FTS5
                                     ▼
                              resumable checkpoint
                              (completed batches are searchable immediately)

question ──▶ dense + FTS candidates ──▶ RRF fusion ──▶ cross-encoder rerank
                                                              │
        TIER 1 (default, no LLM) ◀────────────────────────────┤   top passage, quoted verbatim
        ~1-2 s                                                │   + document, page, section, highlighted span
                                                              │
        TIER 2 (explicit "Explain" / auto-routed) ◀───────────┘   2 chunks x 250 tok ──▶ local Qwen
                                                                  └──▶ cited answer, or insufficient evidence
```

## Stack

| Layer | Choice |
|---|---|
| Backend | Python · FastAPI · Uvicorn (loopback only) |
| Frontend | React · TypeScript · Vite · Tailwind · shadcn/ui |
| PDF extraction | PyMuPDF (processes, never threads) |
| Chunking | Custom structure-aware, 400-token target / 60-token overlap |
| Embeddings | `intfloat/multilingual-e5-small`, local ONNX int8, 384-D normalized |
| Vector search | LanceDB embedded, brute-force cosine |
| Keyword search | SQLite FTS5 |
| Fusion | Reciprocal Rank Fusion |
| Reranking | Small local CPU cross-encoder — **mandatory**, not optional |
| Answer model | Local Qwen via Ollama (`qwen3.5:4b` default, configurable), `think=false`, `num_thread=12`, `num_batch=2048`, `num_ctx`~1536, 60-100 output tokens |
| Metadata / jobs / history | SQLite (WAL) |

## Non-negotiable behaviours

- **Tier 1 returns quoted source text and is never rendered as generated prose.**
- The UI always shows **which tier answered**.
- Every factual claim carries a **page-level citation**.
- Missing or weak evidence produces a **refusal**, never a confident guess.
- Retrieved PDF text is **untrusted data**, never instructions to the model.
- Previous assistant answers are **never** treated as evidence.
- Uploads **stream** to disk; a large PDF is never loaded whole into RAM.
- Killing the process mid-ingestion **resumes from the last completed page batch**.
- A partially-processed document is labelled `partially searchable`, never `ready`.

## Scope cuts applied

Deliberately excluded from the prototype to protect the deadline:

- **OCR** — scanned pages are detected and flagged, not OCR'd
- **ANN index** — brute-force vector search is faster *and* exact at prototype scale
- **Retrieval profiles** — one profile (Balanced)
- **System view** — four views: Documents, Chat, Ingestion, Dashboard (History folded into Chat)
- **Playwright** — acceptance testing is manual and evidenced
- **Offline installer packaging** — the machine has internet; a normal install guide replaces air-gap staging

Full rationale and known limitations: `docs/adr/`.

## Getting started

Not yet available — see `docs/` once `DEV-001` lands.

## Repository conventions

Branch: `<type>/<issue-number>-<stable-id>-<slug>` · squash merge only · one issue → one branch → one PR.

**Never commit** PDFs, extracted text, embeddings, chat history, model weights, secrets, or client metrics.
