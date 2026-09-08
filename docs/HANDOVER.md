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
1. **11 of 18 `DocumentsView.test.tsx` tests are red and NOT triaged.** Five are
   `Unable to find role="dialog"` (chunk inspector, excluded viewer, page image
   viewer); four are classification grouping and confirm; two are delete and
   excluded pages. Some of these are the flaky ones VS Code saw flipping in
   both directions between identical runs — that has not been separated from
   the genuine failures.
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

Backend `.env` (never committed) currently holds: `WATCH_FOLDER`,
`WATCH_INTERVAL_SECONDS=60`, `WATCH_OWNER_EMAIL=testcivil@gmail.com`,
`AUTH_MODE=demo_required`, `AUTH_SECRET` (64 chars), and both market flags ON:
`market_live_enabled`, `market_allow_public_egress`. Allowed hosts:
`api.openalex.org`, `en.wikipedia.org`. Tier-1 web vendor: none (Tavily was
considered; a key was pasted in chat once and Ali was told to rotate it — never
use it).

Data: 19 documents in `backend/data/rag_intelligence.sqlite` (WAL; three files).
The client's `Engineering Deliverables.pdf` (13 pages, 1,354 deliverables) is in
the local DB — fine locally, never in git. Old `nabaa.sqlite*` files may still
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
10. `keyword.py:289`, `lexical.py` — answerability oracle over unreadable documents.
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
28. `keyword.py:71` — `clause 5.3.2` → required phrase `"clause 5"` → zero hits. **Measured.**
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
  D) ingestion + retrieval: `upload.py`, `ingest.py`, `chunker.py`, `ocr.py`, `keyword.py`, `lexical.py`, `intent.py`, `search.py` ·
  E) honesty of output: `synthesis.py`, `claims.py`, `reports.py` ·
  Cowork itself: all of `frontend/` and `contracts/types.ts`.
- Every fix ships with a test proven red-then-green by mutation. No agent runs
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
- Delete old `nabaa.sqlite*` after verifying document counts match.
