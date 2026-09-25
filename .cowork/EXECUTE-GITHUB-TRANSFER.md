# EXECUTION ORDER - commit, push, and stand the project up on the second machine

Authorized by Muhammad Usman, 2026-09-21. Parts 1 to 4 run on laptop ABUBAKAR.
Part 5 runs on the 48 GB machine.

**CORRECTION, 2026-09-21.** An earlier version of this order stated that this was the
project's first push. **That was wrong** - it was inferred from the prohibitions in
earlier orders rather than checked. Part 0 established the truth: the remote already has
10 branches and merged PRs #62 and #138.

What is actually true and narrower: **the last 8 commits and both recovery branches have
never been pushed**, and `main` is **251 commits behind** the working branch.

Treat Part 3 as the gate it is regardless.

## Read first

`.cowork\README-INDEX.md`, `NORTH-STAR.md` (**verify sha256
`3d0505be629a99631e8cbcc0681134c642b7a00ae962a5c9f5ebf9df43499619`**, 9 sections,
checklist at section 8 - **STOP if it differs**), `CURRENT_STATE_AND_BLOCKERS.md`
sections 11, 13, 14 and the checkpoint log, `EXECUTE-COMMIT-B24-B23.md`.

---

# PART 0 - Full repository audit. Measure before touching anything.

The owner's requirement: **a clone on another machine must be a complete, working
starting point, with no guessing about which branch is current.** That is a higher bar
than "the code is pushed". Establish the truth first.

## 0.1 Every branch, local and remote, with its position

    git branch -vv --all
    git for-each-ref --sort=-committerdate refs/heads refs/remotes --format="%(refname:short) %(committerdate:iso8601) %(objectname:short) %(upstream:track)"
    git log --oneline --graph --all --decorate -30

**Report every branch, its last commit date, and whether it is ahead or behind.**
Known from the record: `feat/phase-1-ui-reaches-backend` (the working branch),
`recovery/phase0-head`, `recovery/phase0-stash`.

## 0.2 What is `main`, and how far behind is it?

    git log --oneline main -5
    git rev-list --left-right --count main...feat/phase-1-ui-reaches-backend

**This is the question the owner asked.** If `main` is far behind the working branch,
a clone defaults to `main` and gives whoever clones it an old, possibly broken project.
**Report the two counts. Do not merge anything yet.**

## 0.3 Anything not in a commit

    git status --porcelain=v1 -b
    git stash list
    git worktree list
    git ls-files --others --exclude-standard

**Every untracked file must be named and dispositioned** - committed, ignored, or
deleted with a stated reason. Nothing may be left in limbo. B15 recorded 4,837 lines
sitting untracked; that must not recur.

Specifically account for:

- `.audit_tmp_step4\` - a temporary audit folder. Say what it is and whether it should
  be removed or ignored
- `test.pdf` at the repository root, 5,437 bytes - ignored by `*.pdf`, but say whether
  it is needed at all
- `data\test-corpus\` - **4 PDFs, 15 MB.** Ignored by `*.pdf`. **Confirm these are not in
  history** (Part 3.2 covers it) and state whether they are client documents or test
  material

## 0.4 Does the repository contain what a new machine needs to build?

Confirm each is present and current, and name the ones that are missing:

- `requirements.txt` or equivalent, matching the installed environment
- `frontend/package.json` **and its lockfile**
- `.env.example` covering every variable `backend/.env` actually sets, **names only**
- `.python-version`, `ruff.toml`, `.gitattributes`, `.githooks`, `.github` workflows
- `README.md` - **does it actually describe how to set the project up from a clone?**

**Report Part 0 in full before proceeding.**

---

# PART 0.5 - Re-baseline the environment. Owner decision, 2026-09-21.

Part 0 found **8 of 30 pins in `backend/requirements.txt` newer than the installed
venv** - fastapi 0.141.1 vs 0.120.4, numpy 2.5.3 vs 2.3.4, onnxruntime 1.29.0 vs 1.24.1,
psutil 7.2.2 vs 7.1.3 and four others. These look like merged dependabot bumps that never
reached the local environment. **PR #138 merged a psutil bump that was never tested
locally, and it is already in `main`.**

So the 2,860-pass baseline was measured against an environment **nobody can reproduce
from this repository.**

**Owner decision: re-baseline before pushing.**

1. Reinstall the venv to the **pinned** versions
2. Run the full suite: `cd backend && python -m pytest -q --no-header -p no:cacheprovider`
3. **Report the new pass/fail/skip counts against the 2,860 baseline, and every new
   failure by name**

A new failure here is a **finding, not an obstacle** - it is an untested dependency bump
already sitting in `main`. Report it. **Do not fix it in this task and do not change a
pin to make a test pass.**

The re-baselined number is what goes into `SETUP.md` as the expected count. An
unverifiable expected count is worse than none, because a difference on the new machine
then reads as ambiguous between environment and real regression.

---

# PART 1 - Commit B24 and B23

## The ordering question, decided

Part 0 found that `comparison.py` mixes the B24 work with the in-flight `match_rules`
integration, and that **`test_match_rules.py` is already committed and failing 6 tests
without it.**

That is not optional in-flight work. It is a **committed dependency in a broken state**.

**Owner decision, 2026-09-21: land the matcher integration first, then B24/B23 on top.**
Committing B24 while six already-committed tests fail would push a repository that does
not pass its own suite.

Commit the matcher integration as its own commit, with its own message, stating that it
repairs 6 already-committed failing tests. **Then** execute
`.cowork\EXECUTE-COMMIT-B24-B23.md` in full - checks A to D, the test counts, the
mutation results, precise staging, the commit, and the activation-point record.

**Do not push in that task.** Come back here.

If any check in that order cannot be answered, stop. Do not push uncommitted safety work
you could not explain.

---

# PART 2 - Decide the CRS lane. Do not leave it dangling.

`crs_export.py`, `crs_mapping.py`, `test_crs_export.py`, `test_crs_mapping.py` and
`contracts/types.ts` are in-flight with **13 failing tests** (B3, B4).

Uncommitted work that exists only on one laptop is exactly the preservation risk B15
recorded. But it must not land on the main line failing.

**Commit it to its own branch**, for example `wip/crs-export-b3-b4`, with a message that
states plainly: 13 tests failing, B3 and B4 open, not merge-ready. Push that branch too.

**Do not merge it. Do not fix the tests in this task.**

If anything else is uncommitted, list it and say what you did with it. **Nothing may be
left untracked at the end of this order.**

---

# PART 3 - PRE-PUSH SAFETY GATE. Do not skip any item.

Your `.gitignore` is good. That protects **new** commits. It does not protect **history**.
If a client PDF, the database or a secret was ever committed before the ignore rules
existed, it is still in history and pushing publishes it.

Answer all six. **Any failure stops the push.**

## 3.1 Is the remote repository private?

    git remote -v

Then confirm the repository's visibility on GitHub. **If it is public, STOP and report.**
This project holds work derived from Saudi Aramco standards and the client's contractor documents.

## 3.2 Does history contain anything that must never leave?

    git log --all --numstat --format="%H" | Select-String -Pattern "\.pdf$|\.sqlite|\.db$|\.gguf$|\.onnx$|\.env$"

Also:

    git log --all --diff-filter=A --name-only --format="" | Sort-Object -Unique |
      Select-String -Pattern "\.pdf$|\.sqlite|\.db$|\.gguf|\.onnx|^backend/data/|^uploads/|\.env$"

**Report every hit.** Synthetic CI fixtures under `tests/fixtures/synthetic/` are the only
permitted PDFs. Anything else is a stop.

## 3.3 Secret scan over the whole history, not just the last commit

The gitleaks pre-commit hook scans what is being committed. Run it over **all history**:

    gitleaks detect --source . --log-opts="--all" --report-path gitleaks-full-history.json

**Report the finding count.** Non-zero is a stop, and the remedy is not "push anyway".

## 3.4 What is actually tracked right now?

    git ls-files | Measure-Object -Line
    git ls-files | Select-String -Pattern "\.pdf$|\.sqlite|\.db$|\.env$|^backend/data/|^uploads/"

Expect zero hits outside the synthetic fixtures.

## 3.5 The project memory - SUPERSEDED, read this version

**CORRECTION, 2026-09-21.** An earlier version of this item required every `.cowork` file
to be tracked in Git. **That was wrong.** It cited the `.gitignore` header's paraphrase
instead of the source rule.

The governing rule is **instruction 6 in §0 of `RAG-INTELLIGENCE-POC-EXECUTION.md`**:

> "Never put client PDFs, extracted text, SQLite files, vectors, generated reports,
> secrets, user data, prompts or answers in Git…"

**§3.1 extends this to document filenames and hashes.** Part 0 found that **44 of 48**
`.cowork` files carry such content, including two of the five canonical files.

### What the rule is actually telling you

The project memory mixes two kinds of content:

| Kind | Examples | Destination |
|---|---|---|
| **Policy and plan** | NORTH-STAR, README-INDEX, the client addendum, execution orders | **Git** |
| **Evidence** | Client document names and hashes, extracted text, prompts, model answers, DB row ids | **Direct copy only** |

That is a structural observation worth acting on later. **Do not refactor it now.**

### Owner decisions, 2026-09-21

- **Commit the 9 Git-safe files.**
- **Direct-copy the 36 evidence files.**
- **The 3 files naming the pressure-vessel submittal number** - V3, `ADDENDUM-GAP-ANALYSIS.md`, `B24-B23-PREFLIGHT.md`
  - **direct-copy, do not redact.** §3.1 names filenames specifically, so redaction is a
  thin fix that also degrades the records.

### Required, and easy to forget

**Update `README-INDEX.md` to state plainly which canonical files arrive by direct copy
rather than by clone.** Otherwise a fresh clone carries an index pointing at files that
are not there, and the next person concludes they are missing rather than transported
separately. Name the transport beside each file.

Record the split, and the structural reason for it, in `CURRENT_STATE_AND_BLOCKERS.md`
as work for later.

    git ls-files .cowork/

Report what is tracked now, and confirm the 9 land and the 39 do not.

## 3.6 Repository size

    git count-objects -vH

Report `size-pack`. Anything unexpectedly large suggests a binary got in.

---

# PART 4 - Push, and make the default branch tell the truth

Only after all six items in Part 3 pass.

## 4.1 Push everything

    git push origin <current working branch>
    git push origin wip/crs-export-b3-b4
    git push origin recovery/phase0-head
    git push origin recovery/phase0-stash

The recovery branches were created in checkpoint row 2 and currently exist **only on this
laptop**. Getting them off it is half the point of this order.

**No force. No rebase. No squash. No history rewriting of any kind.**

## 4.2 Settle the branch question. This is what the owner asked for.

Someone cloning this repository gets the **default branch**. If that is a stale `main`,
they get a stale project and will not know it.

Using the Part 0.2 counts, do **one** of these and say which, and why:

- **If `main` is behind and the working branch is good:** merge the working branch into
  `main` with `--no-ff` so the history stays legible, push `main`, and leave the working
  branch in place. **Run the full test suite on `main` after merging and report the
  counts.** Do not merge `wip/crs-export-b3-b4` - it has 13 failing tests
- **If merging is not safe right now:** leave `main` alone and **change the repository's
  default branch on GitHub** to the working branch, so a clone lands on current work
- **Never** force `main` to a different commit

**Report the decision, the reasoning, and the post-change test counts.**

## 4.3 Prove the branch story is unambiguous

    git branch -vv --all
    git symbolic-ref refs/remotes/origin/HEAD

Report the default branch, every remote branch, and **one plain sentence per branch
saying what it is for.** That sentence goes into `SETUP.md` in Part 5.6.

A repository where somebody has to guess which branch is current has not met this
order's requirement.

---

# PART 5 - Stand it up on the 48 GB machine

## 5.1 Clone and verify

    git clone <url>
    git log --oneline -5
    git status

Confirm the commit hash matches the laptop's.

**Immediately verify the project memory arrived:**

    certutil -hashfile .cowork\NORTH-STAR.md SHA256

Expect `3d0505be629a99631e8cbcc0681134c642b7a00ae962a5c9f5ebf9df43499619`.
**If it differs, stop.** Confirm all five canonical files and the EXECUTE files are
present.

## 5.2 What did NOT come with the clone - expect this, do not treat it as a fault

| Missing | Why | Size |
|---|---|---|
| `backend/data/rag_intelligence.sqlite` | `.gitignore` - correct | 186 MB |
| All source PDFs - 272 standards, 3 submittals | `.gitignore` - correct | large |
| `uploads/` | `.gitignore` - correct | - |
| `backend/.env` | `.gitignore` - correct, **secrets** | small |
| Ollama models | Not in git | 2.7 + 3.4 GB |
| `.venv`, `node_modules` | Not in git | - |

**The clone is code and plan only. It cannot run a review until data is moved.**

## 5.3 Move the data out of band. Not through GitHub.

**Owner decision, 2026-09-21: direct copy of the source PDFs, then re-ingest on the new
machine.** EXECUTION.md section 6 stands unchanged - *"no client PDFs, extracted text,
embeddings, chats, model weights, secrets, or production metrics may ever enter Git."*
Nothing below goes into the repository.

### 5.3.1 `.env`

Recreate from `.env.example` on the new machine. **Do not copy secrets through any
channel that logs them.** Record which variable **names** were set, never their values.

### 5.3.2 Source documents - the primary transfer

Copy the PDFs directly - USB or a network share the client's IT permits, not cloud storage.
These are controlled client documents.

Record the **file count and total size** on both sides and confirm they match.

### 5.3.3 Re-ingest, and treat it as a real test

Run ingestion on the new machine. **Nobody has ever run this pipeline on a clean
install.** If it is broken, finding out now is worth more than a fast transfer.

Compare against the laptop and report every difference:

- document count - the laptop has **275** (272 `COMPANY_STANDARD` + 3 submittals)
- chunk counts
- extracted requirement counts by `requirement_type`
- `submittal_facts` counts

### 5.3.4 Expect these differences. They are not transfer failures.

| What will differ | Why |
|---|---|
| `submittal_facts` may be **zero** for re-ingested documents | **B19** - `extract_facts` has no caller. M-03 proved it: 29 chunks, 0 facts |
| The 20,288 historical `review_findings` will be absent | They belong to past runs, not to the documents |
| Row ids, including fact row `75aa9cba…`, will be new | Generated at ingestion |
| `equipment_type`, `service`, `project` still NULL | **B9** - unchanged by re-ingestion |

**Do not "fix" any of these in this task.** Report them. A zero-fact result on the new
machine is B19 confirming itself on clean ground, which is useful evidence.

### 5.3.5 Also copy the existing database, as a reference copy only

The frozen Phase 0.5 packet resolves against fact row `75aa9cba…` in the **current**
database. Re-ingestion will not reproduce that id, which would strand every model test.

So copy `rag_intelligence.sqlite` directly as well, with the backend **stopped** on the
source. Verify with `PRAGMA integrity_check` on arrival. **Store it outside
`backend/data/` as a clearly named reference copy** - not as the live database, and not
in the repository.

This keeps the frozen packet resolvable and keeps the re-ingested database honest. Both,
separately.

### 5.3.6 Models

`ollama pull qwen3.5:4b` on the new machine. Models are not copied.

## 5.4 Build and verify

    python -m venv .venv ; .venv\Scripts\pip install -r requirements.txt
    npm install
    cd backend ; python -m pytest -q --no-header -p no:cacheprovider

**Report the pass/fail/skip counts and compare them against the laptop's baseline.** A
different count on the same commit is a finding, not noise - it usually means an
environment difference that will bite later.

Then start both services and confirm `GET /api/health` returns 200.

## 5.5 Record the machine

Measure and record, same as row 30 did for the laptop: total RAM, available RAM idle,
page file in use, top processes, free disk. **This is the number that decides whether the
model work moves here.**

## 5.6 Write `SETUP.md` at the repository root - the deliverable of this order

The owner's actual requirement: **start working from another system easily.** A pushed
repository does not achieve that on its own. Write `SETUP.md` covering, in order:

1. **Which branch to use, and what every other branch is for.** One line each, from
   Part 4.3
2. **Prerequisites with versions** - Python (from `.python-version`), Node, Ollama
3. **Clone and install**, the exact commands, verified by having just run them
4. **`.env` setup** - from `.env.example`, **variable names only, never values**, and
   where to obtain each
5. **The data that does not come from git** - the database, the source documents, the
   models - with the exact copy steps from 5.3 and where each file belongs
6. **How to verify the setup worked** - the test command, the expected pass/fail/skip
   counts, and `GET /api/health` returning 200
7. **Read the project memory first** - the five canonical `.cowork` files in authority
   order, with the NORTH-STAR hash to verify
8. **What to work on next** - pointing at CURRENT_STATE section 7

**Every command in `SETUP.md` must be one you actually ran in Part 5.** Do not write
instructions you have not executed. An untested setup guide is worse than none, because
it is trusted.

Commit `SETUP.md` and push it.

## 5.7 Prove it from scratch

Delete the clone, clone again into a clean directory, and follow `SETUP.md` exactly as
written, without using knowledge from this session.

**Report anything in it that was wrong, missing or ambiguous, and fix it.** This step is
the only real proof the requirement is met.

---

# PART 6 - Fix the index, and record

## 6.1 README-INDEX has fallen behind and must be corrected

Six EXECUTE files were written today and **none were added to section 3** of
`.cowork\README-INDEX.md`, which its own rule requires. An unlisted file in that folder
will eventually be mistaken for a rule.

Add to section 3, each with one line saying what it is:

- `EXECUTE-COMMIT-B24-B23.md`
- `EXECUTE-GITHUB-TRANSFER.md` (this file)
- `EXECUTE-RAM-OPTIMISATION.md`
- `EXECUTE-CLEAN-BOOT-4B-FAIR-TEST.md`
- `EXECUTE-LAPTOP-MODEL-UPGRADE.md`
- `EXECUTE-CEILING-TEST-QWEN3-5-27B.md`
- `EXECUTE-MODEL-BENCHMARK-QWEN3-5-9B.md` - **mark superseded**
- `EXECUTE-MODEL-BENCHMARK-QWEN3-8B.md` - **duplicate of the above, delete it**
- `LAPTOP-MODEL-UPGRADE-9B.md`

**Change only `README-INDEX.md` in this step**, and show that only it changed.

## 6.2 Record

Checkpoint rows in `CURRENT_STATE_AND_BLOCKERS.md` section 10, continuing from row 30:
one per part. Record the push as the project's first, with the safety-gate results.

---

# THE PLAN, carried with the code

Record this in `CURRENT_STATE_AND_BLOCKERS.md` section 7 so it travels with the repo.
**Estimates are estimates and labelled as such.**

## Needs no model. Do this first, on either machine.

| # | Task | Estimate |
|---|---|---|
| 1 | Commit B24/B23 | 1 hour |
| 2 | **B19 - wire `datasheets.extract_facts`; it has no caller, so new uploads yield zero findings** | 1-2 days |
| 3 | Validate B19 on M-03 (29 chunks, 0 facts today) | 0.5 day |
| 4 | B3/B4 CRS export - 13 failing tests | 1.5-2 days |
| 5 | B7 analysis routes - 4 failures, cause unknown | 0.5-1 day |

**Subtotal 4 to 6 working days. This is the demo path.**

## Blocked on someone other than the developer

| # | Task | Blocker |
|---|---|---|
| 6 | B9 - `equipment_type`, `service`, `project` NULL on all 275 documents, killing 4 of 6 selection routes | Needs a discipline engineer to define the taxonomy |
| 7 | Blind test - engineer writes expected findings before seeing the system | 0.5 day of engineer time |

## Model and hardware - not on the demo path

| # | Task | Status |
|---|---|---|
| 8 | RAM optimisation and inference mode | Order written |
| 9 | Clean-boot fair test of `qwen3.5:4b` | Order written. Never had a fair run |
| 10 | 27b ceiling test on the 48 GB machine | Order written. **Procurement input, not a demo dependency** |

## Open owner decisions

- NORTH-STAR section 9 approval, and the V3 hash pinning. Not recorded
- **B11 contradiction**: checkpoint row 17 closes it "mechanism isolated"; section 12.2
  says it "stays OPEN with no known cause". **Reconcile these**
- Scope: HAZOP, FEED simulation and letters are three separate products, outside the V3
  19.1 cut line

---

# PROHIBITIONS

- **No force push, rebase, squash or history rewrite.** Ever
- **No pushing if any Part 3 item fails**
- **No secrets through any logged channel**
- **No client documents to GitHub or cloud storage**
- No merging the CRS branch. No fixing its 13 tests here
- No production model change. No cloud API, no Claude
- Do not start B19 or the CRS work in this task

# REPORT

- **Part 0**: every branch with its position, how far `main` is behind, every untracked
  file and its disposition, and which build files are missing
- **Part 3**: all six safety results with their numbers
- **Part 4**: the push output, the branch decision with reasoning, the default branch,
  and the post-merge test counts if a merge was done
- **Part 5**: clone verification including the NORTH-STAR hash, the second machine's test
  counts against the laptop baseline, its RAM measurements, and **what the from-scratch
  `SETUP.md` walkthrough got wrong**
- **Part 6**: confirmation that README-INDEX lists every file in the folder

## The one question this order has to answer

**Can someone clone this repository on a fresh machine, follow `SETUP.md`, and reach a
working system without asking anyone anything?**

Answer it yes or no, with the evidence from Part 5.7. **A "yes" that was not actually
walked through from a fresh clone is not an answer.**
