# Rename inventory — "Nabaa" → "RAG Intelligence System"

**Read this before you change a single line.** This is a safety brief, not a
checklist of strings. Three of the references below destroy or orphan data if
renamed carelessly, and two of those fail **silently** — no error, no crash,
no failing test.

Scope verified on this working tree (2026-09-06): **93 matching lines across
50 tracked files**, plus 1 untracked file, plus 3 filesystem names. Every
`file:line` below was read and confirmed. Corrections to the prior scan are in
section 8.

The database is real and populated. Measured directly, read-only:

| Table | Rows |
|---|---|
| documents | 12 |
| pages | 3,717 |
| chunks | 7,656 |
| chunk_vectors | 7,187 |
| conversations | 72 |
| messages | 445 |
| reports | 12 |
| stage_runs | 1,483 |

`backend/data/nabaa.sqlite` is 67,334,144 bytes. It is gitignored
(`.gitignore:14` — `backend/data/`). **There is no copy of it in git. If you
lose it, it is gone.**

---

## 1. The three data-loss hazards

### 1a. THE BIG ONE — the database path

**`backend/app/config.py:17`**

```python
db_path: Path = BACKEND_DIR / "data" / "nabaa.sqlite"
```

**What happens if you rename this alone:** nothing visible. SQLite does not
error on a missing file — `sqlite3.connect()` **creates a new empty database**.
The app starts. The API answers. The UI loads. Every one of the 12 documents,
3,717 pages, 7,656 chunks and 7,187 vectors, all 72 conversations, 445 messages
and 12 reports is simply *not there*, and nothing anywhere says so. You will
look at an empty document list and assume a UI bug.

**The sidecars.** SQLite in WAL mode keeps `nabaa.sqlite-wal` and
`nabaa.sqlite-shm` beside the main file. They are named after the main file. If
you move `nabaa.sqlite` and leave the sidecars behind, any transaction still
only in the WAL is lost, and the orphaned `-wal` will not be replayed into the
renamed file. Move all three together, or checkpoint first (below). Neither
sidecar exists on disk right now, which means the database is cleanly closed —
that is the state you want before touching it.

**Safe procedure**

1. Stop the backend and every worker. Confirm nothing holds the file.
2. Back it up first, and verify the backup:
   ```
   sqlite3 backend/data/nabaa.sqlite ".backup backend/data/nabaa.backup.sqlite"
   sqlite3 backend/data/nabaa.backup.sqlite "PRAGMA integrity_check; SELECT count(*) FROM chunks;"
   ```
   Expect `ok` and `7656`.
3. Checkpoint and close cleanly so the sidecars are absorbed:
   ```
   sqlite3 backend/data/nabaa.sqlite "PRAGMA wal_checkpoint(TRUNCATE);"
   ```
4. Move the file **and** any `-wal` / `-shm` that exist, in the same operation.
5. Change `config.py:17` **and all 15 scripts (below) in the same commit.**
6. Verify before declaring success — the app starting is not evidence:
   ```
   sqlite3 backend/data/<new-name>.sqlite "SELECT count(*) FROM documents, (SELECT 1);"
   ```
   Then hit the API and confirm 12 documents, not 0.

**Cheapest safe option: do not rename the file at all.** The database filename
is not user-visible. Renaming it buys nothing and risks everything. If you must,
consider keeping the path and adding a comment.

#### The scripts that hardcode this path

**15 scripts, not 18** (see section 8). Column "Mode" is the dangerous
distinction: a plain `sqlite3.connect()` **creates** a missing file; a
`?mode=ro` URI **fails loudly** with `unable to open database file`.

| Script | Line(s) | Path form | Mode |
|---|---|---|---|
| `scripts/dbstate.py` | 3 | `data/nabaa.sqlite` (relative) | **READ-WRITE** |
| `scripts/pagesample.py` | 3 | `data/nabaa.sqlite` (relative) | **READ-WRITE** |
| `scripts/resetdoc.py` | 3 | `data/nabaa.sqlite` (relative) | **READ-WRITE — mutating** |
| `scripts/bench_extract.py` | 6, 20 | `os.path.join(BACKEND,"data",...)` | read-only (`?mode=ro`) |
| `scripts/chunk_report.py` | 6, 7 | **absolute Windows path** | read-only |
| `scripts/chunk_samples.py` | 6, 7 | `data/nabaa.sqlite` | read-only |
| `scripts/classify_report.py` | 6, 7 | `data/nabaa.sqlite` | read-only |
| `scripts/embed_ab.py` | 28 | `file:data/nabaa.sqlite?mode=ro` | read-only |
| `scripts/embed_bench.py` | 19 | `file:data/nabaa.sqlite?mode=ro` | read-only |
| `scripts/embed_sanity.py` | 47 | `file:data/nabaa.sqlite?mode=ro` | read-only |
| `scripts/killtest.py` | 13, 17 | `os.path.join(BACKEND,"data",...)` | read-only |
| `scripts/padding_report.py` | 13 | `file:data/nabaa.sqlite?mode=ro` | read-only |
| `scripts/quality_matrix.py` | 6 | `file:data/nabaa.sqlite?mode=ro` | read-only |
| `scripts/quality_tune.py` | 7 | `file:data/nabaa.sqlite?mode=ro` | read-only |
| `scripts/textsample.py` | 2, 3 | **absolute Windows path** | read-only |

**The three read-write ones are the trap.** If `config.py` renames the database
and `scripts/resetdoc.py:3` does not, running `resetdoc.py` opens
`data/nabaa.sqlite`, finds nothing, **creates an empty database**, runs its
DELETE / UPDATE against zero rows, exits 0, and prints success. You get a green
run against a database that does not exist. `dbstate.py` and `pagesample.py`
only read, but they open read-write, so they will happily report an empty
corpus as fact and also litter a stray empty `.sqlite` file next to the real one.

**The two absolute Windows paths** — `scripts/chunk_report.py:6` and
`scripts/textsample.py:2` — are `d:\project\Rag_chatbot\backend\data\nabaa.sqlite`.
These break if the repo directory is *also* renamed, independently of the
product rename. Grep for `d:\project` before you move the checkout.

Note also that the relative-path scripts (`data/nabaa.sqlite`) only work when
run with cwd = `backend/`. That is pre-existing fragility, not something the
rename introduces — do not "fix" it in the rename commit.

Test docstrings that name the DB file — harmless prose, but update them so the
next reader is not misled: `backend/tests/conftest.py:89`,
`backend/tests/test_claims.py:41`, `backend/tests/test_market.py:28`.

---

### 1b. The browser theme key — silent preference loss

**`frontend/src/App.tsx:17`**

```typescript
const THEME_KEY = "nabaa-theme";
```

**What happens if you rename it:** every existing user loses their saved theme
the next time they load the app. `localStorage.getItem("ragintel-theme")`
returns `null`, the code falls through to the `"dark"` default, and a user who
chose light mode is silently put back into dark. The old key stays in their
browser forever — nothing ever cleans it up, and no code will ever read it again.

There is no error, no console warning, and no test that can catch this: tests
start from an empty `localStorage`, where old-key and new-key behave identically.

**Safe procedure — pick one:**

*Option A (preferred): leave the key alone.*

```typescript
//: Storage key is deliberately still "nabaa-theme". Renaming it silently
//: discards every existing user's saved theme. The key is not user-visible.
const THEME_KEY = "nabaa-theme";
```

*Option B: migrate with a fallback read.*

```typescript
const THEME_KEY = "ragintel-theme";
const LEGACY_THEME_KEY = "nabaa-theme";

function readTheme(): string | null {
  const v = localStorage.getItem(THEME_KEY) ?? localStorage.getItem(LEGACY_THEME_KEY);
  if (v && !localStorage.getItem(THEME_KEY)) localStorage.setItem(THEME_KEY, v);
  return v;
}
```

What you must **not** do is change the literal and nothing else.

---

### 1c. The log file — the honesty-audit control

**`backend/app/errors.py:87`**

```python
target = (settings.data_dir / "logs" / "nabaa.log").resolve()
```

This is the **only** place a full traceback is ever written. The docstring
immediately above it says so, and `docs/status-honesty-audit.md:471` records it
as the control: responses carry a sanitised `last_error`; the real stack goes to
`backend/data/logs/nabaa.log` and nowhere else.

**What happens if you rename it:** logging starts a fresh, empty file. Every
prior incident, every traceback anyone might need to explain a past failure, is
orphaned under the old name. `.gitignore:67` ignores `logs/`, so **git shows you
nothing** — no diff, no untracked file, no signal that history was cut.

**Safe procedure:** if you rename it, `mv` the existing
`backend/data/logs/nabaa.log` (and any rotated `nabaa.log.1`, `.2`, … — this is
a `RotatingFileHandler`) to the new name in the same operation, then confirm the
new file actually receives a traceback before you consider it done. Or leave it,
which costs nothing.

**Coupled test — see section 3:** `backend/tests/test_no_internal_leaks.py:166`
asserts on this exact path. That test *will* fail if you rename one and not the
other, which is the one piece of good news in this section.

---

## 2. The trap that WEAKENS security

`"nabaa"` appears in a forbidden-weak-password list. Both locations verified:

| Location | What it is |
|---|---|
| `scripts/seed_access.py:71` | The live `FORBIDDEN` set enforced at seed time |
| `docs/design-authentication.md:173` | The design doc describing that rule |

```python
FORBIDDEN = {
    "password", "passw0rd", "demo", "demo1234", "nabaa", "changeme",
    "letmein", "welcome", "aramco", "12345678", "qwerty", "admin",
}
```

**This is the one place where a find-and-replace makes the system less secure.**
The list is not branding. It is a list of the passwords people actually type at
a demo. The old product name will still be typed at a demo — for months, by
everyone who worked on it — and it is a *more* attractive guess after the
rename, not less.

**Correct action: ADD, do not replace.**

```python
FORBIDDEN = {
    "password", "passw0rd", "demo", "demo1234", "nabaa", "changeme",
    "letmein", "welcome", "aramco", "12345678", "qwerty", "admin",
    # New product name. "nabaa" stays: the old name is a guessable
    # password precisely because it was the product name.
    "ragintel", "ragintelligence", "rag",
}
```

Update `docs/design-authentication.md:173` to list both names. Note the doc also
mentions `aramco` and the email local-part — leave those.

---

## 3. Coupled pairs — change together or not at all

Each of these is two places holding the same string. Changing one alone either
breaks a test (recoverable) or silently disables a control (not).

| # | A | B | Failure if split |
|---|---|---|---|
| 1 | `backend/app/main.py:698` — `filename=f"nabaa-report-{report_id}.pdf"` | `backend/tests/test_reports.py:423` — asserts `f"nabaa-report-{rec['id']}.pdf"` in `content-disposition` | **Loud.** Test fails. Also documented at `docs/design-pdf-report.md:232`; update all three. |
| 2 | `backend/tests/test_access_schema.py:224` — fixture inserts `'kanwar@nabaa.local'` | `backend/tests/test_access_schema.py:232` — asserts `actor_username == "kanwar@nabaa.local"` | **Loud.** Same file, 8 lines apart. A careless partial replace inside one file still breaks it visibly. |
| 3 | `backend/app/errors.py:87` — log path `logs/nabaa.log` | `backend/tests/test_no_internal_leaks.py:166` — asserts that path exists and contains `Traceback` | **Loud.** Test fails. See 1c for the data-loss half. |
| 4 | `backend/tests/conftest.py:64` — `os.environ.get("NABAA_MIN_TESTS", MINIMUM_TESTS)` | Any CI job, shell profile or runbook still exporting `NABAA_MIN_TESTS` | **SILENT.** See below. |
| 5 | `backend/app/errors.py:89` — `logging.getLogger("nabaa")` | Any off-repo log-shipping / alerting rule keyed on the logger name | **SILENT.** See below. |

**Pair 4 — `NABAA_MIN_TESTS`.** This env var exists so the test-count guard can
be *proven* to fire (`conftest.py:61`: "A check nobody has watched fail is not a
check"). Rename the variable and anything still exporting the old name is
ignored — `os.environ.get` falls back to `MINIMUM_TESTS` and the guard runs at
its default instead of erroring. The override appears to work while doing
nothing. If you rename it, accept both names during the transition:

```python
return int(os.environ.get("RAGINTEL_MIN_TESTS", os.environ.get("NABAA_MIN_TESTS", MINIMUM_TESTS)))
```

**Pair 5 — `logging.getLogger("nabaa")`.** The logger name is what any external
collector matches on. Nothing in this repo depends on it, so nothing in this
repo will fail. If a log-shipping rule anywhere is keyed on `nabaa`, it stops
matching and the logs quietly stop arriving. Check outside the repo before
changing, or leave it.

---

## 4. Genuinely safe — display strings, metadata, prose

Change these freely. Nothing reads them programmatically.

**Only two lines are actual user-visible application UI:**

| File:line | What the user sees |
|---|---|
| `frontend/src/components/Shell.tsx:156` | Mobile header brand (`md:hidden` header) |
| `frontend/src/components/Shell.tsx:177` | Sidebar brand, above the subtitle "enterprise FEED intelligence" |

**Two more are visible, but not in the app UI** — worth knowing before you call
them cosmetic:

| File:line | Where it surfaces |
|---|---|
| `backend/app/reports.py:422` | Printed in the footer of **every exported PDF**: `Page N of M \| <watermark> \| Nabaa evidence report` |
| `backend/app/main.py:66` | `FastAPI(title="Nabaa")` — no `docs_url` override in `main.py`, so this is the heading on the live `/docs` Swagger page |

**PDF metadata** (embedded in every generated report; visible in a PDF reader's
document-properties dialog, not in the page body):

- `backend/app/reports.py:436` — `"title": "Nabaa evidence report"`
- `backend/app/reports.py:438` — `"creator": "Nabaa"`

**Frontend comments and CSS banners:**

- `frontend/src/index.css:2`
- `frontend/src/index.redesign.css:2` — **untracked file**, `git grep` will not
  find it. Do not rely on `git grep` alone for the frontend.
- `frontend/src/components/analysis/MarketPanel.tsx:9`
- `frontend/src/types/analysis.ts:8`
- `frontend/src/views/AnalysisView.tsx:4`

**Backend comments:** `backend/app/synthesis.py:9`,
`backend/tests/test_synthesis.py:9`

**Docs prose and titles:**

| File:line | Note |
|---|---|
| `README.md:1` | Title heading |
| `README.md:170`, `README.md:171` | `git clone <repo-url> nabaa` / `cd nabaa` — clone-directory example |
| `SECURITY.md:3` | Prose |
| `docs/demo-script.md:1` | Title |
| `docs/frontend-redesign-brief.md:1, :16, :95` | `:95` mandates the product name in the redesign — update it or the redesign ships the old brand |
| `docs/design-frontend-redesign.html:1, :291, :692` | `:692` is a JS string building a `.brand-name` span inside the mock |
| `docs/design-pdf-report.md:232` | Also part of coupled pair 1 |
| `eval/questions.schema.json:3` | `"title": "Nabaa evaluation question set"` — JSON Schema `title` is annotation only, not validated |
| `docs/status-honesty-audit.md:471` | Names the log path; keep in step with 1c |
| `.gitignore:2` | Header comment |
| `.gitleaks.toml:9` | `title = "nabaa-rag secret scan"` — display title of the scan report, not a matching rule |
| `NABAA-SUNDAY-POC-EXECUTION.md` | 24 prose occurrences of "Nabaa" in body text |

---

## 5. Documentation cross-references that go stale

`NABAA-SUNDAY-POC-EXECUTION.md` is referenced **by name** from 9 places outside
itself. Renaming the file breaks all 9 as dead links. These are broken doc
links, not runtime failures — silent, but fully recoverable.

| Referencing file:line |
|---|
| `backend/app/synthesis.py:9` |
| `backend/tests/test_synthesis.py:9` |
| `docs/issue-map.md:36` |
| `docs/limitations.md:65` |
| `docs/preflight-inventory.md:6` |
| `frontend/src/components/analysis/MarketPanel.tsx:9` |
| `frontend/src/types/analysis.ts:8` |
| `frontend/src/views/AnalysisView.tsx:4` |
| `scripts/seed_access.py:44` |

Most cite a section number (§0, §12, 7.2/7.3, section 3 control 9). If you renumber
sections while renaming, the references become *wrong* rather than merely broken —
which is worse. Do not renumber.

**Correction to the prior scan:** the file contains **no self-references to its
own filename** (0 occurrences). It does reference a sibling document,
`NABAA-CODEBASE.md`, at lines **6, 38 and 56**. That file exists at
`Claude outputs/NABAA-CODEBASE.md` — outside `docs/`, in a directory whose name
contains a space. If you rename `NABAA-CODEBASE.md` you must fix those three
lines. `NABAA-SUNDAY-POC-EXECUTION.md:1657` and `:1658` also embed the old name
in example `git commit` / `git tag` commands describing a tag
(`v1.0.0-prototype`) that may already exist — do not rewrite history to match.

**Filesystem names containing the old brand (3, not 5 — see section 8):**

1. `NABAA-SUNDAY-POC-EXECUTION.md` (repo root, tracked)
2. `Claude outputs/NABAA-CODEBASE.md` (untracked directory)
3. `backend/data/nabaa.sqlite` (gitignored — **see 1a, do not casually rename**)

Use `git mv` for 1 so history follows the file.

---

## 6. The GitHub repository rename

Repo: `abubakarshahid16/saudi-aramco-rag-chatbot` (private, per
`docs/adr/ADR-0004-github-free-tier-gaps.md:9`).

Note this slug does **not** contain "nabaa" — renaming the *product* does not
require renaming the *repo*. Treat this as a separate decision and a separate
commit. Every hardcoded occurrence:

| File:line | Content | Live config? |
|---|---|---|
| `.github/CODEOWNERS:1` | comment naming the repo | no |
| `.github/CODEOWNERS:9` | `*  @abubakarshahid16` | **YES** |
| `.github/CODEOWNERS:12` | `/.github/  @abubakarshahid16` | **YES** |
| `.github/CODEOWNERS:13` | `/.gitignore  @abubakarshahid16` | **YES** |
| `.github/CODEOWNERS:14` | `/.gitleaks.toml  @abubakarshahid16` | **YES** |
| `.github/CODEOWNERS:17` | `/docs/adr/  @abubakarshahid16` | **YES** |
| `.github/CODEOWNERS:18` | `/contracts/  @abubakarshahid16` | **YES** |
| `.github/ISSUE_TEMPLATE/config.yml:4` | full URL to `/blob/main/docs/adr` | yes (link) |
| `.githooks/pre-commit:2` | comment | no |
| `.gitleaks.toml:1` | comment | no |
| `.gitignore:2` | comment | no |
| `docs/issue-map.md:5` | `Repository: abubakarshahid16/saudi-aramco-rag-chatbot (private)` | no |
| `docs/adr/ADR-0004-github-free-tier-gaps.md:9` | repo identity, "verified PRIVATE by API" | no |

**CODEOWNERS is live GitHub configuration, and it fails silently.** GitHub does
not error on an owner handle that does not exist or has no repo access — it
simply does not assign that reviewer. A typo'd or stale handle **voids
code-owner review entirely** while the file still looks correct in the diff.
`.githooks/pre-commit` and `.gitleaks.toml` are described in ADR-0004 as
compensating controls for the absence of GitHub Advanced Security on this
account tier; CODEOWNERS is part of that posture. After any CODEOWNERS edit,
open a throwaway PR and confirm the code-owner reviewer is actually
auto-requested. Do not trust the file.

**Only the `@handle` lines matter functionally.** The repo-name comments are
prose.

**What a GitHub repo rename does and does not break:**

- GitHub **permanently redirects** the old URL for web, API and `git` remote
  operations. Existing clones keep working.
- **Open pull requests, issues, stars, watchers and wiki survive** a rename.
  Issue and PR numbers are unchanged.
- The ADR-0004 note "verified PRIVATE by API" refers to the repo's visibility,
  not its name. A rename does not change visibility — but re-verify it after,
  because that is the whole point of the ADR.
- Anyone who created a *new* repo at the old name would capture the redirect.
  Low risk on a private repo, but do not free the old name casually.
- Update `git remote set-url` in local clones anyway; redirects are a courtesy,
  not a contract.

---

## 7. Recommended order of operations

**Change never (recommended defaults):**

- `backend/app/config.py:17` — the database filename. No user ever sees it.
- `frontend/src/App.tsx:17` — `THEME_KEY`, unless you implement the fallback read.
- `backend/app/errors.py:87` / `:89` — log file and logger name.
- The `"nabaa"` entry in `scripts/seed_access.py:71`. **Add, never remove.**

If you accept all four, the rename becomes a low-risk cosmetic change and you
can skip steps 4 and 5 entirely.

**Numbered procedure:**

1. **Back up the database first, before any edit.** `.backup` +
   `PRAGMA integrity_check` + `SELECT count(*) FROM chunks` (expect 7656).
   Store the copy outside the repo. Nothing below is safe without this.
2. **Record the baseline.** Run the full test suite and note the pass count and
   the test total that `conftest.py`'s guard reports. You cannot tell what the
   rename broke without a known-good number.
3. **Commit 1 — display strings only.** Section 4, plus section 2's *addition*
   to `FORBIDDEN`. Includes `Shell.tsx:156` and `:177`, `reports.py:422/436/438`,
   `main.py:66`, all docs prose, all comments, and the untracked
   `index.redesign.css:2`. *Verify:* full test suite still green; load the UI and
   check both brand positions; export one PDF and check the footer and its
   document properties.
4. **Commit 2 — coupled pairs, each pair whole.** Section 3, pairs 1 and 2.
   Pairs 3, 4 and 5 only if you have decided to take the risk described there.
   *Verify:* `pytest backend/tests/test_reports.py backend/tests/test_access_schema.py`
   green; download a report and check the filename.
5. **Commit 3 — the doc-file rename, on its own.** `git mv NABAA-SUNDAY-POC-EXECUTION.md`,
   then fix all 9 references from section 5 in the same commit. Do not renumber
   sections. *Verify:* `grep -rn "NABAA-SUNDAY-POC-EXECUTION"` returns nothing.
6. **Commit 4 — the database, ONLY if you are renaming it, and ONLY as one commit.**

   > **DO NOT rename the database path unless you also move the file and update
   > all 15 scripts in the same commit.** `config.py:17` and every row of the
   > table in section 1a — especially the three READ-WRITE scripts
   > `dbstate.py:3`, `pagesample.py:3` and `resetdoc.py:3` — move together or
   > not at all. A split commit produces an empty database and a green build.

   Backend stopped, WAL checkpointed, `-wal`/`-shm` moved with the file.
   *Verify, in this order:* (a) `sqlite3 <new path> "SELECT count(*) FROM chunks;"`
   returns 7656; (b) `ls backend/data/` shows **no** stray second `.sqlite`;
   (c) start the app and confirm the API lists **12** documents, not 0;
   (d) run `dbstate.py` and confirm it reports the real corpus.
7. **Commit 5 — GitHub / repo identity, entirely separate.** Section 6. Rename
   on GitHub first, then update CODEOWNERS handles, then the URL in
   `ISSUE_TEMPLATE/config.yml`, then the prose. *Verify:* open a throwaway PR
   and confirm the code-owner reviewer is auto-requested; re-verify repo
   visibility is still PRIVATE per ADR-0004.
8. **Final sweep.** `git grep -in nabaa` **plus** a plain
   `grep -rin nabaa --exclude-dir={.git,.venv,node_modules}` — the second
   catches untracked files that `git grep` misses. Anything left should be
   there deliberately: the `FORBIDDEN` entry, and whichever of the four
   "change never" items you chose to keep. Add a comment at each surviving
   occurrence saying why it survived, or someone will "finish the job" next month.

**Requires its own commit, no exceptions:** the database move (step 6), the doc
rename (step 5), and the GitHub identity change (step 7). Each is independently
revertible only if it is not entangled with a string sweep.

---

## 8. References I could not verify, and corrections made

**Corrected:**

| Prior claim | Verified reality |
|---|---|
| `backend/app/main.py:671` — `nabaa-report-{id}.pdf` | Actually **`backend/app/main.py:698`**. Line 671 is unrelated. |
| "18 scripts under `scripts/` hardcode this path" | **15 scripts.** Full list in 1a, cross-checked against `grep -rn "sqlite3.connect\|\.sqlite" scripts/`. The other 6 files in `scripts/` (`fetch_models.py`, `install-git-hooks.sh`, `killtest.ps1`, `killtest2.ps1`, `make_synthetic_pdf.py`, `seed_access.py`) contain no DB path. Some scripts hit the path on two lines (e.g. `chunk_report.py:6` and `:7`), which may explain the higher count. |
| "5 file/folder names" | **3.** `NABAA-SUNDAY-POC-EXECUTION.md`, `Claude outputs/NABAA-CODEBASE.md`, `backend/data/nabaa.sqlite`. `find -iname "*nabaa*"` outside `.git`, `.venv` and `node_modules` returns exactly these three. No directory name contains the brand. |
| "self-references inside `NABAA-SUNDAY-POC-EXECUTION.md`" | **Zero** references to its own filename. It references `NABAA-CODEBASE.md` at lines 6, 38, 56. |
| "94 matching lines across 50 files" | **93 lines** via `git grep -in nabaa`, plus **1 untracked** (`frontend/src/index.redesign.css:2`) that `git grep` cannot see — 94 total, but only if you count the untracked one. |
| Weak-password list "reported at `scripts/seed_access.py`" | Confirmed, precise line: **`scripts/seed_access.py:71`**. Doc mirror at `docs/design-authentication.md:173` confirmed exactly. |

**Confirmed exactly as reported:** `config.py:17`, `App.tsx:17`, `errors.py:87`,
`errors.py:89`, `test_reports.py:423`, `docs/design-pdf-report.md:232`,
`test_access_schema.py:224` and `:232`, `conftest.py:64`, `Shell.tsx:156` and
`:177`, and both absolute-Windows-path scripts (`chunk_report.py:6`,
`textsample.py:2`).

**Could not verify — outside this repository:**

- Whether any CI workflow or shell profile exports `NABAA_MIN_TESTS`. There is
  no `.github/workflows/` directory in this tree, so nothing in-repo sets it.
  Check your CI provider before renaming coupled pair 4.
- Whether any external log collector matches on the logger name `nabaa`
  (coupled pair 5). Nothing in-repo does.
- Whether `nabaa.sqlite-wal` / `-shm` ever exist under load. Neither is present
  now (clean shutdown). The hazard in 1a is real regardless — verify at the
  moment you move the file, not from this document.
- Live GitHub state: CODEOWNERS effectiveness, open PR/issue counts, and current
  repo visibility. Verify against GitHub itself at rename time.

**Working-tree caveat:** this repo has 9 modified and 12 untracked files at time
of writing. `git grep` searches tracked files only. Re-run the plain `grep`
sweep from step 8 immediately before you start, in case new occurrences have
landed.
