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

Every step below was executed from a clean `git clone` into an empty directory,
on a machine with none of this project's state. Where a step failed, the fix is
in the repository and the step here is the corrected one. A setup guide that has
not been run from a clean clone is a guess.

### Offline at run time. Online ONCE at setup time.

Say this plainly, because the product is described as fully offline and that is
true of the *query* path: no document, question or answer ever leaves the
machine, and there is no outbound request when you ask a question.

**Setup is different.** `backend/models/` and `*.onnx` are gitignored, so the
model weights are not in the clone. They are downloaded exactly once, by
`scripts/fetch_models.py`. **Run that step before the machine is air-gapped.**
`npm ci` and `pip install` also need the network. After setup completes, nothing
reaches the network again except your own Ollama on localhost.

### Prerequisites — none of these come from the clone

| Requirement | Version | Why it is pinned |
|---|---|---|
| **Python** | **3.12 exactly** | Every pin in `backend/requirements.txt` was resolved against 3.12. `onnxruntime==1.24.1` and `numpy==2.3.4` ship per-minor-version wheels, so another 3.x installs different binaries or none. `run.py` refuses to start on the wrong minor and tells you so. |
| **Node** | 24.x (built on 24.18.0) | `npm ci` installs from the committed lockfile. |
| **Ollama** | running, with `qwen3.5:4b` pulled | ~3.4 GB download. Needed only for Tier 2 ("Explain") answers — Tier 1 quotations work without it. |
| **RAM** | ~16 GB | See *If you have less* below. |
| **Disk** | ~2 GB | 179 MB of model weights, plus node_modules and the venv. |
| **Internet** | for setup only | See above. |

> **The `py` launcher may not exist.** On the machine this was verified on,
> `py -3.12` was not installed and only the full interpreter path worked. If
> `py` is not found, invoke your 3.12 interpreter directly — the venv it
> creates is what matters, not how you launched it.

### Steps

```bash
git clone <repo-url> nabaa
cd nabaa
```

**1. Python environment.** Create it with 3.12 specifically:

```bash
py -3.12 -m venv .venv            # Windows, if the launcher exists
python3.12 -m venv .venv          # macOS / Linux
# fallback if neither resolves: use the full path to a 3.12 interpreter

.venv/Scripts/activate            # Windows (PowerShell: .venv\Scripts\Activate.ps1)
source .venv/bin/activate         # macOS / Linux

pip install -r backend/requirements.txt
```

The virtual environment lives at the **repository root**, not inside
`backend/`.

**2. Stage the models. This is the step that needs the network.**

```bash
python scripts/fetch_models.py
python scripts/fetch_models.py --verify-only
```

Downloads ~179 MB: the e5-small embedder, the cross-encoder reranker, and the
OCR detector/recogniser/classifier. `--verify-only` checks presence **and**
SHA-256, and exits non-zero if anything is missing or does not match — a file
of the right name and the wrong content is worse than a missing one, because it
runs.

**3. Frontend.**

```bash
cd frontend
npm ci
npx tsc -b        # typecheck
npm run test      # 115 tests
cd ..
```

**4. Backend tests.** Run from `backend/`, which is where `pytest.ini` lives:

```bash
cd backend
python -m pytest -q      # 496 tests, ~4 minutes
```

Slow tests that build a real ONNX session are marked `slow` and deselected by
default. Run them with `python -m pytest -m slow`.

If the models are not staged, the suite **stops immediately** with the command
that fixes it, rather than producing ninety failures with one cause.

**5. Run it.** Two terminals:

```bash
# terminal 1 - API on 127.0.0.1:8000 (loopback only, by design)
cd backend && python run.py

# terminal 2 - UI on 127.0.0.1:5173
cd frontend && npm run dev
```

Open the UI, upload a PDF, and ask a question. Measured on a 24-page
specification from a clean clone: **answerable 3.9 seconds after upload**,
because the keyword index is built before embedding. Larger documents keep
answering while embedding and OCR continue in the background.

### If you have less than 16 GB

The answer model holds ~3.4 GB and the API process peaks at ~3.2 GB with both
ONNX arenas enabled. Below roughly 16 GB you will see, in this order: Tier 2
answers slow sharply or fail as Ollama swaps; OCR should be run only while the
answer model is unloaded (see `docs/runbook.md`); and ingesting a large document
alongside answering becomes unreliable. Tier 1 quotations and keyword search are
the last things to degrade.

### Troubleshooting

| Symptom | Cause |
|---|---|
| `This project requires Python 3.12` | Wrong interpreter in the venv. Delete `.venv` and recreate it with 3.12. |
| Suite stops with "models are not staged" | Run `python scripts/fetch_models.py`. |
| `WRONG CONTENT (SHA-256 does not match)` | A corrupted or changed download. Re-fetch with `--force`. |
| 404 at `http://127.0.0.1:8000/` | Expected. The API has no root route; everything is under `/api/*`, plus `/docs`. Open the UI on 5173 instead. |
| Vite starts on 5174 or 5175 | Another dev server is already running on 5173. |
| "Explain" reports the model unavailable | Ollama is not running, or `qwen3.5:4b` is not pulled. Tier 1 is unaffected. |

## Repository conventions

Branch: `<type>/<issue-number>-<stable-id>-<slug>` · squash merge only · one issue → one branch → one PR.

**Never commit** PDFs, extracted text, embeddings, chat history, model weights, secrets, or client metrics.
