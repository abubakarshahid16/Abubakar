# SETUP - moving this project to a new machine

> **UNVERIFIED.** Written 2026-09-21 on laptop ABUBAKAR from commands run there. It
> has **not yet been walked through from a fresh clone** on the new machine. The first
> person to follow it should correct every step that fails, in this file, and then
> remove this banner.

`README.md` → *Getting started* has the detail behind each step (why each version is
pinned, how big things are, troubleshooting). This file is the move checklist: what the
clone gives you, what it does not, and what must be hand-carried.

---

## 0. Before anything: read the five canonical files

The project memory is in `.cowork/`. Read these five in order before every task:

| # | File | Arrives by |
|---|---|---|
| 1 | `.cowork/NORTH-STAR.md` - highest authority | clone |
| 2 | `.cowork/CURRENT_STATE_AND_BLOCKERS.md` - live status, bug register, checkpoint log | **hand-carry** |
| 3 | `.cowork/AI_SUBMITTAL_REVIEW_SYSTEM_AUDIT_AND_NORTH_STAR_V3.md` - detailed design | **hand-carry** |
| 4 | `.cowork/CLIENT_FEEDBACK_REQUIREMENTS_ADDENDUM.md` - requested, not built | clone |
| 5 | `.cowork/README-INDEX.md` - navigation only | clone |

**Two of the five do not come from `git clone`.** They contain client document names
and hashes, which instruction 6 in section 0 of `RAG-INTELLIGENCE-POC-EXECUTION.md` keeps
out of Git. If they are missing after the clone, they were **not yet copied**. They were
not deleted. STOP and get the copy (section 6). Never substitute a similar file.

Verify NORTH-STAR before trusting it:

```bash
certutil -hashfile .cowork\NORTH-STAR.md SHA256        # Windows
sha256sum .cowork/NORTH-STAR.md                        # macOS / Linux
```

Expected: `3d0505be629a99631e8cbcc0681134c642b7a00ae962a5c9f5ebf9df43499619`
(9 sections, checklist at section 8). **If it differs, STOP.**

---

## 1. Which branch

**Use `main`.** It is the GitHub default branch and holds the recovered, tested tree
(merged 2026-09-21, merge commit `09abc5d`).

Every other branch on GitHub, one line each:

| Branch | What it is |
|---|---|
| `feat/phase-1-ui-reaches-backend` | The working branch that was merged into `main`; identical tree at the merge. Continue new work on a fresh branch from `main` instead. |
| `wip/crs-export-b3-b4` | **NOT merge-ready.** The client's nine-column CRS export and the Claude router, with 16 failing tests (B3, B4, B5, B8). Do not merge. |
| `recovery/phase0-head` | Frozen safety copy of HEAD as found at the Phase 0 recovery (2026-09-20). Read-only. |
| `recovery/phase0-stash` | Frozen copy of the stash `agent-work-untested-parked` from Phase 0. Holds one patch not in `main`. Read-only. |
| `cowork/layer1-llm-extraction` | **Not merged, untested.** One Cowork commit (2026-09-19): a Layer 1 pre-build where an LLM reads datasheet fields and Python verifies them (`extraction_llm.py`, `extraction_score.py`, a test, a design note). Pushed 2026-09-21 only so it no longer lives on one laptop. |
| `docs/setup-new-machine` | Carried this SETUP.md into `main` (merged; the pre-commit hook blocks direct commits to `main`). History only. |
| `docs/setup-branches-and-readme-count` | Carried this branch-table update and the README test-count fix into `main` (merged). History only. |
| `feat/metadata-statistics` | Old feature branch; its change is already in `main` (patch-equivalent). History only. |
| `feat/stage-3-analysis-summary` | Old feature branch (PR #62); already in `main`. History only. |
| `fix/extraction-and-facets` | Old fix branch; fully merged into `main`. History only. |
| `fix/retrieval-main-sync` | Old fix branch; fully merged into `main`. History only. |
| `chore/60-sec-001-upload-ceiling-and-reachability` | Old chore branch; fully merged into `main`. History only. |
| `dependabot/pip/backend/pydantic-settings-2.15.0` | Open dependabot PR, **untested**. Do not merge without a full suite run. |
| `dependabot/pip/backend/pytest-9.1.1` | Open dependabot PR, **untested**, and a major version. Same rule. |

Branches that exist only on laptop ABUBAKAR are not in the clone. They are listed with a
disposition in `.cowork/CURRENT_STATE_AND_BLOCKERS.md` section 11.7.

---

## 2. Prerequisites

| Tool | Version | Note |
|---|---|---|
| Python | **3.12 exactly** | `run.py` refuses any other minor version |
| Node | 24.x (built on 24.18.0) | for `npm ci` |
| Git | any recent | |
| Ollama | running, with `qwen3.5:4b` pulled (~3.4 GB) | not installed by anything in the repo |
| gitleaks | 8.x (8.30.1 verified) | the pre-commit hook **blocks** commits without it |
| ruff | `0.16.6` | **The only unpinned dependency.** It is not in `requirements.txt`; CI installs it separately. Install by hand for local linting: `pip install ruff==0.16.6` |
| RAM | 16 GB minimum; the laptop is at exhaustion (B26) | the new machine has 48 GB |

---

## 3. Clone and install

```bash
git clone https://github.com/abubakarshahid16/saudi-aramco-rag-chatbot.git rag-intelligence
cd rag-intelligence
git checkout main
```

**Required, immediately after cloning:**

```bash
git config core.hooksPath .githooks
git config --get core.hooksPath          # must print .githooks
```

`core.hooksPath` is local git config and is **not** carried by the clone. Without it the
gitleaks pre-commit hook **never runs**, and nothing warns you.

> **CI IS NOT RUNNING (as of 2026-09-21). The local hook is the only automated gate.**
> GitHub Actions has hit the account's monthly minutes/spending limit. Every workflow
> run on `main` shows a **red X**, but that is a **billing block, not a test failure**.
> The jobs were never started: 0 steps, no runner, and GitHub's annotation reads *"The
> job was not started because recent account payments have failed or your spending
> limit needs to be increased."* So:
> - a red X on `main` says **nothing** about the code; the test figures are in section 5;
> - **no secret scan, test run or client-data guard runs on push** until billing is fixed;
> - `.githooks/pre-commit` (gitleaks on staged content, the path checks, the block on
>   direct commits to `main`) is the **only** automated check. That makes
>   `git config core.hooksPath .githooks` **required, not optional**. A clone without
>   it has no gate at all.
>
> Once Actions runs again, confirm a green run on `main` and then remove this note.

Backend (the venv lives at the repository **root**, not in `backend/`):

```bash
py -3.12 -m venv .venv                   # Windows (or the full path to a 3.12 python)
python3.12 -m venv .venv                 # macOS / Linux
.venv\Scripts\activate                   # Windows   |   source .venv/bin/activate
pip install -r backend/requirements.txt
pip install ruff==0.16.6
python scripts/fetch_models.py           # the embedder, reranker and OCR weights (~179 MB, needs network)
python scripts/fetch_models.py --verify-only
```

Frontend:

```bash
cd frontend
npm ci
npx tsc -b
npm run test
cd ..
```

---

## 4. Configuration: `backend/.env`

Not in the clone. Create it from the example, then set values locally. **Never commit
it, paste it or log it.**

```bash
copy backend\.env.example backend\.env   # Windows   |   cp backend/.env.example backend/.env
```

Variable **names** in `backend/.env.example`:

- **server and model:** `HOST`, `PORT`, `ANSWER_MODEL`, `OLLAMA_URL`
- **remote model (commented out, off):** `ANSWER_MODEL_ALLOW_REMOTE_HOST`, `ANSWER_MODEL_ALLOWED_HOSTS`
- **offline:** `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`
- **access:** `AUTH_MODE`, `AUTH_SECRET`, `AUTH_TOKEN_SECONDS`, `AUTH_MAX_ATTEMPTS`, `AUTH_LOCKOUT_SECONDS`
- **external lanes (all off by default, two flags each):** `MARKET_LIVE_ENABLED`, `MARKET_ALLOW_PUBLIC_EGRESS`, `STANDARDS_READER_ENABLED`, `STANDARDS_READER_ALLOW_PUBLIC_EGRESS`, `ANTHROPIC_API_KEY`
- **watch folder:** `WATCH_FOLDER`, `WATCH_INTERVAL_SECONDS`, `WATCH_OWNER_EMAIL`

`AUTH_SECRET` must be at least 32 characters for `AUTH_MODE=demo_required`. Generate one
locally (`python -c "import secrets; print(secrets.token_urlsafe(48))"`). Leave every
egress flag `false` and `ANTHROPIC_API_KEY` empty unless the owner authorises that lane.

---

## 5. Expected test results: two figures, because of B28

Run from `backend/`: `python -m pytest -q --no-header -p no:cacheprovider`

**16 committed tests need `AUTH_SECRET` in `backend/.env`** (`test_admin_db_routes` x13,
`test_review_code` x3). This is bug **B28**. So the count depends on whether `.env` is
configured:

| State | Failed | Passed | Skipped | Deselected | xfailed |
|---|---|---|---|---|---|
| Fresh clone, **no** `backend/.env` | **26** | 2,850 | 27 | 1 | 18 |
| `backend/.env` configured with an `AUTH_SECRET` | **10** | 2,866 | 27 | 1 | 18 |

Both were measured on `main` at `09abc5d`, 2026-09-21:
- **Fresh clone:** `git archive` of `main`, no `.env` - **26 failed / 2,850 passed**.
- **Configured `.env`:** the laptop checkout, run as **11 failed / 2,865 passed**. The
  11th was `test_backup_db::test_two_backups_in_the_same_second_never_overwrite_each_other`.
  It is intermittent (B30: two backups can get the same microsecond timestamp on Windows)
  and passed 5 of 5 when rerun alone. So expect **10**, or **11** when B30 trips.

The difference between the two rows is exactly the 16 B28 tests. The 10 that fail
either way are known and registered:
- `test_claude_api` x5: the Claude router is deliberately not registered (B5);
- `test_analysis_routes` x4 (B7);
- `test_extraction_quality` x1 (B6).

A different count is a finding: compare the failures **by name**, not by total.

> Earlier records give **21 failed / 2,860 passed**. That figure was measured on a working
> tree that still carried uncommitted CRS work, so it is **not** reproducible from any
> commit. Do not use it as the reference.

---

## 6. What does NOT come from Git: hand-carry these

Copy these from laptop ABUBAKAR (`D:\project\Rag_chatbot\`) by direct copy: USB or a
private share. Never commit them, attach them to an issue or upload them anywhere.

### 6.1 The 39 `.cowork` evidence files (into `.cowork/`, same names)

**`CURRENT_STATE_AND_BLOCKERS.md` above all.** It is the live status, the bug register
and the checkpoint log.

Top level (19):
`CURRENT_STATE_AND_BLOCKERS.md`, `AI_SUBMITTAL_REVIEW_SYSTEM_AUDIT_AND_NORTH_STAR_V3.md`,
`ADDENDUM-GAP-ANALYSIS.md`, `B24-B23-PREFLIGHT.md`, `DIAGNOSTIC-OUTPUT-FORMAT.md`,
`EXECUTE-CEILING-TEST-QWEN3-5-27B.md`, `EXECUTE-CLEAN-BOOT-4B-FAIR-TEST.md`,
`EXECUTE-LAPTOP-MODEL-UPGRADE.md`, `EXECUTE-MODEL-BENCHMARK-QWEN3-5-9B.md`,
`EXECUTE-MODEL-BENCHMARK-QWEN3-8B.md`, `EXECUTE-NEXT.md`,
`EXECUTE-OUTPUT-FORMAT-DIAGNOSTIC.md`, `EXECUTE-PHASE-0.5-RUN.md`, `EXECUTE-PHASE-0.5.md`,
`PHASE-0.5-GATE-RESULTS.md`, `PHASE-0.5-PREPARATION.md`, `PHASE-0.5-RUN-RECORD.md`,
`PROMPT-PHASE-0.md`, `STEP-2-M03-CAUSE-AND-ORDER.md`

`diagnostic-output-format-artifacts/` (9):
`expectation.txt`, `manifest_diag.json`, `output_D1.txt`, `output_D2.txt`,
`prompt_diag.txt`, `run_D1.json`, `run_D2.json`, `thinking_D1.txt`, `thinking_D2.txt`

`phase-0.5-artifacts/` (11), which are **frozen**; do not edit them:
`FROZEN.txt`, `FROZEN_v2.txt`, `manifest.json`, `manifest_v2.json`, `manifest_v3.json`,
`model_output_v3.txt`, `model_thinking_v2.txt`, `prompt.txt`,
`run_record_v1_inconclusive.json`, `run_record_v2.json`, `run_record_v3.json`

The repository `.gitignore` ignores `.cowork/*` except the ten tracked policy files, so
these cannot be committed by accident once copied in. After copying, the
NORTH-STAR check in section 0 must still pass.

### 6.2 The database, as a reference copy only

`backend/data/rag_intelligence.sqlite` is **WAL mode: three files**:
`rag_intelligence.sqlite`, `rag_intelligence.sqlite-wal`, `rag_intelligence.sqlite-shm`.
Stop the backend before copying, and copy all three together; copying only the first
loses data.

Store the copy **OUTSIDE `backend/data/`**, for example `D:\reference\rag_intelligence\`.
It is a reference for comparison, not the new machine's live database. The new machine
builds its own by re-ingesting (6.3).

### 6.3 The source PDFs, then re-ingest

The uploaded PDFs are in `backend/data/uploads/` (hash-named) on the laptop. Copy them,
then upload/ingest them on the new machine so that its database, vectors and page images
are built there.

### 6.4 `doc02.pdf` is UNIDENTIFIED

**Do not copy, move or ingest `doc02.pdf`.** The owner is identifying it.

---

## 7. First checks on the new machine

1. NORTH-STAR hash matches (section 0), and all five canonical files are present.
2. `git config --get core.hooksPath` prints `.githooks`.
3. Backend suite matches one of the two rows in section 5, **by failure name**.
4. `cd backend && python run.py`, then `GET http://127.0.0.1:8000/api/health` returns 200.
5. `cd frontend && npm run dev` serves `http://127.0.0.1:5173/`.

---

## 8. Next task: B19

**`datasheets.extract_facts` has no caller anywhere in `backend/app`.** Until it is
wired, a newly uploaded datasheet produces **zero facts and so zero findings**. This
decides whether the demo workflow works end to end. The detail is in
`.cowork/STEP-2-M03-CAUSE-AND-ORDER.md` (hand-carried) and the bug register.
