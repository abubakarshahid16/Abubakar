# SETUP - moving this project to a new machine

> **VERIFIED ON THE SOURCE LAPTOP ONLY - NOT YET ON A DIFFERENT MACHINE.**
> On 2026-09-21 this guide was followed from a genuinely fresh `git clone` into an empty
> folder on laptop ABUBAKAR. Sections 0 to 5 and 7 worked, and the fresh-clone test figure
> matched exactly, by failure name. Every gap found was fixed in this file.
>
> **What that walkthrough cannot prove:**
> - that it works on a **different machine**: same laptop, so the same Windows, the same
>   Python 3.12.10 and Node 24.18.0, warm pip/npm caches, gitleaks and Ollama already
>   installed;
> - **section 6** (hand-carry and re-ingest), which was deliberately not exercised;
> - the **configured-`.env`** figure from a clone, which was measured only on the laptop
>   checkout.
>
> The first person to use this on the new machine should correct every step that fails
> here.

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
not deleted. You may still install and test (sections 2 to 5) without them. But **STOP
before any project work**, meaning any change, review or decision, until you have the copy
(section 6). Never substitute a similar file.

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
| `docs/ci-billing-block`, `docs/setup-clone-test-fixes` | Carried SETUP.md updates into `main` (merged). History only. **Any `docs/*` branch in this repository is a merged carrier of documentation changes**, because the hook blocks direct commits to `main`; later ones may not be listed individually. |
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
| gitleaks | 8.x (8.30.1 verified) | the pre-commit hook **blocks** commits without it. Download the release binary from <https://github.com/gitleaks/gitleaks/releases>. The hook looks for it on `PATH`, then at `%LOCALAPPDATA%\gitleaks\gitleaks.exe` (Windows), `~/.local/bin/gitleaks`, `/usr/local/bin/gitleaks` and `/opt/homebrew/bin/gitleaks`, or wherever `GITLEAKS_PATH` points |
| ruff | `0.16.6` | **The only unpinned DIRECT dependency.** It is not in `requirements.txt`; CI installs it separately. Install by hand for local linting: `pip install ruff==0.16.6` |
| RAM | 16 GB minimum; the laptop is at exhaustion (B26) | the new machine has 48 GB |
| Disk | **1.4 GB inside the clone**, measured 2026-09-21 (`.venv` 833 MB, models 171 MB, `node_modules` 169 MB, `.git` 71 MB), plus **~3.4 GB** for the Ollama model outside it | README's older "773 MB" figure is stale |
| Free ports | `8000` (backend) and `5173` (frontend) on `127.0.0.1` | see section 7 if either is taken |

> **Transitive dependencies are NOT pinned.** `requirements.txt` pins the 30 direct
> packages; what they pull in resolves to whatever is newest on the day. On the
> 2026-09-21 fresh clone, **12 transitive packages differed** from the laptop's venv,
> including two major-version jumps: `starlette` 0.49.3 -> **1.6.0** and `filelock`
> 3.32.5 -> **4.0.1**. The test result was identical, by name, but the environment is not
> byte-reproducible. If a failure appears that the laptop does not show, compare
> `pip freeze` first. A lock or constraints file would close this; none exists yet.

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

**Find a Python 3.12 first.** The `py` launcher is often **not installed** on Windows; it
was not on the machine this guide was tested on, and `py -3.12` failed with "not
recognized". Check what you have:

```powershell
py -3.12 --version                       # works only if the launcher is installed
where.exe python                         # lists every python.exe on PATH
python --version                         # must say 3.12.x
```

If none reports 3.12, install Python 3.12 from <https://www.python.org/downloads/> and use
its full path (for a per-user install, typically
`%LOCALAPPDATA%\Programs\Python\Python312\python.exe`).

```bash
py -3.12 -m venv .venv                   # Windows, if the launcher exists
<full path to python 3.12> -m venv .venv # Windows otherwise, e.g. ...\Python312\python.exe
python3.12 -m venv .venv                 # macOS / Linux
.venv\Scripts\activate                   # Windows   |   source .venv/bin/activate
pip install -r backend/requirements.txt
pip install ruff==0.16.6
python scripts/fetch_models.py           # the embedder, reranker and OCR weights (~179 MB, needs network)
python scripts/fetch_models.py --verify-only
```

Activation lasts only for that terminal; activate again in every new one. If PowerShell
refuses to run `Activate.ps1`, skip activation and call the venv's interpreter directly,
e.g. `.venv\Scripts\python.exe -m pip install ...`. **In Windows PowerShell 5.1, pip's
"new release available" notice is printed in red as `NativeCommandError`. That is not a
failure;** check the exit code or the last line (`Successfully installed ...`).

Frontend:

```bash
cd frontend
npm ci
npx tsc -b
npm run test      # expect: 63 test files, 695 tests passed (measured 2026-09-21)
cd ..
```

`npx tsc -b` prints nothing and finishes in about a second (TypeScript 7 is the native
compiler); silence with exit code 0 is success. README's "496 tests across 42 files" is
stale.

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

A different count is a finding: compare the failures **by name**, not by total. The 26
expected on a fresh clone, all in `backend/tests/`:

- `test_admin_db_routes.py` (13, **B28**, pass once `AUTH_SECRET` is set):
  - `test_a_page_of_rows_states_the_whole_table_as_its_denominator`
  - `test_a_real_admin_is_let_through[...]` x3 (`/tables`, `/tables/users`, `/tables/users/rows`)
  - `test_a_real_non_admin_with_a_real_token_gets_the_silent_404[...]` x3 (same three paths)
  - `test_an_unknown_table_is_not_found_rather_than_an_error`
  - `test_the_column_name_is_never_hidden`
  - `test_the_real_password_hash_never_reaches_the_wire`
  - `test_the_row_cap_holds_however_loudly_it_is_asked`
  - `test_the_table_list_carries_row_counts`
  - `test_unmasked_columns_in_the_same_row_are_untouched`
- `test_review_code.py` (3, **B28**):
  - `test_an_engineer_cannot_decide_a_run_they_may_not_read`
  - `test_an_engineer_who_is_not_an_admin_can_record_the_final_code`
  - `test_the_route_still_refuses_an_override_with_no_reason`
- `test_claude_api.py` (5, **B5**):
  - `test_the_four_routes_are_registered`
  - `test_an_unknown_run_is_404_before_the_model_is_asked[...]` x4 (`select-standards`, `read-datasheet`, `recheck`, `crs-draft`)
- `test_analysis_routes.py` (4, **B7**):
  - `test_a_sentence_whose_number_is_in_no_cited_span_is_dropped_not_flagged`
  - `test_an_uncited_sentence_never_reaches_the_prose`
  - `test_an_unreachable_model_is_503_and_not_a_crash`
  - `test_confidence_is_never_high_and_names_the_checks_that_fired`
- `test_extraction_quality.py` (1, **B6**):
  - `test_a_sentence_with_no_comparator_has_no_subject`

**Reproduced from a genuinely fresh clone on 2026-09-21:** 26 failed / 2,850 passed / 27
skipped / 1 deselected / 18 xfailed in 10 m 43 s, the same 26 names. Warnings seen:
PyMuPDF's `fitz` deprecation (B25), and on a fresh install a Starlette deprecation about
`httpx`, which comes from the unpinned transitive `starlette` 1.6.0 (section 2).

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

The uploaded PDFs are in `backend/data/uploads/` on the laptop. Copy them, then ingest
them on the new machine so that its database, vectors and page images are built there:
upload them through the UI (README, *Getting started* step 6), or use the watched folder.
**The watched folder needs an owner first:** it ingests nothing unless `WATCH_FOLDER` is
set **and** `WATCH_OWNER_EMAIL` names an existing, active user who holds a discipline role
(`backend/app/watcher.py`, `OWNER_UNSET`). A fresh database has no users, so create that
user before relying on it. Without an owner, an ingested document would be readable by
nobody.

> **Open question for the owner, not answered here:** the stored files are named by
> content hash (e.g. `0048d7e4...c45.pdf`), not by their original names. Uploaded as they
> are, they would appear under those hash names. The original names are in the reference
> database (6.2). How to restore them before re-ingesting is **not yet defined**, so decide
> that before ingesting anything.

### 6.4 `doc02.pdf` is UNIDENTIFIED

**Do not copy, move or ingest `doc02.pdf`.** The owner is identifying it.

---

## 7. First checks on the new machine

1. NORTH-STAR hash matches (section 0). All five canonical files are present **once
   section 6 is done**; straight after the clone, only three are.
2. `git config --get core.hooksPath` prints `.githooks`.
3. Backend suite matches one of the two rows in section 5, **by failure name**.
4. `cd backend && python run.py` (venv active), then `GET http://127.0.0.1:8000/api/health`
   returns 200.
5. `cd frontend && npm run dev` serves `http://127.0.0.1:5173/`.

**What a correct start looks like, with no `.env` and no data** (observed on the fresh
clone):
- the backend logs `WARNING: AUTH_MODE=disabled - every request sees every document ...`.
  That is expected until `.env` sets `AUTH_MODE=demo_required`;
- startup **creates an empty database** at `backend/data/rag_intelligence.sqlite` (about
  0.6 MB), plus empty `uploads/` and `page_images/`;
- `/api/health` returns `{"ok":true,...}`; `/api/documents` and `/api/standards` return
  `[]`; the dashboard is all zeros;
- a question (`/api/answer?q=...`) returns `insufficient_evidence` with no answer text. It
  says "none of the indexed documents mention this topic" even though nothing is indexed;
- **this is a working, empty system.** Nothing is broken until section 6 is done.

**If port 8000 or 5173 is already taken**, for example by another copy of this project on
the same machine:
- The backend starts, then exits with `[Errno 10048] error while attempting to bind on
  address ('127.0.0.1', 8000)`. Choose another port with `PORT=8010` in `backend/.env`,
  or as an environment variable.
- Vite does **not** fail: it prints `Port 5173 is in use, trying another one...` and serves
  on the next free port (e.g. `5174`). Read the URL it prints.
- **The frontend's `/api` proxy still points at `http://127.0.0.1:8000`** (in
  `frontend/vite.config.ts`), whatever is running there. If you moved the backend, start
  the frontend with `VITE_API_TARGET=http://127.0.0.1:8010`. Otherwise the new UI silently
  talks to the **other** instance and its data.

---

## 8. Next task: B19

**`datasheets.extract_facts` has no caller anywhere in `backend/app`.** Until it is
wired, a newly uploaded datasheet produces **zero facts and so zero findings**. This
decides whether the demo workflow works end to end. The detail is in
`.cowork/STEP-2-M03-CAUSE-AND-ORDER.md` (hand-carried) and the bug register.
