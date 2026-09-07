# Plan conformance audit — RAG-INTELLIGENCE-POC-EXECUTION.md

**Date:** 2026-09-06
**Commit audited:** `9f3f6dbc682071d03b29b3008d5f95553b60cf3e` (`feat/frontend: gap rows that do not contradict themselves, ordered and counted`, 2026-09-06 21:54:10 +0500)
**Working tree at audit time:** one untracked file, `backend/tests/test_metrics_host_telemetry.py`. It is **not** part of the audited commit and is treated separately (see §10).
**Plan audited:** `RAG-INTELLIGENCE-POC-EXECUTION.md` (audited under its former
filename `NABAA-SUNDAY-POC-EXECUTION.md`), Revision 4, 2026-09-05, 2,150 lines / 132,932 bytes.
**Auditor:** read-only pass. No repository file was modified, created or deleted except this document.

---

## 0. Why this document exists

Completion for this project has been quoted as "89%" and "94%" with no denominator.
`docs/status-honesty-audit.md` records fourteen prior instances of a number stated with
more confidence than its evidence supported. This document replaces the guess with a
count: every testable requirement in the plan, numbered, assessed against the code, and
totalled.

**The headline finding is that the plan cannot honestly be reduced to one percentage,
and §9 explains why.** The count is given anyway, with its denominator named, because a
refusal to count would be its own kind of evasion.

---

## 1. Method — how to reproduce this

### 1.1 Requirement extraction

Every sentence of the plan was read. A sentence was extracted as a **requirement** when it
states something the system must do, must not do, or must say, **and** an independent
reader could decide the question by looking at the repository, running a command, or
observing the running system. "The system must return 404, never 403, for an out-of-scope
document" is a requirement. "This plan values honesty" is not.

Requirements are numbered `R001`–`R513` and grouped by the plan section they come from.
Negative requirements ("must not claim", "never promise") and honesty invariants
("nulls render as nothing", "confidence never high") are included — they are the majority
of §1's *Not promised Sunday* block and all of §18.

**Sections deliberately excluded, and why:**

| Plan section | Why excluded |
|---|---|
| §2 *Research basis* (lines 228–243) | A bibliography. Cites papers; asks nothing of the build. |
| §2/§2B *Deferred challenger* columns | Explicitly post-demo ("promotion gate"). Not a Sunday commitment. |
| §2B.1 *RAG family* table | Classification prose. Its one testable consequence — the naming rule — is extracted as R097. |
| §12 (ISSUE-001…015) | **Restates §§4–11 with time estimates and branch names.** Its acceptance bullets map one-to-one onto requirements already counted. Counting it again would inflate the denominator by ~60 duplicates. Its two non-duplicated facts (branch names, the `v1.0.0-prototype` tag) appear as R431 and R432. |
| §13 timebox table and no-go gates | A schedule for one specific day, now past. Not assessable after the fact. Its one durable rule — the "never cut" list — is R448. |
| §15.1/15.2 demo preparation and sequence | A runbook for a meeting, not a property of the build. §15.3's wording rule is R486. |
| §17 post-Sunday roadmap | The plan's own heading says "not part of the one-day build". |

**Requirements that duplicate across sections are counted once, at the section that states
them most precisely, and cross-referenced.** §14's acceptance matrix (A01–A37) is the one
exception: it is counted in full as R449–R485 because it is the plan's own *test* list, and
"does an acceptance test exist and pass" is a different question from "does the feature
exist".

### 1.2 Rules of evidence applied

1. **A file existing is not evidence.** Every `MET` for a UI or route surface was checked
   for reachability. `App.tsx:12–19,228–246` imports and renders all eight screens, so the
   "850 lines of admin UI no route imported" failure mode does not recur here — that was
   checked, not assumed.
2. **A passing test is evidence only if it could fail.** Where a verdict rests on a test,
   the row says in one line what would go red. Tests whose fixtures cannot produce the
   condition are recorded as `PARTIAL` or `NOT TESTABLE HERE`, not as `MET`.
3. **Where verification was impossible, the verdict is `NOT TESTABLE HERE`** with the
   reason. No cell was filled by inference.

### 1.3 Commands actually run (reproducible)

The repository lives on a Windows host at `D:\project\Rag_chatbot`. It was copied
read-only to a Linux VM (`rsync`, excluding `.git`, `node_modules`, `.venv`,
`backend/data`, `__pycache__`). `backend/data/rag_intelligence.sqlite` was never opened on the mount.

```
# Backend — Python 3.12.14, backend/requirements.txt installed at its pinned versions
cd backend && python -m pytest -q            # run in 14 file-batches (120 s call ceiling)

# Frontend
cd frontend && npx tsc -b
cd frontend && npx tsc -p tsconfig.app.json --noEmit --listFiles   # coverage check
cd frontend && npx vitest run
```

**Results, this machine, this commit:**

| Suite | Collected | Passed | Failed | Skipped | xfailed | Deselected |
|---|---:|---:|---:|---:|---:|---:|
| Backend (committed tests only) | 1,070 | 1,040 | 0 | 3 | 27 | 1 (`slow`) |
| Backend incl. untracked new file | 1,078 | 1,044 | **4** | 3 | 27 | 1 |
| Frontend (vitest, 39 files) | 467 | 467 | 0 | 0 | — | — |
| `tsc -b` | 79 source files | clean | — | — | — | — |

Three notes that matter more than the totals:

- **The suite guards its own arming.** A `conftest` hook prints `no tests were skipped -
  the whole suite ran` per batch; `.github/workflows/tests.yml` runs
  `scripts/fetch_models.py --verify-only` *before* pytest, so a run with unstaged model
  weights cannot pass as clean. This is the direct fix for honesty-audit entry "CI never
  ran the tests".
- **`tsc -b` was checked for what it covered.** `tsconfig.json` still has `"files": []`;
  run as `tsc --noEmit -p tsconfig.json` it would check zero files. `tsc -p
  tsconfig.app.json --listFiles` reports **79** files under `frontend/src`, so the clean
  result is real.
- **The 27 `xfailed` are a specification, not rot.** `backend/tests/test_recommendation_gate.py`
  carries `pytest.mark.xfail(strict=True)` for issue #90. Strict means the suite goes *red*
  the day the feature lands, so the marker cannot outlive the gap.

**The README's own test counts are stale in the safe direction:** it claims "279" frontend
and "887" backend tests against 467 and 1,079 actual. Recorded because a stale count is the
same defect class this project has fourteen entries about, even when it under-claims.

---

## 2. Total

**513 requirements extracted, numbered R001–R513.**

| Verdict | Count | % of 513 |
|---|---:|---:|
| MET | 262 | 51.1% |
| PARTIAL | 112 | 21.8% |
| NOT MET | 103 | 20.1% |
| NOT TESTABLE HERE | 34 | 6.6% |
| SUPERSEDED | 2 | 0.4% |

### The two percentages, stated separately, with the denominator named

> **Percentage MET: 51.1% — 262 of 513.**
> **Percentage MET-or-PARTIAL: 72.9% — 374 of 513.**
>
> **Denominator in both cases: 513 testable requirements extracted from
> `RAG-INTELLIGENCE-POC-EXECUTION.md` Revision 4 (2026-09-05), excluding the sections listed
> in §1.1 above.**

### A second denominator, because the first one hides something

**34 requirements could not be assessed here at all** (§7 lists each and why). They need a
second 48 GB Windows host, a 20-document human-labelled gold fixture, six or seven
1,000–1,200-page client PDFs, an approved market provider, a GitHub plan this account does
not have, or `RAG-INTELLIGENCE-CODEBASE.md`, which is not in the repository. Against the **479
requirements that could be assessed**:

> **MET: 54.7% — 262 of 479 assessable. MET-or-PARTIAL: 78.1% — 374 of 479 assessable.**

### What this does to "89%" and "94%"

**No denominator in this audit produces either figure.** The closest number to 89% is
78.1%, and it is reached only by (a) counting PARTIAL as done and (b) dropping the 34
requirements that could not be checked — that is, by twice choosing the more flattering
reading. **A 94% over half the plan is not 94%**, and the same is true of a percentage that
counts "some of it holds" as "it holds".

The honest one-line summary is: **about half the plan is met, about a fifth is met in part,
and about a fifth is not met at all** — and the not-met fifth is concentrated in exactly
the places a client looks first (§3 and §5).
---

## 3. Per-section table — where the gaps are

| Plan section | Reqs | MET | PARTIAL | NOT MET | NOT TESTABLE | SUPERSEDED | % MET |
|---|---:|---:|---:|---:|---:|---:|---:|
| §0 Instructions + Phase-1 preservation contract | 27 | 20 | 3 | 2 | 2 | 0 | 74% |
| §1 Frozen Sunday outcome / not-promised / cutline | 49 | 33 | 9 | 7 | 0 | 0 | 67% |
| §2–§2B Stack and architecture decisions | 21 | 15 | 2 | 4 | 0 | 0 | 71% |
| §3 Privacy boundary and threat model | 32 | 11 | 9 | 5 | 7 | 0 | 34% |
| §4 Bounded "smart agent" design | 110 | 58 | 29 | 23 | 0 | 0 | 53% |
| §4A Integration map and request-scoped retrieval | 12 | 9 | 2 | 0 | 1 | 0 | 75% |
| §5 Role-based access control | 41 | 26 | 8 | 7 | 0 | 0 | 63% |
| §6/§6A Governed organizational learning | 16 | 2 | 1 | 13 | 0 | 0 | **13%** |
| §7 Analysis, gaps, market, recommendation | 23 | 16 | 6 | 1 | 0 | 0 | 70% |
| §8 PDF report | 28 | 13 | 8 | 7 | 0 | 0 | 46% |
| §9 Frontend | 32 | 19 | 8 | 5 | 0 | 0 | 59% |
| §10 API additions | 9 | 1 | 4 | 4 | 0 | 0 | **11%** |
| §10A Reproducible clone and two-machine handoff | 30 | 5 | 2 | 8 | 15 | 0 | **17%** |
| §11 GitHub execution strategy | 17 | 6 | 2 | 2 | 5 | 2 | 35% |
| §13 Cut line — the "never cut" list | 1 | 1 | 0 | 0 | 0 | 0 | 100% |
| §14 Acceptance test matrix A01–A37 | 37 | 15 | 12 | 7 | 3 | 0 | 41% |
| §15.3 Honest performance wording | 1 | 1 | 0 | 0 | 0 | 0 | 100% |
| §16 Rollback and failure behaviour | 13 | 4 | 4 | 5 | 0 | 0 | 31% |
| §18 Definition of done | 14 | 7 | 3 | 3 | 1 | 0 | 50% |
| **Total** | **513** | **262** | **112** | **103** | **34** | **2** | **51.1%** |

**Read this table by its worst rows, not its best.** §5 (access control) at 63% and §0
(preservation) at 74% are the strongest parts of the build and they are the parts a client
never sees. The four weakest — §6 governed learning (13%), §10 API additions (11%),
§10A reproducible handoff (17%), §16 rollback (31%) — are, respectively: a promised
feature that does not exist, the asynchronous analysis lifecycle the whole of §4.2 depends
on, the ability to run this on the demonstration machine at all, and the ability to get
back if it breaks.

---

## 4. The requirements, one by one

Verdicts are grouped where every member of a contiguous block shares one verdict and one
piece of evidence. `file:line` references are to the audited commit.

### §0 — Instructions to Claude and the Phase-1 preservation contract (R001–R027)

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R001 | Preserve all twelve Nabaa invariants (§0.3) | NOT TESTABLE HERE | `RAG-INTELLIGENCE-CODEBASE.md` is not in the repository; the twelve invariants are defined there and nowhere else. The list cannot be checked against anything. |
| R002 | Introduce no PostgreSQL, Qdrant, LangChain, LlamaIndex, Docker, Kubernetes, Keycloak | MET | `backend/requirements.txt` — 17 direct dependencies, none of them. `frontend/package.json` unchanged framework. |
| R003 | No client PDFs, text, DBs, vectors, reports, secrets, prompts or answers in Git | MET | `.gitignore` reproduces §11.5 verbatim plus additions; `.githooks/pre-commit` blocks them before history; `.github/workflows/secret-scan.yml` runs gitleaks 8.30.1 pinned by SHA-256 plus a `no-client-data` job. ADR-0004 records a deliberate failure test: fake AWS key → commit rejected, `git log` unchanged. |
| R004 | Typed backend/frontend contracts; new fields required unless absence is meaningful and explicitly `null` | MET | `contracts/types.ts` mirrored by `backend/app/schemas.py`; `test_api_contract.py` and `test_runtime_contract.py` hold them together. Would fail if a Pydantic field and its TS twin diverged. |
| R005 | A planted negative test for each security/correctness guard, confirmed failing before the fix | PARTIAL | The practice is real and documented per-commit ("proven by deliberate failure"), and several tests carry the planted defect in the fixture (`test_reports.py::test_the_passage_label_names_no_clause` plants `9.9.9 PLANTED CLAUSE LABEL` so the absence assertion can fail). It cannot be verified *per guard* from the tree, and `docs/status-honesty-audit.md` records three guards that were green over broken code. |
| R006 | Never claim a test, benchmark, security property or feature not directly verified | PARTIAL | Overwhelmingly held — `docs/limitations.md`, `docs/corpus-provenance.md` and the `NOT_IMPLEMENTED` list in `app/analysis.py:38-45` all state gaps in the build's own output. Two live exceptions: `README.md:209,217` claims 279 frontend / 887 backend tests against 467 / 1,079 measured, and `docs/limitations.md:317` states the PDF download needs `auth_mode=disabled` when commit `31f0592` fixed exactly that. |
| R007 | Update `runbook.md`, `limitations.md`, `benchmarks.md` with observed results only | MET | All three present. `benchmarks.md:3` — "nothing enters this file that was not measured on the target hardware. Empty rows stay empty." |
| R008 | Develop under `development_16gb`; the same commit runs under `demo_48gb` | NOT MET | No `config/profiles/` directory exists. There is one configuration in `app/config.py` and no profile mechanism. |
| R009 | Dependency and license inventory (SBOM) before client distribution | NOT MET | No SBOM, no license inventory file, no CI job producing one. (The PyMuPDF half of this is separately met — see R430.) |
| R010 | Fix the live OCR provenance label: recognized text must not read "Quoted verbatim from the document" | MET | `frontend/src/components/chat/Provenance.tsx:21,27`; `provenance.enumerated.test.tsx` **enumerates every renderer of `AnswerPassage` found in source** and asserts each one (a) never applies the verbatim label to `text_source === "recognised"` and (b) still applies it to extracted text. A first test asserts the enumeration found renderers at all, so the scan cannot silently shrink to zero. Regressing the label to unconditional makes it red. |
| R011 | Fix the short-follow-up resolver so a new-topic question does not inherit unrelated terms | MET | `app/chat.py:146-168` — the old `len(content_words) < 3` heuristic was replaced by `is_complete_question`, so "what is the warranty period" no longer inherits a subject. `test_chat.py:63,120-137` assert a standalone question is not a follow-up and that a competing designator does not leak back. |
| R012 | Begin with a written preflight inventory of real names, migration pattern, routers, test commands, branch | MET | `docs/preflight-inventory.md`, 254 lines. |
| R013 | Existing upload, document lifecycle and legal state transitions remain backward compatible | MET | `app/states.py` + `check_transition`; `test_stage_atomicity.py` (5 tests) proves no stage leaves work done with the state unadvanced. |
| R014 | `partially_searchable` stays answerable; `ready` still means embeddings completed | MET | `docs/status-honesty-audit.md` status table; `test_no_internal_leaks.py:235,252,276` — a fully scanned PDF and an all-excluded document are not called `ready`; `no_searchable_content` is terminal but not answerable. |
| R015 | Tier 1 remains verbatim and available with every new flag off | MET | `app/answer.py` Tier 1 path untouched; `test_answer.py` + `test_auth_required_mode.py::test_auth_disabled_changes_nothing`. |
| R016 | The lexical presence gate remains absolute for local-document questions | MET | `app/lexical.py:233-251`; `app/coverage.py:24-34` explicitly forbids re-invoking `assess` per document because that would turn "does not appear anywhere" into "does not appear here". `test_correctness_fixes.py:253-304`. |
| R017 | `rerank_max_tokens == chunk_max_tokens` remains asserted as a relationship | MET (with recorded deviation) | `test_correctness_fixes.py:413` asserts `rerank_max_tokens >= chunk_max_tokens` — the relationship, not the literal. Both are 480. Deviation: `>=` not `==`; recorded in `docs/limitations.md`. |
| R018 | `RrfScore` and `RerankScore` stay separate; no feature mixes score scales | MET | `app/scores.py:122,128` — two distinct classes. `schemas.py` carries `relevance_score_type` alongside every score so a bare figure cannot invite the comparison. |
| R019 | Exclusions remain complete and inspectable | MET | `exclusions` table with scope+reason; `GET /api/documents/{id}/excluded`; `ExcludedViewer.tsx`. Honesty audit entry 12 records that dedup and pool-builder drops are now recorded under one slug vocabulary. |
| R020 | OCR remains in `page_ocr`; extraction must not overwrite it | MET | `db.py:69` table; `test_ocr.py`. |
| R021 | `text_source` remains required end-to-end | MET | `contracts/types.ts:293,480,498` — required, non-nullable on chunk and passage types. Enforced at the one place it decides what a claim may say (R010). |
| R022 | Unmeasured dashboard values remain `null`, never fabricated zeroes | MET | `app/rates.py` returns `null` below a near-zero denominator; `schemas.py:415-442` — `best_rerank_score` "NEVER 0.0 as a stand-in", `complete` null "MUST render as nothing at all"; `DashboardView.test.tsx` and `test_rates.py` hold it. |
| R023 | Existing API response contracts do not change silently; new response models for analysis | MET | `AnalysisSummary`, `AnalysisGaps`, `AnalysisRecommendation` are new models; Tier 1 `AnswerResult` unchanged. |
| R024 | Existing tests must not be weakened, deleted or converted to skips | MET | 1,079 collected, 3 skips (all condition-guarded, none blanket), 1 `slow` deselection. The per-batch `no tests were skipped - the whole suite ran` hook exists precisely to make a silent skip visible. |
| R025 | Run a characterization test before editing each touched Phase 1 path | NOT TESTABLE HERE | A per-edit process claim. The tree shows characterization-shaped tests but cannot show they preceded each edit. |
| R026 | Every migration additive and idempotent; no renamed or reinterpreted columns | MET | `db.py:460-505` uses `CREATE TABLE IF NOT EXISTS` / `PRAGMA table_info` guarded `ALTER`; `test_access_schema.py::test_the_migration_is_idempotent` runs it twice. Would fail if a migration became destructive. |
| R027 | Change budget: do not tune chunk sizes, quality thresholds, quantization, rerank thresholds, OCR settings or measured retrieval heuristics | PARTIAL | Chunking (300/480/60), `MIN_RERANK_SCORE = -3.0` and OCR settings are untouched. **`rerank_max_tokens` was changed 256 → 480 and `rerank_candidates` 20 → 16.** Recorded, measured and justified in `docs/limitations.md` (+650 ms median, retrieval 9/10 → 10/10) — a deviation taken openly, not a silent tune, but a deviation from the stated budget. |

### §1 — Frozen Sunday outcome, universal contract, not-promised, proof matrix, cutline (R028–R076)

**The 19 prototype-target bullets (R028–R046)**

| ID | Target | Verdict | Evidence |
|---|---|---|---|
| R028 | Local login with prepared Administrator and engineering-role users | MET | `POST /api/auth/login`, `LoginView.tsx`, `scripts/seed_access.py`, `test_auth.py`. |
| R029 | Server-enforced role and document access; role model configurable, not hard-coded | MET | `app/access.py`; roles are rows in `roles` with a `kind` column, not an enum. `test_access_schema.py::test_there_is_no_row_that_means_everyone`. |
| R030 | A controlled 20-document gold fixture proving comprehensive mode over two prepared questions | NOT MET | `docs/corpus-provenance.md` — the corpus is **12** documents. No 20-document fixture, no Query A / Query B gold labels. |
| R031 | Six or seven pre-indexed 1,000–1,200-page native-text PDFs | NOT MET | One document exceeds 1,000 pages (`book4`, 1,400 pp). Next largest are 613 and 546. Total corpus 3,717 pages against the plan's ~7,200. |
| R032 | One small live upload demonstrating ingestion | MET | Streaming upload path, `test_upload.py`, `IngestionView.tsx`. |
| R033 | Universal question answering across FEED packages, specs, standards, manuals, procedures, text-bearing blueprint PDFs | PARTIAL | Works across the 12-document corpus of standards, manuals and textbooks. No FEED package and no blueprint PDF is in the corpus, so the blueprint half of the claim is untested. |
| R034 | Comprehensive multi-document retrieval across every selected document the user may read | PARTIAL | Retrieval is scope-filtered across the whole authorized corpus and `app/coverage.py` reports per-document participation. There is **no document-axis coverage pass** and no `selected_document_ids` — see R187–R190. |
| R035 | Concise synthesis supported by document, page, clause and evidence-span citations | PARTIAL | Document, page and span are carried and validated. **Clause was deliberately removed** — commit `a73c096`, "stop printing a clause label that is wrong more often than right" (wrong on 5 of 6 cited passages, 0 of 11 on doc16). An honest removal, but the plan asked for it. |
| R036 | A detailed evidence ledger listing every relevant document and atomic supported finding | MET | `evidence_ledger` is a required field on all three analysis responses (`schemas.py:562,616,639`); `ClaimTable.tsx` renders it. |
| R037 | Evidence panels and rendered source pages | MET | `EvidencePanel.tsx`, `PageImageViewer.tsx`, `highlight.py`. |
| R038 | Explicit conflicts and an honest insufficient-evidence response | PARTIAL | Refusal is real and tested (`test_synthesis_honest_gate.py`, `test_advice_refusal.py`). Conflicts are emitted as `possible_conflict` only, never `conflict` — `schemas.py:580-582`: "documents carry no revision or approval status, so which supersedes cannot be known". |
| R039 | A preliminary structured gap analysis | MET | `POST /api/analysis/gaps`, `GapAnalysisCard.tsx`, `test_claims.py`. |
| R040 | An AI-generated advisory recommendation separated from documentary facts | PARTIAL | Exists, separately labelled, cited, confidence-bounded. **Its gating is specified and not implemented** — 27 strict-xfail tests in `test_recommendation_gate.py` describe three defects seen live, including a recommendation that spoke when the summary refused. |
| R041 | A downloadable, locally generated PDF report | MET | `app/reports.py`, PyMuPDF, `GET /api/reports/{id}/download`, `test_reports.py` (46 tests). |
| R042 | Approved organizational memory ("governed learning") | NOT MET | No `knowledge_feedback` table, no feedback module, no route, no UI. Nothing in the tree implements §6. |
| R043 | Optional public-market search through a sanitized, allowlisted egress boundary | NOT MET | `app/market.py` is a labelled local fixture with `sample://` URLs and no HTTP client. There is no egress boundary to sanitize. |
| R044 | Persistent local chat and report history | MET | `conversations`/`messages`/`reports` tables; `ReportsScreen.tsx`; restart persistence covered by `test_conversations_ownership.py`. |
| R045 | A dashboard showing documents, pages, roles, reports, model state and measured latency | PARTIAL | All present except the four-way latency split (R386) and the resource profile. |
| R046 | Reproducible startup from the same commit on the 16 GB laptop and the 48 GB computer | NOT MET | See §10A. No bootstrap/doctor/run-local scripts, no profiles, no second machine. `docs/benchmarks.md:20` states the 15.6 GB laptop **is** the production machine. |

**Universal question contract (R047–R048)**

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R047 | Answer any of the 11 listed intents from the authorized corpus | PARTIAL | `app/intent.py` classifies; lookup, definition, procedure, comparison, gap and summary paths exist. Table/list extraction is a stated limitation (`limitations.md` — flattened tables), calculation/counting is refused by design, market context is a fixture. |
| R048 | The same evidence rules apply to every intent; never invent an answer because the question is not about a named standard | MET | `test_advice_refusal.py`, `test_synthesis_honest_gate.py`; the lexical gate and the −3.0 floor are intent-independent. |

**Not promised Sunday — 13 negative requirements (R049–R061)**

| ID | Verdict | Evidence |
|---|---|---|
| R049–R061 — the build must not claim production readiness, Aramco approval, certified engineering/safety/legal compliance, 1,200-document or 1.2 M-page validation, CAD/P&ID/blueprint interpretation, SSO/AD/HA/DR/key management, many simultaneous users, autonomous retraining, unrestricted browsing, that every question uses every document, perfect recall, 7,200-page hybrid readiness in minutes, or guaranteed counting/table/drawing reasoning | **MET (13/13)** | Each is either absent from the code or explicitly disclaimed. `docs/limitations.md` (418 lines) states the CAD/vision boundary, the phrasing-sensitivity limit (6/10 facts), the three-passage answer cap, the equation-extraction loss and the single-user scope. `app/market.py` NOTICE forbids the word "live". `NOT_IMPLEMENTED` in `analysis.py` names three gaps on the API response itself. **These 13 are the strongest block in the audit and they are all negative requirements** — this build is markedly better at not claiming than at delivering. |

**Sunday proof matrix (R062–R066)**

| ID | Proof | Verdict | Evidence |
|---|---|---|---|
| R062 | Functional coverage: 20 controlled documents, Query A 15 relevant, Query B 10 relevant, scored against human-labelled gold | NOT MET | No 20-document fixture exists (R030). |
| R063 | Large-document scale: six or seven pre-indexed 1,000–1,200-page PDFs with measured latency | NOT MET | One such document (R031). |
| R064 | Live ingestion: one small PDF, upload→hash→extract→keyword-searchable with background progress | MET | `test_upload.py`, `IngestionView.tsx`, `docs/benchmarks.md`. |
| R065 | Security: prepared users, grants and canary data; cross-role denial and access-controlled report download | MET | `test_access_routes.py`, `test_auth_required_mode.py`, `test_reports_suppressed_count.py`. The private-data egress half is vacuous here because nothing is ever sent (R119). |
| R066 | Do not substitute one proof for another | MET | `docs/corpus-provenance.md` states the corpus exactly and separates claims that carry over to a client's documents from those that do not. |

**One-day cutline — 10 rows (R067–R076)**

| ID | Feature | Verdict | Evidence |
|---|---|---|---|
| R067 | Local chat/history/dashboard real, persisted, role-scoped | MET | Persisted and scoped; `test_conversations_ownership.py`. |
| R068 | Role-based document access real server-side, never faked | MET | §5. |
| R069 | 20-document comprehensive Q&A real, or show focused evidence and state the blocker | PARTIAL | The fallback was taken and the blocker is stated in `corpus-provenance.md`, but the coverage ledger is presented on screen, which is more than "focused evidence only". |
| R070 | Six/seven large corpus, or fewer validated large files with the exact count disclosed | MET | The fallback was taken and the count is disclosed document by document with page counts. |
| R071 | Summary and evidence ledger real and citation-validated | MET | Sentences citing nothing, or carrying a number absent from their cited spans, are **dropped** and reported in `dropped_sentences` (`main.py:601-612`) rather than rendered with a warning. |
| R072 | AI recommendation and gap analysis real and bounded, or hidden if validation fails | PARTIAL | Gap analysis real. The recommendation is neither fully gated nor hidden — the three defects in `test_recommendation_gate.py` are live on screen. |
| R073 | PDF report real, from an immutable snapshot | MET | `reports.py` renders from the snapshot only; `verify()` reports `evidence_drift` rather than silently re-reading current documents. |
| R074 | Governed self-learning: one approved glossary item, or defer the UI and never claim autonomous learning | MET (by fallback) | Deferred entirely; no autonomous-learning claim anywhere. |
| R075 | Market intelligence: approved live provider, or a dated local sample clearly labelled | MET (by fallback) | `market.py` refuses at load time any row that is not `is_sample: true`, not `sample://`, or not `source_not_verified`. `MarketPanel.tsx:295` renders "SAMPLE DATA — NOT LIVE". |
| R076 | Automatic categorization suggestion-only, or manual discipline tags | MET (by fallback) | Manual grants only; no classification writes an access grant. |
### §2–§2B — Stack and architecture decisions (R077–R097)

| ID | Decision the plan froze | Verdict | Evidence |
|---|---|---|---|
| R077 | Keep FastAPI, one Uvicorn worker | MET | `app/main.py:65`; `config.py:30-31` binds 127.0.0.1:8000. |
| R078 | Keep React 19 + TypeScript + Vite + Tailwind | MET | `frontend/package.json`. |
| R079 | Keep SQLite WAL | MET | `app/db.py`. |
| R080 | Keep FTS5 + dense vectors + RRF + cross-encoder rerank | MET | `keyword.py`, `vectorcache.py`, `scores.py`, `reranker.py`. |
| R081 | Keep the custom pipeline; no LangChain/LlamaIndex | MET | Absent from `requirements.txt`. |
| R082 | Keep chunking at 300 target / 480 max / 60 overlap | MET | `config.py:167-169` — exactly those values. |
| R083 | Keep multilingual-e5-small ONNX int8, 384 dimensions | MET | `embedder.py`, `scripts/fetch_models.py`. |
| R084 | Keep the local Qwen generator | MET | `config.py:107` `answer_model: "qwen3.5:4b"`. |
| R085 | Keep the ONNX int8 cross-encoder; fix the displayed model identity; do not tune thresholds | PARTIAL | Kept, and `DashboardView.tsx:701-713` now displays `embed_model`, `reranker_model`, `answer_model` by name. Revision, quantization, hash and context settings are not displayed (see R483/A35). Thresholds untuned except the window change recorded at R027. |
| R086 | Heavy work in the durable worker/subprocesses, not in-process `BackgroundTasks` | MET | `app/worker.py`, `ingest.py`, `extract.py` dispatch to processes; PyMuPDF never used from threads. |
| R087 | One codebase, two measured configuration profiles | NOT MET | No profiles (R008). |
| R088 | "Smart agent" is a bounded deterministic workflow — no arbitrary tools, loops, shell or hidden actions | MET | No shell, filesystem, SQL or HTTP tool is exposed to the model anywhere; the only model call sites are `analysis.py` and `answer.py` with fixed system prompts. |
| R089 | Filter access before retrieval and recheck at the resource | MET | `search.py` takes `allowed_document_ids` as a keyword-only argument; every route re-checks via `require_document`. |
| R090 | Market web search through a separate sanitized egress broker | NOT MET | No broker exists (R043). |
| R091 | Learning through human-approved memory records | NOT MET | §6 absent. |
| R092 | Recommendations separate, cited and advisory | MET | `RecommendationCard.tsx`, `REVIEW_SENTENCE` in both backend and frontend. |
| R093 | Deterministic template → PDF; the LLM provides content, not layout | MET | `reports.py` — the renderer's only input is the validated snapshot; no model call in the module. |
| R094 | Pre-index the large demo corpus before the client meeting | PARTIAL | All 12 documents are `ready` and fully embedded, so the pre-indexing discipline holds — but for a 12-document corpus, not the six or seven 1,000–1,200-page files the row is about. |
| R095 | Record exact model name, revision, quantization, hash, context size and runtime options in `models/manifest.json` | NOT MET | `models/manifest.json` does not exist. `scripts/fetch_models.py` stages weights and verifies staging, which is adjacent but is not the manifest. |
| R096 | The market adapter receives no database path, vector handle, report path or conversation object | MET | `app/market.py` imports only `json`, `functools`, `pathlib`. It cannot reach any of them. (Vacuously true while there is no adapter, but the module boundary is real and `main.py:648-651` records why the sample routes are scoped anyway: "so adding a real provider later cannot introduce an unscoped route by inheriting this shape.") |
| R097 | Use the architecture name consistently; do not market as GraphRAG, self-training agent or full multimodal blueprint intelligence | MET | No such claim in code, UI copy, README or docs. `ADR-0001` names the architecture; `test_copy_matches_reality.py` scans backend, frontend **and** contracts for copy claiming capability the build lacks. |

### §3 — Privacy boundary and threat model (R098–R129)

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R098 | §3.1 — none of the seven listed data classes leaves the machine | MET | There is no outbound HTTP client in the request path other than `httpx` to `127.0.0.1:11434` (Ollama). `market.py` makes no network call at all. |
| R099 | §3.2 — the only allowed outbound object is an approved public-market query assembled from a separate public form, never from retrieved evidence | MET | `market.preview_query` takes a query string from the caller and cannot accept passages; `main.py:658-672` states the rule at the route. Nothing is ever sent. |
| R100 | §3.3.1 `WEB_SEARCH_ENABLED=false` by default | PARTIAL | `market.egress_state()` returns `{"web_search_enabled": False, "allow_public_egress": False}` — but these are **hard-coded returns, not settings**. The plan asked for a default; there is no knob to default. |
| R101 | §3.3.2 The LLM cannot construct or call arbitrary URLs | MET | No tool interface exists; the model's output is parsed for `[Sn]` citation markers only. |
| R102 | §3.3.3 Provider base URLs are configuration allowlists, not user input | NOT MET | No provider, no allowlist. |
| R103 | §3.3.4 `https` only; block localhost, private, link-local and metadata ranges | NOT MET | No egress code path to enforce it on. |
| R104 | §3.3.5 Do not follow redirects outside the allowlist | NOT MET | Same. |
| R105 | §3.3.6 Query payload passes a deterministic secret/confidentiality scanner | NOT MET | No scanner exists. `preview_query` normalizes whitespace and truncates to 200 characters; that is not a confidentiality scan. |
| R106 | §3.3.7 Query must not contain text copied from retrieved chunks | PARTIAL | Structurally true — the function's only inputs are the caller's words and two public fields — but nothing *checks* it, so a future caller could pass a passage in. |
| R107 | §3.3.8 Query must not contain filenames, document IDs, project IDs, user IDs or history | PARTIAL | Same structural argument, same absence of a check. |
| R108 | §3.3.9 UI displays the exact outbound query and requires approval | MET | `MarketPanel.tsx` preview flow; `main.py:658` returns `sent: false` and the reason with the previewed object. |
| R109 | §3.3.10 Log only query hash, approval, provider, timestamp, result count | NOT TESTABLE HERE | Nothing is sent, so there is no outbound log to inspect. |
| R110 | §3.3.11 Public web content is untrusted data and cannot issue agent instructions | NOT MET | **No prompt-injection handling exists anywhere.** `grep -rni "untrusted\|injection" backend/app/*.py` returns one unrelated comment. See R331 and R472/A24. |
| R111 | §3.3.12 Market findings appear under "Public market information", never "Documented requirements" | MET | `MarketPanel.tsx` is a separate card; `analysis.py` keeps `public_market_findings` a separate response field from `documented_findings`. |
| R112 | §3.3.13 If policy rejects the query, continue with local documents and explain | NOT TESTABLE HERE | No policy gate exists to reject. |
| R113 | §3.3.14 Hard network-kill configuration `ALLOW_PUBLIC_EGRESS=false` | PARTIAL | Reported in the payload, not configurable (as R100). |
| R114 | §3.3.15 Do not claim regex/redaction makes arbitrary private text safe | MET | No such claim; `market.py`'s docstring makes the opposite argument. |
| R115 | §3.3.16 The provider receives only public-form fields after confirmation | NOT TESTABLE HERE | No provider. |
| R116 | §3.3.17 Store title, publisher, URL, retrieval time and excerpt; a snippet is not a verified standard | MET | `market._check` requires `claim`, `url`, `publisher`, `retrieved_at`; `published_at` may be null and renders as nothing. |
| R117 | §3.3.18 Fetch only search results/snippets; do not build a crawler | MET | No fetch of any kind. |
| R118 | §3.3.19 The adapter process receives no DB path, index handle, report path or conversation | MET | As R096. |
| R119 | §3.3.20 Treat snippets as preliminary; record source URL, publisher, dates, freshness; state `source_not_verified` where the page was not read | MET | `SAMPLE_VERIFICATION = "source_not_verified"` is the **only** value a row may carry, enforced at load time; a fixture edited later to claim otherwise raises `SampleIntegrityError` rather than rendering. |
| R120 | §3.3.21 Real Aramco data only on a client-approved device and storage location | NOT TESTABLE HERE | A deployment authorization, not a code property. |
| R121 | §3.4 — demo privacy proof: run with search disabled and prove Q&A works; then capture the outbound query and find no private text | PARTIAL | The first half holds and is the permanent state of the build (`test_market.py`, and every other test runs with no network). The second half cannot be run: there is no outbound query to capture. |
| R122 | §3.5 Bind API, frontend preview and Ollama to loopback; verify sockets in `doctor-windows.ps1` | PARTIAL | `config.py:30` `host: "127.0.0.1"`; Ollama URL is `http://127.0.0.1:11434`. **`scripts/doctor-windows.ps1` does not exist**, so the verification half is absent. |
| R123 | §3.5 Keep repository, DB, temp and reports outside auto-synchronized folders | NOT TESTABLE HERE | A property of where the operator put the clone. |
| R124 | §3.5 Dedicated non-administrator Windows account, device encryption, screen lock, encrypted transfer | NOT TESTABLE HERE | Host configuration. |
| R125 | §3.5 Disable analytics, crash uploads, remote fonts/CDNs at runtime | PARTIAL | No analytics or crash reporter is present and `reports.py` embeds local fonts. Frontend remote-asset absence was not exhaustively verified (no automated check asserts it). |
| R126 | §3.5 Restrictive Content Security Policy; escape all user/document content | PARTIAL | Escaping is real and tested (`reports.py` uses `html.escape`; `test_reports.py` asserts it). **No CSP header is set** — `grep -rni "content-security-policy"` finds nothing in `backend/app` or `frontend/index.html`. |
| R127 | §3.5 Temp files under an application-owned directory, random server-side names, retention cleanup; no secure-erasure promise | PARTIAL | Report paths are server-generated beneath a fixed root with `secrets`-derived names. No retention cleanup job exists. No secure-erasure claim is made. |
| R128 | §3.5 Log event types, IDs/hashes, durations and outcomes — not prompts, document text, filenames, tokens or rendered answers | MET | `errors.py` redaction; `test_no_internal_leaks.py:101` scans **every GET route** with hostile input for leaks, `:184` proves the redactor catches a path-bearing message. Full tracebacks go to a local log file only. |
| R129 | §3.5 Default the OS firewall to block application egress | NOT TESTABLE HERE | Host configuration. |

### §4 — Bounded "smart agent" design (R130–R239)

**§4.1 Modes and mode separation (R130–R138)**

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R130 | Implement a bounded state machine, not a general autonomous agent — no shell, filesystem, SQL, email or arbitrary HTTP tools | MET | No tool surface exists (R088). |
| R131 | Mode `extract` — existing verbatim Tier 1 | MET | `answer.py` Tier 1. |
| R132 | Mode `synthesize_focused` | MET | `POST /api/analysis/summary`. |
| R133 | Mode `synthesize_comprehensive` — coverage-aware across every selected authorized document | PARTIAL | Synthesis batches and reduces (`synthesis.py`), and `coverage.py` reports per-document participation, but there is no document-axis retrieval pass and no document selection (R187–R190). |
| R134 | Mode `gap_analysis` | MET | `POST /api/analysis/gaps`. |
| R135 | Mode `recommend` — after evidence validation | PARTIAL | Exists and runs last; gating unimplemented (R040). |
| R136 | Mode `market` | PARTIAL | Sample fixture only. |
| R137 | Mode `report` — render an already validated result | MET | `POST /api/reports` freezes an answered message. |
| R138 | Intent and coverage mode are separate; a user-requested comprehensive analysis is never silently reduced to focused | NOT MET | There is no coverage-mode parameter on any analysis request (`schemas.AnalysisRequest` = `question`, `limit`, `baseline_document_id`). The UI's Quote/Focused/Comprehensive selector chooses which *route* to call, not a mode the server enforces, so the invariant has nothing to protect. |

**§4.2 Workflow, twenty steps plus the async contract (R139–R159)**

| ID | Step | Verdict | Evidence |
|---|---|---|---|
| R139 | 1. Authenticate the user | MET | `auth.py`, `access.current_scope`. |
| R140 | 2. Resolve conversation follow-up without unrelated term borrowing | MET | R011. |
| R141 | 3. Classify intent and requested mode | PARTIAL | `intent.py` classifies intent; there is no requested mode (R138). |
| R142 | 4. Build an immutable `AccessScope` from the server-side user record | MET | `access.py` — `@dataclass(frozen=True, slots=True)`, no default constructor argument, never cached in module state. `test_access_routes.py::test_two_concurrent_requests_never_share_scope` runs two roles genuinely in parallel and would fail if a module-level cache were introduced. |
| R143 | 5. Classify the answer operation across eight kinds | PARTIAL | Lookup, procedure, summary, comparison, gap and recommendation are distinguishable; calculation/counting and unsupported-visual are refused rather than classified. |
| R144 | 6. Decompose into at most three subquestions without changing meaning | NOT MET | No decomposition step exists. `coverage_max_subqueries` is not in the configuration. |
| R145 | 7. Choose coverage; in comprehensive mode run a bounded pass per selected authorized document and record a status for each | PARTIAL | `coverage.py` assigns a per-document status **from what already happened**, by its own statement ("Report-only. Nothing here changes retrieval"). No independent per-document retrieval pass runs. |
| R146 | 8. Fuse, rerank and deduplicate while retaining document identity and provenance | MET | `search.py` + `scores.py`; drop reasons for all five drop sites recorded under one slug vocabulary (honesty audit entry 12). |
| R147 | 9. Produce citation-preserving per-document evidence maps, then compare across documents | PARTIAL | Cross-document comparison is real (`claims.py`, claim clusters by facet). Per-document evidence *maps* are not built as a separate artefact. |
| R148 | 10. Evaluate sufficiency, coverage, agreements, conflicts, revision differences and missing information | PARTIAL | All but revision differences, which the corpus cannot support (R038). |
| R149 | 11. If weak, reformulate once and retrieve once more; no unbounded loop | NOT MET | No retry exists. `coverage_max_retries` is not in the configuration. (The "no unbounded loop" half is trivially satisfied.) |
| R150 | 12. Refuse unsupported claims or unsupported operation types | MET | `test_advice_refusal.py`, `test_synthesis_honest_gate.py`. |
| R151 | 13. Generate structured documentary findings from validated evidence | MET | `documented_findings` on `AnalysisSummary`. |
| R152 | 14. Verify every factual claim maps to real citation IDs and that numeric values/units are present in cited evidence | MET | `synthesis.py` + `assertions.py`; a sentence carrying a number no cited span contains is **dropped**, not flagged. A regression that let an uncited sentence through fails `test_synthesis.py` / `test_synthesis_honest_gate.py` (151 tests in that batch). |
| R153 | 15. Generate agreements, conflicts and preliminary gap items | PARTIAL | Agreements and gaps yes; `possible_conflict` only (R038). |
| R154 | 16. Optionally accept a separately entered public query through the policy/approval gate | NOT MET | No gate (R105). |
| R155 | 17. Compare public findings with documentary findings without treating public as an internal requirement | PARTIAL | Separation is real; the comparison matrix of §7.3B.7 is not built. |
| R156 | 18. Generate the advisory recommendation last, from validated sections only | MET | `synthesis.confidence_checks(...)` is computed after the gap analysis, per-document statuses, cluster labels and coverage — the module docstring states this is "computed LAST … per 7.3A". |
| R157 | 19. Persist inputs, per-document coverage, evidence IDs, result, model/config versions and timings | NOT MET | **There is no `analyses` table.** `analysis.py:44` says so on the response itself. Analysis results live only in the HTTP response and, for reports, in the frozen report snapshot. |
| R158 | 20. Render the report on explicit user action | MET | `POST /api/reports` is user-initiated. |
| R159 | Long comprehensive work is asynchronous: `202 Accepted` + `analysis_id`, persisted checkpoints, SSE with polling fallback, safe cancellation with an auditable `cancelled` status | NOT MET | Every analysis route is synchronous. No `202` anywhere in `app/`; no `StreamingResponse`; no `text/event-stream`; no cancel route. |

**§4.3 / §4.3A Rationale and evidence contract (R160–R163)**

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R160 | Return the auditable rationale object of §4.3 (documented_findings, cross_document_analysis, conflicts, gaps, recommendation, assumptions, confidence, citations, retrieval_summary) | PARTIAL | Findings, gaps, conflicts (as `possible_conflict`), recommendation, confidence and citations exist across three separate responses. `assumptions` and the nine-field `retrieval_summary` block do not. |
| R161 | Never display scratchpad tokens or ask the model to reveal hidden reasoning | MET | No route exposes a prompt or raw model output; `test_no_internal_leaks.py:285` requires every endpoint to declare a typed success response. |
| R162 | Every downstream section uses the immutable evidence object of §4.3A | PARTIAL | `analysis.evidence_id` is `sha256(document_id|page_start|page_end|section|exact_span)[:16]` — **better than the plan asked**, because it survives re-chunking, and `exact_span` is the chunk's own text, never a reflow. Missing from the contract: `citation_id`, `revision`, `approval_status`, `content_hash`, `parent_context`, `supported_facets`. |
| R163 | Report reproduction uses the stored immutable snapshot and never silently re-reads current document text | MET | `reports.render()` performs no query against `documents`, `chunks` or `pages`; `verify()` returns `evidence_drift`. `test_reports.py` covers regeneration after a metadata change. |

**§4.4 Evidence sufficiency gate (R164–R170)**

| ID | Condition | Verdict | Evidence |
|---|---|---|---|
| R164 | The lexical presence gate passes for distinctive local terms | MET | R016. |
| R165 | At least one authorized passage exceeds the credibility threshold | MET | `MIN_RERANK_SCORE = -3.0`, absolute; `limitations.md` records why it is not lowered (a floor admitting every correct-at-rank-1 query also admits 3 of 3 unanswerable ones). |
| R166 | Each generated factual claim has a valid supporting citation | MET | R152. |
| R167 | Numeric claims preserve value, unit and identifier from the evidence | MET | R152 — the number check is the same code path. |
| R168 | Conflicting current requirements are presented as conflicts, not silently merged | PARTIAL | Not merged, and surfaced — but as `possible_conflict` (R038). |
| R169 | OCR-derived claims carry recognized-text provenance | MET | R010/R021. |
| R170 | Otherwise return `INSUFFICIENT_EVIDENCE` with the passages checked and narrowing suggestions | MET | `test_acronyms.py` — "an absent acronym gets a useful refusal not a dead end", "the refusal names the term rather than only lacking confidence". |

**§4.5 Multi-document synthesis (R171–R178)**

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R171 | Retrieve 30 lexical and 30 dense candidates | MET | `config.py:174` `search_candidates: 30`. |
| R172 | Preserve RRF, identifier precedence, conflict penalty, cross-encoder reranking | MET | `search.py`, `scores.py`, `reranker.py`. |
| R173 | Retain every validated atomic evidence item in the ledger; cap only what enters one LLM call | MET | `context_budget.py` caps the prompt; the ledger is emitted whole. |
| R174 | Add diversity after reranking — up to three complementary passages per document, then further deterministic batches; never delete evidence because a prompt is full | PARTIAL | Deterministic batching and reduce exist. **The three-per-document diversity rule does not**; instead an answer takes at most three highest-ranked passages overall, which `limitations.md` records as a known cut: "a passage that cleared the credibility floor in another document can be left out". |
| R175 | Prefer approved/current revisions over obsolete ones where revision metadata is explicit | NOT MET | The `documents` table has no `revision` or `approval_status` column (R261), so the preference cannot be expressed. Declared in `analysis.NOT_IMPLEMENTED`. |
| R176 | Never summarize a 1,200-page document by placing it in the prompt | MET | `context_budget.py` computes the allowance before every call and fails configuration validation if it is non-positive. |
| R177 | Interpret "summarize across all documents" as retrieve-all-relevant-then-synthesize | PARTIAL | Behaviourally true within the global pipeline; not enforced as a mode (R138). |
| R178 | Report how many authorized documents were searched and which supplied evidence | MET | `Coverage.searched_documents` plus per-document rows; `CoverageLedger.tsx`. |

**§4.5A "Do not miss information", operationally (R179–R188)**

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R179 | Product 1 — a consolidated readable answer | MET | `AnalysisSummary.summary`, null (not an empty block) when refused. |
| R180 | Product 2 — a complete validated evidence ledger with page/clause/span citations, document status and inclusion reason | MET | `evidence_ledger` + `evidence_removed` + `dropped_sentences`. Clause is deliberately absent (R035). |
| R181 | Nothing silently removed between validated ledger and report snapshot; a source may leave the prose only under `Also supported by` | PARTIAL | Removal is never silent — `evidence_removed` and `dropped_sentences` carry reasons, and the five candidate-drop sites now record one. **`also_supported_by` does not exist** in any schema or type. |
| R182 | Measure relevant-document recall | NOT MET | No gold fixture to measure against (R030). |
| R183 | Measure atomic-claim recall | NOT MET | Same. |
| R184 | Measure citation precision and entailment | PARTIAL | `eval/run_eval.py` measures citation correctness on an 11-question set and, per honesty-audit entry 14, now scores both tiers. Entailment is not measured. |
| R185 | Measure unsupported-claim rate | PARTIAL | Structurally zero by construction (uncited sentences are dropped) and `dropped_sentences` is observable, but no rate is computed or recorded. |
| R186 | Measure non-relevant-document exclusion | NOT MET | No gold fixture. |
| R187 | Measure failed/not-searchable visibility | PARTIAL | Document status is visible and honest (`no_searchable_content`, `failed`), but not as a coverage metric over a labelled set. |
| R188 | The Sunday fixture requires 100% relevant-document recall and 100% citation precision | NOT MET | No fixture. |

**§4.5A Focused versus comprehensive retrieval — ten steps plus the disclosure rule (R189–R199)**

| ID | Step | Verdict | Evidence |
|---|---|---|---|
| R189 | 1. Resolve `selected_document_ids ∩ allowed_document_ids` on the server | NOT MET | No request carries selected document IDs. |
| R190 | 2. Per-document exact + lexical + dense retrieval with a per-document quota | NOT MET | Retrieval is global over the authorized scope; no per-document quota exists. |
| R191 | 3. Rerank pooled candidates in deterministic batches giving each document a fair validation opportunity | NOT MET | One 16-candidate global shortlist. `coverage.py`'s own header documents the consequence: on gold question Q4 a passage scoring **+2.104 against a −3.0 floor** was ranked fifth and lost to `limit=3`. |
| R192 | 4. Assign exactly one per-document status from `relevant / no_sufficient_evidence / failed / not_searchable` | NOT MET | A **different seven-value enum** is used (`credible_not_cited` among them). This is a deliberate, recorded correction — honesty-audit entry 13 records that none of the plan's four values was true of Q4 — but it is not the contract the plan specifies, and no plan value maps cleanly onto `credible_not_cited`. |
| R193 | 5. Build an evidence map per relevant document with exact citation IDs | PARTIAL | Evidence items carry stable IDs; they are not grouped into per-document maps. |
| R194 | 6. Split evidence maps by facet and deterministic token budget when one call would overflow | MET | `context_budget.py` + `synthesis.py` batching. |
| R195 | 7. Produce citation-preserving batch syntheses retaining the underlying evidence IDs | MET | `synthesis.py` — a reduce is built from evidence IDs re-expanded through the ledger, **never** from a lower level's `[Sn]` markers, because position 1 means a different passage at every level. That is the single most likely way this feature would invent a citation, and it is closed by construction. |
| R196 | 8. Reduce batches recursively into agreements, additions, conflicts, gaps and findings without losing provenance | MET | Same module; `test_synthesis.py`. |
| R197 | 9. Run claim-to-citation validation on the final output | MET | R152. |
| R198 | 10. Return the coverage ledger with searched/relevant/no-evidence/failed counts | PARTIAL | A coverage ledger is returned with `searched_documents` and per-document rows, but not those four counts, and `complete` is structurally never `true`. |
| R199 | Do not expose counts or identities of selected documents removed by authorization | MET | The ledger is built from the scope after filtering; `test_access_routes.py::test_a_hidden_document_is_indistinguishable_from_a_missing_one`. |

**§4.5A Query plan and coverage honesty (R200–R202)**

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R200 | The planner extracts entities, acronyms/identifiers/clauses, actions, numbers/units, revision/applicability constraints, comparison dimensions and exhaustiveness intent | PARTIAL | `keyword.find_designators`, `acronyms.py`, `symbols.py` and `intent.py` cover entities, identifiers, acronyms, designators and comparison intent. Revision/approval constraints and exhaustiveness intent are absent. |
| R201 | Exact identifiers and quoted phrases are never discarded or replaced by an LLM paraphrase | MET | Identifier precedence in `search.py`; `test_correctness_fixes.py:484` asserts the zinc-temperature answer is the same clause whatever the phrasing. |
| R202 | "No relevant evidence found" is a retrieval result, not proof of absence; "all relevant information" is an evaluation target, not a prompting guarantee | MET | `coverage.py:16-24` states exactly this and `complete: true` is unreachable by construction — a test holds it, and `schemas.py:436-442` explains that a null rendered as a checkmark turns "I did not check" into "I checked and it is fine". |

**§4.5A Fast comprehensive execution — ten rules (R203–R212)**

| ID | Rule | Verdict | Evidence |
|---|---|---|---|
| R203 | 1. Normalize the question and compute each query-variant embedding once, reused for all documents | MET | `embedder.py` / `search.py` embed once per request. |
| R204 | 2. Resolve the immutable authorized/selected scope once | MET | `access.current_scope` per request. |
| R205 | 3. Exact/FTS retrieval per document with a bounded read pool, one SQLite read connection per worker | PARTIAL | One connection per request and never shared concurrently (which is the safety half). There is no per-document read pool. |
| R206 | 4. One vectorized dense pass over the selected authorized rows, then partition by document | PARTIAL | One vectorized pass over the authorized mask — the efficient half is met. No partitioning or per-document quota. |
| R207 | 5. Merge/deduplicate per document using existing RRF and identifier rules | PARTIAL | Global merge/dedupe, not per document. |
| R208 | 6. Rerank in deterministic per-document batches through the single ONNX session; no competing reranker sessions | PARTIAL | One session, deterministic batching — met. Per-document batches — not. `limitations.md` records the measured batch-composition sensitivity (±0.5 on a −3.0 floor) that makes this non-trivial. |
| R209 | 7. Apply the credibility/evidence gate independently per document | NOT MET | The gate is global. |
| R210 | 8. Build extractive evidence maps first; do not call the LLM merely to copy passages | MET | Tier 1 is extractive and needs no model; `analysis.to_evidence` is pure. |
| R211 | 9. Synthesize once if everything fits, otherwise deterministic citation-preserving batches then one reduce | MET | `synthesis.py`. |
| R212 | 10. Stream stage progress (`20 searched → 15 relevant → synthesis batch 1/N → validation → complete`) | PARTIAL | `app/progress.py` + `GET /api/progress/{id}` + `usePoll` give real progress with named phases, and `AnalysisModeScreen` shows what the run is doing. It is not the coverage-stage sequence the plan specifies, and it does not stream (polling only). |

**§4.5A Profiles, bounds and the token budget (R213–R218)**

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R213 | Expose configuration through two committed profiles with the stated per-control values | NOT MET | No profiles (R008). |
| R214 | Commit the `coverage_*` bounds (`coverage_max_documents`, `_lexical_per_doc`, `_dense_per_doc`, `_rerank_per_doc`, `_max_subqueries`, `_max_retries`) | NOT MET | None of the six exists in `app/config.py`. |
| R215 | Count tokens with the exact deployed tokenizer and compute the evidence allowance; fail configuration validation if it is non-positive | MET | `app/context_budget.py` (9 KB) does exactly this, against the deployed tokenizer, with the measured table recorded in `docs/benchmarks.md`. `test_context_budget.py` would fail if the allowance were computed from a constant. |
| R216 | If an evidence map does not fit, split only at atomic-evidence boundaries; never cut a citation span in half | MET | `synthesis.py` splits on evidence items; `_HALF_CITATION` exists specifically to catch a marker the output cap cut in half. |
| R217 | Benchmark 2,048/4,096 on 16 GB and 4,096/8,192 on 48 GB and select the smallest context that passes | PARTIAL | `num_ctx = 4096` is set and `docs/benchmarks.md` records the measurement behind it — on the 16 GB host only. The 48 GB half cannot be run. |
| R218 | A memory-aware stage lease making `ocr`, `embedding`, `rerank` and `generation` mutually exclusive on 16 GB, enforced by a process-level semaphore | NOT MET | No lease and no semaphore. The runbook forbids simultaneous OCR and Q&A **in prose**, which is honesty-audit standing rule 11 ("a documented hazard is not a guard") applied to this exact case. |

**§4.5A Ingestion capacity and the lifecycle contract (R219–R222)**

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R219 | "Answerable in two minutes" may only mean extraction + keyword availability, and the actual state must be displayed | MET | `documentStatus.ts` + `states.tsx`; `test_no_internal_leaks.py` proves a partially processed document is never called ready; `docs/status-honesty-audit.md` fixes the meaning of each status. |
| R220 | Each lifecycle state permits only its stated behaviour | MET | `app/states.py` `check_transition`; answerable = `partially_searchable` or `ready`, nothing else. |
| R221 | The 20-to-15 case renders the exact four-line coverage statement | NOT MET | No such rendering, and no fixture to produce it. |
| R222 | Label the overall result `analysis_incomplete` when any document failed or was not searchable | NOT MET | **`analysis_incomplete` appears exactly once in the whole repository** — `frontend/src/types/analysis.ts:22`, as a member of a union that nothing produces and nothing renders. A declared status no code can emit is the same shape as a provenance field no assertion reads. |

**§4.6 Blueprint boundary (R223–R229)**

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R223–R228 | Must not claim reliable understanding of CAD geometry, engineering symbols without labels, P&ID line connectivity, graphical-only dimensions, flattened table row/column relationships, or formulas whose operators were lost | **MET (6/6)** | No such capability is claimed anywhere, and each is disclaimed specifically: `docs/limitations.md:368-369` states tables flatten and that PyMuPDF loses `=` and `+` operators so an equation page "becomes prose *about* mathematics with the mathematics missing". `test_copy_matches_reality.py` scans for copy that would overstate. |
| R229 | The page image is verification evidence, not proof the text model interpreted the drawing | MET | `PageImageViewer.tsx` is presented as source evidence; no interpretation claim attaches to it. |

**§4.7 Large-file ingestion controls (R230–R239)**

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R230 | Stream uploads to an application-owned temp file; enforce request/file/page/disk quotas before work | MET | `upload.py` streams in `upload_chunk_bytes` blocks; `max_upload_mb: 512`; `test_upload.py`. |
| R231 | Validate magic bytes and parser result, sanitize the display filename, generate the storage path server-side, reject encrypted/corrupt files cleanly, hash for idempotent duplicate detection | MET | `errors.py` codes `not_pdf`, `encrypted_pdf`, `too_large`, `duplicate`; `test_upload.py`. |
| R232 | Run parser/OCR in the isolated subprocess boundary with no network and bounded resources; scan for malware or record scanning as a production blocker | PARTIAL | The subprocess boundary is real (`extract.py`, `ocr.py`). **No malware scanner and no recorded production blocker** for it in `limitations.md`. |
| R233 | Persist page/batch checkpoints; resume only when file hash and configuration signature match | MET | `ADR-0003` "never cut: crash resume from the last completed page batch"; `test_stage_atomicity.py:175` recovers a document stranded by an older build. |
| R234 | Queue documents; one heavy stage at a time on 16 GB; never use PyMuPDF concurrently from threads | MET | `worker.py` single loop; `extract_processes: 2` uses processes, not threads. |
| R235 | Commit document metadata and the uploader/admin's initial access grants transactionally | NOT MET | `upload.py` writes no grant. A newly uploaded document has **no** grant until an administrator adds one — which fails safe (nobody can read it) but is not the transactional commit the plan specifies, and §5.5's thirteenth negative test has nothing to test. |
| R236 | Publish `partially_searchable` immediately after valid FTS chunks commit | MET | `test_stage_atomicity.py:96` — indexing and the state advance are one transaction. |
| R237 | Use content signatures to invalidate only stale vectors/chunks; extraction never overwrites `page_ocr` | MET | R020. |
| R238 | Store exclusions with reasons and counts; "processed 1,200 pages" means every page reached a recorded outcome | MET | `exclusions` + `chunk_count` / `chunk_count_total` published together (standing rule 3). Honesty-audit entry 8's second instance records the count of silently-dropped pages as **zero**, measured. |
| R239 | Reserve estimated disk headroom for originals, DB/WAL, page images, vectors, reports and one backup before accepting a batch | NOT MET | No headroom reservation exists. `ADR-0003` records ~45 GB free as a prototype-scale constraint, which is a note, not a check. |

### §4A — Integration map and the request-scoped retrieval contract (R240–R251)

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R240 | Create focused new modules rather than enlarging `main.py`, `search.py`, `answer.py` | PARTIAL | `auth.py`, `access.py`, `analysis.py`, `market.py`, `reports.py`, `claims.py`, `synthesis.py`, `coverage.py`, `context_budget.py` were all created. But there is **no `backend/app/routers/` package** — `main.py` is 49 KB / ~1,170 lines carrying all 41 routes, and `search.py` grew to 35 KB. |
| R241 | `search()` takes `allowed_document_ids` explicitly | MET | Keyword-only parameter; the honesty audit records the deliberate choice of no default, and that five `eval/` call sites surfaced only because of it. |
| R242 | The default must never mean "all documents" | MET | `access.py` — "It never defaults to 'everything'. `AccessScope` has no default constructor argument." `unrestricted_scope()` says in its own name what it is. `test_search.py:354` — an empty scope returns nothing rather than everything. |
| R243 | Never store the current user or allowed IDs in a process global, singleton, environment variable or shared vector-cache state | MET | Enforced by `test_two_concurrent_requests_never_share_scope`, which runs genuinely in parallel; a module-level cache makes it red. |
| R244 | Parameterized document-ID restrictions, checked against SQLite's variable limit | MET | `keyword.py` parameterizes; no SQL identifier concatenation. |
| R245 | Dense filtering uses the same resolved scope before top-k selection | MET | `test_search.py:335` — the dense path cannot reach a document outside the scope. Would fail if filtering moved after selection. |
| R246 | Cache only by an immutable authorization-version/scope hash; never trust a cached scope because a token is still valid | MET | No scope cache exists; `auth.py:368-380` re-reads `is_active` on every request rather than trusting the token. |
| R247 | `AUTH_MODE=disabled\|demo_required`; `disabled` only for backward compatibility; `demo_required` required by the Sunday runbook | PARTIAL | Both modes exist and `test_auth_required_mode.py` (52 tests) covers `demo_required`. `disabled` is the shipped default and `docs/runbook.md` does not require the switch. |
| R248 | Under `demo_required` every non-health route requires identity unless documented public | MET | `test_auth_required_mode.py::test_an_unauthenticated_caller_is_refused_rather_than_served_everything`. |
| R249 | `/api/health` may stay unauthenticated but returns no filenames, counts, paths or confidential model/config details | MET | `test_health.py`, `test_no_internal_leaks.py:120`. The `current_document`/`last_error` fields were removed from it (honesty-audit entry 15). |
| R250 | Preserve old Tier 1 payloads; new synthesis/gap responses use a new response model | MET | R023. |
| R251 | Feature flags alter availability, never the evidentiary meaning of an existing response | NOT TESTABLE HERE | There are no feature flags (R487–R491), so the invariant has no subject. |
### §5 — Role-based access control (R252–R292)

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R252 | §5.1 The six roles are seed data, not a hard-coded enum; a user may hold several; a package may span disciplines | PARTIAL | Configurability is real — roles are rows with a `kind` column (`db.py:242-268`), `admin` is a capability rather than a fifth discipline, and multi-role users are tested. **Four disciplines are seeded (Civil Engineering, Mechanical, Chemical-Process, IT); `electrical_engineer` is not.** §1 asks for four, §5.1 tabulates five plus admin. |
| R253 | §5.1A Categorization and authorization are separate; a suggestion never creates a grant; reclassification never widens access | MET | Only `admin.py`'s explicit grant path writes `document_role_access`; no classifier writes it. `test_admin.py`. |
| R254 | §5.1A Each suggestion carries confidence, evidence page IDs and classifier version; `unknown` and `multidisciplinary` are valid | NOT MET | There is no suggestion record at all. `scripts/categorize_documents.py` and `scripts/classify_report.py` are offline operator tools writing no versioned suggestion; `admin.UNKNOWN_DISCIPLINE` is an error code, not an outcome. |
| R255 | §5.2 The seven tables of the minimum schema exist | PARTIAL | `users`, `roles`, `user_roles`, `document_role_access`, `audit_events` — **present**. `disciplines`, `document_disciplines`, `document_user_access` — **absent**. Disciplines are modelled as `roles.kind = 'discipline'` instead, which is a defensible simplification; `document_user_access` is not replaced by anything. |
| R256 | §5.2 Access resolution is deny-by-default | MET | Deny-by-default is a property of the schema: `db.py:288-292` — "There is no row meaning 'everyone', and no wildcard document id". `test_access_schema.py::test_there_is_no_row_that_means_everyone`, `::test_a_user_with_a_role_but_no_document_grant_still_sees_nothing`. |
| R257 | §5.2 An explicit user `deny` overrides any role `allow`; a user `allow` may grant a narrower exception | NOT MET | There is no user-level grant or deny. `scope_for_user` is a single join over `user_roles → document_role_access` with no second query and, deliberately, no Python fallback. Adding deny requires a table that does not exist. |
| R258 | §5.2 Administrator status grants management, not automatic read of every confidential document | MET | `access.py` grants an administrator no read bypass — "an IT+admin user sees exactly the six documents IT sees". `main.py:143-176` records that corpus-wide *counts* on `/api/metrics` are a new, deliberately narrow capability and travel with a `corpus_wide` flag so the screen can say which kind of number it shows. |
| R259 | §5.2 Seed demo access through a local setup command, never hard-coded plaintext passwords or production migrations | MET | `scripts/seed_access.py`; `test_seed_access.py`; `users` has no column a password could be stored in. |
| R260 | §5.2 Add nullable `project_code`, `document_type`, `revision`, `approval_status` to `documents` | NOT MET | None of the four columns exists. This is the root cause of R038, R175 and half of §8.2. |
| R261 | §5.2 Ownership on user-generated records: `conversations.owner_user_id`, and required owners on `reports` and `analyses` | PARTIAL | `conversations.owner_user_id` and `reports.owner_user_id` exist and are enforced. There is no `analyses` table (R157). |
| R262 | §5.2 Legacy conversations denied to ordinary users; `NULL` ownership never means globally readable | MET | `test_conversations_ownership.py::test_owner_id_has_no_default_so_a_legacy_row_cannot_look_owned` and `::test_a_legacy_conversation_is_assigned_to_the_admin_capability`. Would fail if a default were added to the column. |
| R263 | §5.2 Indexes for every authorization join on the request path | MET | `db.py:301-302,497` — `idx_dra_role`, `idx_user_roles_user`, `idx_conversations_owner`. |
| R264 | §5.2A The `analyses`, `analysis_document_status` and `reports` tables with their indexes | PARTIAL | `reports` and `report_documents` exist with owner/created indexes. The other two do not. |
| R265 | §5.2A All JSON schema-validated before storage and after reading | PARTIAL | Report snapshots are validated on read and hashed (`snapshot_sha256`). Message payloads are stored as JSON without a schema round-trip. |
| R266 | §5.2A `run_status` and `answer_status` must not be collapsed into one enum | NOT MET | Neither exists; analyses are synchronous, so there is no run status. The distinction the plan protects has no subject here. |
| R267 | §5.2A Resume only from a validated checkpoint whose hashes, authorization snapshot and config version still match | NOT MET | No analysis checkpoints. (Ingestion resume *does* validate hash and config signature — R233 — but that is a different subject.) |
| R268 | §5.2B The nine-step migration and rollback protocol, with a verified backup and rollback by restore | PARTIAL | Migration is additive, transactional and proven idempotent (R026). **No backup step, no `PRAGMA integrity_check` verification, no restore drill** exists in the tree or the runbook. |
| R269 | §5.3 A maintained password hasher, Argon2id preferred | MET | `auth.py:55,67` — `argon2.PasswordHasher`. |
| R270 | §5.3 Short-lived signed access tokens held in memory on the frontend; never in local storage | MET | `auth.py:147-165` HMAC-SHA256 signed, `auth_token_seconds` 8 h; `App.tsx:57` — "module-level variable, never localStorage". |
| R271 | §5.3 Signing secret generated at setup, kept in `.env`, never in Git | MET | `config.py:57` `auth_secret: ""` default; `.env` gitignored; `.githooks/pre-commit` + gitleaks. |
| R272 | §5.3 Constant-time password verification | MET | `hmac.compare_digest` at `auth.py:165`; Argon2 verify for the password itself. |
| R273 | §5.3 Disable inactive users | MET | `auth.py:306,368-380` — `is_active` re-read on **every** request rather than trusted from the token, so a deactivation takes effect immediately. |
| R274 | §5.3 Rate-limit login attempts locally | MET | `auth_max_attempts: 8`, `auth_lockout_seconds: 300`; `test_auth.py`. |
| R275 | §5.3 Add `GET /api/me` | PARTIAL | The route is `GET /api/auth/me` (`main.py:533`). Functionally equivalent, path differs from the contract in §10. |
| R276 | §5.3 Do not call this corporate SSO | MET | No such claim. |
| R277 | §5.4 One central `AccessScope` with `user_id`, `role_ids`, `readable_document_ids`, `manageable_document_ids`, computed server-side and never accepted from request JSON | PARTIAL | Central, immutable and server-derived — the strongest part of this build. Its fields are `user_id`, `allowed_document_ids`, `capabilities`; **there is no `manageable_document_ids`**, so manage-permission is resolved ad hoc through the admin capability rather than through the scope. |
| R278 | §5.4 Apply it before data access to all eleven listed resource classes | MET | 41 routes; `Depends(access.current_scope)` on every non-health, non-login route and `require_document` before each resource read (`main.py:249,308,324,339,349,373,396,433,756,853,895,946,997,1034`). |
| R279 | §5.4 An unauthorized document ID produces the same non-revealing response whether it exists or not | MET | `test_access_routes.py::test_a_hidden_document_is_indistinguishable_from_a_missing_one`; `test_auth_required_mode.py::test_an_out_of_scope_document_returns_404_and_never_403`. Commit `6d42249` records the decision explicitly. The fixture builds two documents with **different text** and asserts `visible != hidden`, because an earlier version used identical bytes that deduplicated into one document and every test was asserting a document could not see itself. |
| R280–R292 | §5.5 The thirteen required negative tests | **11 MET, 2 NOT MET** | Present and non-vacuous: Civil cannot list an IT document (R280); nor reach it by keyword (R281, `test_search.py:317`); nor by dense search (R282, `:335`); nor by guessing document, page-image, chunk, exclusion or report IDs (R283); nor through another user's conversation (R284); nor request a report containing it (R285, `test_reports.py:448` — a report vanishes when a cited document leaves the reader's scope); frontend manipulation of role/document IDs changes nothing server-side (R286); admin metrics do not leak through ordinary metrics (R287); revocation takes effect on the next request (R288, `test_admin.py:220`, whose fixture asserts the grant existed first so a revoke proves something); two simultaneous different-role requests never share scope (R290); a legacy `NULL`-owner conversation is inaccessible (R292). **Missing: R289** — a user-level deny overriding a role allow in both lexical and dense retrieval (no such feature, R257) — and **R291** — an uploaded document and its initial grant committing or rolling back together (no grant is written at upload, R235). |

### §6 / §6A — Governed organizational learning (R293–R308)

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R293 | Do not fine-tune or update model weights | MET | No training code, no weight write path. |
| R294 | The `knowledge_feedback` table | NOT MET | Absent from `db.py`. |
| R295–R301 | §6.2 The seven rules: only administrators approve; an approved factual correction requires a citation or is labelled organizational guidance; approved records are versioned and revocable; pending/rejected records are never retrieved as trusted; organizational knowledge is permission-scoped; retrieved guidance appears in its own labelled section; feedback stays local | **NOT MET (7/7)** | No feedback module, no approval path, no retrieval of organizational knowledge. `grep -rn "knowledge_feedback\|governed"` across `backend/app`, `contracts` and `frontend/src` returns one unrelated UI sentence. |
| R302–R306 | §6.3 The five Sunday UI elements: `Suggest correction` on an answer; an admin `Knowledge review` list; approve/reject controls; an `Approved organizational guidance` badge; one demonstrated glossary item affecting a later answer | **NOT MET (5/5)** | None exists. |
| R307 | §6A Two deliberately separate memory layers, with conversation memory never citable as proof | PARTIAL | The conversation layer is correct and enforced — `chat.py` accepts only prior **user** questions, and `test_chat.py::test_prior_user_questions_exclude_assistant_messages` would fail if an assistant answer were admitted. The approved-organizational layer does not exist. |
| R308 | §6A Acceptance: restart persistence, no cross-user history, a genuine follow-up resolves, a short unrelated question does not inherit prior identifiers, remembered scope re-intersected with the current `AccessScope`, revoked grants invalidate remembered scope | MET | `test_chat.py` (follow-up resolution, window, competing designators), `test_conversations_ownership.py` (cross-user), `test_admin.py:220` (revocation). |

### §7 — General analysis, gap analysis, market comparison, recommendation (R309–R331)

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R309 | §7.1 Inputs: any supported question, selected authorized documents, optional baseline, optional market toggle | PARTIAL | Question and baseline yes (`AnalysisRequest.baseline_document_id`, resolved through `require_document` so an unreadable id is 404). **No selected-document input.** The market toggle is a UI switch over a fixture. |
| R310 | §7.2 The output contract of §7.2 | PARTIAL | Delivered as three responses rather than one. Present: `evidence_ledger`, `documented_findings`, `claim_clusters`, `gaps`, `recommendation` with `citation_ids`/`basis`/`confidence`, `public_market_findings` with `verification`. Absent: `analysis_id`, the `coverage.complete` boolean as specified, the six-value `status` enum, `agreements`/`conflicts` as top-level arrays, `market_comparison`, `assumptions`, `limitations`. |
| R311 | §7.3 Every query receives documented findings and a coverage ledger; gap analysis may be `not_applicable` | PARTIAL | Findings and a ledger yes; the coverage ledger is attached to the analysis screen rather than to every query response. `not_applicable` is a real gap state. |
| R312 | §7.3 `compliant` only where positive matching evidence exists; absence of a discovered gap is not compliance | MET | `claims.py` gap states are `met`, `possible_gap`, `conflict`, `insufficient_evidence`, `not_applicable`; `test_claims.py`. Commit `8a74139` — "a gap status that agrees with its own note". |
| R313 | §7.3 A gap requires an explicit or confidently extracted baseline plus missing/conflicting project evidence | MET | `analysis.gaps` refuses to choose a baseline: "Choosing one here — the oldest document, the one with 'standard' in its name — would be the system deciding which document is authoritative." |
| R314 | §7.3 Missing evidence becomes `insufficient_evidence`, not automatically a gap | MET | Same enum; `test_claims.py`. |
| R315 | §7.3 Conflicting revisions become `conflict` unless authority is unambiguous | PARTIAL | Emitted as `possible_conflict` in every case because no document carries a revision (R260). Honest, and not what the plan specified. |
| R316 | §7.3 All documentary findings require citations | MET | R152. |
| R317 | §7.3 Public web findings cannot prove internal project compliance | MET | Separate response field and separate card; sample rows are `source_not_verified` by construction. |
| R318 | §7.3 Recommendations labelled AI-generated and advisory | MET | `RecommendationCard.tsx` — the advisory label sits in the `<summary>` so it stays visible when the card collapses. |
| R319 | §7.3 Recommendation runs last and may reference only retained evidence IDs | MET | R156; `synthesis.py:960-971`. |
| R320 | §7.3 Snippets labelled `snippet_only` or `source_not_verified`; never imply the page was read | MET | R119. |
| R321 | §7.3 Every result displays "Review and approval by a qualified engineer is required." | MET | One constant, three places: `synthesis.py:175`, `RecommendationCard.tsx:18`, `GapAnalysisCard.tsx:23`, asserted by `RecommendationCard.test.tsx:40` and `GapAnalysisCard.test.tsx:17`. |
| R322 | §7.3A Compute the full analysis before rendering, in the stated order, with the recommendation calculated after gaps and market comparison | MET | `synthesis.py:63-66` states the ordering as a contract of the function signature: the confidence checklist is "computed LAST, after everything it describes, per 7.3A". |
| R323 | §7.3B.1 Typed candidate claims with subject, property, value, unit, condition, applicability, revision/approval metadata and citations, span preserved | PARTIAL | All but revision/approval metadata (R260). The original span is preserved verbatim. |
| R324 | §7.3B.2 Cluster only claims on the same query facet; never merge on wording similarity | MET | `ClaimClusterOut.facet`; `test_claims.py`. |
| R325 | §7.3B.3 Deterministic normalization; keep raw and normalized; no silent LLM unit conversion | MET | `claims.py` normalizes mechanically; `analysis.gaps` makes **no model call** at all. |
| R326 | §7.3B.4 Label same-facet claims agreement / addition / possible conflict / unresolved | MET | `schemas.py:580` — exactly those four. |
| R327 | §7.3B.5 A gap comparison requires a user-selected or unambiguous baseline; record its citation; classify met / possible_gap / conflict / insufficient_evidence / not_applicable | MET | R313/R312. |
| R328 | §7.3B.6 Keep revision authority explicit; never assume a later filename or larger revision string supersedes | MET | Nothing infers authority from a filename; the absence of revision data is stated rather than guessed around. |
| R329 | §7.3B.7 Compare public-market facts in a separate matrix after internal gaps are formed | PARTIAL | Separation yes; no comparison matrix is built. |
| R330 | §7.3B.8 Validate every rendered row against its cited evidence; warn and show page evidence instead of a confident comparison where structured extraction is unreliable | MET | `ClaimTable.tsx` + `GapAnalysisCard.contradiction.test.tsx` — commit `9f3f6db`, "gap rows that do not contradict themselves, ordered and counted". |
| R331 | §7.4 Wrap retrieved document and web content as untrusted source data; state in the system prompt that source content cannot modify instructions; strip or flag instruction-shaped patterns for review | **NOT MET** | No untrusted-content wrapper, no instruction-pattern detection, no system-prompt clause on the subject anywhere in `answer.py` or `analysis.py`. |

### §8 — PDF report (R332–R359)

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R332 | §8.1 Ten-minute renderer spike on 16 GB, repeated on the 48 GB host, then freeze one renderer | PARTIAL | The spike was run and recorded (CHANGELOG 2026-09-05, `reports.py:25-42`) and one renderer is frozen — PyMuPDF, reusing an installed library exactly as step 1 prescribes. The 48 GB repeat did not happen. |
| R333 | §8.1 No cloud report API, remote font, remote stylesheet or browser URL dependency | MET | `test_reports.py` asserts no external asset fetch; fonts are embedded locally. |
| R334 | §8.1 The renderer consumes only a validated `ReportSnapshot` and a versioned local template; it must not ask the LLM to emit HTML/CSS | MET | `TEMPLATE_VERSION = "1"`; no model call in `reports.py`; `render()` performs no database query. |
| R335 | §8.1 A golden long report with Arabic/English, a long evidence table, page breaks, OCR warnings and 20 document rows, rendered and visually inspected on both machines | NOT MET | The Arabic test exists (`test_reports.py:540`) and checks glyph coverage and font identity — **but it `pytest.skip`s itself when the ingested fixture lost its Arabic before the report, and it skipped on this run.** It is honestly labelled ("nothing measured here"), and it is still a test that can pass by not running. There is no 20-row golden report and no second machine. |
| R336–R353 | §8.2 The eighteen required report contents | **5 MET / 7 PARTIAL / 6 NOT MET** | **MET:** title + `PROTOTYPE - NOT FOR CONSTRUCTION` watermark; report ID, timestamp and generating user; the exact question; documented findings; OCR provenance warnings. **PARTIAL:** documents searched with filename and content-hash prefix (revision and approval status do not exist, R260); executive summary (the answer, not a multi-section summary); table of contents and section numbering (hand-built from element positions; the PDF outline is empty and the report is short enough not to need one — recorded, not hidden); claim-level document/page citations (**clause deliberately removed**, R035); assumptions/limitations/engineer-approval block (approval block yes, assumptions no); model/embedding/reranker/configuration identifiers (`config_version` yes, model identities partial). **NOT MET:** user role, project and analysis mode; the coverage ledger; per-document evidence status with include/exclude/fail reasons; conflicts and gaps; advisory recommendation and confidence; public-market findings; the evidence appendix with `also_supported_by`. **`reports.py:66-67` names four of these as `NOT_INCLUDED` in a bordered box on page 1 of every PDF** — an absent section is visible as absent, and nothing is rendered empty or with zeros. |
| R354 | §8.3 Persist a snapshot with citation IDs, document hashes/revisions, structured analysis JSON, prompt/config version and report SHA-256; regenerating must not silently use newer documents | MET | `reports` table carries `snapshot_json`, `sha256`; `verify()` returns `evidence_drift`. `report_sha256` is documented as **not** a reproducibility hash (PyMuPDF embeds a producer string), and `snapshot_sha256` is the one to compare — a distinction most builds get wrong silently. |
| R355 | §8.4 The report endpoint rejects unauthorized analysis IDs | MET | `test_reports.py:477,491`. |
| R356 | §8.4 A report cannot include a document removed from the user's scope | MET | `test_reports.py:448`; `test_reports_suppressed_count.py` — the listing carries `suppressed_count` so a user sees **that** something is hidden without seeing what. |
| R357 | §8.4 HTML escapes document text and user input | MET | `html.escape` in `reports.py`; asserted. |
| R358 | §8.4 No remote image, font, stylesheet or URL fetch during rendering | MET | R333. |
| R359 | §8.4 Generated files use server-assigned IDs and sanitized paths beneath a fixed root | MET | `secrets`-derived names resolved beneath the report root. |

### §9 — Frontend (R360–R391)

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R360–R362 | Login: username/password form; current user/role badge; logout clears the in-memory token | **MET (3/3)** | `LoginView.tsx`, `RoleBadge`, `App.tsx:57` module-level token. `LoginView.test.tsx`. |
| R363 | Documents: discipline, project, revision and approval badges | PARTIAL | Discipline only — the other three columns do not exist (R260). `DocumentCard.discipline.test.tsx`. |
| R364 | Documents: admin-only access-grant control | MET | `AdminScreen.tsx`, reached at `App.tsx:246` behind `canAdmin &&` — "the gate, not the absence of a nav entry". |
| R365 | Documents: manual discipline selection during upload | NOT MET | `Uploader.tsx` carries no discipline field; grants are made afterwards in the admin screen. |
| R366 | Documents: "AI suggested category" is P2 and never grants access automatically | MET | No suggestion UI exists and no classifier writes a grant (R253). |
| R367 | Chat: mode selector Quote / Focused Answer / Comprehensive Analysis | MET | `ModeSelector.tsx:23-38` — exactly those three, with descriptions and an explicit note that Quote mode runs only cited document evidence. |
| R368 | Chat: optional toggles Gap Analysis, Public Market Intelligence, Generate Recommendation | MET | `ModeSelector.tsx:41-50` — all three, with the market toggle labelled "Public market sample (sample data)" in the control itself. |
| R369 | Chat: selected document scope | NOT MET | No document-selection control; analysis runs over the whole authorized scope (R189). |
| R370 | Chat: live comprehensive progress and a visible coverage ledger | PARTIAL | `CoverageLedger.tsx` is real and rendered. Progress is polled phase text, not the coverage-stage stream (R212). |
| R371 | Chat: structured sections — Summary, Recommendation, Gap Analysis, Public Market Intelligence, Market Comparison, Sources | PARTIAL | Five of six as separate cards. **Market Comparison does not exist** (R329). |
| R372 | Chat: recommendation warning | MET | R321. |
| R373 | Chat: `Suggest correction` action | NOT MET | §6 absent. |
| R374 | Chat: `Generate report` action | MET | `ReportsScreen.tsx`, `ReportsScreen.download.test.tsx`. |
| R375 | Chat: public-search preview/confirmation dialog showing the exact outbound query | MET | `MarketPanel.tsx` preview; the payload itself carries `sent: false` and the reason. |
| R376 | Dashboard: authorized documents/pages/chunks for ordinary users | MET | `DashboardView.tsx`; `test_metrics.py`. |
| R377 | Dashboard: admin-only total corpus/user/access metrics | MET | `main.py:171-175` — `corpus_wide` computed from the scope and carried in the payload so the screen states which kind of number it shows. |
| R378 | Dashboard: reports generated | MET | `DashboardView.tsx`. |
| R379 | Dashboard: query latency split into retrieval, rerank, generation and report | PARTIAL | Retrieval and generation latency are measured from questions actually asked (`DashboardView.tsx:588`). Rerank and report are not split out. |
| R380 | Dashboard: web-search enabled/disabled indicator | MET | Driven by `egress_state()` from the API rather than hard-coded in the component. |
| R381 | Dashboard: preserve "not measured yet"; never replace a missing value with zero | MET | R022. This is the single most consistently enforced invariant in the build. |
| R382 | Reuse existing design tokens and components; no second design system | MET | `theme.test.ts`, `Shell.branding.test.tsx`. |
| R383 | A persistent application shell with role badge, privacy/egress state and current resource profile; navigation covering Dashboard, Documents, Chat, Reports and admin-only areas | PARTIAL | `Shell.tsx` with all navigation and the role badge; commit `dc02911`. **No resource-profile indicator** (R008). |
| R384 | Desktop: readable answer column plus a collapsible evidence drawer; full-width evidence tab on small screens; never squeeze page images into an unreadable sidebar | MET | `Drawer.tsx`, `EvidencePanel.tsx`, `Shell.test.tsx`. |
| R385 | A persistent stage/progress card and a virtualized or paginated 20-document coverage table, with status shown by text/icon as well as colour | NOT MET | No virtualized or paginated coverage table; the ledger renders all rows. No 20-document case exists to need it. |
| R386 | Concise answer first, separate cards for Recommendation, Gaps, Market, Evidence Ledger and Sources, with advisory/OCR/incomplete warnings visible when cards collapse | MET | `AnalysisModeScreen.tsx`; the advisory label sits in the `<summary>` element specifically so collapsing cannot hide it. |
| R387 | Citation selection opens the exact rendered page/highlight and preserves scroll position on return | PARTIAL | Opening the page and highlight is real (`highlight.py`, `PageImageViewer.tsx`, `AnalysisModeScreen.citation.test.tsx`). Scroll-position preservation is not asserted anywhere. |
| R388 | Destructive actions require confirmation; long jobs support cancel; transient errors offer retry without clearing the persisted result | PARTIAL | Confirmation is enforced server-side (`confirm_required` error code) and retry exists (`onRetryConnection`, `errorSurfaces.test.tsx`). **Cancel does not exist** (R159). |
| R389 | Keyboard navigation, visible focus, semantic landmarks, labelled controls, contrast, reduced motion; automated accessibility checks on the login/upload/analyze/report flow; one keyboard-only rehearsal | PARTIAL | Semantic markup and labelled controls are present throughout and `tsc`/tests cover structure. **No automated accessibility check exists** (no axe or equivalent in `package.json`), and a keyboard-only rehearsal cannot be evidenced from the tree. |
| R390 | Skeleton/progress states rather than a frozen page; do not fake percentages — report completed documents/batches when total duration is unknown | MET | `states.tsx`, `usePoll.ts`; commit `8a74139` — "a phase name is not a percentage". Exactly the requirement, named in the commit that implemented it. |
| R391 | At 1,200 documents, document lists and admin tables use server pagination/filtering | NOT MET | `GET /api/documents` returns the full list; `DocumentsView` renders all of it. Acceptable at 12 documents, and it is what the plan asked not to ship. |

### §10 — API additions (R392–R400)

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R392 | Auth endpoints `POST /api/auth/login`, `GET /api/me` | PARTIAL | Login matches; `/api/me` is `/api/auth/me` (R275). |
| R393 | Admin endpoints: users list/create, and per-document access GET/PUT/DELETE for roles **and** users | PARTIAL | `GET|POST /api/admin/users`, `DELETE /api/admin/users/{id}`, `GET /api/admin/disciplines`, `GET|PUT|DELETE /api/admin/grants` exist and work. The shape differs (a flat grants collection rather than `/documents/{id}/access/...`), and the **user-grant half does not exist** (R257). |
| R394 | Analysis endpoints: `POST …/analyses → 202`, `GET /api/analyses/{id}`, `GET …/events` (SSE), `POST …/cancel`, `POST …/market-query/preview`, `POST …/market-query/execute` | **NOT MET** | None of the six exists. Three synchronous routes stand in their place (`/api/analysis/summary`, `/recommendations`, `/gaps`) plus `POST /api/market/preview-query`. No `202`, no SSE, no cancel, no execute. |
| R395 | Feedback endpoints: `POST /api/feedback`, `GET /api/admin/feedback`, `POST /api/admin/feedback/{id}/review` | **NOT MET** | None exists (§6). |
| R396 | Report endpoints: `POST …/reports`, `GET /api/reports`, `GET /api/reports/{id}`, `GET /api/reports/{id}/pdf` | PARTIAL | `POST /api/reports`, `GET /api/reports`, `GET /api/reports/{id}/verify`, `GET /api/reports/{id}/download` exist. `GET /api/reports/{id}` does not; `download` stands in for `/pdf`. |
| R397 | Do not expose raw prompts or hidden reasoning through APIs | MET | R161. |
| R398 | Every state-changing route validates bounded body sizes, uses server-derived actor identity, writes an audit event and returns a stable typed response | PARTIAL | Bounded bodies and typed responses are universal (`test_no_internal_leaks.py:285,330`); actor identity is always server-derived. **Audit events are written only by `admin.py:158` and `auth.py:255`** — an upload, a conversation delete or a report generation writes none. |
| R399 | Reject (not silently trim) any submitted document ID outside the current scope, returning the same non-revealing authorization error and starting no job | NOT MET | Analysis requests carry no document IDs, so the documented reject policy has nothing to apply to. (`baseline_document_id` **is** rejected this way — `main.py:638-640` — which is the right shape applied to the one field that has it.) |
| R400 | `GET`/SSE/cancel routes re-authorize the analysis on every request; possession of an `analysis_id` is not authority | NOT MET | Those routes do not exist. The principle *is* honoured where it has a subject: report routes re-check owner **and** every cited document on every request. |

### §10A — Reproducible clone and two-machine handoff (R401–R430)

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R401 | `.env.example` (names and defaults only) | NOT MET | Absent. |
| R402 | `config/profiles/development_16gb.*` | NOT MET | Absent. |
| R403 | `config/profiles/demo_48gb.*` | NOT MET | Absent. |
| R404 | `models/manifest.json` (name, revision, license, size, SHA-256) | NOT MET | Absent. |
| R405 | `scripts/bootstrap-windows.ps1` | NOT MET | Absent. |
| R406 | `scripts/doctor-windows.ps1` | NOT MET | Absent. |
| R407 | `scripts/run-local.ps1` | NOT MET | Absent. |
| R408 | `scripts/verify-runtime-bundle.py` | NOT MET | Absent. |
| R409 | `docs/runbook.md` | MET | 119 lines. |
| R410 | `docs/benchmarks.md` | MET | 750 lines, measured-only. |
| R411 | `docs/limitations.md` | MET | 418 lines. |
| R412 | One authoritative fully pinned Python lock; a clean install uses it in frozen mode | PARTIAL | `backend/requirements.txt` pins every direct dependency to an exact version and `backend/run.py` refuses to start on anything but Python 3.12 — better than most. It is **not a lock** (transitive dependencies float) and no install runs frozen. |
| R413 | The frontend uses the committed lock and `npm ci`, never unconstrained `npm install` | MET | `.github/workflows/tests.yml` — `npm ci` with `cache-dependency-path: frontend/package-lock.json`. |
| R414–R420 | Runtime/data bundle rules: contents limited to weights, tokenizer/config, approved PDFs, WAL-safe SQLite export, vector artefacts and an inventory manifest; encrypted physically controlled transfer; SHA-256 computed at source and verified at destination; never copy a live SQLite main file alone; generate a new signing secret and demo passwords at the destination; ports on loopback; verify free disk | **NOT TESTABLE HERE (7/7)** | There is no bundle and no second machine. Each of these is a property of a transfer that has not happened. |
| R421–R428 | Clean-host acceptance sequence, eight steps on the 48 GB Windows computer from a user-owned directory | **NOT TESTABLE HERE (8/8)** | The 48 GB machine does not exist in evidence: `docs/benchmarks.md:20` states "There is no faster environment later. Every number here is a production number" about the 15.6 GB laptop. |
| R429 | Generate an SBOM and third-party license inventory; pin GitHub Actions to immutable commit SHAs; run secret scanning, dependency review and CodeQL where available; CI uses only synthetic/public fixtures | PARTIAL | Secret scanning is real and **stronger than the plan asked** — gitleaks pinned by version *and* SHA-256 checksum, plus a pre-commit hook that blocks before history, plus a `no-client-data` job the plan did not require. CI uses synthetic fixtures only. **But: no SBOM, no license inventory, no dependency review, no CodeQL, and `tests.yml` pins `actions/checkout@v4` and `actions/setup-python@v5` by tag, not by commit SHA.** |
| R430 | The PyMuPDF licence gate is resolved, or recorded as an explicit release blocker | MET | `docs/limitations.md:312-315` — "**Not cleared for client distribution.** PyMuPDF now generates a deliverable rather than only parsing an input. That is a different licence question (AGPL-3.0 / commercial dual) … and it is open." Recorded as open, in the client-facing register, exactly as the plan permits. |

### §11 — GitHub execution strategy (R431–R447)

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R431 | §11.1 A recoverable baseline tag `v1.0.0-prototype` | MET | `git tag -l` → `v1.0.0-prototype`. |
| R432 | §11.2 The branch model: issue branches → `demo/sunday-enterprise-poc`, annotated `v1.1.0-sunday-poc-rc1` on the candidate, fixes by new `rcN` tag, merge to `main`, tag `v1.1.0-sunday-poc` | NOT MET | The repository uses the **earlier** issue-numbered scheme (`feat/40-hybrid-search`, `fix/22-frontmatter-classification`, …). There is no `demo/sunday-enterprise-poc` branch, no `rc` tag, and `v1.0.0-prototype` is the only tag. HEAD sits on `feat/phase-1-ui-reaches-backend`. |
| R433 | §11.3 Conventional Commits | MET | Every one of the last 12 commits conforms (`fix(frontend):`, `feat(analysis):`, `docs(security):`, `test(analysis):`). |
| R434 | §11.4 `.github/CODEOWNERS`, PR template, issue forms, security policy | MET | All four present (`CODEOWNERS`, `pull_request_template.md`, `ISSUE_TEMPLATE/bug.md` + `implementation.md`, `SECURITY.md`). |
| R435 | §11.4 Link exactly one issue per PR | NOT TESTABLE HERE | A property of PR bodies, not the tree. |
| R436 | §11.4 Explain scope and excluded scope | NOT TESTABLE HERE | Same. |
| R437 | §11.4 List changed invariants and why they remain satisfied | NOT TESTABLE HERE | Same. |
| R438 | §11.4 Include tests and planted-negative-test evidence | PARTIAL | The template asks for it and commits carry "proven by deliberate failure"; per-PR verification is not possible here (R005). |
| R439 | §11.4 Include privacy/data-flow impact | NOT TESTABLE HERE | Same as R435. |
| R440 | §11.4 Include rollback instructions | NOT TESTABLE HERE | Same. |
| R441 | §11.4 Require backend tests, frontend tests, typecheck, source-hygiene test and secret scan | MET | `tests.yml` runs pytest, vitest, `tsc -b` and the production build; `secret-scan.yml` runs gitleaks and the no-client-data guard; `test_source_hygiene.py` is in the suite **and guards its own scope** — one test plants a 0x08 byte and requires it to be caught, another asserts the scan covers more than forty files so an empty sweep cannot pass as clean. |
| R442 | §11.4 Require at least one review when a reviewer exists | **SUPERSEDED** | `docs/adr/ADR-0004` (Accepted, 2026-09-04): one engineer; self-review is explicitly **not** represented as independent approval, and CODEOWNERS is annotated advisory-only. This is the disclosure the plan's own sentence permits. |
| R443 | §11.4 No merge with skipped model-dependent acceptance tests | MET | `tests.yml` runs `scripts/fetch_models.py --verify-only` **before** pytest, so a run with unstaged weights fails rather than skipping to green. |
| R444 | §11.4 CI installs from frozen locks, verifies expected tests actually ran, type/lint/source-hygiene checks, secret and dependency scans, CodeQL where supported | PARTIAL | Verification-that-tests-ran, typecheck, hygiene and secret scanning are all real. Frozen locks (R412), dependency review and CodeQL are not. |
| R445 | §11.4 Branch protection on `main`: PRs required, passing checks, resolved conversations, no force pushes, no deletion | **SUPERSEDED** | `ADR-0004`: `GET /repos/.../rulesets → HTTP 403 "Upgrade to GitHub Pro or make this repository public"`. Making it public would violate §0.6 and §18 outright. Four compensating controls are named, three of them stronger than the originals, and the ADR requires all four gaps to appear in the client limitations register and **never to be described as enforced**. |
| R446 | §11.4 Generate an SBOM/license report in a local release job | NOT MET | No release job and no SBOM (R429). |
| R447 | §11.5 `.gitignore` covers the required paths | MET | Reproduces the plan's block verbatim plus platform additions, with one deliberate allowlist (`!tests/fixtures/synthetic/*.pdf`) and a comment explaining it. |

### §13 — The cut line's non-negotiables (R448)

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R448 | Never cut authorization tests, citation validation, confidentiality controls or the rollback tag | MET | All four intact: `test_access_routes.py` + `test_auth_required_mode.py` + `test_access_schema.py` (83 tests), claim-to-citation validation (R152), the privacy boundary (§3.1 MET), and `v1.0.0-prototype` (R431). Where cuts were taken, they were taken elsewhere and recorded in `ADR-0003`. |
### §14 — Acceptance test matrix A01–A37 (R449–R485)

This block asks a different question from the rest of the audit: not "does the feature
exist" but "does an acceptance test exist, and did it pass".

| ID | Test | Verdict | Evidence |
|---|---|---|---|
| R449 | A01 Six/seven large documents load after restart with correct counts | NOT MET | The corpus is 12 documents, one over 1,000 pages (R031). |
| R450 | A02 Live upload becomes partially searchable, observed time recorded | MET | `test_upload.py`; `docs/benchmarks.md` records the measurement. |
| R451 | A03 Civil isolation through **any** route | MET | `test_access_routes.py` + `test_auth_required_mode.py`; the route-enumerating leak scan in `test_no_internal_leaks.py:101` covers "any route" for GET. |
| R452 | A04 IT isolation, inverse | MET | Same fixtures, both directions (`test_access_schema.py::test_a_grant_is_visible_only_to_the_role_that_holds_it`). |
| R453 | A05 20-document fixture reports 20 searched / 15 relevant / 5 no-evidence, all 15 contribute, none of the other five presented as support | NOT MET | No fixture (R030), no such rendering (R221). |
| R454 | A06 Unsupported question refused, showing what evidence was checked | MET | `test_acronyms.py`, `test_advice_refusal.py`, `test_synthesis_honest_gate.py`. Regressing the refusal into an answer makes several red. |
| R455 | A07 Conflicting clauses reported with both citations | PARTIAL | Both citations are carried and the row is rendered, but labelled `possible_conflict` (R315). |
| R456 | A08 Recognized answer labelled and source image opens | MET | R010 + `PageImageViewer`. |
| R457 | A09 True follow-up resolves; short new-topic question does not inherit | MET | R011; `test_chat.py:63,120-137`. |
| R458 | A10 Gap status follows §7; missing evidence never falsely called compliant | MET | R312–R314; `test_claims.py`; `GapAnalysisCard.contradiction.test.tsx`. |
| R459 | A11 Recommendation carries a separate advisory label, confidence, citations and the engineer-review warning | PARTIAL | All four are present. The 27 strict-xfail tests in `test_recommendation_gate.py` record that the recommendation still speaks when the summary refuses and still restates the summary — so the label is right and the content is not yet gated. |
| R460 | A12 Pending correction ignored; approved guidance used and labelled | NOT MET | §6 absent. |
| R461 | A13 Private canary strings absent from the outbound payload; the exact sanitized query approved | NOT TESTABLE HERE | No payload is ever sent. The test cannot be run, passed or failed — and a green result here would be the vacuous shape this project has fourteen entries about. |
| R462 | A14 Local RAG works with network and market search disabled | MET | This is the permanent state of the build; the whole suite runs with no network. |
| R463 | A15 PDF opens correctly, contains the evidence snapshot and warning, no unauthorized source | MET | `test_reports.py` (46 tests) including `test_a_report_vanishes_when_a_cited_document_leaves_the_readers_scope`. |
| R464 | A16 Documents, grants, conversations, feedback and reports survive restart | PARTIAL | Four of five survive and are tested. Feedback does not exist. |
| R465 | A17 No traceback, path, SQL, prompt or internal detail reaches the client | MET | `test_no_internal_leaks.py` — 12 tests, one of which scans **every** GET route with hostile input, another proving no client error ever reports `internal`. |
| R466 | A18 Backend, frontend and typecheck pass; actual executed and skipped counts recorded | MET | Measured this run: backend 1,040 passed / 3 skipped / 27 xfailed, frontend 467 passed, `tsc -b` clean over 79 files. Counts are recorded here; **`README.md` still states 279 and 887** (R006). |
| R467 | A19 Retrieval/generation/report p50 and p95 measured on prepared questions; no invented targets | PARTIAL | `docs/benchmarks.md` carries real measured retrieval and generation figures with corpus and machine state read at run time (honesty-audit entry 9's fix). Report-render latency is not measured; p95 is not reported for every stage. |
| R468 | A20 Two consecutive complete rehearsals without manual database editing | NOT TESTABLE HERE | A live operator exercise. |
| R469 | A21 Phase 1 regression: upload, states, Tier 1, exclusions, OCR storage, highlighting and metrics retain characterized behaviour | MET | `test_stage_atomicity.py`, `test_answer.py`, `test_ocr.py`, `test_highlight.py`, `test_metrics.py`, `test_no_internal_leaks.py`. |
| R470 | A22 A verified backup restores; a second migration run changes nothing and errors nothing | PARTIAL | The second half is proven (`test_the_migration_is_idempotent`). **The backup/restore half has no procedure and no test** (R268). |
| R471 | A23 Parallel Civil and IT queries return only their own permitted evidence | MET | `test_two_concurrent_requests_never_share_scope` runs them genuinely in parallel; a shared module-level scope makes it red. |
| R472 | A24 Instructions embedded in local or public sources cannot change tools, access scope or output policy | NOT MET | No prompt-injection handling exists (R110, R331). Access scope is structurally safe because it never derives from content — but nothing tests the output-policy half, and a PDF containing instruction text is fed to the model unwrapped. |
| R473 | A25 Report content still matches its stored snapshot after current document metadata changes | MET | `verify()` → `evidence_drift`; `test_reports.py`. |
| R474 | A26 Civil, Mechanical, Chemical/Process and IT grants work without a hard-coded role enum; a multi-role user gets the union of allows minus explicit denies | PARTIAL | The union half is real and tested; roles are rows, not an enum. **"minus explicit denies" cannot be tested — denies do not exist** (R257). |
| R475 | A27 A multi-discipline document stays governed by explicit grants and never becomes readable through an AI category suggestion | PARTIAL | The suggestion half is vacuously safe (no suggestions exist). `book2` is granted to all four disciplines and behaves correctly, so the multi-discipline half holds in practice. |
| R476 | A28 The UI streams retrieval, rerank, evidence-map, synthesis and validation progress, ending with the same persisted coverage totals shown in the PDF | NOT MET | No streaming (R212), no coverage totals in the PDF (R336–R353). |
| R477 | A29 Public evidence derives only from the approved sanitized query, is visually separate, and cannot silently override internal requirements | PARTIAL | Visual separation and non-override are real and enforced. "Derives from the approved query" is untestable while nothing is fetched. |
| R478 | A30 Second coverage fixture: 10 gold-relevant of 20, all contribute, other 10 not presented as support, every document terminal | NOT MET | No fixture. |
| R479 | A31 Every validated atomic evidence ID remains in the persisted ledger and PDF appendix; compressed prose retains `also_supported_by` | PARTIAL | The ledger retains everything and removals carry reasons (R181). **No PDF evidence appendix and no `also_supported_by`.** |
| R480 | A32 Analysis returns `202`; progress survives refresh and restart; cancellation reaches a terminal state; a partial checkpoint is never presented as complete | NOT MET | No async lifecycle (R159). The third clause is satisfied only because there are no checkpoints to misrepresent. |
| R481 | A33 16 GB profile: focused Q&A plus one queued comprehensive fixture without paging or OOM; OCR, embedding and generation leases do not overlap | PARTIAL | Focused Q&A on 16 GB is measured throughout `docs/benchmarks.md`, and the queue serialises heavy work. **The leases are prose, not a semaphore** (R218), and there is no comprehensive fixture to queue. |
| R482 | A34 48 GB clean clone from the exact tag: frozen installs, verified hashes, no unexpected skips, restart, two rehearsals | NOT TESTABLE HERE | No second machine (R421–R428). |
| R483 | A35 UI and report record exact generator, embedding and reranker identifiers, revisions/quantization, hashes, context settings and profile; no directory-name placeholder | PARTIAL | `DashboardView.tsx:701-713` names all three models and they are real identifiers, not directory placeholders. Revision, quantization, hash, context settings and profile are absent (R095, R008). |
| R484 | A36 Upload-to-`partially_searchable`, semantic-ready, OCR progress and answer latency measured separately; the UI never calls partial search "fully processed" | MET | `documentStatus.ts` + `docs/status-honesty-audit.md`'s status table; `test_no_internal_leaks.py:235,252`. This is the invariant the build defends hardest. |
| R485 | A37 Secret/dependency/code scans run where available; SBOM/license inventory exists; PyMuPDF licensing resolved or an explicit blocker | PARTIAL | Secret scanning exceeds the requirement (R429); the PyMuPDF gate is recorded as an open blocker (R430). **No SBOM, no license inventory, no dependency review, no CodeQL.** |

### §15.3 — Honest performance wording (R486)

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R486 | State that the corpus is pre-indexed; attribute the 13-second figure to the earlier benchmark and machine; do not extrapolate to the 1,200-document target | MET | `docs/benchmarks.md` opens with "nothing enters this file that was not measured on the target hardware"; `docs/corpus-provenance.md` separates claims that carry over to a client's documents from those that do not; §15.3's exact caution about extrapolation is honoured throughout `docs/limitations.md`. |

### §16 — Rollback and failure behaviour (R487–R499)

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R487 | Feature flag `DEMO_AUTH_ENABLED` | PARTIAL | `auth_mode: disabled\|demo_required` serves the same purpose and is genuinely switchable (`test_auth_required_mode.py`, 52 tests). Different name, same effect. |
| R488 | Feature flag `MULTIDOC_SYNTHESIS_ENABLED` | NOT MET | No such setting. Synthesis cannot be disabled without removing routes. |
| R489 | Feature flag `GOVERNED_MEMORY_ENABLED` | NOT MET | Nothing to flag (§6). |
| R490 | Feature flag `WEB_SEARCH_ENABLED` | PARTIAL | Reported in `egress_state()`, hard-coded `False`, not configurable (R100). |
| R491 | Feature flag `PDF_REPORT_ENABLED` | NOT MET | No such setting. |
| R492 | A feature-flag failure falls back to existing Tier 1 local evidence, not a fabricated answer | PARTIAL | The fallback behaviour is right — `_analysis_or_503` returns a clean 503 when the model is unreachable and Tier 1 continues to work without any model. There are no flags to fail. |
| R493 | Back up SQLite with a WAL-safe method before migration | NOT MET | No backup step anywhere (R268). |
| R494 | Test downgrade/restore using a copied database | NOT MET | No restore drill (R470). |
| R495 | Keep original models and configurations unchanged | MET | `scripts/fetch_models.py` stages by hash and verifies; no model is modified. |
| R496 | If generated synthesis fails, show Tier 1 verbatim evidence | MET | Tier 1 needs no model and is the default path; `test_answer.py`. |
| R497 | If web search fails, continue locally and state that public evidence is unavailable | MET | Permanently the case, and stated: `market.NOTICE` plus the `egress` block in every findings response. |
| R498 | If PDF generation fails, preserve the analysis and offer local HTML; never a cloud converter | PARTIAL | No cloud converter exists (the important half). There is no HTML fallback path — a render failure surfaces as an error. |
| R499 | If the new branch is unstable, return to `v1.0.0-prototype` and demonstrate the original system | MET | The tag exists and is reachable (R431). |

### §18 — Definition of done (R500–R513)

| ID | Requirement | Verdict | Evidence |
|---|---|---|---|
| R500 | Original Nabaa invariants remain enforced | NOT TESTABLE HERE | R001 — the invariant list is in a document not present. |
| R501 | The critical OCR and follow-up defects are fixed | MET | R010, R011 — both with tests that go red if the defect returns. |
| R502 | Access denied by default and tested at every resource boundary | MET | R256, R278, R280–R292 (11 of 13). |
| R503 | Private document context never enters public web queries | MET | R098, R099 — there is no path by which it could. |
| R504 | Multi-document findings supported by real citations | MET | R152, R195 — a reduce is rebuilt from evidence IDs, never from a lower level's markers. |
| R505 | Comprehensive mode records a terminal status for every authorized selected document and never silently skips or hides a failed one | NOT MET | No per-document retrieval pass and no selected set (R189–R192). `coverage.py` reports honestly on what happened, which is not the same as running the pass. |
| R506 | The prepared 20-to-15 gold fixture passes claim-coverage, citation and exclusion tests | NOT MET | No fixture (R030). |
| R507 | Weak evidence produces refusal rather than confident invention | MET | R165, R170; the −3.0 floor is absolute and `docs/limitations.md` records, with measurements, why it is not lowered — lowering it trades three correct refusals for three confident wrong answers. |
| R508 | Recommendations, public evidence and organizational guidance are separately labelled | PARTIAL | Two of three are separately labelled and tested. Organizational guidance does not exist. |
| R509 | "Self-learning" requires human approval and is reversible | NOT MET | §6 absent. The compensating fact is that nothing claims self-learning either (R049–R061). |
| R510 | PDF reports are local, reproducible and access-controlled | MET | R333, R354, R355–R359. |
| R511 | All relevant automated tests and two manual rehearsals pass | PARTIAL | The automated half passes and is measured above. The rehearsals are R468. |
| R512 | Measured results and known limitations are documented honestly | MET | 418 lines of `limitations.md`, 750 of `benchmarks.md`, 582 of `status-honesty-audit.md`, 202 of `corpus-provenance.md`, and a `NOT_IMPLEMENTED` list emitted on the API response itself. **This is the requirement this project meets most completely, and by a distance.** |
| R513 | The original stable tag and a database backup can restore the demo | PARTIAL | The tag exists; there is no backup procedure (R493). |
---

## 5. The ten most important NOT MET items, ranked by what a client would notice

Ranked by the order in which a Saudi Aramco reviewer sitting in front of the
demonstration would hit them — not by implementation effort.

| # | Requirement | Plan ref | What the client sees |
|---|---|---|---|
| 1 | **The 20-document gold fixture does not exist** | R030, R453 (A05), R478 (A30), R506 | The plan's headline proof is "20 authorized documents searched / relevant evidence found in 15 / no sufficient evidence in 5", demonstrated live. The corpus is 12 documents of public standards and textbooks, no gold labels, no Query A or Query B. **The one number the whole demonstration is built around cannot be produced.** |
| 2 | **There is no comprehensive coverage pass** | R189–R192, R505 | "Comprehensive Analysis" is a button in `ModeSelector.tsx`. Behind it, retrieval runs the same global 30+30 → RRF → rerank-16 pipeline as Focused, and `coverage.py` *reports on* what that pipeline happened to do. The module says so itself: "Report-only. Nothing here changes retrieval." The plan's §4.5A gives a ten-step document-axis algorithm precisely because a global top-k lets strong documents crowd out others — and `coverage.py`'s own header records that happening: on gold question Q4 a passage scoring **+2.104 against a −3.0 floor** was ranked fifth and lost to `limit=3`. A client asking "did you check all my documents?" gets an honest report that the answer is no, rather than a system that checked them. |
| 3 | **Six or seven 1,000–1,200-page documents are not there** | R031, R449 (A01), R063 | The scale story is one 1,400-page document out of 3,717 total pages, against the plan's ~7,200. Every latency figure the client is shown is therefore measured at roughly half the intended scale, and the 1,200-document production target is four orders of magnitude away. |
| 4 | **The asynchronous analysis lifecycle does not exist** | R159, R157, R394, R480 (A32) | No `202 Accepted`, no `analysis_id`, no progress persistence, no SSE, no cancel, no `analyses` table. On a 15 W CPU where `docs/limitations.md` records a **195-second** LLM answer over a full RAG context, a synchronous request is the difference between a progress bar and a hung browser. Refresh the page mid-analysis and the work is gone; there is nothing to reload. |
| 5 | **Governed organizational learning is entirely absent** | R042, R294–R306, R460 (A12), R509 | "Self-learning" is a named client expectation with its own demo step (§15.2 step 10) and its own no-go handling. There is no `knowledge_feedback` table, no `Suggest correction` button, no admin review list, no badge. The mitigation is real — nothing claims autonomous learning — but the client asked to see something and there is nothing to show. |
| 6 | **No prompt-injection handling anywhere** | R110, R331, R472 (A24) | A PDF's text goes into the model with no untrusted-source wrapper, no system-prompt clause saying source content cannot issue instructions, and no instruction-pattern flagging. A24 is an acceptance test with nothing to run. Access scope is structurally safe (it never derives from content), so the blast radius is output policy rather than confidentiality — but for a client whose documents come from many contractors, "we did not consider it" is the wrong answer. |
| 7 | **The PDF report is a single-answer evidence report, not the §7.2 analysis report** | R336–R353, R479 (A31) | Seven of the eighteen required contents are missing: user role/project/mode, the coverage ledger, per-document evidence status and reasons, conflicts and gaps, the advisory recommendation, public-market findings, and the evidence appendix. This is handled better than any other gap in the build — `reports.py` names four of them in a bordered box on page 1 of every PDF, so absence is visible rather than implied — but the deliverable the client takes away from the meeting is a fraction of what §8.2 specifies. |
| 8 | **No `document_user_access`: a user-level deny cannot override a role allow** | R257, R289, R474 (A26) | Access is role-grant only. The plan's model — role allow, user allow as a narrower exception, user deny overriding both — is half implemented. In an enterprise conversation, "can you exclude one named engineer from one document?" is the first question after "can you scope by discipline?", and the answer today is no. |
| 9 | **Nothing on the demonstration machine will start** | R401–R408, R421–R428, R046, R482 (A34) | `.env.example`, both resource profiles, `models/manifest.json`, `bootstrap-windows.ps1`, `doctor-windows.ps1`, `run-local.ps1` and `verify-runtime-bundle.py` are all absent — eight of the eleven required repository artefacts. `docs/benchmarks.md:20` states the 15.6 GB development laptop **is** the production machine, so the two-machine handoff §10A exists to make safe has not been attempted. The demonstration runs on the laptop it was built on, or it does not run. |
| 10 | **No backup, and therefore no rollback** | R493, R494, R268, R470 (A22) | §5.2B specifies a nine-step protocol; §16 requires a WAL-safe backup before migration and a tested restore from a copy; A22 makes it an acceptance test. Migrations are additive and proven idempotent, which removes most of the need — but the plan's stated rollback is "restore the verified database backup and the tagged code", and only half of that exists. **`v1.0.0-prototype` restores the code and nothing restores the data.** |

**Two that narrowly miss the list and are worth naming:** the missing
`document_type`/`revision`/`approval_status`/`project_code` columns (R260), which are the
single root cause of five other gaps — conflicts can only ever be `possible_conflict`,
revision preference is impossible, and three §8.2 report fields cannot be filled; and the
untracked host-telemetry defect in §10 below, which is live in the audited commit.

---

## 6. Recorded deviations — requirements met by something other than what the plan specified

These are not failures. Each is a place where the build does something different from the
plan and **says so in writing**, which is the behaviour §0.11 asks for. They are listed
because a conformance number that silently absorbs them is exactly the kind of figure this
audit exists to replace.

| # | Plan requirement | What was built instead | Where it is recorded | Verdict given |
|---|---|---|---|---|
| 1 | §11.4 Branch protection on `main` — PRs, required checks, resolved conversations, no force push, no deletion | Four compensating controls: PR-only convention, CI on every PR with manual merge gating, a **pre-commit** gitleaks hook (stronger than GitHub's post-push alerting), and a `no-client-data` CI job the plan never asked for | `docs/adr/ADR-0004` (Accepted, 2026-09-04). `GET /repos/.../rulesets → HTTP 403 "Upgrade to GitHub Pro or make this repository public"`. Making it public would violate §0.6 and §18. The ADR requires all four gaps in the client limitations register and forbids describing them as enforced. | **SUPERSEDED** (R445) |
| 2 | §11.4 At least one review when a reviewer exists | One engineer; self-review explicitly not represented as independent approval; CODEOWNERS annotated advisory-only | `ADR-0004` | **SUPERSEDED** (R442) |
| 3 | §4.5A The four-value per-document status enum (`relevant / no_sufficient_evidence / failed / not_searchable`) | A **seven**-value enum including `credible_not_cited` | `docs/status-honesty-audit.md`, thirteenth entry: none of the plan's four values was true of gold question Q4 — doc17 was retrieved, shortlisted, scored +2.104 above a −3.0 floor, not cited, and not `searched_no_match`. Had the plan's enum shipped, Q4 would have been filed under whichever value was least wrong. | NOT MET (R192) — the deviation is *better*, and it is still not the contract |
| 4 | §0 `rerank_max_tokens == chunk_max_tokens`; §0 change budget forbids tuning rerank settings | `rerank_max_tokens` 256 → 480, `rerank_candidates` 20 → 16; the test asserts the **relationship** (`>=`) rather than the literal | `docs/limitations.md` — +650 ms median (1.45 s → ~2.1 s) bought retrieval 9/10 → 10/10, citation 8/9 → 9/9 on an independent 15-question set. A 486-token passage was being scored on its first 256 tokens with the answer at token 350. | R017 MET, R027 PARTIAL |
| 5 | §1 "clause" as a citation component; §8.2 claim-level clause citations | Clause labels removed from chat, claim table and PDF | Commit `a73c096`; the chunker's `section` was wrong on 5 of 6 cited passages and 0 of 11 on doc16. `test_reports.py::test_the_passage_label_names_no_clause` **plants** a distinctive clause on the passage so the absence assertion can actually fail. | R035, part of R336–R353 — PARTIAL |
| 6 | §5.2 `disciplines` and `document_disciplines` tables | Disciplines modelled as `roles.kind = 'discipline'`, with `admin` as an orthogonal capability | `db.py:246-268` argues it at length: `user_roles` is already many-to-many, so a person holding IT and admin needs no new table; a boolean on `users` would fix `is_admin` alone. | R255 PARTIAL |
| 7 | §5.3 `GET /api/me`; §10 endpoint paths generally | `GET /api/auth/me`; a flat `/api/admin/grants` collection instead of `/api/admin/documents/{id}/access/...` | Not separately recorded — this is the one deviation on this list with **no written justification**. | R275, R392, R393 PARTIAL |
| 8 | §16 named boolean feature flags | `auth_mode: disabled\|demo_required` covers the auth flag; the other four are absent rather than renamed | `access.py:41-45` explains the auth-mode choice ("what makes the rollback a config change rather than a revert"). | R487 PARTIAL, R488–R491 NOT MET |
| 9 | §8.1 "if an existing local PDF library passes a smoke test, reuse it" — with a repeat on the 48 GB host | PyMuPDF chosen by that rule on the 16 GB host; three specific findings recorded (`<thead>` does not repeat across page breaks; Arabic shapes only through `Story`; the outline is empty and the TOC is hand-built) | `reports.py:25-42`, CHANGELOG 2026-09-05 | R332 PARTIAL |
| 10 | §2 The 48 GB demonstration host | There is one machine | `docs/benchmarks.md:20` — "There is no faster environment later. Every number here is a production number." | Root cause of 15 NOT TESTABLE HERE verdicts |

**A deviation that is a genuine improvement, recorded so it is not read as drift:**
`analysis.evidence_id` is `sha256(document_id|page_start|page_end|section|exact_span)[:16]`
rather than the opaque `ev_...` the plan sketches. It is deliberately **not** a chunk id,
because chunk ids change when a document is re-chunked "and a citation that moves when the
chunker is retuned is not a citation". Two identical spans on the same page of the same
document are the same evidence — which is the property a cross-document comparison needs
and the plan's own `also_supported_by` would have required.

---

## 7. What could not be assessed, and why — 34 requirements

**This number matters as much as the percentage.** A 94% over half the plan is not 94%;
this audit's 51.1% is over 93.4% of the plan, and the missing 6.6% is listed here in full
so nobody has to guess what it hides.

| Count | Requirements | Why not assessable | Would flip to a real verdict if… |
|---:|---|---|---|
| 15 | R414–R428 — the runtime/data bundle rules and the eight-step clean-host acceptance sequence | **There is no second machine.** The 48 GB Windows host is asserted by the plan and contradicted by `docs/benchmarks.md`, which names the 15.6 GB laptop as the production machine. No bundle has been assembled and no clean clone has been attempted. | …a 48 GB Windows host existed and the sequence were run from the tagged commit. |
| 7 | R109, R112, R115, R120, R123, R124, R129 — outbound logging, policy rejection, provider field discipline, client-approved device, non-synchronized folders, OS account hardening, firewall default | **Host and deployment configuration, or an egress path that does not exist.** Six of the seven are properties of the operator's machine; the seventh cannot be observed because nothing is ever sent. | …the audit ran on the demonstration host with an approved provider enabled. |
| 5 | R435–R437, R439, R440 — per-PR content requirements (one issue, scope, invariants, privacy impact, rollback instructions) | **Properties of pull-request bodies on GitHub, not of the repository tree.** The PR template asks for all five; whether every PR supplied them is not visible from a clone. | …the GitHub PR history were read. |
| 3 | R461 (A13), R468 (A20), R482 (A34) — market canary test, two live rehearsals, 48 GB clean clone | **Live exercises.** A13 in particular *cannot be run*: no payload is ever sent, so a green result would be the vacuous shape this project has fourteen recorded entries about. | …a provider were enabled (A13) or an operator ran the demo (A20, A34). |
| 2 | R001, R500 — "preserve all twelve Nabaa invariants" | **`RAG-INTELLIGENCE-CODEBASE.md` is not in the repository.** The twelve invariants are defined there and nowhere else, so the list cannot be checked against anything. The eleven-item Phase-1 preservation contract in §0 *is* assessable and is R013–R024, 11 of which are MET. | …`RAG-INTELLIGENCE-CODEBASE.md` were supplied. |
| 1 | R025 — a characterization test before each touched Phase 1 path | **A claim about the order of edits.** The tree shows characterization-shaped tests; it cannot show they preceded the edits. | …the commit history were walked per touched path. |
| 1 | R251 — feature flags must not alter evidentiary meaning | **The invariant has no subject** — there are no feature flags. | …flags were implemented. |

**Not counted as NOT TESTABLE:** twelve requirements that *could* have been marked so and
were instead marked NOT MET, because the reason they cannot be tested is that the feature
does not exist (R102–R105, R110, R154, R394, R395, R399, R400, R460, R480). Calling those
"not testable" would let an absence hide behind an excuse.

---

## 8. Things that contradicted the brief, or the plan, or both

**1. The plan assumes two machines. There is one.** §0.13, §2, §4.5A's profile table, the
whole of §10A, A33 and A34 are written for a 16 GB development laptop plus a 48 GB
demonstration computer. `docs/benchmarks.md:20` says: *"There is no faster environment
later. Every number here is a production number."* Twenty-three requirements across four
sections are addressed to a host that does not appear to exist. This is the single largest
structural gap between plan and reality, and it is not a coding failure.

**2. This codebase is far more honest than the brief's history suggests.** The brief warns
about a "78% section citation" with no measurement, "all six features done" from files
existing, and "72 tests" in a file with 28. Nothing of that shape was found at this commit.
What was found instead: an API that names its own unimplemented sections **on the response
object** (`analysis.NOT_IMPLEMENTED`); a PDF that prints what it does not contain in a box
on page 1; a coverage field that is structurally incapable of returning `true`; a market
module that raises at load time if a fixture row could be mistaken for real; 27 tests
marked `xfail(strict=True)` so the suite goes red the day the feature lands; and a
`no tests were skipped` assertion printed by the suite itself. **The gap between plan and
build here is a gap in delivery, not in candour.**

**3. The brief's specific trap examples were checked, and three of the four are closed.**
The `"files": []` tsconfig still exists — but CI runs `tsc -b` with a comment saying why,
and `--listFiles` confirms 79 files are covered. The "reads only the 200 key" test shape is
gone: `test_no_internal_leaks.py:330` asserts error responses are documented, not
undocumented. The "asserts a refusal without granting one" shape is closed by fixtures that
assert their own preconditions (`test_admin.py:229` — "the fixture did not grant the
document, so a revoke would prove nothing"). **The fourth is still open:** the Arabic
report test at `test_reports.py:563` `pytest.skip`s itself when extraction dropped the
Arabic, and **it skipped on this run**. It is honestly labelled — "nothing measured here" —
but §8.1's Unicode requirement rests on a test that can pass by not running (R335).

**4. The plan's own §12 is 60 duplicated requirements.** ISSUE-001 through ISSUE-015
restate §§4–11 with time estimates. Counting them would have moved the denominator from
513 to roughly 573 and the MET percentage by about four points, in either direction
depending on which copy was scored. Excluded, and said out loud, because a denominator
chosen after seeing the numerator is not a measurement.

**5. Two live inaccuracies in the project's own documents.** `README.md:209,217` claims
279 frontend and 887 backend tests; measured, 467 and 1,079. `docs/limitations.md:317`
says the PDF download "needs `auth_mode=disabled` today" — commit `31f0592` ("download
reports with the bearer token, not a navigation") appears to have fixed exactly that. Both
are stale-claim defects of the family this project has fourteen entries about; both
under-claim rather than over-claim, which is the safer direction and still the same defect.

---

## 9. Why this plan cannot honestly be reduced to one number

Three reasons, each sufficient on its own.

**The requirements are not commensurable.** R049 ("must not claim Saudi Aramco approval")
and R159 ("return `202`, persist checkpoints, stream progress, support safe cancellation")
each count as one. The first is satisfied by not writing a sentence; the second is several
days of work touching the database, the worker, four routes and the entire analysis screen.
The build scores **13 of 13** on §1's *Not promised* block and **0 of 6** on §10's analysis
endpoints. A single percentage averages those, and the average is meaningless: this build
is excellent at not claiming and incomplete at delivering, and one number hides precisely
that distinction.

**The gaps are clustered, not distributed.** 51.1% MET reads like "half of everything is
done". It is not. §0 preservation is at 74%, §2 stack decisions at 71%, §5 access control
at 63% — and §10 API additions at 11%, §6 governed learning at 13%, §10A handoff at 17%.
**The build is strongest exactly where the client cannot see it and weakest exactly where
the demonstration happens.** A per-section table is the minimum honest reporting unit here;
a scalar is not.

**A third of the plan is scaffolding for a day that has passed.** §13's timebox, §15's demo
sequence and §12's issue list describe how to spend one Sunday. They were excluded from the
count as unassessable-after-the-fact, which is defensible — but it means the denominator is
already a judgement, and any percentage over it inherits that judgement.

**What should be reported instead of a percentage:**

> Against the 513 testable requirements in the plan: **262 met, 112 met in part, 103 not
> met, 34 not assessable on this machine, 2 superseded by recorded decision.** The security
> and honesty layers are substantially complete and tested. The comprehensive-coverage
> feature, the asynchronous analysis lifecycle, governed learning, the two-machine handoff
> and the 20-document gold fixture are not built. The demonstration corpus is 12 documents,
> not 20 plus six large ones.

That is five sentences. It is longer than "94%" and it is the first version of the claim
that cannot be wrong in a direction nobody checked.

---

## 10. Appendix D — the four failing tests in the working tree

`backend/tests/test_metrics_host_telemetry.py` is **untracked** at commit `9f3f6db`. It is
not part of the audited commit and does not affect any verdict above. It is recorded here
because it demonstrates a defect in **committed** code, and because it is the fifteenth
instance of this project's recurring pattern found by the person writing the test rather
than by the suite.

Run here, four of its eight tests fail:

```
FAILED test_an_authenticated_non_admin_receives_no_host_telemetry
FAILED test_an_unauthenticated_caller_receives_no_host_telemetry
FAILED test_the_host_block_is_omitted_rather_than_blanked
FAILED test_the_low_memory_warning_still_reaches_a_non_admin
```

`GET /api/metrics` serves a `system` block — `cpu_logical_cores`, `ram_total_bytes`,
`ram_free_bytes`, `process_rss_bytes`, `disk_total_bytes`, `disk_free_bytes`,
`data_dir_bytes` — to any caller, authenticated or not. The fourth failure is the sharper
one: the low-memory warning restates free RAM in prose (`"0.6 GB of R…t is needed."`), so
**gating the block and then printing its contents in a sentence is not a gate** — the same
shape as honesty-audit entry 15, where a leak was relocated rather than closed.

This is a real defect in the audited commit. It is not counted against any requirement
because no requirement in the plan names host telemetry: §5.4 scopes "metrics that reveal
restricted corpus details", and CPU and disk figures are not corpus details. §3.5's logging
rule is the nearest neighbour and concerns logs, not responses. **Recorded rather than
scored**, so that a future reader does not conclude the audit missed it.

---

## 11. How to re-run this audit

1. `git checkout 9f3f6dbc682071d03b29b3008d5f95553b60cf3e`
2. Create a Python **3.12** environment (`backend/run.py` refuses anything else) and
   `pip install -r backend/requirements.txt`.
3. `cd backend && python -m pytest -q` — expect 1,040 passed, 3 skipped, 27 xfailed,
   1 deselected from the committed suite. Confirm each batch prints
   `no tests were skipped - the whole suite ran`.
4. `cd frontend && npm ci && npx tsc -b && npx vitest run` — expect 467 passed, 39 files.
   Confirm coverage with `npx tsc -p tsconfig.app.json --noEmit --listFiles | grep -c src/`
   → 79.
5. Read `RAG-INTELLIGENCE-POC-EXECUTION.md` and apply the extraction rule in §1.1: a sentence
   is a requirement when it states a must-do, must-not-do or must-say **and** a reader can
   settle it from the repository, a command, or the running system. Exclude the sections
   named in §1.1's table.
6. Assess each against the file:line evidence in §4. Any verdict here that cannot be
   reproduced from its cited evidence is wrong and should be corrected in place, with the
   date and the reason — the same rule `docs/status-honesty-audit.md` follows.

**A disagreement about the denominator is expected and is not a defect in the method.**
A reader who counts §12's ISSUE acceptance bullets separately will get ~573; one who groups
§14's A01–A37 under the features they test will get ~476. What must not change under either
choice is the shape: the security and honesty layers substantially met, the
comprehensive-coverage and analysis-lifecycle layers substantially absent, and no
denominator producing 89% or 94%.
