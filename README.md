# RAG Intelligence System — Private Document Intelligence Prototype

Local hybrid-RAG prototype for petroleum engineering documentation.
Ask questions against your own PDFs and get answers that cite the exact page they came from — or an honest "insufficient indexed evidence" when they can't.

> **Status: in development.** Every number in this README is measured, and each says
> where it was measured; a figure nobody has run is not written here.
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

```text
PDF ──▶ stream + SHA-256 ──▶ page batches ──▶ PyMuPDF text ──▶ structure-aware chunks
                                     │                                    │
                                     │                                    ├──▶ ONNX int8 E5 ──▶ SQLite BLOBs (brute-force)
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
| Vector search | Vectors as BLOBs in SQLite (`chunk_vectors`), memory-mapped into one numpy matrix (`vectorcache.py`), brute-force cosine. `lancedb` is still pinned in `backend/requirements.txt` but nothing imports it |
| Keyword search | SQLite FTS5 |
| Fusion | Reciprocal Rank Fusion |
| Reranking | Small local CPU cross-encoder — **mandatory**, not optional |
| Answer model | Local Qwen via Ollama (`qwen3.5:4b` default, configurable), `think=false`, `num_thread=12`, `num_batch=2048`, `num_ctx=4096`, up to 250 output tokens (`backend/app/config.py`) |
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

- ~~**OCR**~~ — **no longer cut.** Scanned pages are recognised offline (RapidOCR / PP-OCRv6, in a subprocess), and recognised text is labelled as such rather than presented as a quotation. Coverage across the corpus rose 94.0% → 96.3%. See `docs/adr/ADR-0005` and `ADR-0006`.
- **ANN index** — brute-force vector search is faster *and* exact at prototype scale
- **Retrieval profiles** — one profile (Balanced)
- ~~**System view**~~ — **no longer four.** Six built views (Dashboard, Documents, Chat, Analysis, Reports, Ingestion) plus an Administration section, per the navigation in `frontend/src/components/Shell.tsx`. History is still folded into Chat.
- **Playwright** — acceptance testing is manual and evidenced
- **Offline installer packaging** — the machine has internet; a normal install guide replaces air-gap staging

Full rationale and known limitations: `docs/adr/`.

## Getting started

Every step below was executed from a clean `git clone` into an empty directory,
on a machine with none of this project's state. Where a step failed, the fix is
in the repository and the step here is the corrected one. A setup guide that has
not been run from a clean clone is a guess.

**Last verified end to end on 2026-09-07**, from a fresh clone of
`feat/phase-1-ui-reaches-backend` at 5baf18e. What that run produced, so you
can tell whether yours is going right: models staged 179 MB; backend suite
**1,170 passed, 3 skipped, 17 xfailed in 5m56s**; frontend **496 passed across
42 files**; `npx tsc -b` clean; the API answering 200 on `/api/health`,
`/api/documents` (`[]`, no corpus in the clone) and `/api/metrics`. The backend
figure is four lower than step 5 because it was taken at 5baf18e, before
cd72bac added four tests - the commit is named here rather than the number
being quietly refreshed, so the two can be reconciled instead of looking like
a contradiction. Two things
that run found and this guide now fixes: `backend/.env` is never created by
anything (step 4), and `py -3.12` does not exist on every Windows machine
(step 1).

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
| **Python** | **3.12 exactly** | Every pin in `backend/requirements.txt` was resolved against 3.12. `onnxruntime==1.29.0` and `numpy==2.5.3` ship per-minor-version wheels, so another 3.x installs different binaries or none. `run.py` refuses to start on the wrong minor and tells you so. |
| **Node** | 24.x (built on 24.18.0) | `npm ci` installs from the committed lockfile. |
| **Ollama** | running, with `qwen3.5:4b` pulled | **The one prerequisite `fetch_models.py` cannot get for you** — see below. Needed only for Tier 2 ("Explain") answers; Tier 1 quotations work without it, verified by pointing the backend at a dead port. |
| **RAM** | ~16 GB | See *If you have less* below. |
| **Disk** | **773 MB in the clone, plus ~3.4 GB elsewhere** | Measured on the clean clone of 2026-09-07, not estimated — see below. |
| **Internet** | for setup only | See above. |

#### Ollama, in full

`scripts/fetch_models.py` stages the embedder, the reranker and the OCR
weights. It does **not** install Ollama or pull the answer model, and nothing
else in this repository does either — this is the one prerequisite you have to
satisfy by hand.

1. Install Ollama from **<https://ollama.com/download>** (Windows, macOS and
   Linux installers; on Linux, `curl -fsSL https://ollama.com/install.sh | sh`).
2. Start it and pull the model:

```bash
ollama serve                 # a service on Windows/macOS; usually already running
ollama pull qwen3.5:4b       # ~3.4 GB
ollama list                  # confirm qwen3.5:4b is there
```

The model name must match `answer_model` in `backend/app/config.py`, which
defaults to `qwen3.5:4b`. If Ollama is not running, Tier 1 quotations still
work and the "Explain" button reports `model_unavailable` rather than failing
silently.

#### What 773 MB covers, and what it does not

Measured on a completed clean clone, so a reader can size a disk honestly:

| | Size |
|---|---|
| `.venv` | 528 MB |
| `backend/models` (staged weights) | 159 MB |
| `frontend/node_modules` | 78 MB |
| `.git` | 3 MB |
| **Total inside the clone** | **773 MB** |

**The Ollama model is NOT in that figure.** It lives outside the repository —
`~/.ollama/models` — and `qwen3.5:4b` is a further **~3.4 GB**. Budget
**roughly 4.2 GB** in total for a working machine.

> An earlier version of this README said "~2 GB", which nobody had measured.
> It was wrong by 2.6× in the safe direction, which is why it survived: nothing
> depended on it. See `docs/status-honesty-audit.md`.

> **The `py` launcher may not exist.** On the machine this was verified on,
> `py -3.12` was not installed and only the full interpreter path worked. If
> `py` is not found, invoke your 3.12 interpreter directly — the venv it
> creates is what matters, not how you launched it.

### Steps

```bash
git clone <repo-url> rag-intelligence
cd rag-intelligence
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
npm run test      # 496 tests across 42 files, ~1 minute
cd ..
```

**4. Configuration. `backend/.env` is NOT in the clone, and nothing creates it.**

```bash
cp backend/.env.example backend/.env      # Windows: copy backend\.env.example backend\.env
```

The application runs **without** this file - it did, on the clean clone this
guide was verified against - so it is easy to skip and then wonder why access
control does nothing. With no `.env`, `AUTH_MODE` defaults to `disabled` and
the server says so at startup, in these words:

```text
WARNING:  AUTH_MODE=disabled - every request sees every document, and no login
is required. Set AUTH_MODE=demo_required in backend/.env to enforce access
control.
```

That warning names a file the clone does not contain, which is why this step
exists. `.env.example` carries every key with a safe default; the two that
decide behaviour are `AUTH_MODE` (`disabled` or `demo_required`) and
`AUTH_SECRET`, which is **empty in the example and must be at least 32
characters before `AUTH_MODE=demo_required` will start at all**:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

A short or absent secret is refused at **startup**, not at first login -
deliberately, because a system that boots and then rejects everyone looks like
a broken deployment, while one that boots with a guessable key looks like a
working one. No key in `.env.example` is a real credential.

**5. Backend tests.** Run from `backend/`, which is where `pytest.ini` lives:

```bash
cd backend
python -m pytest -q      # expected counts: SETUP.md section 5 (two figures, with and without .env)
```

**The count is stable; the duration is not.** The expected count lives in
`SETUP.md` section 5 and nowhere else, so it cannot go stale in two places. As
an illustration from early September 2026, when the suite was much smaller:
three CI runs reported the same count every time, in 3m18s, 4m57s and 10m48s -
the same work, three times the wall clock, on the same runner type. Locally it took
5m44s idle and over 11 minutes with the dev server, Ollama and a second test
run competing. So treat the count as the thing to check and the duration as
weather. If your run matches SETUP.md's count in twelve minutes, nothing is wrong.

Run it from `backend/`, not from the repository root. `pytest.ini` lives there,
and so does `.env` - which the application reads for `AUTH_MODE`. The suite pins
the authentication mode itself (`tests/conftest.py`) so its result does not
depend on whether you have a local `.env`, but the same is not true of the
server: see step 6.

Slow tests that build a real ONNX session are marked `slow` and deselected by
default. Run them with `python -m pytest -m slow`.

If the models are not staged, the suite **stops immediately** with the command
that fixes it, rather than producing ninety failures with one cause.

**6. Run it.** Two terminals:

**Start the API from `backend/`, not from the repository root.** `python
backend/run.py` starts and appears to work, but `backend/.env` is read relative
to the working directory - so `AUTH_MODE=demo_required` in that file is silently
ignored and the server comes up with authentication OFF. There is no warning.
(Fixed in `config.py` by anchoring the path; the habit is still worth keeping,
because `pytest.ini` has the same requirement.)

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

### Engineering review baselines

Engineering review comparisons support configurable baseline rules. An
administrator maps the uploaded submittal's classified document type and
discipline to a baseline type/discipline, with a priority. The review API can
then select the newest searchable matching document within the caller's access
scope. A user-supplied baseline remains an explicit override; the API never
silently chooses an authoritative document when no rule matches.

Reviewers can label the comparison intent as baseline vs submittal,
requirements vs submittal, revision delta, or discipline coordination. The
label is validated at the API boundary and returned with the comparison.

Management summaries also support an opt-in daily or weekly schedule. The
schedule is UTC/config-driven, idempotent per reporting window, and uses the
same fail-closed SMTP and audit trail as event notifications.

### Branches

    <type>/<issue-number>-<stable-id>-<slug>

`type` is one of `feat`, `fix`, `chore`, `docs`, `perf`, `style`, `test`.
Real examples from this repository:

    feat/14-ing-001-stream-pdf-upload
    feat/16-ing-002-page-batch-extraction
    feat/20-emb-001-structure-aware-chunking
    chore/6-gov-001-repo-guardrails
    docs/7-arc-001-rag-adr

One issue → one branch → one PR. **The issue number is not optional**: it is
what lets someone reading `git log` in a year find out why a change was made.

> **This convention lapsed and nobody noticed.** It held for 17 issues and 58
> PRs, then stopped the moment work went off-plan onto a branch with no issue
> number — after which 1 of 11 commits referenced an issue. Nothing in the
> repository said it should, which is why it is written here and enforced by
> `.github/pull_request_template.md`.

### Commits

Merge commits, not squash. The commit messages carry the reasoning and the
measured numbers — *"the isolated figure was measuring the wrong thing"*,
*"one bug wearing three faces"*. Squashing tidies a graph nobody reads at the
cost of the project's memory.

**Never commit** PDFs, extracted text, embeddings, chat history, model weights, secrets, or client metrics.

Deliverable intelligence supports configured expected items per WBS code and
reports whether each expected deliverable is registered or missing.

`/api/search/structured` searches deliverables and review findings by their
structured fields, with the same document access scope as the rest of the API.

The risk register uses governed types: schedule, review, dependency, and
compliance. Unknown types are rejected at creation.

Review finding traceability is available at `/api/reviews/findings/{id}/traceability`;
it links the finding, source document/baseline, citations, event history, and
linked deliverables in one access-scoped response.

Overdue deliverables now use distinct audited reminder and escalation functions;
they are not collapsed into the daily summary.

The current KJO requirements scorecard is maintained in
[`docs/requirements-audit.md`](docs/requirements-audit.md); it separates
shippable UI from backend scaffolding and client-blocked templates.

Chat can search workflow records (deliverables, findings, risks, and
stakeholders) separately from page-cited document evidence.

Expected deliverables are inferred from requirement passages using the same
claim text used by engineering review; manual expectations remain overrides,
and the UI labels inferred versus manual origins.

The risk register also creates idempotent schedule, review, dependency, and
compliance risks from overdue deliverables, aged findings, overdue parents,
and unresolved requirement evidence, with an audited notification attempt.

Review traceability now continues through the assigned owner and required
action, so an engineer can inspect the complete finding-to-action chain.

Recommendation refusals now preserve the backend reason through the API and
show it directly in Analysis; the UI does not guess why advisory output was
withheld.
