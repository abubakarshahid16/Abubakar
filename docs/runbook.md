# Runbook

Operational rules for running this system on the demo machine. Everything here
is a consequence of a measurement in `docs/benchmarks.md`, not a preference.

## Backend restart after code changes

`backend/run.py` starts Uvicorn without `--reload`, and this deployment has no
supervisor or file-watching process manager. The frontend may refresh during
development, but backend code and configuration changes are **not** picked up
until the backend process is restarted. After any backend change, stop the
running process and start it again from `backend` with the project virtual
environment (for example, `..\\.venv\\Scripts\\python.exe run.py`).

## The machine has no spare memory. This governs everything below.

| Component | Resident |
|---|---|
| Backend API, both ONNX arenas ON | 3,247 MB |
| Backend API, both arenas OFF | 503 MB |
| `qwen3.5:4b` in Ollama, when loaded | ~3,400 MB |
| Measured free RAM at demo time | **1.15 GiB** |

## OCR must not run while questions are being answered

**This is the rule, and it is not a preference.** The real stage measured
**598 MB for one worker and 1,399 MB for two**, parent and children at their
simultaneous peak. Against the 1.15 GiB free at demo time, one fits and two do
not.

- **Before a demo or a Q&A session:** let ingestion finish, or stop the worker.
  Check `GET /api/documents` for any document not yet `ready`.
- **While OCR is running:** query latency is not protected. The machine is
  shared and OCR is CPU-bound on the same two performance cores retrieval uses.
- **Run ONE worker. `ocr_processes` is 1.** An earlier estimate from measuring
  a worker in isolation (524-549 MB) suggested two would fit. Measuring the
  real stage - parent and children at their simultaneous peak - gave
  **1,399 MB for two against 598 MB for one**. Two do not fit in 1.15 GiB.
  Raise it to 2 only when the answer model is unloaded AND you have checked
  free RAM first.

To check what is actually resident before deciding:

```powershell
Get-Process | Where-Object {$_.Name -match 'ollama|python'} |
  Select-Object Name, Id, @{n='RSS_MB';e={[math]::Round($_.WorkingSet64/1MB)}}
```

An `ollama` process at ~23 MB is the server with no model loaded. At ~3,400 MB
the answer model is resident.

## Ordering: OCR never sits in front of the first answer

The pipeline is extract → chunk → **keyword index** → *(OCR rounds)* → embed.
Keyword search needs no vectors, so a text document is answerable seconds after
upload. OCR runs after that point, in rounds that double in size, re-indexing
between rounds — so a scanned document becomes progressively searchable rather
than being unavailable until recognition finishes.

Never move the OCR stage earlier. Time-to-first-answerable on a 1,400-page text
document is ~13 s and recognition would put minutes in front of it.

## Staging models on a fresh machine

```bash
python scripts/fetch_models.py              # stages all three families
python scripts/fetch_models.py --verify-only  # checks presence AND SHA-256
```

This is the one script that reaches the network. **Run it before the machine is
air-gapped.** Without the OCR weights staged, RapidOCR would try to download
from modelscope.cn at the first recognition — which fails offline, at the worst
possible moment. `--verify-only` exits non-zero if anything is missing or if a
staged file's SHA-256 does not match the pinned value.

## Recognised text is labelled, never quoted

An answer drawn from a recognised page must never carry the verbatim label.
If you see *"Quoted verbatim from the document"* above text that came from a
scanned page, that is a defect — report it. The correct label is *"Read by OCR
from a scanned page"* with the page image expanded.

---

## Clean-clone verification — last passed 2026-09-05

**A passing clone test is only useful if the next person can see when it last
passed.** Update this section, with the date and the branch, whenever it is
re-run. If the date is old, the setup guide is a guess again.

| | |
|---|---|
| **Date** | 2026-09-05 |
| **Branch** | `perf/vector-cache-and-measurement-provenance` @ `935b336` |
| **Machine** | Windows 11 26200, i7-1255U, 15.6 GB RAM, Python 3.12.10, Node 24.18.0, npm 11.16.0 |
| **Method** | `git clone` from the remote into an empty directory, then the README "Getting started" steps followed as written |

Six steps, all clean:

| Step | Result |
|---|---|
| `pip install -r backend/requirements.txt` | Clean. Every dependency from a wheel — no compiler or build tools needed |
| `fetch_models.py` then `--verify-only` | 179 MB staged, presence and SHA-256 verified |
| `npm ci` | 0 vulnerabilities, from the committed lockfile |
| `npx tsc -b` | Clean |
| `npm run test` | **119 passed** |
| `python -m pytest -q` | **496 passed**, 210 s |

Then, in the clone:

- `run.py` on 127.0.0.1:8000 and `npm run dev` on 127.0.0.1:5173, both the
  documented ports; the Vite `/api` proxy returned 200.
- NORSOK M-501 uploaded → **answerable 3.9 s after upload**, `ready` at 19 s.
  24 pages, 80 chunks, 3 pages needing OCR of which 1 was recognised.
- *"what does NDFT stand for"* → `extract`, cited **page 7, clause 3.2
  Abbreviations**, `text_source=extracted`, 1.91 s.
- **Tier 1 without Ollama, verified rather than assumed:** with the backend
  pointed at a dead port, Tier 1 still answered with its citation and Tier 2
  returned `model_unavailable` with `ConnectError`.

### What the run found

| Finding | Status |
|---|---|
| A default `git clone` lands on `main` | **Verified — `main` is the release branch and contains the current README and tests** |
| README named Ollama as a prerequisite without an install source or `ollama pull` command | Fixed |
| README claimed ~2 GB disk; measured 768 MB, and the 3.4 GB Ollama model was unmentioned | Fixed |
| `py -3.12` does not exist on this machine | Not a defect — the README warns about it and its fallback worked |
