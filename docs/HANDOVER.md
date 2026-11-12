# HANDOVER — RAG Intelligence System

**Purpose of this file.** Give it to any Claude session (Cowork, Claude Code, a
web chat) and it can continue the work without losing context. Everything below
is stated as of **2026-09-08**, branch `feat/phase-1-ui-reaches-backend`, HEAD
`d5357a3`. Where a fact could go stale, the command to re-check it is given.

Read `CLAUDE.md` first for the standing rules. This file is the state.

---

## 1. What the project is

An offline, privacy-first RAG system for engineering documents, built for an
oil-and-gas client (the client's name must not appear in the product; the GitHub
slug still carries it and only the owner can rename it). Engineers ask a
question and get: the document's own words with page citations (Chat), a
cross-document summary + gap analysis against a nominated baseline + advisory
recommendation (Analysis), frozen-evidence PDF reports, a watched folder that
ingests PDFs automatically, and a gated public "market intelligence" lane.

**The client's actual job-to-be-done is reviewing contractor submittals against
specifications.** Gap analysis (baseline = the specification) is the engine for
that; a dedicated submittal workflow is not built yet.

**Stack.** Python 3.12 + FastAPI (loopback only) · React 19 + TypeScript + Vite +
Tailwind v4 · PyMuPDF · e5-small ONNX int8 embeddings · cross-encoder reranker ·
SQLite WAL + FTS5 · Qwen3.5:4b via Ollama · RapidOCR. Hardware today: i7-1255U,
16 GB, no GPU (the user has said better hardware is coming; do not optimise for
the laptop).

**Repo.** `D:\project\Rag_chatbot` on Windows machine "abubakar" ·
`github.com/abubakarshahid16/saudi-aramco-rag-chatbot` · plan file
`RAG-INTELLIGENCE-POC-EXECUTION.md`.

**People and lanes.**
- Ali Zulqarnain (user) — approves, demos, flips `.env`, owns GitHub actions.
- Claude Code in VS Code — backend, git, GitHub. Receives prompts written by Cowork.
- Cowork (Claude desktop) — frontend, tests, docs, design canvases, code review,
  writing the VS Code prompts. Standing instruction from Ali: *"give me a VS
  prompt, don't do yourself all GitHub work."*

---

## 2. Current state of the working tree

**As of 2026-09-08, after the second pass: the tree is CLEAN, and the three
newest commits are NOT yet pushed.** Branch `feat/phase-1-ui-reaches-backend`.
Draft PR: https://github.com/abubakarshahid16/saudi-aramco-rag-chatbot/pull/70

Read the second table below before the first: the first records the save pass
(pushed, HEAD was `26e54ce`), the second records what happened after it.

```
git --no-optional-locks status --porcelain     # re-check
```

Five commits were made:

| Commit | What |
|---|---|
| `75cc6fc` | `docs:` review register, architecture, handover, CLAUDE.md, NEW-MACHINE-SETUP, /review command |
| `64c992c` | `feat(classification):` frontend type filter, grouping, admin confirm — **WIP, do not merge**, known defects named in the message |
| `29366b8` | `fix(analysis):` recommendation runs after summary resolves (+14/−5) |
| `9484e5f` | `fix(frontend):` page images fetched with the bearer header — **no tests yet** |
| `26e54ce` | `test(parked):` relevance floor + typo tolerance, module-level skip (both were red at fixture setup on a function that lives only in the stash) |

**MEASURED test state at that point** (this replaces the earlier estimate,
which was wrong):

- **Frontend: 108 failed, 434 passed of 542.** **101 of the 108 are ONE crash**
  at `DocumentsView.tsx:298` reading `types.length` on a vocabulary body that
  has none. Files that never touch classification fail only because they render
  the app, whose first view is Documents.
- **Backend: 8 failed, 1428 passed.** All 8 are environmental: this machine's
  `.env` has both market flags ON while those tests assert flags-off behaviour.
  No backend code changed in the save pass.

**Committed 2026-09-08, second pass.** Everything described above as
uncommitted is now IN. Three commits, all authored by Cowork and committed by
VS Code, which verified them but did not write them:

| Commit | What |
|---|---|
| `3ae8499` | `fix(privacy):` the answer model's socket is checked, not assumed — review P1 #4 |
| `a90677a` | `fix(classification):` both P0 frontend defects and the `ClassificationSource` wire drift |
| this one | `docs:` this section, corrected |

**P1 #4 is CLOSED.** `settings.ollama_url` was an unvalidated `.env` string
that four call sites formatted their own URL from, and the body carries
retrieved passage text verbatim. There is now a `model_transport.py` — the only
module besides `market_transport.py` allowed to open a socket — and
`config.check_model_url`, which parses with `urllib` rather than string
splitting, refuses a non-loopback host, and runs both at startup and again
immediately before every request. A remote host needs two settings and writes
an audit row. `test_socket_containment.py` globs the whole `app/` package, so a
new module that opens a socket is red without anyone maintaining a list.
Retraction 25 is recorded.

**MEASURED after those two commits** (one full run each, not estimated):

- **Frontend: 14 failed, 528 passed of 542.** Down from 108. The P0 #2 fix
  cleared 94, because 101 of the 108 were the single `types.length` crash
  inherited by every file that renders `<App>`.
- **Backend: `test_socket_containment.py` 38 passed.** The full backend suite
  has NOT been re-run since these commits.

**Still to fix before this branch can leave draft:**
1. **UPDATE, 2026-09-11 (commits `6a4b5fa`, `593d5e1`), everything below this
   paragraph in §2 is now stale.** `DocumentsView.test.tsx` had four real,
   root-caused defects, all fixed: `await user.click(...)` never resolved for
   buttons in this tree (`fireEvent.click`/`fireEvent.keyDown` do — swapped
   throughout the file); `renderDocuments()` always passed the static
   `onlineConnection`, so a test overriding `mockApi`'s `health` changed
   nothing WorkerPanel could see (the stalled-worker test asserted against
   health nothing rendered from); two heading-name regexes didn't match this
   screen's own aria-label shape (comma, not `\s`) and one silently bound to
   the wrong heading; `getByText(/Awaiting a type/i)` was ambiguous (group
   heading, filter chip and card chip all say it). **A genuine cross-test
   race remains, NOT fixed**: the identical suite run twice back to back
   fails a different, overlapping subset each time, in tests whose
   assertions follow a `renderDocuments()` that fires several concurrent
   fetches (metrics+documents, vocabulary+coverage, per-document
   classification). Full frontend suite is 42 of 43 files fully green and
   stable across repeated runs; this one file still varies. Next step: find
   what's actually racing (leading suspects: the per-document classification
   hook's N concurrent fetches, or effect-cleanup timing on unmount) rather
   than patching individual tests further.
2. **2 `ChatView.test.tsx` failures are collateral from `9484e5f`** (authed page
   images). Both assert an `<img>` src CONTAINS the API path; it is now a
   `blob:` URL. The tests encode the pre-fix behaviour and need rewriting. The
   fix itself is right and still has NO tests of its own.
3. 1 `AnalysisModeScreen.markers.test.tsx` failure, pre-existing.
4. The 8 backend market failures depend on the developer's `.env`. That is the
   "passes only on this machine" defect class this project has had before
   (audit #10, and eight tests in `test_facet_identity.py`). The tests should
   set the flags they assert, not inherit them. **New finding — add to the
   register.**
5. P1 findings 2-10 from the access-control and privacy set (admin gate reading
   `roles.name`, unscoped `recent_events`, unscoped `term_occurrences` and
   `example_questions`, the anonymous admin deactivation, the zero-length
   signing key, and the rest) are UNTOUCHED. See `docs/code-review/`.

---

## 3. What is done and working (verified in demo 2026-09-08)

| Capability | State |
|---|---|
| Upload, extract, OCR, chunk, embed, keyword index | ✅ |
| Chat: quoted answers with page + clause, follow-ups, Tier 2 explanation | ✅ |
| Analysis: summary with citations, sentences without citation dropped | ✅ (shows "N sentences were removed") |
| Gap analysis against nominated baseline or typed requirement | ✅ works; false conflicts exist (§4) |
| Advisory recommendation with confidence checks, never "high" | ✅ thin quality (§4) |
| PDF reports with frozen evidence | ✅ (verbatim label bug in PDF, §4) |
| Watched folder auto-ingest (stable-file check, sha256 dedup, audit rows) | ✅ live |
| Users, disciplines, access grants, admin ("super user" label) | ✅ |
| Three document types (Document / Drawing / LicensorFinalBEP) from the register; suggestion tiers; filter that only narrows | ✅ backend committed; frontend uncommitted |
| Market lane built flag-off, leak test, per-tier payload preview | ✅ built; flags now ON in `.env`; **first real outbound call not yet confirmed** |
| Product renamed everywhere in code (52 files) | ✅ |
| Pre-commit gitleaks hook fails closed | ✅ |
| `/review` slash command built from the project's own 24 defects | ✅ (`.claude/commands/review.md`, uncommitted) |
| Full code review, 134 findings, in repo | ✅ `docs/code-review/` |
| Architecture document written from the code | ✅ `docs/architecture.md` |
| Design canvas of the whole system incl. Compare screen | ✅ published artifact "RAG Intelligence System" (Claude Design) |

**Approved documents for the cloud model (#806 S3, 2026-10-11).** A Claude call is refused before it
leaves unless every document its prompt carries is on the owner's list
`backend/data/claude_approved_documents.json` (outside git; one entry per file sha256 with
`status: approved`, `approved_by`, `approved_on`; missing or empty = nothing approved). Every caller
declares its documents (`claude_approved.carrying`); a caller that declares nothing is refused too
(fail closed). The check sits in `claude_spend.reserve_all`, which both Claude lanes pass. A refusal
is in the spend ledger at USD 0 (ids only). A change to the list reaches the audit table only with
the #1584 switch on (`sync_audit` has no other caller; A-1587). Chat on
an unapproved document: the Claude-first path answers with the local model and says so; the other
chat paths say the document is not approved and ask the reader to choose the Local model.

**Automatic list entries (#1584, owner decision, `CLAUDE_AUTO_APPROVE_REVIEWS_ENABLED`, off).** With the
switch on, `claude_auto_approve` approves documents by The AUTOMATIC routes are exactly these four: (1) a file uploaded as a contractor submittal or a specification, or given either role later, is approved when it is uploaded or when the role is set, unless the code's own kind decision reads it as a contract (a contract is never approved by an automatic route); (2) the paper a review is started on is approved when the review starts, if its role is none, contractor submittal or specification and it is not a contract; (3) a rule book (a document classed as a standard) that the AI reviewer asks rules from is approved just before it asks, if the paper qualifies and the book is inside the access of the user who started the review; (4) a rule book that a review cites, or that governs its equipment type, is approved when the review starts or records it. The citation route approves rule books only; a cited specification goes out only if it is already on the list through its role. Any other document a review cites (a contract, a supporting document, a drawing, another datasheet, a procedure) is not approved automatically: the review shows "not sent: this document is not a rule book; the owner approves it". A specification on the approved list may be sent to Claude when it is the paper under review. When another paper's review cites it, it goes out only when it was on the list shown before the start (`review_shown`: the run's stored list; owner decision of 12 Nov 2026, #1584). `GET /api/reviews/plan` lists every document a Claude review of the paper may send (`documents.leaving`: the paper, the held rule books it cites or that govern its type, cited specifications on the approved list, chosen project papers; each with title, kind and why; what will not go, with the reason; a book the caller may not read is counted, never named), and `POST /api/reviews/start` with `shown_document_ids` stores that list with the run (and with the AI run that follows its rule check): a run with a stored list sends ONLY the documents it names, paper, rule books and specifications alike, and says "not sent" for the rest. A start that showed no list (the older routes) keeps its behaviour for the paper and rule books and sends no cited specification. A rule book that the scope step finds only during a review is not on the list shown: it is not sent, the result counts it ("N more rule book(s) apply to this paper. They were not sent because they were not on the list you saw. Review again to include them.") and the next plan lists the books the paper's last completed review applied by scope. A held book does not stop the AI reviewer: it drops that book's rules before any request is built and goes on with the listed books; the rule check's Claude steps run on the local model for that review and say so. At send time a document that is a contract by role or by the code's kind decision is refused on every route except chat (whose per-request consent is its own lane), including "cited by another review", unless the run's consent record (below) covers it or the owner's older per-upload yes for that file is recorded (`contract_yes`). BESIDES THE AUTOMATIC ROUTES, a review started with an explicit choice of Claude (not Automatic) sends exactly the documents listed on the screen before the start, of any kind (a contract, a specification, a procedure, a supporting document, a cited document on the list), and records that start (who, when, run, engine, each document's kind, role and file hash; `review_claude_consent`; ids only, no title, no text; owner decision of 12 Nov 2026, #1584: "button is enough"). Automatic never sends a contract or an unscored kind to Claude by itself. A document not on the run's list is not sent, and a run with no stored list (the older starts) sends a contract only if the owner's older per-upload yes is recorded for it, and no cited specification. The client's register stays blocked on every route even if it is listed (name and checksum block, `claude_blocked_hashes.json`, any file the owner marks), and so do the money caps. Nothing else is approved automatically: no library-wide approval, and chat uses its own per-request consent. The register file (rule 3) and any blocked hash or name never. The name block is by file name: a register renamed before it was uploaded is recognised only by its checksum when that file is held, and accented or look-alike letters in a name are not matched. To block a file: a `status: blocked` row on the list, its hash in
`backend/data/claude_blocked_hashes.json` (`{"blocked_sha256": ["<sha256>"], "blocked_names": ["<file name>"]}`, outside
git), or its name there; `scripts/write_block_file.py --name <file name>` / `--file` / `--sha256` adds an entry and never drops
one. Owner decision of 12 Nov 2026 afternoon (#1584): the register is blocked by its file name, built in (any case, spacing,
extension, copy or date suffix; a longer name that contains it too), so the switch needs no block file; one that exists but
cannot be read: nothing carrying a document is sent. A marked name matches the same way (at least 5 letters and digits).
Blocks apply with the switch off too; off, an automatic row does not count.
Sends are in the spend ledger (`sent_documents`), list changes in `audit_events`
(`claude_auto_approved`, `claude_auto_blocked`, `claude_auto_withdrawn`). No route shows the list; read the file.

**Datasheet AI reader ("AI reads, code checks"), added 2026-09-30, ON BY
DEFAULT (local engine) since the owner order of 2026-10-11. Measured on copies
of the three real datasheets (F1, 2026-10-11, qwen3.5:4b): findings identical
to AI-off on all three; the model read 1, 3 and 6 pages of 5, 7 and 11 within
the budget, most other pages timed out, and it added 2 AI-only facts and 1
agreement in total. Safe, and of little use on this PC. Since the planner
decision of 2026-10-11 an AI-read value whose quote the code proved on the page
decides like a code-read one (`comparison.ai_quote_proved`); the verdict says so.** `DATASHEET_AI_READER` (`ollama` default | `off` |
`claude`; tests pin it off). A model call past `DATASHEET_AI_TIMEOUT_SECONDS`
(180) and every page after `DATASHEET_AI_MAX_SECONDS` (900) per document keep
the code readers' reading, and the review says which reader read the sheet
(`datasheets.latest_reader_summary`, `absence.reader_summary_line`). An owner's
`backend/.env` that still says `DATASHEET_AI_READER=off` keeps it off.
makes `datasheets.extract_facts` also read every page with text through
`claude_datasheet.read_page` (two runs must agree; each fact's quote, value and
label must be on the page) and merge it with the rule readers
(`datasheet_ai.merge_readings`): agreement raises the rule fact to confidence
0.7, disagreement keeps both marked `validation_state='conflict'`, an AI-only
fact is stored as `extraction_method='model'` with the engine in its
provenance. `claude` needs `REASONING_PROVIDER=claude` + both egress flags + a
key and is metered by `claude_spend` (step `datasheet-ai-reader`); `ollama`
goes through `model_transport`. A failing or unavailable engine leaves the page
to the rules with a recorded reason. Tested with fake models only
(`test_datasheet_ai.py`, M1670-M1685); no accuracy claim until it is measured.

Backend `.env` (never committed) currently holds: `WATCH_FOLDER`,
`WATCH_INTERVAL_SECONDS=60`, `WATCH_OWNER_EMAIL=testcivil@gmail.com`,
`AUTH_MODE=demo_required`, `AUTH_SECRET` (64 chars), and both market flags ON:
`market_live_enabled`, `market_allow_public_egress`. Allowed hosts:
`api.openalex.org`, `en.wikipedia.org`. Tier-1 web vendor: none (Tavily was
considered; a key was pasted in chat once and Ali was told to rotate it — never
use it).

Data: 19 documents in `backend/data/rag_intelligence.sqlite` (WAL; three files).
The client's `Deliverables Register.pdf` (13 pages, 1,354 deliverables) is in
the local DB — fine locally, never in git. Old `oldname.sqlite*` files may still
exist beside it; delete only after verifying counts.

---

## 4. The review — 134 findings, and the order to fix them

Full register: `docs/code-review/README.md`. Detail per area in the same folder.
Nine parallel static reviews on 2026-09-08 (Cowork). Summary of what matters:

**P0 — blocks the commit (frontend, Cowork's lane)**
1. `DocumentsView.tsx:208` — Confirm sends only `doc_type`; backend upserts
   discipline/doc_class to NULL and deletes subjects. **Data loss on a routine
   admin click, reported as success.** Send the full classification.
2. `DocumentsView.tsx:298` / `TypeFilter.tsx:94` — unvalidated vocabulary body
   throws on `types.length`; takes down the view; **this is what fails the 24
   Dashboard tests** (mock has coverage, not vocabulary). Guard + fix mocks.
3. 15 `DocumentsView` tests red (text split across elements).

**P1 — privacy and access control (backend, VS Code's lane)**
4. **`settings.ollama_url` unvalidated** — `answer.py:404`, `analysis.py:667`,
   `metrics.py:271` POST prompts *with document passages* to whatever `.env`
   says. No allowlist, no loopback check. Contradicts the headline privacy
   claim. Socket-containment test covers four market files and misses this.
   **Fix first.**
5. `main.py:193`, `metrics.py:439,484` — `corpus_wide = unrestricted or is_admin`
   means everybody under default `AUTH_MODE=disabled`.
6. `admin.py:442` — anonymous caller can deactivate every admin under that default.
7. `admin.py:193,372` — admin gate reads `roles.name`, not `roles.kind='capability'`.
8. `market_providers.py:282` — `check_host` bypass via `https://evil.test?@api.openalex.org/`.
9. `watch_api.py:233,304` — recent events unscoped; leaks filenames + grants.
10. `fts_index.py:289`, `lexical.py` — answerability oracle over unreadable documents.
11. `intent.py:212` — `example_questions()` unscoped.
12. `metrics.py:378-410` — three aggregates with no WHERE beside `corpus_wide:false`.
13–14. `auth.py` — rate limiter keyed on attacker input; zero-length key accepted.

**P2 — claims the client can read that are false**
15. `reports.py:354` — PDF says "Quoted verbatim" unconditionally (audit #6 re-shipped).
16. `ClaimTable.tsx:160`, `GapAnalysisCard.tsx:357`, `claims.py:215` — same, and provenance is dropped before render.
17. `schemas.py:841` — `recommendation_refusal` not on the wire; screen invents a reason.
18. "This machine is offline" hardcoded in 5 places while egress is on.
19. `market_providers.py:480` — previewed payload ≠ sent payload.
20–27. Audit-row timing, `jobs.running` at upload (audit #1 still live), a
    confidence check that could not be computed renders "clear", baseline's own
    row counted as "Met", OCR warning can never clear, `ocr_failed` dead code.

**P3 — functional**
28. `fts_index.py:71` — `clause 5.3.2` → required phrase `"clause 5"` → zero hits. **Measured.**
29. `ingest.py:418` — any exception → permanent `failed`; nothing can resume; re-upload dedups to the dead row.
30–33. 1-of-9 status writers guarded; identifier boost on wrong scale; OperationalError reported as "nothing matched"; double synthesis.

**P4 — vacuous tests** (34–40): a dead `hasattr` assertion; the "never certifies"
guard tested only against a stub; production increment reimplemented in the test;
admin-capability test that passes if `roles.kind` were dropped.

**P5 — docs** (41–47): ADR-0006 says "no code written" over shipped code;
LanceDB in README stack table but not in the system; stale test counts
(measured: backend 1,151 `def test_` in 72 files, frontend 515 in 43 files);
`main.py:873-874`, `:1413`, `schemas.py:164` comments false.

**Found after the review, during the demo (add to register):**
- Facet named by unit tokens (`design (MPa, µm)`) survived into the gap table and
  produced a false conflict between 15.3 MPa (doc02) and 60% (doc13). The rule
  "unit tokens never name a facet" in `claims.py` is not holding.
- Percentage-recall pass has no topical floor: any document containing "%" can
  enter a percentage question's evidence (doc02, a power-plant cost study, kept
  appearing in submittal questions).
- 30% vs 60% statements that agree ("60% includes the 30% items") reported as
  conflicts because 30 ≠ 60.
- Same finding labelled ✕ Conflict in gap panel and ▲ Possible conflict in claim table.
- Tier 2 explanation lists a citation number with no sentence using it.
- Page images broken under auth (fixed, untested — see §2).
- `frontend/dash-body.txt` is NOT stray scratch: `DashboardView.host.test.tsx:139`
  writes it into the repo on every suite run, so it reappears after each run. A
  test writing into the working tree is a defect in its own right. **New finding.**
- The 8 backend test failures are inherited from the developer's `.env` rather
  than set by the tests. **New finding**, same class as audit #10.
- The P0 #2 crash was in the exported `useTypeVocabulary` hook returning a
  non-array `types`, not in `DocumentsView`. The review located the symptom
  correctly and the cause one file away — worth remembering when reading the
  register: it names the line that threw, not always the line to change.

**Second pattern identified by the review** (beyond the audit's "derived from
something adjacent to the truth"): *a defect fixed in one of its two homes.*
Before closing any fix, grep for every other place the same claim lives.

---

## 5. The plan that was agreed

Ali's stated priority (2026-09-08): **not** scale testing, **not** new features.
First: review all existing code and architecture, fix, track, and commit to
industry standards. That review is done (§4). The fix campaign was about to start
when the demo interrupted it.

**Agreed execution shape for the fixes:**
- Cowork has a verified Python 3.12 test loop in its cloud container:
  `/root/work/repo` (synced copy) with venv `/root/sut/.venv` and models
  symlinked. `cd /root/work/repo/backend && /root/sut/.venv/bin/python -m pytest tests/<f> -q`.
  Re-sync before use: tar the repo (excluding `.git node_modules models data
  *.sqlite*`) into the Cowork scratchpad on the device, stage, extract.
- Five parallel fix agents by **file ownership**, so nothing collides:
  A) egress + privacy: `config.py`, `market_*.py`, `answer.py`, `analysis.py` ·
  B) access: `auth.py`, `admin.py`, `access.py`, seed ·
  C) routes/metrics/schemas: `main.py`, `metrics.py`, `watch_api.py`, `schemas.py` ·
  D) ingestion + retrieval: `upload.py`, `ingest.py`, `chunker.py`, `ocr.py`, `fts_index.py`, `lexical.py`, `intent.py`, `search.py` ·
  E) honesty of output: `synthesis.py`, `claims.py`, `reports.py` ·
  Cowork itself: all of `frontend/` and `contracts/types.ts`.
- Every fix ships with a test proven red-then-green (by reverting the fix once;
  by a mutation entry only in the CLAUDE.md rule 6 danger zone). No agent runs
  the whole backend suite (5 min); Cowork runs it once at the end.
- Changed files go back to the device via SendUserFile → `device_commit_files`
  (writing into `.claude/` is refused by the bridge; use device_bash `cp`).
- Commits and pushes: VS Code / Ali, with prompts from Cowork. Merge commits,
  `Closes #N`, one logical change per commit.

**After the fix campaign**, in order: type filter in Chat (needs `scope` on
`AskRequest`, which has `extra: forbid`), recommendation quality (2–4 cited
actions; reuse summary findings), Compare screen (designed), then the client's
remaining items: health-check scheduler, escalation ladder, news monitoring.
Scale/load testing, backup-restore, installer, firewall rule: recognised as
required for "enterprise", explicitly deferred by Ali.

---

## 6. Key decisions and why (so they are not re-litigated)

| Decision | Reason |
|---|---|
| Three document types only: Document, Drawing, LicensorFinalBEP | Measured from the client's register (598/540/216 of 1,354). Ali rejected richer schemes twice ("you are making it very complex"). Subjects/equipment tags rejected: equipment tags cover 16%. |
| Compare screen = Topic (required) + Set A (type+discipline) vs Set B | Set-vs-set without a topic yields "not addressed" lists, not gaps. Process alone is 104 Documents vs 194 BEP. Civil has 0 BEP — honest results from Documents only. |
| Market sources: OpenAlex + Wikipedia; no general web vendor yet | Free, no key, low leak surface. Instant Data Scraper rejected. Tavily needs billing details; undecided. |
| Recommendation runs after summary in the frontend | Two concurrent syntheses on a CPU 4B model → the second returns no cited sentence → false refusal beside a cited summary. Backend reuse-summary fix still owed. |
| Page images fetched with bearer header, blob URL | `<img src>` cannot carry the token; putting the token in the URL is forbidden. |
| `/review` built from the audit, not generic rules | The project's real failure modes are documented; generic linting misses them. |
| Dashboard unchanged except counts inside the Documents tile | Ali: "we have to be minimalistic dashboard keep it as it is." |
| No `.env` ever committed; hook fails closed | ADR-0004. Hook previously failed open (audit #24). |
| **AI-approved rules** (owner decision 1, 11 Nov 2026): a rule is usable by the AI reviewer when a person approved it (owner or engineer tier, `rulebook_approval`) OR its label `ai_approved` | No engineer is available. `ai_approved` = two DIFFERENT Claude models agree on the rule's paper kind, field and reading under one prompt version, AND code finds its quote word for word on the rule-book page; rules where they disagree are `needs_human` and decide nothing. It lives in its own tables (`rule_label`, `rule_label_event`, made only when `agent_review_enabled` is on) and never writes an owner or engineer approval; a person's refusal is never overridden. It replaces the engineer sample FOR NOW: when an engineer comes he reviews the `needs_human` list and a sample, not everything. The label job writes a database COPY only (`scripts/run_rule_labels.py`); the live app takes the label file through `POST /api/admin/rule-labels/import`, which checks every row again. Code: `rule_labels.py` (decision, tier), `rule_label_job.py`, `rule_label_import.py`. With the server STOPPED, `scripts/import_rule_label_files.py` loads the label file and the equipment label file through the same checks and prints the same counts; a live database is written only after `live_guard.prepare_live_write` (backup and restore drill). `scripts/trial_on_copy.py` runs one AI review on a COPY (closed lane free, open lane with the caller's key) and checks every route, the contract pairs, the Rules used page, the Pass/Fail proof rule and the standing approval; it exits non-zero on any failed check. `scripts/write_block_file.py` writes `claude_blocked_hashes.json` from the register-named documents (counts only printed). Standing approval (issue #1584, comment 6806441133, owner decision of 12 Nov 2026, to be confirmed there by the owner): with `CLAUDE_AUTO_APPROVE_REVIEWS_ENABLED=true` and that block file, the paper and the rule books the AI reviewer asks rules from join the approved list (`claude_auto_approve.on_agent_standards`, called by `agent_review_run.Runner.run`); the register never does. The import trusts the admin who places the label file (a file's `origin` is its own word); every row is still re-checked by code. |

---

## 7. Demo — what works and what to say

**Start:** Terminal 1 `cd backend && ..\.venv\Scripts\activate && python run.py`
· Terminal 2 `cd frontend && npm run dev` · Ollama running (`ollama list`) ·
open `http://127.0.0.1:5173` · sign in as `testadmin`.

**Safe questions (all verified 2026-09-08):**
- Chat: *What drawing size is required for design submittals?* → ANSI-D 22×34, doc16 p.22.
- Chat: *What must the 60% design analysis include?* → doc13 p.88.
- Analysis (baseline doc13, Search in Document, Focused): *What are the 30% and
  60% design submittal requirements?* → real conflict p.125 vs p.88, honestly
  unresolved. Best run.
- Analysis (baseline doc13): *What must the 60% design submittal include?* →
  checklist incl. asbestos test from p.230; "2 sentences were removed" shown.
  Gap panel on this run has false conflicts — point at Summary, not Gap.
- Analysis: *Compare design requirements with drawing requirements* → S1–S6 across doc13/15/16/civil.

**Avoid:** clicking Confirm on a document type until P0 #1 is fixed; questions
about the register PDF (tabular, untested); percentage questions without a
baseline (pulls in doc02); promising live market data or Chat type filter.

**Framing that landed:** "Facts, opinion, disagreements — three boxes, never
mixed, every one traceable to a page." Use "flags to check" not "conflicts
found"; "evidence found" not "compliant". Hero example: the asbestos requirement
on page 230 a tired reviewer misses.

**Submittal-review scenario (client's real goal):** contractor sends a 60%
package → engineer asks what it must include → gets the checklist with pages →
holds the package against it → sends it back same day instead of a month later.

---

## 8. How to resume in a new session — checklist

1. Read `CLAUDE.md`, then this file, then `docs/code-review/README.md`.
2. `git status --porcelain` and `git log --oneline -5` — compare with §2. If the
   working tree differs, someone worked since this file was written; ask before
   touching anything.
3. Confirm which Claude you are: VS Code → backend/git lane; Cowork → frontend/
   docs/review lane. Do not cross lanes without being asked.
4. If continuing the fix campaign: start with P0 (frontend, get the suite
   green), then P1 #4 (`ollama_url`). Re-sync the cloud test copy first.
5. Before any commit: `/review`, frontend `npm run test`, backend
   `python -m pytest -q` (Windows, 3.12). Record retractions in
   `docs/status-honesty-audit.md`. Grep for every other home of a fixed claim.
6. Never run npm/npx against the repo from the Cowork Linux VM.
7. Ali communicates in short messages, often during live demos. When he asks
   "is this correct", check the actual evidence on his screen claim by claim and
   say which are verified and which he must click to verify. When he asks "what
   does this prompt do", answer in a table with ✅/❌ before he runs it.

---

## 9. Things only Ali can do (pending)

- Rename the GitHub repo away from the client's name.
- Delete stray files: `docs/review-command.md`, `frontend/dash-body.txt`;
  revert `lightningcss-win32-x64-msvc` from `package.json`.
- Add `.claude/settings.local.json` to `.gitignore`; commit `.claude/commands/review.md`.
- Confirm the first live market call (VS Code prompt was given; result not seen).
- Decide the tier-1 web vendor, or keep general web search off for the client.
- Send the client the three open questions (deliverables register scope,
  escalation ladder definition, news/media privacy expectations).
- Delete old `oldname.sqlite*` after verifying document counts match.


---

## 10. The AI reviewer in the app (#1690, 11 Nov 2026) - what the one switch turns on

**Switch.** `AGENT_REVIEW_ENABLED` (`settings.agent_review_enabled`, default OFF; read only by
`agent_review_gate.enabled()`). Off: no table, every `/api/reviews/agent-*`, `.../agent/*` and `.../rules-used` route answers
404 `feature_off`, no `agent_review` job is claimed, no Claude call, the classic review is unchanged. The Claude lane gate is
not replaced: `REASONING_PROVIDER`, both `STANDARDS_READER_*` flags and a key (read from the process env, else from the app
settings), the owner-approved document list and the USD caps in `claude_spend` (step `agent_review`: USD 5 per step, USD 15
per run) all still apply. A cap stops the run with a PARTIAL result and a stop reason.

**Rule review: datasheets only (owner, 11 Nov 2026).** The RULE review accepts a paper only when its decided kind is
"datasheet" (`AGENT_REVIEW_KINDS`). Any kind the general review does not name (below), or an unknown one, is refused with 409
`kind_not_enabled`: no job, no call, no charge. Reason: in the experiment's procedure and contract runs most
"AI thinks: not met" lines were wrong because the paper was silent. Widening the tuple is the owner's decision; the silent-paper
rule (`silence_guard`: a "not met" that rests only on silence is a Query for any kind but a datasheet) is already wired at the
one exit.

**General review of procedures and contracts (owner, 11 Nov 2026, STATE 16.4; #781, #1690 step F).** The owner CORRECTED the
"datasheets only" order for procedures and contracts: do not switch them off; review them in GENERAL REVIEW mode when we hold no
rule book for the paper ("Switch it on in the app only if that score is clearly better than tonight's"). The lab run scored
clearly better (wrong lines 26 to 2 on a procedure and 18 to 1 on a contract; planted errors caught 0 to 5 of 10 on each; false
alarms 10 to 1 and 6 to 1), so the SAME switch now also takes `AGENT_GENERAL_REVIEW_KINDS = ("procedure", "contract")`; every
other non-datasheet kind (drawing, calculation, other, unknown) stays 409 `kind_not_enabled`. A datasheet still goes to the rule
review. What a general run does: (1) one line per cited rule book we do not hold, "Not checked: rule book not held"; a held
cited book is decided by code and recorded: one with no approved rule of this paper's kind is "not used in this general
review", one that DOES carry approved rules of the kind is named in one line ("rule books we hold that fit this paper were not
used: rule review for this kind is switched off"); (2) the completeness checklist of the kind, only when its subject fits the
paper, else "no completeness checklist for this kind of paper" (contracts have none); (3) the paper against itself, every quote
verified by code, a second model of another family keeps or drops each finding, figures are "differ: by code" only under the
strict rule; (4) the paper against the PROJECT PAPERS the request named (`project_document_ids`; the app has no project or folder
field on a document, so they are never chosen silently: each is checked against the caller's scope, is not the paper or a rule
book, and is checked again when the job runs and against the approved-documents list before any call; none named: one line
"no project paper was given to check against"); (5) at most 10 AI engineering comments per run, each tied to a verified quote.
Classes: "Not checked: rule book not held", "AI note, no rule book", "Query for the engineer" (silence is a Query), "Not
reviewed" (a cut-off or failed answer). No Pass, Fail, "AI thinks" or "Proven by code" can leave `agent_general_review.
finalize_line`, and no rule item is ever built; the contractor and comment-only copies are written EMPTY. Code: `agent_general_
review.py` (exit, decision), `_parts.py`, `_prompts.py`, `_job.py`, `_crs.py`. Money: the existing step caps through the runner;
nothing new. Tables: `agent_review_line` has two new columns and classes and `agent_review_general` is new (created by
CREATE IF NOT EXISTS; a line table of the older shape is UPGRADED in one transaction by the server with the switch on (renamed to `agent_review_line_before_general_<time>` and kept, every row copied, the event written to `audit_events`); if that fails the transaction rolls back, every AI-review route answers 503 "the AI review tables could not be upgraded: <reason>" and no run starts: the shape is checked before the first Claude call). Three defects of the lab scoring are fixed and tested: the stored text is whole (it was cut at 200
characters), a checklist Query says whether the answer was "partly covered" or "not found" and a "present" answer that carries
a concern becomes an AI note, and a claim that something is MISSING on a page whose pictures or formulas were not read as text
is a Query ("could not be checked").
**NOT proven (general review).** It found 2 of the 4 key problems on the one HAZOP paper (1 weakly); removed items are not
caught (a planted removal leaves nothing to quote: 4 of 10 planted changes missed on each paper); contracts have no
checklist, so on a contract parts 3 and 4 and the comments carry everything; a procedure of another subject than the one
checklist gets "no checklist"; 2 of 22 lines were wrong on the HAZOP paper and one false "missing" on a page of pictures; the
second quote of a project-paper finding can be unrelated (the second model is now asked, and such a line is shown as a plain
comment, not as "disagrees with"). It was never run on live data, and the app code was never run with a real model.

**What it does.** Paper kind first, then the right rules only (kind equal, tier usable, equipment fits), batches by page through
the Claude lane, code verifies every quote and compares every number, a second model of another family must agree, a Fail is
proven only after the rule-book page context check. One exit (`Runner.exit_line`) caps every line by its rule's CURRENT tier
(label table) before it is stored, written to the CRS or served. Tables: `agent_review_run`, `_rule`, `_line`, `_missing_book`.
CRS internal and contractor copies (xlsx) and the trace file go to `<data dir>/agent_reviews/<run id>/`.

**Owner, 12 Nov 2026: "A Pass where the code compared nothing is 'AI verdict, two readers agree', internal copy only. Proven Pass always means the code compared a value."** (`agent_review_wording.code_compared` / `demote_uncompared_pass`, guards in `agent_review_pass_guards`.)
**Wording classes (owner decision 2).** "Proven by code" (Pass / Fail), "AI opinion, engineer to confirm" (AI thinks: met / not
met, with the reason it is not proven), "AI opinion, rule not yet approved", "Query for the engineer", "Not applicable", and
"Not reviewed" (the AI gave no answer even after the batch was split: never a Query about the paper). The contractor copy holds
the proven Fail only. Order 13 adds, behind `AGENT_REVIEW_TWO_READER_VERDICT_ENABLED` (default off), the class "AI verdict, two
readers agree" (words "AI verdict: met" / "AI verdict: not met"; internal copy only; never a Pass or a Fail): a second model of
another family answers the same question without seeing the first answer, and the class is given only when both verdicts agree,
code verified both readers' quotes, the two paper quotes stand on the same page, and no guard objects (`agent_review_two_reader`).

**NOT proven / not in this PR.** No frontend. No run on live data. Not run with a real model (every test uses an invented fake).
Page pictures (drawings, scans) are not wired: a page with no text yields no Pass or Fail. The absence proof is built and off.
The Rules used page's coverage numbers come from a coverage file the lead places under the data dir (`coverage/coverage.json`);
without it every number is null. Checklist lines show no rule tier (null).

**Guards left out on purpose.** There is no final check / tiebreak: no path in the runner calls a third model, so a line whose
second opinion disagrees stays "AI thinks" (never a Pass or Fail). A short clause quote is never widened: a line whose clause
quote is verified but weak simply stays held (a Query or an AI opinion), so no path needs the widen conditions.

**Order for step H (live update).** 1. Update the code and start the server with the switch still off; check the table list is
unchanged. 2. Switch on (`AGENT_REVIEW_ENABLED`, then `REASONING_PROVIDER`, `STANDARDS_READER_ENABLED`,
`STANDARDS_READER_ALLOW_PUBLIC_EGRESS` in `backend/.env`, names only, after saving a copy). 3. Import the rule labels
(`POST /api/admin/rule-labels/import`, #1744). 4. Import the equipment labels (`POST /api/admin/rule-equipment/import`, the
core's route). 5. Place `coverage.json` under `<data dir>/coverage/` (the Rules used page shows nothing for coverage without it).
6. One datasheet review through the app; save the CRS and the Rules used page.

**Equipment.** The paper's equipment is read by the app's own reader and passed to the rule choice with
`equipment_filter="type"`: a rule whose agreed label names another type or family is left out ("another equipment type"); the
paper's equipment state (names none / not in the list / unreadable) is said on the summary and Rules used routes
(`equipment_state`, `equipment_notes`).

**Known gaps (plainly).** (a) The reuse of the classic standards selection (`agent_review_jobs._scope_run_id`: a finished classic
run of the same code version, else `applicability.select` inline) is untested; the tests replace it. (b) Page pictures (drawings
and scans) are not wired. (c) The general review mode for procedures and contracts (owner correction 16.4) is not in the app;
the reviewer is on for datasheets only. (d) The reviewer has never been run with a real model or on live data. Rules that are
not AI approved are not asked in the app (`ASK_UNAPPROVED = "off"`: measured 11 Nov, no key row gained, more wrong opinions);
the cap and the class stay in the code and tests.

**Checklist data.** Checklist content (the skill files of `agent_skills`) is local only and never committed: it lives in
`~/project/mirror/skills` (or `AGENT_SKILLS_DIR`). On a machine with none (a clean checkout, CI) `checklist_ids()` is empty: no
line can be a checklist line, so any line of an item that is not a stored rule is capped as not approved (safe, never a Pass or
Fail), and the job logs "agent review: no checklist data found". An empty list is never remembered, so adding the files needs no
restart. Step H must check that the live Mac has the skill files.

## 11. One Review button: Automatic, Claude, Local only (12 Nov 2026, #1584 comment 6820183348)

Backend (PR 1): `review_engine.decide` is the one resolver (pure; a brute force walks every combination); `review_engine.plan_for`
and `GET /api/reviews/plan` give the pre-start answer (no side effect, no call); `POST /api/reviews/start` queues the rule check
and, when the plan runs it, the AI review follows on the same worker (`review_engine_start.follow_up`, checked again). Local only
and any part the plan keeps local are barred from Claude for the whole run (`review_engine.barring`). The AI reviewer has NO local
reader on the job path (`agent_local_lead` is used only by the experiment loop), so Local only means: rule check on the local
model, AI review not run, said in plain words. Approvals: role SPECIFICATION (approved like a submittal, behind the existing
auto-approve switch); a contract goes only on the explicit choice of Claude (the older per-upload `contract_yes` still counts at send time). Unscored kinds:
`agent_review_gate.SCORED_KINDS` (datasheet ONLY; owner, 12 Nov) and `REVIEW_UNSCORED_KINDS_FOR_CLAUDE_ENABLED` (off). The CRS header names the engine
("Reviewed by:", `crs_layout.engine_rows`). The screen (PR 2) waits for the owner's picture. Trial: `scripts/trial_on_copy.py --engine`.

Review R47 (12 Nov): the engine choice is written in the SAME transaction as the job (`review_jobs.enqueue(in_transaction=...)`;
a job of the new route has an id starting `job_x`), and the bar FAILS CLOSED: an unreadable choice, or a marked job with no choice
row, keeps the run on this computer and says why on the run (`outcome_json.engine_choice_note`); a job of the older routes (no mark,
no row) behaves as before. "Local only" (any run kept on this computer) also bars the public web check of standards
(`REVIEW_WEB_STANDARDS_ENABLED`). The cost line gives the bound per part and in total (each review has its own USD 15 per-run cap).
The header's engine is saved at the end of the run (`outcome_json.engine_ran`). With only datasheets scored, Automatic never sends a contract or an unscored kind;
an explicit choice of Claude sends it (owner decision 12 Nov 2026, #1584: "button is enough"), as a draft, internal copy only.
