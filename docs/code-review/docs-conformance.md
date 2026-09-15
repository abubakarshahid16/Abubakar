# Documentation conformance audit — RAG Intelligence System

**Tree audited:** working tree at `d5357a3` (`feat/phase-1-ui-reaches-backend`), 17 commits
after `cd72bac` and 20 after `5baf18e` — the two commits the README names as the source of
its measured figures. Measured: `git log --oneline cd72bac..HEAD | wc -l` → 17,
`git log --oneline 5baf18e..HEAD | wc -l` → 20.

**Method.** Read-only. No file on the device was modified. Every number below names the
command that produced it. **No test suite was executed** (the device carries Python 3.10 and
the project requires 3.12); every test count here is a *static declaration count* and is
labelled as one — see "How the test counts were measured" before quoting any of them.

**Result: 25 findings** — 6 high, 16 medium, 3 low. The seventh through thirty-first
documentation defects, continuing `docs/status-honesty-audit.md`'s numbering of six.

The dominant shape is not the one the audit records. It is narrower and worse:
**a defect was fixed in one of its two homes.** `egress_state()` was corrected to read the
flags and `market.NOTICE` was not. `AnswerCard.tsx` gained a positive provenance predicate
and `reports.py` did not. The README's "four views" line was corrected and `Shell.tsx`'s own
docstring above the data was not. The disk *heading* was re-measured and the table rows
under it were not. In each case the visible half was repaired and the half nobody was looking
at kept the claim alive.

---

## HIGH

### H1 — The one rule has no enforcement point on the answer path's own socket

- **Severity:** High
- **file:line:** `README.md:14`; `docs/adr/ADR-0002-privacy-boundary.md:27-32` (Enforcement);
  `backend/app/config.py:106`; `backend/app/answer.py:404`; `backend/app/analysis.py:667`
- **The claim:** README:14 — "**Client document content never leaves this machine.**"
  ADR-0002's Enforcement section lists four controls: `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE`,
  "Services bind to `127.0.0.1` only", no remote assets in the UI, and "Retrieved document
  text is treated as untrusted data and is never sent anywhere."
- **The reality:** `ollama_url` is an ordinary `.env`-settable string with a loopback
  *default* and no validation (`config.py:106`, `ollama_url: str = "http://127.0.0.1:11434"`;
  `OLLAMA_URL` is line 5 of `backend/.env.example`). `answer.py:404` and `analysis.py:667`
  both do `client.post(f"{settings.ollama_url}/api/generate", json=body)`, and `body` carries
  the prompt built by `answer._build_prompt` / `synthesis.build_prompt` — that is retrieved
  passage text, verbatim. `metrics.py:271,279` call the same host. So the entire Tier 2 path
  posts client document content to whatever host that string names, and the four Enforcement
  controls do not touch it: the binding rule is *inbound*, and the offline flags govern
  HuggingFace, not this call.
  The system's one host allowlist (`config.py:372`, `market_allowed_hosts`) does not cover
  this path — `market_providers.check_host` is called only from `market_providers` and
  `market_transport`.
- **How I measured it:** `grep -rn "ollama_url" backend/ --include="*.py"` → five hits, all
  listed above, and **no guard**. `grep -rln "127.0.0.1\|loopback" backend/tests/*.py` returns
  `test_api_contract.py`, `test_health.py`, `test_metrics.py`; the only `ollama_url` reference
  in any test is `test_metrics.py:188` monkeypatching it to a dead port. There is no test
  asserting the host is loopback.
- **Smallest fix:** two changes. In `ADR-0002`, add to Enforcement: *"The answer model is
  reached at `settings.ollama_url`, which must resolve to a loopback host. This is the one
  outbound call on the query path that carries document text, and it is enforced by a
  validator on the setting, not by its default."* In `config.py`, add a
  `@field_validator("ollama_url")` rejecting a non-loopback host, with a test that a
  non-loopback value refuses at startup. Until the validator exists, the README sentence at
  line 14 should read *"Client document content never leaves this machine, provided
  `OLLAMA_URL` names a local Ollama — the setting is not currently validated."*

### H2 — The report PDF labels recognised text as a verbatim quotation

- **Severity:** High
- **file:line:** `backend/app/reports.py:354`
- **The claim:** `docs/adr/ADR-0006-provenance-for-recognised-text.md:4-6` — recognised text
  "is **never** labelled as a verbatim quotation." `docs/runbook.md:78-82` goes further and
  tells the reader it is a defect: *"If you see 'Quoted verbatim from the document' above text
  that came from a scanned page, that is a defect — report it."*
- **The reality:** `reports.py:354` is
  `parts.append('<p class="label">Quoted verbatim from the document</p>')`, reached by
  `if s["answer_type"] == "extract":` and by nothing else. There is no `text_source` test on
  that branch. The field is present and used elsewhere in the same file — `reports.py:154,169`
  compute a per-document `text_source` (including `"mixed"`) and `reports.py:264` adds
  *"Read by OCR from a scanned page - not the document's own text"* to each recognised
  passage in section 3. So for a recognised extract answer the PDF carries both labels: the
  verbatim claim in section 2 and the OCR caveat in section 3. That is precisely the failure
  standing rule 13 names — "presence-only assertions pass while both claims are on screen."
  The chat surface does gate it correctly, with a positive predicate:
  `AnswerCard.tsx:569` `const extracted = p?.text_source === "extracted";`, used at :580-583.
- **How I measured it:** `grep -rn "verbatim\|Quoted" backend frontend contracts` located the
  label; `sed -n '300,400p' backend/app/reports.py` read the branch in full;
  `grep -n "text_source" backend/app/reports.py` shows the field is available at :154, :169,
  :264, :388, :510, :556 and unread at :354.
- **Smallest fix:** mirror the chat predicate. In `to_html`, before the extract branch:
  `cited = next((p for p in s["passages"] if p.get("cited")), None)` and render the verbatim
  label only when `(cited or {}).get("text_source") == "extracted"`, else the OCR label. A
  test must assert the **absence** of the verbatim string over a recognised passage, proven by
  restoring the current line and watching it go red.

### H3 — ADR-0006 says "No code written". The code is written and shipped

- **Severity:** High
- **file:line:** `docs/adr/ADR-0006-provenance-for-recognised-text.md:3`
- **The claim:** "**Status:** Proposed — awaiting approval. No code written."
- **The reality:** every element of the ADR exists. `page_ocr` is created at `db.py:69`.
  `chunks` carries `text_source` (`search.py:69`, `Candidate.text_source`). `backend/app/ocr.py`
  is 333 lines. `README.md:82` describes OCR as shipped and quotes a coverage figure from it.
  ADR-0006 is cited by the README as authority for a shipped feature while its own status line
  says the decision is unapproved and unimplemented.
- **How I measured it:** `sed -n '1,12p'` on the ADR; `grep -n "CREATE TABLE" backend/app/db.py`
  → `page_ocr` at line 69; `wc -l backend/app/ocr.py` → 333.
- **Smallest fix:** `- **Status:** Accepted and implemented. See ADR-0005 for the engine
  decision; the recogniser remains open.` Then either resolve or delete the two follow-up
  bullets at :271-275, one of which is still outstanding (see M16).

### H4 — `benchmarks.md` declares four metrics unmeasured that its own file measures

- **Severity:** High
- **file:line:** `docs/benchmarks.md:117-131`
- **The claim:** the heading "## Not yet measured" and "These rows stay empty until measured.
  Do not fill them with estimates." Rows: Tier 1 end-to-end (:123), Cross-encoder rerank
  latency (:127), System prompt token count (:128), Embedding throughput chunks/s (:129).
  `README.md:8` points readers here as the authority: "Benchmarks are recorded in
  `docs/benchmarks.md` only after they are actually run on this hardware."
- **The reality:** all four are measured, three of them in this same file.
  - Embedding throughput — `benchmarks.md:93-95` gives 6.9 / 6.8 / 5.7 chunks/s, and :171
    says "at the measured 9.22 chunks/s sustained".
  - System prompt token count — `benchmarks.md:713` "| Generated | **122 tokens** |", and
    `answer.py:36` "System prompt variant B, measured at 122 net tokens".
  - Tier 1 end-to-end — `benchmarks.md:565` measures "Tier 1, warm, five gold questions", and
    `limitations.md` states "Tier 1 median is ~2.1 s".
  - Cross-encoder rerank latency — `config.py:271-277` carries a five-row measured table
    (256→583 ms, 320→603, 384→910, 480→796, 512→1182, median of 5, 20 candidates).
- **How I measured it:** `grep -n "rerank\|chunks/s\|Tier 1\|System prompt\|122" docs/benchmarks.md`.
- **Smallest fix:** delete the four rows and add a line under the table pointing at where each
  figure now lives. A row that says "unmeasured" about a measured quantity is the inverse of
  the defect this file exists to prevent, and it is worse, because it invites someone to spend
  a morning re-measuring.

### H5 — LanceDB is in the stack table and is not in the system

- **Severity:** High
- **file:line:** `README.md:59`, `README.md:35`
- **The claim:** README:59 "| Vector search | LanceDB embedded, brute-force cosine |", and the
  architecture diagram at :35 "ONNX int8 E5 ──▶ **LanceDB** (brute-force)".
- **The reality:** no module imports lancedb. Vectors are BLOBs in the SQLite table
  `chunk_vectors` (`db.py:132-140`), loaded by `search._load_vectors` (:141) from a
  memory-mapped numpy cache (`vectorcache.py`) and scored by one matmul,
  `search.py:189` `scores = matrix @ query_vec`. `lancedb==0.38.0` is pinned in
  `backend/requirements.txt:23` and `lance_dir` survives in `config.py:36` and `:431`, so the
  dependency is installed, the directory is created, and nothing reads either. The
  "brute-force cosine" half of the claim is true; the store is not LanceDB.
- **How I measured it:** `grep -rn "lancedb\|import lance\|lance_dir" backend/app/ backend/*.py`
  → three hits, all in `config.py`, none an import; `grep -n "def _load_vectors" -A 15
  backend/app/search.py`; `sed -n '132,142p' backend/app/db.py`.
- **Smallest fix:** README:59 → "| Vector search | `chunk_vectors` BLOBs in SQLite, mapped to a
  numpy matrix (`vectorcache.py`), brute-force cosine |", and :35 → "ONNX int8 E5 ──▶
  chunk_vectors (brute-force cosine)". Separately: `lancedb` is an installed dependency nothing
  uses — the mirror of the `huggingface_hub` finding in the honesty audit, and it should be
  dropped or its intended use recorded.

### H6 — A comment records a false reason for the market routes' shape

- **Severity:** High
- **file:line:** `backend/app/main.py:873-876`
- **The claim:** "No network call exists in this build. **Both routes** are scoped like every
  other, not because a sample is sensitive, but so that adding a real provider later cannot
  introduce an unscoped route by inheriting this shape."
- **The reality:** false on both counts, and it is the entry-15 shape — a comment that makes a
  design decision look settled and is then read as a guarantee.
  - There are **four** market routes below that comment, not two: `/api/market/findings` (:879),
    `/api/market/preview-query` (:885), `/api/market/preview` (:944), `/api/market/search` (:976).
  - A network call path exists. `market_transport.py` imports `httpx` (:50) and `_fetch` (:81)
    opens a client; `market_search` at :1010 passes `market_transport_mod.transport()` as the
    fetch callable. It is gated on both flags being true (`market_providers.live_enabled`,
    :661) and both default false — so nothing leaves today, but "no network call exists in this
    build" is not what the build says, and the route docstring at :980-984 contradicts the
    section comment by explaining why `fetch` is left unset.
- **How I measured it:** `grep -n "^@app\.\(get\|post\|put\|delete\|patch\)" backend/app/main.py`
  for the route inventory; `sed -n '860,1020p' backend/app/main.py`;
  `grep -n "httpx" backend/app/*.py`.
- **Smallest fix:** "Four routes. Two serve labelled samples and a preview that is never sent;
  two are the live tiers, inert unless `market_live_enabled` and `market_allow_public_egress`
  are both true. All four take the scope, so a real provider cannot inherit an unscoped shape."

---

## MEDIUM

### M1 — Both README test counts are stale again, in the same direction as defects 16 and 17

- **Severity:** Medium
- **file:line:** `README.md:224` (frontend), `README.md:264` (backend), `README.md:101-103`
- **The claim:** ":224 — `npm run test # 496 tests across 42 files, ~1 minute`";
  ":264 — `python -m pytest -q # 1174 passed, 3 skipped, 17 xfailed`"; and :101-103 records
  those as measured at `5baf18e` / `cd72bac`.
- **The reality:** the figures were honest when taken and the tree has moved 20 and 17 commits.
  Static declaration counts (see method note below):

  | ref | frontend files | frontend `it(`/`test(` | backend files | backend `def test_` |
  |---|---:|---:|---:|---:|
  | `5baf18e` (README's frontend source) | 42 | 466 | 61 | 952 |
  | `cd72bac` (README's backend source) | 42 | 466 | 61 | 956 |
  | `HEAD` tracked | 42 | 491 | 70 | 1,126 |
  | **working tree** (incl. untracked) | **43** | **515** | **72** | **1,151** |

  So relative to the tree a reader clones today: **+49 frontend declarations and one more
  frontend file; +195 backend declarations and 11 more backend files.** The README's "42 files"
  is already wrong of the working tree (43), which is the one number a reader can check in a
  second. Three of the new test files are untracked
  (`backend/tests/test_relevance_floor.py`, `test_typo_tolerance.py`,
  `frontend/src/views/AnalysisModeScreen.typeFilter.test.tsx`, per `git status --porcelain`).
- **How I measured it:** working tree — `find frontend/src -name "*.test.ts*" | wc -l`,
  `grep -rhoE "\b(it|test)(\.each|\.skip|\.todo|\.only|\.concurrent)?\s*\(" frontend/src --include="*.test.ts*" | sort | uniq -c`
  (508 `it(` + 7 `test(`, no `.skip`/`.each` variants present),
  `find backend/tests -name "test_*.py" | wc -l`,
  `grep -rhoE "^\s*(async )?def test_" backend/tests --include="*.py" | wc -l`.
  Historical refs — the same greps over `git ls-tree -r --name-only <ref>` piped through
  `git show <ref>:<file>`.
- **Smallest fix:** re-run both suites on a 3.12 machine and replace both figures with the run,
  naming the commit as the README already does. Do **not** substitute my static counts: they
  are declarations, not tests. And add to the frontend line what the backend line already
  says — that the count is the thing to check.

### M2 — Two documents each claim to be the clean-clone record, with different results

- **Severity:** Medium
- **file:line:** `docs/runbook.md:88-119`, against `README.md:98-110`
- **The claim:** runbook — "## Clean-clone verification — last passed 2026-09-05 … **A passing
  clone test is only useful if the next person can see when it last passed.** Update this
  section, with the date and the branch, whenever it is re-run. If the date is old, the setup
  guide is a guess again." Its table reports `npm run test` → **119 passed** and
  `python -m pytest -q` → **496 passed**, 210 s, at `935b336`.
- **The reality:** a later clean-clone run exists and is recorded in the *other* file:
  README:98-103, 2026-09-07, `5baf18e` — frontend 496 across 42 files, backend 1,170 passed in
  5m56s. The runbook was not updated, so by its own stated rule the setup guide is a guess.
  The collision is the dangerous part: **496 is the backend figure in the runbook and the
  frontend figure in the README.** A reader cross-checking one against the other finds an
  apparent agreement that is a coincidence between two different quantities. The runbook's
  "What the run found" table also still lists "README claimed ~2 GB disk; measured 768 MB" —
  a third disk figure, against the README's current 773 (see M3).
- **How I measured it:** read both sections; `git log --oneline 5baf18e..HEAD | wc -l` → 20,
  so neither run describes HEAD.
- **Smallest fix:** delete the results table from `runbook.md` and replace the section with one
  line — "The clean-clone record lives in README.md 'Getting started'; there is one, and it is
  there." Two homes for one measurement is how they diverge.

### M3 — The disk table's rows do not sum to its own total

- **Severity:** Medium
- **file:line:** `README.md:161-167`, `README.md:132`, `README.md:157`
- **The claim:** rows `.venv` 528 MB, `backend/models` 159 MB, `frontend/node_modules` 78 MB,
  `.git` 3 MB; "**Total inside the clone** | **773 MB**"; and the heading and prerequisites row
  both say 773.
- **The reality:** 528 + 159 + 78 + 3 = **768**, not 773. `git show cd72bac -- README.md`
  shows exactly what happened: that commit changed the prerequisites row and the heading from
  768 to 773 — "The table was re-measured to 773 MB on the clean clone; the prose heading above
  it and the prerequisites row still said 768" — and changed no row of the table. So the
  re-measurement updated the headline and left the parts, which is the same fix-one-of-two-homes
  shape as H2 and M11. The audit's own entry 9 records a third breakdown (`.venv` 527, weights
  159, `node_modules` 80 → 766).
  I could not reproduce a clean-clone figure read-only: this working tree measures `.venv`
  914 MiB, `backend/models` 171 MiB, `frontend/node_modules` 204 MiB, `.git` 11 MiB, 1,682 MiB
  total — legitimately larger, being a dev tree with caches and extra packages, so this is not
  offered as a correction to the clean-clone number, only as evidence that I did not verify it.
  One row I can corroborate: `backend/models` at 171 MiB is 179 MB decimal, which matches the
  "~179 MB staged" at README:212 and `fetch_models.py:237` (`total / 1e6`) exactly.
- **How I measured it:** arithmetic on the table; `git show cd72bac -- README.md`;
  `du -sm .venv backend/models frontend/node_modules .git node_modules data` and `du -sm .`
  in the working tree.
- **Smallest fix:** re-measure the four rows on a clean clone in the same units as the total,
  or state the total as the sum of the rows. Add the unit: the models row is 179 MB / 171 MiB
  and the two are five percent apart, which is most of the 768-vs-773 gap.

### M4 — ADR-0003 records mypy as a control that runs. It does not exist

- **Severity:** Medium
- **file:line:** `docs/adr/ADR-0003-scope-cuts.md`, cuts table, row "mypy blocking"
- **The claim:** "| **mypy blocking** | Runs in CI, reports, does not block merge. | Flip to
  blocking when the type surface stabilises |"
- **The reality:** mypy does not run anywhere. It is in neither workflow
  (`.github/workflows/` holds `secret-scan.yml` and `tests.yml`), not in
  `backend/requirements.txt`, not in `CONTRIBUTING.md`, not in any config file. The string
  `mypy` appears in exactly one file in the repository: this ADR. A cut recorded as
  "reports but does not block" reads as a control in place; a control that was never installed
  is a different decision, and the reversal path ("flip to blocking") describes work that
  cannot be done in one step.
- **How I measured it:**
  `grep -rln "mypy" --include="*.yml" --include="*.toml" --include="*.ini" --include="*.cfg" --include="*.txt" --include="*.md" .`
  (excluding `node_modules` and `.venv`) → `./docs/adr/ADR-0003-scope-cuts.md` only;
  `ls .github/workflows/`; `grep -rn "mypy\|tsc -b\|pytest\|vitest" .github/workflows/`.
- **Smallest fix:** "| **mypy** | **Cut entirely — never installed.** Static typing on the
  Python side is unchecked; `tsc -b` covers the TypeScript side in CI. | Add mypy to
  requirements and to `tests.yml` in reporting mode first |"

### M5 — ADR-0001 and ADR-0003 are superseded on five points and marked Accepted

- **Severity:** Medium
- **file:line:** `docs/adr/ADR-0001-hybrid-rag-two-tier-answer.md` (Decision, Supporting
  decisions); `docs/adr/ADR-0003-scope-cuts.md` (cuts table)
- **The claim / the reality**, each measured against `backend/app/config.py`:

  | Where | The claim | The reality |
  |---|---|---|
  | ADR-0001 Tier 2 | "Context budget: **2 chunks × 250 tokens**" | `generated_context_chars = 1200` per passage (`config.py:311`); `num_ctx = 4096` admits six of eight passages per the same file's own note at :117-128 |
  | ADR-0001 Tier 2 | "Answer capped at **60–100 tokens**" | `max_output_tokens = 250` (`config.py:142`) — the change is documented at length in `config.py:130-142` and in `limitations.md`, and never reached the ADR |
  | ADR-0001 Supporting | "**`num_ctx` capped near 1536**, set from measurement" | `num_ctx = 4096` (`config.py:129`), and `config.py:117` calls the change "a DECISION, not a tuning pass" overridden by the project owner |
  | ADR-0001 Supporting | "Its exact token count must be reported and tracked" (system prompt) | measured at 122 (`answer.py:36`) and still listed as unmeasured in `benchmarks.md:128` — see H4 |
  | ADR-0003 cuts | "**OCR** — Detect and flag scanned pages only. No OCR implementation. Reversal path: Tesseract `eng+ara`" | OCR ships, via RapidOCR / PP-OCRv6 (`ocr.py`, ADR-0005); Tesseract was never the engine |
  | ADR-0003 cuts | "**System view** — Four UI views: Documents, Chat, Ingestion, Dashboard" | six, all `built: true` (`Shell.tsx:31-36`) plus `ADMIN_NAV` at :50. This is recorded defect 19, fixed in the README and not here |

  Defect 18 in the honesty audit is the README quoting `num_ctx` 1536 and 60-100 tokens. The
  README was fixed (:63 now states 4096 and 250 correctly). **ADR-0001 is where those figures
  came from and it still says them**, and it is what a reader is sent to by README:89 ("Full
  rationale and known limitations: `docs/adr/`"). Note also README:46, which still shows
  "2 chunks x 250 tok" in the architecture diagram — the one place in the README the old budget
  survived.
- **How I measured it:** `cat -n backend/app/config.py` against the two ADRs;
  `grep -n "label\|built" frontend/src/components/Shell.tsx`.
- **Smallest fix:** add to ADR-0001 a "**Superseded in part**" block naming the four values, the
  commit that changed each, and where the current value lives; add "Cut then REVERSED" entries
  to ADR-0003 for OCR and System view, alongside the Reranker entry that is already there —
  that section exists and is the right shape, it simply was not extended. And correct
  README:46 to the current budget.

### M6 — The chunking row quotes a target that changed

- **Severity:** Medium
- **file:line:** `README.md:57`
- **The claim:** "| Chunking | Custom structure-aware, **400-token target** / 60-token overlap |"
- **The reality:** `chunk_target_tokens = 300` (`config.py:236`). Overlap is 60, correct, and
  `chunk_max_tokens = 480` is unmentioned though it is the value the reranker window is pinned
  to (`config.py:260-278`, and a test asserts the relationship per `limitations.md`). This is
  defect 18's family exactly — a stack table quoting a config value that has moved — in the row
  next to the one that was fixed.
- **How I measured it:** `grep -n "chunk_target_tokens\|chunk_overlap_tokens\|chunk_max_tokens"`
  in `config.py` → 300 / 60 / 480 at :236-238.
- **Smallest fix:** "| Chunking | Custom structure-aware, 300-token target / 60-token overlap /
  480-token ceiling (`backend/app/config.py`) |". Cite the file, as the answer-model row at :63
  already does — that is why that row survived and this one did not.

### M7 — Reranking is described as mandatory and is a request parameter

- **Severity:** Medium
- **file:line:** `README.md:62`; `docs/adr/ADR-0003-scope-cuts.md` "Cut then REVERSED"
- **The claim:** README:62 "| Reranking | Small local CPU cross-encoder — **mandatory**, not
  optional |". ADR-0003: "**Reinstated as mandatory** by ADR-0001".
- **The reality:** `search.search(..., rerank: bool = True, ...)` (`search.py:616`) and the
  route exposes it: `main.py:447` `rerank: bool = Query(True)`. Any caller of `/api/search` can
  turn the cross-encoder off. One internal caller does, deliberately and with a recorded reason
  — `analysis.py:491` passes `rerank=False, dense=False` because "reranking re-imposes the
  `rerank_candidates` (16)" cap the analysis path is trying to escape (`analysis.py:474`).
  "Mandatory" is true of the *default* and of the Tier 1 answer path; it is not true of the
  API, and the ADR-0001 argument it rests on ("what makes Tier 1 trustworthy enough to be the
  default") is an argument about a default.
- **How I measured it:** `grep -n "def search" -A 20 backend/app/search.py`;
  `grep -rn "rerank=False\|rerank:" backend/app/*.py`; `sed -n '440,450p' backend/app/main.py`.
- **Smallest fix:** README:62 → "| Reranking | Small local CPU cross-encoder — **on by default
  on every answer path**. `/api/search?rerank=false` can disable it for inspection, and the
  analysis path does so deliberately (`analysis.py:474`) |".

### M8 — The design document whose "number that governs everything" is the old number

- **Severity:** Medium
- **file:line:** `docs/design-analysis-and-synthesis.md:16-27`, and again at `:409`
- **The claim:** ":4 — "The headline conclusion is arithmetic, not opinion."" Then
  ":19 `num_ctx = 1536`" and ":24 `evidence_budget = 1536 - 122 - 250 - 25 - 45 - 50 = 1044
  tokens`". ":409" repeats "3,567 tokens against a `num_ctx` of 1,536".
- **The reality:** `num_ctx = 4096` (`config.py:129`). The correct arithmetic is
  `4096 - 122 - 250 - 25 - 45 - 50 = 3,604` — 3.5× the stated evidence budget, which changes
  every conclusion the document draws from it, including ":75 **Raising `num_ctx` does not
  help**" and the overflow warning at :450 ("the current three-passage Tier 2 prompt is already
  overflowing `num_ctx` silently — a live defect"). The document is aware the value could
  change: ":376" lists "`num_ctx` at 4,096" under "### Cut, and say so out loud". So the doc
  records the raise as a *cut it did not take*, while the raise happened. Nothing at the top of
  the file says so. This is defect 18 again, in the third of its three homes: README (fixed),
  ADR-0001 (M5), and here.
  `context_budget.py:12` also carries 1,536, but the honesty audit already rules that
  acceptable — it names the value a past measurement was taken at, and reads as history.
  This document reads as current arithmetic.
- **How I measured it:** `grep -n "4096\|1536\|num_ctx" docs/design-analysis-and-synthesis.md`
  → 1536 at :19, :24, :409; 4096 at :376 only. `grep -n "num_ctx" backend/app/config.py` → 129.
- **Smallest fix:** a note under the heading at :16 — "**`num_ctx` was raised to 4096 after
  this was written** (`config.py:129`, and the reasoning is recorded there). The budget below
  is the arithmetic at 1536 and is kept because the conclusions about map-reduce cost were
  drawn from it; at 4096 the evidence budget is ~3,604 tokens and the three-passage overflow
  concern at §"The uncertainty to resolve first" no longer applies."

### M9 — The coverage design's central premise is still on the page after being retracted

- **Severity:** Medium
- **file:line:** `docs/design-multi-document-coverage.md:22-24`
- **The claim:** "That shortlist truncation at `search.py:661` is **the one place in this
  system where candidates are dropped with no recorded reason.** It is an invariant-5 gap and
  it is cheaper to close than any retrieval work."
- **The reality:** this exact sentence is entry 12 of `docs/status-honesty-audit.md`, recorded
  as false — `deduplicate()` and the pool builder dropped silently too. It has since been
  false in a second way: drops are now recorded. `search.py:662-680` builds an `evicted` list
  with a reason per candidate (`chunk_no_longer_exists`, `not_retrievable`),
  `search.py:392-422` `deduplicate(candidates, dropped)` appends a record per discarded
  candidate, and `search.py:706` is `pool = deduplicate(pool, evicted)`. The design document
  is now wrong about a premise its own project has recorded as wrong and then fixed, and says
  neither. It opens with "Written against the real code, not from general RAG practice."
  Its file:line anchors have also drifted unevenly, which matters because the doc's stated
  contract is that every claim carries one: `search.py:661` is now inside the eviction block
  rather than the rerank call; `answer.py:374` is `_build_prompt`, not the `search()` call
  the sentence attributes to it. Others still hold — `keyword.py:289-311` is
  `term_occurrences`, `lexical.py:111-113` is `is_compound_question`.
- **How I measured it:** `sed -n '655,690p' backend/app/search.py`;
  `grep -n "deduplicate\|dropped\|evicted" backend/app/search.py`;
  `sed -n '370,380p' backend/app/answer.py`; `sed -n '285,315p' backend/app/keyword.py`;
  `sed -n '105,120p' backend/app/lexical.py`.
- **Smallest fix:** replace :22-24 with — "**This premise was wrong and is recorded as entry 12
  of `docs/status-honesty-audit.md`.** The shortlist cut was not the one place: `deduplicate()`
  and the pool builder dropped silently too. All five reasons are now recorded under one slug
  vocabulary (`search.py:392-422`, `search.py:662-680`), so the gap this design was written to
  close is closed. The rest of this document is the reasoning that produced that fix." Then
  either refresh the anchors or add a line saying they are as-of `<commit>`.

### M10 — The conformance audit still reports a gate that is half-built

- **Severity:** Medium
- **file:line:** `docs/plan-conformance-audit.md:254` (R040), `:754` (R459)
- **The claim:** R040 — "**Its gating is specified and not implemented** — **27 strict-xfail
  tests** in `test_recommendation_gate.py` describe three defects seen live". R459 — "The 27
  strict-xfail tests … record that the recommendation still speaks when the summary refuses …
  so the label is right and the content is **not yet gated**."
- **The reality:** the advisory gate landed. `test_recommendation_gate.py` now declares
  **19** tests, of which **4** carry an xfail marker, and its module note says so directly:
  "PARTIALLY IMPLEMENTED. #90 has two halves and only the first has landed. DONE, and now
  ordinary passing tests: the advisory GATE." That is honesty-audit entry 23, which corrected
  the test module's docstring — and did not reach the conformance audit that cites it twice.
  Mitigating: this document names its own commit in its header (`9f3f6db`, 2026-09-06) and is
  therefore honestly dated rather than falsely current. `git log --oneline 9f3f6db..HEAD | wc -l`
  → **35**. So the verdict is STALE-by-design, not FALSE — but two PARTIAL verdicts quoting a
  count that has changed are the ones a reader will lift out of a 1,046-line file without the
  header.
- **How I measured it:** `grep -c "def test_" backend/tests/test_recommendation_gate.py` → 19;
  `grep -c "xfail" backend/tests/test_recommendation_gate.py` → 4;
  `sed -n '1,60p'` of the same file for the module note;
  `git log --oneline 9f3f6db..HEAD | wc -l` → 35.
- **Smallest fix:** in both rows, append "— *as of `9f3f6db`; the gate half of #90 has since
  landed and the module now declares 19 tests, 4 still xfail. Re-assess.*" A dated audit does
  not need rewriting; its two most-quoted verdicts need a pointer.

### M11 — `Shell.tsx`'s own docstring contradicts the data three lines below it

- **Severity:** Medium
- **file:line:** `frontend/src/components/Shell.tsx:4-5`
- **The claim:** "Documents, Chat and Dashboard are built. **Ingestion is listed but visibly
  marked**, so the navigation never implies capability that does not exist."
- **The reality:** `NAV` at :31-36 marks all six `built: true`, Ingestion included, and
  `ADMIN_NAV` at :50 adds Administration. `README.md:85` was corrected to say exactly this
  ("Six built views … plus an Administration section, per the navigation in
  `frontend/src/components/Shell.tsx`") — and it cites this file as its evidence, so a reader
  following the citation lands on a docstring that contradicts the sentence that sent them.
  This is recorded defect 19 fixed in one of its two homes.
- **How I measured it:** `sed -n '1,40p' frontend/src/components/Shell.tsx`.
- **Smallest fix:** "All six views are built (`built: true` below). Administration is appended
  only for a caller holding the admin capability — see `hasAdminCapability`. The `built` flag
  stays because the navigation must never imply capability that does not exist."

### M12 — `access.py` says authentication is not wired and login does not exist

- **Severity:** Medium
- **file:line:** `backend/app/access.py:39-42`, `backend/app/access.py:202-206`
- **The claim:** ":39 — "Authentication is not wired into the routes yet, and every existing
  test runs with it off."" ":203 — "**Login does not exist yet** and is deliberately not built
  here: it is the easy part, and it is the part that would make this feature feel finished
  while the enforcement was still untested.""
- **The reality:** login exists and is wired. `backend/app/auth.py` is 438 lines with
  `issue_token` (:132), `read_token` (:151), `resolve_user_id` (:362) and
  `access.set_user_resolver(resolve_user_id)` at :438. `POST /api/auth/login` (`main.py:596`)
  and `GET /api/auth/me` (:618) are routes. `backend/tests/test_auth_required_mode.py` exists.
  `README.md:228-258` is a whole setup step about `AUTH_MODE` and `AUTH_SECRET`, and README:213
  ff. calls `demo_required` "the only mode anyone deploys". These are the "not yet implemented"
  comments the brief warns about, in the module that decides what every request may see — the
  worst place for a reader to be told the feature is unbuilt.
- **How I measured it:** `cat -n backend/app/access.py`;
  `grep -n "def resolve_user_id\|set_user_resolver" backend/app/auth.py`;
  `grep -n "^@app\." backend/app/main.py | grep auth`.
- **Smallest fix:** :39 → "`disabled` is the default and most tests run under it, which is what
  proves the enforcement is additive: the filter always runs and only its contents differ."
  :203 → "The resolver is injected rather than imported so this module never depends on
  `auth`. `auth.install()` supplies `auth.resolve_user_id`; tests supply their own, which is
  how `test_two_concurrent_requests_never_share_scope` drives two users at once."

### M13 — Two access-hole designs read in the present tense over a partly-remediated system

- **Severity:** Medium
- **file:line:** `docs/design-access-holes.md` (whole file), `docs/design-authentication.md:12-58`
- **The claim:** both documents state five holes as facts about the running system. There is no
  status marker on any of them.
- **The reality:** three are closed, one is closed, one is open, and nothing on the page
  distinguishes them:

  | Hole | Claim | Reality |
  |---|---|---|
  | 4 — `/api/metrics` unscoped | "declares `scope` … and **never reads it**" | **Closed.** `main.py:158-200` passes `allowed` and `corpus_wide` into `metrics_mod.snapshot`, and the docstring at :168-180 records that the old claim was false when written |
  | 2 — conversations cross role boundaries | "takes `scope` and **never reads it**" | **Closed.** `access.AccessScope.owns_conversation` (:82) and `conversation_filter` (:112) are the single rule, spelled once as a predicate and once as a WHERE clause |
  | 3 — upload has no scope | "carries no scope dependency" | **Closed.** `main.py:230` `_require_identity_to_write(scope)`, and `admin_mod.grant_on_upload` at :243 closes the invisible-to-uploader half |
  | 5 — upload dedupe oracle | returns "the full record of a document the caller has no grant on" | **Closed.** `main.py:244-250` returns `{"document": None, …, "awaiting_grant": True}` when the duplicate is outside scope |
  | **1 — page images bypass authentication** | "**Delete them.** Leaving them exported guarantees the next screen re-introduces the hole" | **Open.** `client.ts:622` `pageImageUrl` and `:634` `pageImageWithAnswerUrl` still return URL strings, still consumed by `<img src>` at `PageImageViewer.tsx:145` and `EvidencePanel.tsx:238-244`. The "gain that falls out of this" is also unrealised: `X-Answer-Located` is read by no frontend code |

- **How I measured it:** the four fixes read directly in `main.py` and `access.py` as cited;
  hole 1 by `grep -n "pageImage" frontend/src/api/client.ts` and
  `grep -rn "pageImageUrl\|pageImageWithAnswerUrl" frontend/src --include="*.tsx"` (three
  non-test consumers), and `grep -rn "Answer-Located" frontend/src` → two hits, both comments
  in `client.ts`.
- **Smallest fix:** a status column at the top of `design-access-holes.md` — five rows, four
  CLOSED with the commit, HOLE 1 **OPEN**. A remediation design with no status column asks
  every future reader to re-derive which half of it happened, and the one still open is the one
  serving the literal page of a client specification.

### M14 — "Egress is one file" is not true of the codebase

- **Severity:** Medium
- **file:line:** `.claude/commands/review.md:104-105` (identical text in `docs/review-command.md`)
- **The claim:** "**Egress is one file.** Only the market transport module may open a socket.
  Any new outbound call anywhere else is a finding, however harmless it looks."
- **The reality:** four modules import `httpx` and three of them open sockets on the ordinary
  answer path: `answer.py:22/:404`, `analysis.py:34/:667`, `metrics.py:17/:271,:279`,
  `market_transport.py:50/:105`. The invariant the code actually holds is narrower and is
  enforced: `test_market_no_document_leak.py` asserts by AST that the *market* modules import
  no HTTP client (`test_market_modules_import_no_http_client`) and that the transport cannot
  reach the corpus (`test_the_transport_cannot_reach_the_corpus`,
  `test_the_transport_is_the_only_module_here_with_a_client`). "Here" is the operative word in
  that last test name, and the rule as written in review.md dropped it. A reviewer applying
  the rule literally would file `answer.py:404` as a finding on every review, and a reviewer
  who learns to ignore it there stops applying it anywhere — which is how the real invariant
  (H1) went unenforced.
- **How I measured it:** `grep -rn "import httpx" backend/app/*.py` → four files;
  `grep -n "def test_" backend/tests/test_market_no_document_leak.py`.
- **Smallest fix:** "**Public egress is one file.** Only `market_transport` may open a socket
  to a non-loopback host; `answer`, `analysis` and `metrics` reach Ollama at
  `settings.ollama_url`, which is expected to be loopback and **is not currently validated**.
  Any new outbound call outside those four, and any change that could let `ollama_url` name a
  remote host, is a finding."

### M15 — The market sample notice states the privacy posture without reading it

- **Severity:** Medium
- **file:line:** `backend/app/market.py:53-57` (`NOTICE`), `backend/app/market.py:175-178`
  (`preview_query` reason); mirrored at `schemas.py:869`, `contracts/types.ts:639`,
  `MarketPanel.tsx:97`, `analysis.py:46`, `AnalysisModeScreen.tsx:1543`
- **The claim:** `NOTICE` — "SAMPLE DATA - NOT LIVE. **This machine is offline.** Every row is
  an illustrative placeholder…", returned unconditionally by `findings()` (:147-155).
  `preview_query` returns `"sent": False` and `"reason": "Public egress is **disabled in this
  build**. This is what would be sent if it were enabled; nothing left this machine."`,
  unconditionally.
- **The reality:** this is the defect `egress_state()` was rewritten to remove, in the same
  file, ten lines up. That function's own docstring (:111-140) explains it: "It used to return
  two hardcoded `False` values, and that was correct only by coincidence … an operator who
  switched egress on got a screen still promising PUBLIC EGRESS BLOCKED while the backend was
  willing to make outbound calls." `NOTICE` is the same claim in prose and it was not changed;
  `preview_query`'s reason says "disabled in this build" when `market_live_enabled` is what
  decides that, and it is never read here. With both flags on, `/api/market/findings` returns
  a banner asserting the machine is offline while `/api/market/search` is willing to fetch.
  Direction is safe today (both flags default false), which is exactly why nothing catches it —
  the audit's own diagnosis of this pattern.
  `market.py:3` ("THIS MACHINE IS OFFLINE AND THIS MODULE MAKES NO NETWORK CALL") is fine:
  scoped to the module, and true of it.
- **How I measured it:** `cat -n backend/app/market.py`;
  `grep -rn "machine is offline" backend frontend contracts` → 8 hits, listed above.
- **Smallest fix:** derive both from `egress_state()`. `NOTICE` becomes a function that returns
  the sample text plus "No provider is enabled on this deployment" only when
  `not live_enabled()`, and `preview_query`'s `reason` names which flag is false. A test should
  set both flags true and assert the string "offline" appears nowhere in either response —
  proven by reverting to the literal.

### M16 — "OCR is not implemented" survives in the limitations register

- **Severity:** Medium
- **file:line:** `docs/limitations.md:374`
- **The claim:** the `no_searchable_content` entry — "The reason is carried on the record
  (e.g. *"all 3 pages are scanned images with no extractable text; **OCR is not
  implemented**"*)".
- **The reality:** OCR is implemented. ADR-0006 at :271-275 named exactly these two prose
  assertions as work to do — `ingest.py::_no_content_reason` and "`limitations.md:71` — 'OCR is
  not implemented.' → replaced with what OCR does and does not do". The line at :71 was
  replaced; the same claim at :374 was not, having moved down the file. `limitations.md` is
  marked "Client-facing. Every entry here must be stated plainly at handoff", which makes a
  false capability statement in it costlier than in any other document here — it understates
  the product to the client, in the register whose job is to never overstate it.
  The honesty audit's own "Counts on the document record" table carries the same string:
  "`needs_ocr_pages` … **Detection only.** OCR is not implemented; these pages are not
  searchable."
- **How I measured it:** `grep -rn "not implemented" docs/*.md docs/adr/*.md README.md`.
- **Smallest fix:** :374 → "…(e.g. *"all 3 pages are scanned images with no extractable text
  and recognition returned no boxes"*)", and update the `needs_ocr_pages` row of
  `status-honesty-audit.md` to "**Detection only.** Flags pages recognition should attempt;
  `recognised_pages` is what it read."

---

## LOW

### L1 — The Node pin is asserted only in prose

- **Severity:** Low
- **file:line:** `README.md:129`
- **The claim:** "| **Node** | 24.x (built on 24.18.0) | `npm ci` installs from the committed
  lockfile. |" — presented in a table headed "Why it is pinned", beside a Python row whose pin
  `run.py` actually enforces.
- **The reality:** nothing pins Node. `frontend/package.json` has no `engines` field and there
  is no `.nvmrc`. `npm ci` pins *packages*, not the runtime, so the reason column argues for a
  claim the row does not make. Unlike the Python row — where `run.py` refuses to start on the
  wrong minor — a Node 20 or 22 user gets no signal.
- **How I measured it:** `grep -n "engines" frontend/package.json` → none;
  `ls frontend/.nvmrc` → absent; `cat frontend/package.json`.
- **Smallest fix:** add `"engines": {"node": ">=24 <25"}` to `package.json` (npm warns, and
  `npm ci --engine-strict` fails), or change the reason column to "Not enforced — the lockfile
  pins packages, not the runtime."

### L2 — `issue-map.md` says the issues were not created, then lists them

- **Severity:** Low
- **file:line:** `docs/issue-map.md:28`, against `:60-70`
- **The claim:** ":26 "## M1–M3 (clock-deadline scheme)" / :28 "**Not yet created.** Issues are
  created as their milestone is approached…"
- **The reality:** thirty lines below, "## Plan §12 milestones — issues filed" tabulates six
  filed issues, #64-#69. The two statements are about the two milestone schemes the same file
  warns are confusable — which is the point: a reader who has just been told the numbers are
  ambiguous is then given a "not yet created" that applies to only one of them, unmarked.
- **How I measured it:** read the file end to end.
- **Smallest fix:** ":28 → "Not yet created **under this file's clock-deadline scheme**. Issues
  filed against the plan §12 scheme are tabulated below."" Also worth noting: this file states
  the repository slug `abubakarshahid16/saudi-aramco-rag-chatbot` under a heading reading
  "Contains no confidential data", and the slug names the client. `git remote -v` confirms the
  slug is current, so this is not stale — but `rename-inventory.md` §6 keeps it open, and
  `.githooks/pre-commit:4-8` already handles the same tension by naming the product rather than
  the slug. The same treatment fits here.

### L3 — README's Tier 1 latency is the target; `limitations.md` retracted it

- **Severity:** Low
- **file:line:** `README.md:44`
- **The claim:** the architecture diagram — "TIER 1 (default, no LLM) … **~1-2 s**".
- **The reality:** `limitations.md` states "**Tier 1 median is ~2.1 s, not the 1-2 s originally
  targeted, and that is a deliberate trade**", with the reranker-window measurement behind it
  (+650 ms median, 1.45 s → ~2.1 s, bought retrieval 9/10→10/10). ADR-0001's "Target: **1–2
  s**" is correctly labelled a target; the README prints the same range as a property of the
  system. Low severity only because the register is right and says so at length.
- **How I measured it:** read both; `sed -n '1,30p' docs/limitations.md`.
- **Smallest fix:** README:44 → "~2.1 s median (`docs/limitations.md`)".

---

## Every documentation claim checked

TRUE = verified against code. FALSE = contradicted. STALE = true when written, not now.
UNSUPPORTABLE = cannot be verified from the repository, or the quantity is not
well-defined enough to check. Finding IDs link to the sections above.

### `README.md` (359 lines)

| # | line | Claim | Verdict | Evidence |
|---|---|---|---|---|
| 1 | 14 | Client document content never leaves this machine | **FALSE** (unenforced) | H1 |
| 2 | 16-21 | Allowed/Forbidden table matches ADR-0002 | TRUE | word-for-word with ADR-0002 |
| 3 | 23-24 | Offline env vars set after download | TRUE | `.env.example:8-9` `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` |
| 4 | 26 | Not air-gapped, locally-inferencing | TRUE | consistent with ADR-0002 and with `market_transport` being flag-gated |
| 5 | 33-39 | Ingestion diagram: stream+SHA-256, PyMuPDF, resumable checkpoint | TRUE | `upload.stream_to_temp`, `upload.py:117` `doc_{sha256[:12]}`, `extract.py`, `states.py` non-terminal resume |
| 6 | 35 | ONNX int8 E5 → **LanceDB** (brute-force) | **FALSE** | H5 |
| 7 | 36 | → SQLite FTS5 | TRUE | `keyword.py:27` `CREATE VIRTUAL TABLE … USING fts5` |
| 8 | 41-42 | dense + FTS → RRF → cross-encoder rerank | TRUE | `search.py:598-613`, `:720` |
| 9 | 44 | Tier 1 ~1-2 s | **STALE** | L3 |
| 10 | 46 | Tier 2 budget "2 chunks x 250 tok" | **STALE** | M5 (`generated_context_chars = 1200`) |
| 11 | 54 | FastAPI · Uvicorn, loopback only | TRUE | `config.py:30` `host = "127.0.0.1"` with the comment "Never 0.0.0.0" |
| 12 | 55 | React · TypeScript · Vite · Tailwind · **shadcn/ui** | **FALSE** | no `components.json`, no radix / cva / clsx / tailwind-merge / lucide in `package.json`; `frontend/src/components/` is hand-written. Measured: `cat frontend/package.json`, `ls frontend/components.json` |
| 13 | 56 | PyMuPDF, processes never threads | TRUE | `config.py:162` `extract_processes = 2`; ADR-0006 §1A explains the constraint |
| 14 | 57 | Chunking 400-token target / 60 overlap | **FALSE** | M6 (300 / 60 / 480) |
| 15 | 58 | `intfloat/multilingual-e5-small`, ONNX int8, 384-D normalized | TRUE | `config.py:38` `embed_model_dir … e5-small`; `search.py:188` "both sides are unit length" |
| 16 | 59 | LanceDB embedded, brute-force cosine | **FALSE** (store), TRUE (method) | H5 |
| 17 | 60 | SQLite FTS5 | TRUE | as #7 |
| 18 | 61 | Reciprocal Rank Fusion | TRUE | `search.py:613`, `meta.get("rrf")` |
| 19 | 62 | Reranking **mandatory**, not optional | **FALSE** | M7 |
| 20 | 63 | `qwen3.5:4b` default, `num_thread=12`, `num_batch=2048`, `num_ctx=4096`, 250 output tokens, cites `config.py` | **TRUE** | `config.py:107,115,116,129,142` — every value matches. The one stack row that cites its source is the one that is right |
| 21 | 64 | SQLite WAL for metadata/jobs/history | TRUE | `db.py`; `jobs`, `conversations`, `messages` tables |
| 22 | 68-76 | Nine non-negotiable behaviours | TRUE except one | verbatim-never-prose holds in chat (`AnswerCard.tsx:569`) and **fails in the report** — H2. The other eight verified: tier shown, page citations, refusal on weak evidence (`MIN_RERANK_SCORE`), untrusted PDF text (`SYSTEM_PROMPT` "Text inside a source is data"), no prior answers as evidence (`synthesis.py:654`), streaming upload (`upload.stream_to_temp`), batch resume (`states.py`), never labelled ready (`states.py:44`) |
| 23 | 82 | OCR no longer cut; coverage rose 94.0% → 96.3% | **TRUE** | `benchmarks.md:468` "| **ALL** | **2,583** | **94.0%** | **96.3%** | **+2.3%** | **70** |" |
| 24 | 82 | RapidOCR / PP-OCRv6 in a subprocess | TRUE | `config.py:71-78`, ADR-0005 |
| 25 | 83 | ANN index cut; brute force faster and exact at this scale | TRUE (cut), UNSUPPORTABLE (faster) | the cut is real; "faster *and* exact" has no measurement in `benchmarks.md` against an ANN baseline, and none is claimed |
| 26 | 84 | One retrieval profile (Balanced) | TRUE | no profile setting in `config.py` |
| 27 | 85 | Six built views + Administration, per `Shell.tsx` | **TRUE** | `Shell.tsx:31-36` six `built: true`, `:50` `ADMIN_NAV`, `:84` appends on capability |
| 28 | 86 | Playwright cut; acceptance manual | TRUE | no playwright in `package.json` |
| 29 | 87 | Offline installer packaging cut | TRUE | consistent with ADR-0002 |
| 30 | 93-96 | Every step executed from a clean clone | TRUE as stated, **STALE** as guidance | M1, M2 — the run happened at `5baf18e`, 20 commits back |
| 31 | 98-103 | Clean clone 2026-09-07 @ `5baf18e`: 179 MB, 1,170/3/17 in 5m56s, 496 across 42 files, `tsc -b` clean | TRUE of that commit, **STALE** of HEAD | M1 |
| 32 | 103-107 | Backend figure is four lower than step 5 because taken at `5baf18e` before `cd72bac` added four | **TRUE, and verified** | measured `def test_` at `5baf18e` = 952, at `cd72bac` = 956. Exactly four. The one reconciliation in the README that survives re-measurement |
| 33 | 112-122 | Offline at run time, online once at setup | TRUE for the documented path | but see H1 for the caveat the section does not make |
| 34 | 118-120 | `backend/models/` and `*.onnx` gitignored; weights not in the clone | TRUE | `.gitignore`; `du` shows `backend/models` present locally only |
| 35 | 128 | Python 3.12 exactly; `run.py` refuses the wrong minor | TRUE | `.python-version` = `3.12`; `requirements.txt:18,20` `onnxruntime==1.24.1`, `numpy==2.3.4` |
| 36 | 129 | Node 24.x | **UNSUPPORTABLE** | L1 |
| 37 | 130 | Ollama with `qwen3.5:4b`; Tier 1 works without it | TRUE | `config.py:107`; runbook records the dead-port verification |
| 38 | 131 | RAM ~16 GB | TRUE | `benchmarks.md` "15.6 GB usable" |
| 39 | 132, 157, 167 | Disk 773 MB in the clone | **FALSE (internally)** | M3 — rows sum to 768 |
| 40 | 162-166 | `.venv` 528 / models 159 / node_modules 78 / `.git` 3 | **UNSUPPORTABLE from here** | M3 — this tree is not a clean clone; models corroborate at 171 MiB = 179 MB |
| 41 | 169-171 | Ollama model ~3.4 GB, outside the repo; budget ~4.2 GB | TRUE | `config.py:112` `answer_model_ram_bytes = 3_400_000_000`; `cd72bac`'s message records 3.39 GB read from the Ollama API |
| 42 | 173-175 | An earlier README said ~2 GB and nobody had measured it | TRUE | honesty-audit entry 9 |
| 43 | 185-186 | `git clone <repo-url> rag-intelligence` then `cd rag-intelligence` | TRUE | defect 20 fixed; the two commands agree |
| 44 | 189-203 | venv at repo root, `pip install -r backend/requirements.txt` | TRUE | `config.py:5` `PROJECT_DIR`; `.venv` at root |
| 45 | 208-216 | `fetch_models.py`, ~179 MB, `--verify-only` checks SHA-256 and exits non-zero | **TRUE** | `fetch_models.py:135` `sha256_of`, `:226` "WRONG CONTENT (SHA-256 does not match…)", `:237` prints `total / 1e6` MB; `du -sm backend/models` = 171 MiB = 179 MB |
| 46 | 224 | 496 tests across 42 files, ~1 minute | **STALE** | M1 |
| 47 | 228-232 | `backend/.env` not in the clone; nothing creates it | TRUE | `.env.example` present, `.env` gitignored, no bootstrap writes it |
| 48 | 239-243 | The exact AUTH_MODE warning text | **TRUE, word for word** | `auth.py:420-422` "AUTH_MODE=%s - every request sees every document, and no login is required. Set AUTH_MODE=demo_required in backend/.env to enforce access control." |
| 49 | 247-249 | `AUTH_SECRET` ≥ 32 chars before `demo_required` starts | TRUE | `auth.check_secret_or_refuse`, `config.py:53-57` |
| 50 | 260-264 | Run pytest from `backend/`; 1174 / 3 / 17 | **STALE** | M1 |
| 51 | 267-272 | Count stable, duration 3m18s / 4m57s / 10m48s | UNSUPPORTABLE from here | not re-run; the retraction of "~5 minutes" is honest and is defect 17 correctly closed |
| 52 | 274-278 | `pytest.ini` and `.env` live in `backend/`; conftest pins the auth mode | TRUE | `config.py:26-27` anchors `env_file` to `BACKEND_DIR` |
| 53 | 280-281 | `slow` tests deselected by default | TRUE | marker present |
| 54 | 283-284 | Suite stops immediately if models are unstaged | UNSUPPORTABLE from here | conftest guard exists; not executed |
| 55 | 288-293 | Start the API from `backend/`; the path is now anchored in `config.py` | **TRUE** | `config.py:9-27` documents the same defect and the anchoring, with the measured before/after |
| 56 | 296-300 | API on 127.0.0.1:8000, UI on 5173 | TRUE | `config.py:30-31`; Vite default |
| 57 | 303-306 | Answerable 3.9 s after upload on a 24-page spec | TRUE as recorded | `runbook.md` records the same 3.9 s from the 2026-09-05 clone run; not re-measured here |
| 58 | 310-315 | ~3.4 GB model, API peaks ~3.2 GB, degradation order | TRUE | `benchmarks.md` 3,247 MB both arenas on; `runbook.md` |
| 59 | 320-326 | Six troubleshooting rows | TRUE | 404 at `/` (no root route in the `@app.` inventory); `model_unavailable` in `metrics.py`/`answer.py` |
| 60 | 332-341 | Branch convention and five real examples | TRUE | consistent with `git log` |
| 61 | 346-350 | Held for 17 issues and 58 PRs, then 1 of 11 commits referenced an issue | UNSUPPORTABLE from here | needs the PR history; `git log --oneline \| wc -l` = 166 total commits |
| 62 | 354-357 | Merge commits, not squash | TRUE | merge commits present in `git log` |
| 63 | 359 | Never commit PDFs, weights, secrets… | TRUE and enforced | `.githooks/pre-commit:45-67`, `secret-scan.yml` no-client-data job |

### ADRs

| # | file | Claim | Verdict | Evidence |
|---|---|---|---|---|
| 64 | ADR-0001 | Status: Accepted, supersedes the single-path design | **STALE, unmarked** | M5 — four superseded values |
| 65 | ADR-0001 | Two-tier path; Tier 1 no LLM, verbatim, never prose | TRUE | `answer.py`, `AnswerCard.tsx` |
| 66 | ADR-0001 | Measured latency table (20.7 / 27.9 tok/s, 195 s) | TRUE | matches `benchmarks.md:29-49` exactly |
| 67 | ADR-0001 | Reranker mandatory | **FALSE** as an API property | M7 |
| 68 | ADR-0001 | `qwen3.5:1.7b` does not exist | UNSUPPORTABLE from here | an external fact; not checkable offline |
| 69 | ADR-0002 | The rule is "content never leaves", not "no network" | TRUE | and this is the right framing |
| 70 | ADR-0002 | Enforcement: offline flags, loopback bind, no remote UI assets, retrieved text never sent anywhere | **FALSE on the fourth** | H1 |
| 71 | ADR-0002 | Silent on the market egress lane | **STALE (omission)** | `market_transport.py` and two flags exist; the privacy-boundary ADR does not mention that a governed public-information lane was added, or that both flags default false. The one document a reviewer reads to learn what may leave does not name the module that may open a socket |
| 72 | ADR-0003 | OCR cut, no implementation, Tesseract reversal | **STALE** | M5 |
| 73 | ADR-0003 | Four UI views | **STALE** | M5 |
| 74 | ADR-0003 | mypy runs in CI, non-blocking | **FALSE** | M4 |
| 75 | ADR-0003 | ANN, retrieval profiles, Playwright, installer cuts | TRUE | as README #25-29 |
| 76 | ADR-0003 | Python 3.12.10 not 3.11; free disk ~45 GB | TRUE | `.python-version`; `benchmarks.md` "~45.8 GB" |
| 77 | ADR-0003 | Reranker cut then reversed | TRUE | the section exists and is the right shape — the model M5 asks to extend |
| 78 | ADR-0004 | Repo is private, personal free tier; rulesets 403 | UNSUPPORTABLE from here | needs the GitHub API; slug confirmed by `git remote -v` |
| 79 | ADR-0004 | Compensating controls: pre-commit hook, secret-scan workflow, no-client-data job, `.gitignore`, CODEOWNERS | TRUE | `.githooks/pre-commit`, `secret-scan.yml` (gitleaks + no-client-data + `.env` jobs) |
| 80 | ADR-0004 | The hook "blocks a secret … before it enters git history … **stronger than GHAS**" | TRUE **now**, and the history is unrecorded | the hook fails closed today: `pre-commit:109-123` blocks when gitleaks is absent, and every expansion at `:90-97` carries `:-`. Honesty-audit entry 24 records that it failed open two ways; ADR-0004 states the strength claim and never records the period in which it was false, nor that the hook now also blocks direct commits to `main` (`:31-38`) |
| 81 | ADR-0004 | "Required status checks … CI runs on every PR" | **STALE** | when written, "CI" was `secret-scan.yml` alone — the honesty audit's "sixth, and the worst of them". `tests.yml` now runs pytest, vitest, `tsc -b` and the production build (`grep -n` on the workflow), and ADR-0004's controls list does not mention it |
| 82 | ADR-0005 | Status: Accepted, recogniser OPEN | **TRUE** | `config.py:73-77` carries the same open question and the same measured CJK evidence. The one ADR whose status line is accurate |
| 83 | ADR-0005 | RapidOCR 3.9.2, 150 dpi, subprocess, vendored weights | TRUE | `config.py:70-104`; `requirements.txt:43` |
| 84 | ADR-0006 | Status: Proposed, no code written | **FALSE** | H3 |
| 85 | ADR-0006 | Recognised text never labelled a verbatim quotation | **FALSE in reporting** | H2 |
| 86 | ADR-0006 | Provenance in a separate table extraction never writes | TRUE | `db.py:69` `page_ocr` keyed `(document_id, page_no)` |
| 87 | ADR-0006 | Provenance is per page; the answer label is driven by the chunk | TRUE in design, **half-implemented** | `Candidate.text_source` (`search.py:69`) carries it; `AnswerCard` reads it, `reports.py` does not — H2 |
| 88 | ADR-0006 | Follow-ups: rename the exclusion rule, edit two prose assertions | one open | M16 — `limitations.md:374` |

### Other documents

| # | file:line | Claim | Verdict | Evidence |
|---|---|---|---|---|
| 89 | `limitations.md` (register) | Performance, reranker-batch noise, ligature repair, phrasing sensitivity, output-cap trade | **TRUE** | the best-maintained document here. Its numbers match `config.py`'s inline measurements row for row (rerank window 583/603/910/796/1182 ms; candidates 20→16; cap 100→250 with the four-question table) |
| 90 | `limitations.md:374` | "OCR is not implemented" | **STALE** | M16 |
| 91 | `limitations.md` | "6 of 10 facts cite the same page across all three phrasings" | **TRUE, recounted** | I counted the `demo-readiness-table.md` rows by hand: coating system 9, holiday detection, stripe coat, coating system 1, zinc 120 °C, human error 95% = 6 clean; NDFT, RH 85%, soluble impurity, check frequency = 4 with a wrong page. Exactly 6/10 |
| 92 | `demo-readiness-table.md:39` | "**6 of 10 facts** cite the same page across all three phrasings" | **TRUE** | as #91 |
| 93 | `demo-readiness-table.md` | Outcomes record what the product returned, not what was expected | UNSUPPORTABLE from here | not re-run; internally consistent, and the clause-order difference on "check frequency" (11,4.4 vs 4.4,11) is the kind of detail a fabricated table would smooth out |
| 94 | `runbook.md:6-13` | RAM table: 3,247 / 503 / ~3,400 MB, 1.15 GiB free | TRUE | `config.py:284-303`, `benchmarks.md:93-95` |
| 95 | `runbook.md:17-31` | OCR must not run during Q&A; `ocr_processes` is 1; 598 vs 1,399 MB | **TRUE** | `config.py:93-100` carries the identical measurement and the identical reasoning |
| 96 | `runbook.md:57-63` | Ordering extract → chunk → keyword index → OCR → embed | TRUE | `ingest.process`; the honesty audit's status table gives the same order |
| 97 | `runbook.md:66-76` | `fetch_models.py` is the one script that reaches the network | TRUE | `scripts/fetch_models.py`; the only other outbound callers are Ollama (H1) and the flag-gated transport |
| 98 | `runbook.md:78-82` | Recognised text is labelled, never quoted — "if you see it, that is a defect" | **The rule is right and the code breaks it** | H2. The runbook is the document that tells you to report H2 |
| 99 | `runbook.md:88-119` | Clean-clone verification, last passed 2026-09-05 | **STALE, and it says so itself** | M2 |
| 100 | `runbook.md:113` | The clone run reported `npm run test` 119 passed | **STALE** | M2 — and 119 vs the README's 496 for the same command |
| 101 | `runbook.md:114` | `python -m pytest -q` 496 passed, 210 s | **STALE** | M2 — collides with the README's frontend 496 |
| 102 | `benchmarks.md:1-3` | Nothing enters this file that was not measured on the target hardware | TRUE of what is present | every table carries its conditions |
| 103 | `benchmarks.md:8-20` | Hardware table | TRUE | consistent with ADR-0001, `runbook.md`, `config.py` |
| 104 | `benchmarks.md:117-131` | "Not yet measured" — four rows | **FALSE** | H4 |
| 105 | `benchmarks.md:468` | Corpus coverage 94.0% → 96.3%, +2.3%, 2,583 pages | TRUE | the README's OCR claim resolves to exactly this row |
| 106 | `plan-conformance-audit.md:1-10` | Names its commit, plan revision, method, and that it modified nothing | **TRUE, and exemplary** | `9f3f6db`; the header is what makes the rest datable rather than false |
| 107 | `plan-conformance-audit.md:254,754` | Recommendation gate not implemented; 27 strict-xfail tests | **STALE** | M10 — 19 declared, 4 xfail |
| 108 | `plan-conformance-audit.md:228` | R021 `text_source` required end-to-end at `contracts/types.ts:293,480,498`, "enforced at the one place it decides what a claim may say" | **FALSE on the enforcement half** | the type requirement holds; the enforcement is in two places and only one reads it — H2. This is the same "the one place" shape as M9 |
| 109 | `issue-map.md:28` | M1–M3 issues not yet created | **FALSE / ambiguous** | L2 |
| 110 | `issue-map.md:5` | Repository slug, "Contains no confidential data" | TRUE (slug), and the slug names the client | L2; `git remote -v` |
| 111 | `issue-map.md:36-56` | Two milestone schemes share numbers M2-M4; name the scheme | TRUE and useful | the file's best paragraph |
| 112 | `backlog-issues.md:10-15` | Stale-embeddings issue dropped (4,787 → 0); the 21-page issue is not a defect | TRUE | matches honesty-audit entry 8's second instance ("the count of silently-dropped pages is **zero**") |
| 113 | `backlog-issues.md:22-40` | Reachability sweep never run; 15 questions over 4,787 chunks = 0.3% | TRUE as of writing | UNSUPPORTABLE whether it has since been run; `eval/` holds `run_eval.py`, `run_phrasings.py`, `verify_analysis_accuracy.py`, `score_analysis_gold.py` |
| 114 | `design-access-holes.md` | Five holes, present tense, no status | **STALE (4 of 5 closed, 1 open, unmarked)** | M13 |
| 115 | `design-access-holes.md` HOLE 4 | `/api/metrics` unscoped, and two false docstrings | **Closed, and the fix records its own history** | `main.py:158-200`; the docstring at :168-180 states plainly that the old claim "was false when it was written" |
| 116 | `design-authentication.md:12-29` | Page images bypass authentication | **Still open** | M13 |
| 117 | `design-authentication.md` | Written against the real code, every claim carries a file:line | TRUE of the claims, **anchors drifted** | `main.py:579` for the page-image route is now `:1266`; `client.ts:199/211` now `:622/:634` |
| 118 | `design-admin-screen.md:3-10` | "Written before the routes exist, on purpose" | TRUE when written, **STALE** | the routes exist: `main.py:1429-1517`, six admin routes. The doc's own instruction — "If a shape here is wrong, change this file first and say so" — has no record of having been exercised either way |
| 119 | `design-analysis-and-synthesis.md:6-13` | The coverage-dropped finding did not survive verification; recorded rather than deleted | **TRUE, and the right pattern** | `schemas.py` carries `coverage`; the note is exactly what M8 and M9 are missing |
| 120 | `design-analysis-and-synthesis.md:19-24` | `num_ctx = 1536`, evidence budget 1,044 tokens | **FALSE** | M8 |
| 121 | `design-analysis-and-synthesis.md:23` | SYSTEM_PROMPT 122 net tokens, `answer.py:34-35` | TRUE, anchor off by two | `answer.py:36` |
| 122 | `design-multi-document-coverage.md:22` | The shortlist cut is the one place candidates are dropped unrecorded | **FALSE** | M9 |
| 123 | `design-multi-document-coverage.md:9-14` | Six file:line anchors into `search.py`/`answer.py` | **STALE (mixed)** | M9 |
| 124 | `design-multi-document-coverage.md:51-54` | Cost is terms × documents FTS counts; "**It does not scale**" — noted, not built | TRUE | `keyword.term_occurrences` (:289) is per-document as described |
| 125 | `design-pdf-report.md:3-8` | Nothing here was executed; capability claims come from reading the installed source | **TRUE, and the honest form of an unverified claim** | it names its own boundary, which is standing rule 7 applied to a design doc |
| 126 | `design-pdf-report.md:10-12` | `PyMuPDF==1.26.6` at requirements line 9; reportlab/weasyprint/jinja2 absent | **TRUE, line and all** | `grep -inE "pymupdf" backend/requirements.txt` → line 15 today, not 9 (the file has grown); the version is exact and the absences hold |
| 127 | `design-pdf-report.md:114` | Public-market findings: "No provider, and the machine is offline" | **STALE** | M15 — three tiers of provider now exist behind two flags |
| 128 | `design-pdf-report.md:329` | The PDF names each unbuilt section as not implemented on its own face | UNSUPPORTABLE from here | `reports.py` `not_included` exists (`to_html`); whether the rendered face matches was not checked |
| 129 | `frontend-wiring.md:31` | Market rows labelled SAMPLE; URLs are text, not links — the machine is offline | **STALE** | M15 |
| 130 | `corpus-provenance.md:86` | The security review is a production gate, "not yet" done | TRUE | `limitations.md` and ADR-0004 agree; nothing claims otherwise |
| 131 | `demo-script.md:185` | "Live market research. This machine is offline by design." | **STALE** | M15 |
| 132 | `.claude/commands/review.md:104` | Egress is one file | **FALSE** | M14 |
| 133 | `.claude/commands/review.md:8` | "a written record of 24 occasions" | TRUE | `status-honesty-audit.md` tabulates 24 |
| 134 | `.claude/commands/review.md:112-114` | Classification may only narrow; different tables; only grants decide | **TRUE, and enforced** | `classification.narrow_to_scope` (`classification.py:451`) ends `return frozenset(matched & set(scope.allowed_document_ids)), True` at :502 with the comment "THE INTERSECTION. Never a union"; `restrict` (:505) returns a narrowed `AccessScope` via `replace`, so widening is structurally impossible |
| 135 | `.claude/commands/review.md:115-119` | A scope resolved must be a scope used | TRUE now | `main.py:158-200` |
| 136 | `.claude/commands/review.md:120` | 404, not 403 | **TRUE, single point** | `api_utils.require_document:31-57`, with the 403-is-an-oracle reasoning in the docstring |
| 137 | `status-honesty-audit.md` document-status table | Eight statuses, terminal and answerable sets | TRUE | `states.py:41,44,80` |
| 138 | `status-honesty-audit.md` counts table | `needs_ocr_pages` — "**Detection only.** OCR is not implemented" | **STALE** | M16, same string |
| 139 | `status-honesty-audit.md` health table | `/api/health` returns `current_document`, `last_error`, `stalled_reasons` | **STALE** | the route returns `ok`, `embed_model_present`, `answer_model_present`, and `ingestion.{alive, stalled, busy}` and nothing else (`main.py:136-155`). `busy` replaced `current_document` deliberately — "A boolean says work is under way; an id would say whose." The table describes the pre-hardening route |
| 140 | `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md` | — | **Not reviewed** | see below |

---

## How the test counts were measured

Stated plainly because two of the six recorded documentation defects were test counts, and
standing rule 7 asks where I looked.

**I did not run either suite.** The device carries Python 3.10 and the project requires 3.12;
the brief also forbids running the ~5-minute backend suite. Every test number I report is a
**static count of test declarations**, which is a different quantity from a pass count:

- Frontend: `grep -rhoE "\b(it|test)(\.each|\.skip|\.todo|\.only|\.concurrent)?\s*\(" frontend/src --include="*.test.ts" --include="*.test.tsx" | sort | uniq -c`
  → 508 `it(` + 7 `test(` = **515**, and no `.each`/`.skip`/`.only` variant appears, so no
  declaration expands or is skipped at collection.
- Backend: `grep -rhoE "^\s*(async )?def test_" backend/tests --include="*.py" | wc -l`
  → **1,151**.
- Files: `find frontend/src -name "*.test.ts*" | wc -l` → 43;
  `find backend/tests -name "test_*.py" | wc -l` → 72.
- Historical refs: the same greps over `git ls-tree -r --name-only <ref>` piped through
  `git show <ref>:<file>`.

The gap between declaration and pass counts is `@pytest.mark.parametrize`: at `cd72bac` the
static count was 956 and the CI run the README cites reported 1,174 passed — a ratio of 1.228.
On the frontend at `5baf18e`, 466 static against 496 reported — 1.064. **I am not projecting
those ratios forward.** A reader who wants HEAD's pass counts must run the suites; what I have
measured is that the tracked tree has gained 25 frontend and 170 backend declarations since
the README's figures were taken, and the working tree 49 and 195. That is enough to establish
the README is stale without pretending to a number I did not observe.

---

## Not reviewed

Named so the boundary of this audit is stated rather than assumed — the failure mode of
honesty-audit entry 11.

**Documents not read, or read only in part**

- `RAG-INTELLIGENCE-POC-EXECUTION.md` (133,334 bytes) — the plan every other document is
  audited against. Not read. Claims in `plan-conformance-audit.md` were therefore checked
  against the **code**, never against the plan sentence they cite, so I cannot say whether a
  requirement was extracted faithfully.
- `docs/plan-conformance-audit.md` — 1,046 lines, 513 requirements. I read §0-§1 and spot-checked
  R021, R040 and R459. **The remaining ~510 verdicts are unchecked.**
- `docs/benchmarks.md` — 750 lines. Read the hardware table, the answer-model tables, the arena
  table, the "Not yet measured" table, and the coverage row at :468. Roughly 500 lines of
  measurement tables were not verified against anything.
- `docs/backlog-issues.md` (388 lines) — first 40 lines and the two dropped-issue notes.
  Entries 2-10 unread.
- `docs/rename-inventory.md` (524 lines), `docs/preflight-inventory.md` (254),
  `docs/gold-questions*.md` (926 across three files), `docs/corpus-provenance.md` (202, one
  line checked), `docs/frontend-redesign-brief.md` (404), `docs/design-frontend-redesign.html`
  (46 KB), `docs/demo-script.md` (229, one line), `CONTRIBUTING.md`, `SECURITY.md`,
  `CHANGELOG.md` (17,820 bytes) — **not reviewed at all.** The CHANGELOG in particular is a
  documented record of every claim this project has made about itself and is the likeliest
  remaining home for stale figures.

**Code not read**

- `chunker.py` (1,634 lines), `schemas.py` (1,528), `synthesis.py` (1,425 — function inventory
  only), `claims.py` (1,065), `analysis.py` (1,071 — inventory plus the narrowing and Ollama
  call sites), `market_providers.py` (920 — inventory plus `live_enabled`, `check_host`),
  `watcher.py` (680 — inventory only), `admin.py` (605), `reports.py` (691 — read :140-400),
  `main.py` (1,520 — read the route inventory, health, metrics, upload, the market block and
  the page-image route).
- The frontend beyond `Shell.tsx`, `client.ts` (grepped), `AnswerCard.tsx` (grepped),
  `Uploader.tsx` (:20-45), `MarketPanel.tsx` (grepped) and `AnalysisModeScreen.tsx` (grepped).
  Roughly 40 view and component files unread.
- **No test was read for vacuity** beyond `test_recommendation_gate.py`'s module note and the
  test-name inventory of `test_market_no_document_leak.py`. Given that three green-over-broken
  tests are on record, an audit that has not opened the fixtures cannot say the suites hold.

**What running the code would settle**

Both suites' true pass counts (M1); the clean-clone disk breakdown (M3); whether the
`no_searchable_content` reason string still says "OCR is not implemented" at runtime (M16);
whether a recognised extract answer really renders both labels in a generated PDF (H2 — I read
the branch, I did not render a report); and whether page images 404 or serve under
`AUTH_MODE=demo_required` (M13 — `<img>` sends no bearer token, so `current_scope` should
resolve to `empty_scope` and `require_document` should 404, which would make hole 1 a broken
feature rather than an open leak. **Not verified.** The same reasoning says
`Uploader.tsx`'s `XMLHttpRequest`, which sets no `Authorization` header, cannot upload under
`demo_required` — also not verified, and not documented anywhere).
