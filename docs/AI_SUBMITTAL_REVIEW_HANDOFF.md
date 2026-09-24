# AI Submittal Review: canonical handoff

Written 2026-09-18 by Claude Desktop (Cowork). This file is the single source
of truth for resuming the AI Contractor Document Submittal Review project in a
fresh session. Everything below was verified against the repository on the date
above, not recalled. Where a fact was not verified it says so.

---

## 1. Project path and current branch

| | |
|---|---|
| Path | `D:\project\Rag_chatbot` |
| Branch | `feat/phase-1-ui-reaches-backend` |
| Remote | `https://github.com/abubakarshahid16/saudi-aramco-rag-chatbot.git` |

## 2. Current Git status

Working tree clean. Nothing uncommitted, nothing untracked.

```
HEAD                                     732ce429eef18e7f208e782c9e0cb65498f2607e
origin/feat/phase-1-ui-reaches-backend   732ce429eef18e7f208e782c9e0cb65498f2607e
ahead of origin/main                     107
behind origin/main                       0
```

## 3. Commits pushed and commits still local

**Nothing is local-only.** The 62-commit backlog was pushed on 2026-09-18 and
verified: local HEAD equals the remote ref, and `git branch -r --contains` lists
both new commits on `origin/feat/phase-1-ui-reaches-backend`.

| Hash | Message |
|---|---|
| `f0c70a2` | `feat(nav): rename navigation for AI submittal review workflow` |
| `732ce42` | `docs: redefine dashboard rule for submittal review as primary workflow` |

The branch is 107 commits ahead of `origin/main` and 0 behind, so no rebase or
merge is pending.

## 4. Files changed by Claude Desktop

Three files, in the two commits above. No backend code was written by Cowork.

| File | Change |
|---|---|
| `frontend/src/components/Shell.tsx` | `NAV` labels and order: AI Submittal Review (was Review flow) moved to position 2, Analysis Hub (was Analysis), Document Q&A (was Chat), CRS & Reports (was Reports). `ViewId` keys untouched. |
| `frontend/src/routing.ts` | `titles` map updated to match. Route keys untouched. |
| `CLAUDE.md` | Rule 10 rewritten. "Dashboard stays minimal, no new tiles" now means a focused operational dashboard: exactly four cards (Contractor Submittals, Active Standards, Reviews in Progress, Needs Attention), one Upload-and-Run button, one compact Recent Reviews table, one conditional warning banner. |

## 5. Existing architecture and important modules

Measured 2026-09-18: 57 backend modules, 26,432 lines, 82 HTTP routes, 34
tables across all `ensure_schema()` owners. Note `docs/architecture.md` is stale
on these numbers (it says 52 / 22,775 / 46 / 23); its narrative is still the
best overview.

Stack: FastAPI + SQLite (WAL) + SQLite FTS5 + brute-force cosine dense search
+ local CPU cross-encoder rerank + local Ollama (`qwen3.5:4b`) + React 19 /
TypeScript / Vite / Tailwind v4. Fully local. CPU only.

| Module | Role |
|---|---|
| `db.py` | Core schema, 23 tables, migration block near `:574` |
| `access.py` | `AccessScope` frozen dataclass at `:55`, `allowed_document_ids: frozenset[str]` |
| `search.py` | Hybrid retrieval. `allowed_document_ids` is keyword-only with NO default |
| `answer.py` | Tier 1 verbatim / Tier 2 generated, `MIN_RERANK_SCORE = -3.0` refusal floor |
| `analysis.py` | Summary, gaps, recommendation. `gaps` deliberately makes no model call |
| `model_transport.py` | The only module that may open a socket to Ollama. Two host gates |
| `market_transport.py` | The only module that may reach a public host |
| `reports.py` | Freezes an answer into a PDF snapshot, refuses partial reports |
| `metrics.py` | `_where()` at `:60` is the reference scoped-SQL helper |
| `classification.py` | `narrow_to_scope` intersects, never unions |

## 6. Existing review infrastructure that must be extended

Do not build a parallel findings system. `backend/app/review.py` already owns:

| Table | Notes |
|---|---|
| `review_templates` | Has `governing_sources`, `categories`, `severity_levels`, `approval_terms`, `required_sections`. This is already the standards-compliance shape. |
| `review_baseline_rules` | Drives `auto_select_baseline()` / `resolve_baseline()` |
| `review_findings` | Defined at `review.py:55`. Migration ALTER block at `review.py:83` |
| `review_finding_events` | Append-only audit of finding changes |

Routes already exist under `/api/reviews/*` (templates, baseline-rules,
baseline-selection, findings, history, traceability, report). Frontend screens
exist: `views/SubmittalReviewView.tsx`, `components/analysis/ReviewWorkflowPanel.tsx`.

## 7. Completed frontend changes

Only the navigation relabel in section 4. **Not verified by Cowork**: the Cowork
VM cannot resolve the TypeScript native binary, so `tsc -b` did not run. The
edit is a string-literal swap with no type surface, and no test file references
the old labels (checked). `npm run build` on Windows is still outstanding.

## 8. Current Phase 1 scope

Foundation only. No Standards Library UI, no extraction engine, no applicability
engine, no comparison engine, no CRS export.

1. Extend `document_classification` (`db.py:505`) with nullable columns:
   `document_role`, `document_number`, `revision`, `effective_date`, `project`,
   `contractor_vendor`, `equipment_type`, `equipment_tags` (JSON as TEXT),
   `service`, `transmittal_number`, `superseded_by` (document id, no FK).
2. Extend `review_findings` via its ALTER block at `review.py:83`:
   `review_run_id`, `compliance_status`, `contractor_page`, `contractor_section`,
   `contractor_evidence_text`, `standard_document_id`, `standard_clause`,
   `standard_page`, `requirement_source_text`, `ai_rationale`.
   Existing `status` and `disposition` keep their guided-review meaning.
3. New tables with module-local `ensure_schema()`: `standard_requirements`,
   `review_runs`, `submittal_facts`, and a normalized
   `review_applicable_standards` relation (not JSON: it needs joins,
   permissions and audit).
4. Every read path on those four tables takes `allowed_document_ids` as a
   keyword-only parameter with no default.

Roles: `CONTRACTOR_SUBMITTAL`, `COMPANY_STANDARD`, `CONTRACT_DOCUMENT`,
`SUPPORTING_DOCUMENT`, `CRS_TEMPLATE`.
Compliance statuses: `COMPLIANT`, `NON_COMPLIANT`, `MISSING_INFORMATION`,
`CONDITIONAL`, `NOT_APPLICABLE`, `NEEDS_ENGINEER_REVIEW`.
Both validated in Pydantic, not by SQL CHECK constraints (see section 12).

## 9. Exact Phase 1 implementation prompt for VS Code Claude Code

Paste verbatim. The backlog push in the original Step 0 is already done, so it
is omitted here.

```
Repository: D:\project\Rag_chatbot
Branch: feat/phase-1-ui-reaches-backend

Read docs/AI_SUBMITTAL_REVIEW_HANDOFF.md, CLAUDE.md and docs/architecture.md
first. Working tree is clean and fully pushed. Preserve all history. Do not
reset, stash, rebase, squash or rewrite.

BASELINE BEFORE EDITING
1. Activate the real Python 3.12 environment (run.py refuses other versions).
2. cd backend && python -m pytest -q
   Record exact passed/failed/skipped. Quote real numbers, never estimates.
3. cd frontend && npm run build
   This verifies the navigation label edits Cowork could not typecheck.

CONVENTIONS ALREADY VERIFIED IN THIS REPO. Do not invent alternatives.
- New workflow tables: id TEXT PRIMARY KEY = str(uuid.uuid4()), as in
  review.py:317 and deliverables.py:122. Only documents.id uses the
  doc_{sha256[:12]} hash; do not copy that.
- Timestamps: TEXT from the module's local _now() (UTC, timespec seconds, Z).
  created_at TEXT NOT NULL always; updated_at only on mutating tables.
- NO CHECK constraints. This backend has exactly one (db.py:483). SQLite
  cannot ALTER-ADD a CHECK, so it would block the next migration. Validate
  roles and compliance statuses in Pydantic; keep columns plain TEXT.
- Migrations: no shared helper. Use the PRAGMA table_info + conditional
  ALTER TABLE ADD COLUMN idiom already in the file you are editing. db.py:574
  uses r["name"]; review.py:83 uses row[1]. Match the file, do not unify.
- Foreign keys: ON DELETE CASCADE for owned rows, ON DELETE SET NULL for
  references that must outlive their target. Follow the reports.py precedent
  and use NO foreign key for a finding's standard_document_id, so deleting a
  standard cannot erase the record that it was cited.
- Indexes: idx_<table>_<purpose>, composite, DESC on the timestamp.
- Permissions: reuse the shape of metrics.py:60 _where(). Filter inside the
  query, never in Python after. Do NOT copy deliverables.py:150, whose
  "document_id IS NULL OR document_id IN (...)" makes NULL rows world
  readable. A review run always has a submittal; NULL must never mean
  visible to everyone.
- A pre-commit hook requires gitleaks (ADR-0004) and blocks when it is
  missing. If blocked run: bash scripts/install-git-hooks.sh
  Do NOT use git commit --no-verify.

SCOPE
Implement sections 8.1 to 8.4 of docs/AI_SUBMITTAL_REVIEW_HANDOFF.md exactly.
Foundation only. No Standards Library UI, no extraction, no applicability
engine, no comparison engine, no CRS export.

TESTS (CLAUDE.md rule 6: mutation-proven, never vacuous)
Each test must fail when its feature is removed. Prove it and state the
mutation you used. Required:
- Existing documents readable after migration
- Existing review findings still work unchanged
- All 5 document roles validate; invalid role rejected
- All 6 compliance statuses validate; invalid status rejected
- Unauthorized user cannot read another user's review run, facts or findings
- Authorized user can read them
- Permission tests FAIL when the access filter is deleted
- Init and migration idempotent when run twice
- FK delete behavior, including that deleting a standard does not erase
  findings that cited it
- Guided-review status/disposition behavior unchanged

VERIFICATION
1. Migrate a COPY of the database first. It is WAL mode: three files
   (.sqlite, -wal, -shm). Copying one loses documents.
2. Full backend suite, reported against the baseline.
3. The new targeted tests.
4. cd frontend && npm run build
5. python run.py, confirm /api/health responds and /openapi.json loads.
6. Confirm the app starts against the EXISTING database with no rows lost.
7. git diff --check

DELIVERABLE
Create docs/AI_SUBMITTAL_REVIEW_PROGRESS.md with baseline vs final test
counts, files changed, schema changes, migration behavior, API changes,
frontend result, known limitations and recommended Phase 2 scope.
Commit with conventional prefixes. Do not push. Stop after Phase 1 and give
an evidence-based report. Do not claim anything works because a file or
route exists. Trace the real execution path.
```

## 10. Required tests and verification commands

```bash
# Baseline and regression (Python 3.12 only)
cd backend && python -m pytest -q

# Frontend
cd frontend && npm run build

# Server
python run.py          # then check /api/health and /openapi.json

# Hygiene
git diff --check
git config --local core.hooksPath      # expect .githooks
```

Static test declaration counts are not pass counts. At an earlier commit the
static backend count was 956 while CI reported 1,174 passed; the difference is
`parametrize`. Always quote a suite run, never a grep.

## 11. Known limitations

**Cowork / Claude Desktop VM (the session that wrote this file):**

| Limitation | Consequence |
|---|---|
| Python 3.10 only, no 3.12 | Cannot run the backend suite or start the backend. Backend work must go to VS Code Claude Code. |
| Cannot reach Windows localhost | Cannot hit `/api/health` or any running service |
| No GitHub credentials (`could not read Username`) | Cannot push. The user pushes from Windows. |
| TypeScript native binary unresolvable | Cannot run `tsc -b`. Frontend edits go to Windows for `npm run build`. |
| Must never run `npm` or `npx` against the repo | Installs Linux binaries into `node_modules` and breaks `npm run dev` on Windows. `node node_modules/typescript/bin/tsc` is the only safe node entry point. |
| Must never open the live SQLite DB | WAL mode over the bridge causes disk I/O errors |

**Repository:**

- `docs/architecture.md` is stale on counts (section 5) and still lists the
  Ollama host as unguarded. That was fixed: `model_transport.py` now enforces
  loopback at startup and again immediately before every request.
- Still open: `reports.py:361` prints "Quoted verbatim from the document" based
  only on `answer_type == "extract"`, with no `text_source` check. The chat UI
  gates this correctly at `AnswerCardView.tsx:125`. OCR text can therefore be
  labelled verbatim in a generated PDF.
- SMTP is not configured, so reminder, escalation and notification email
  delivery remain unverified rather than complete.

## 12. What must not be changed

1. Privacy boundary. No document text, filename or page reference may leave the
   machine. Only `market_transport.py` may reach a public host in normal use;
   only `model_transport.py` may reach the answer model. Two further socket
   modules exist, both off by default: `reader_transport.py` (cloud reader,
   router unregistered) and `notifications.py` (SMTP). See
   `docs/architecture-call-graph.md` §3 and honesty audit entry 49.
2. `status` and `disposition` on `review_findings`. Existing guided-review rows
   depend on their current meaning. Add `compliance_status` alongside them.
3. Deny by default. Absence of a row in `document_role_access` is the only way
   to express no access. No wildcard, no "everyone" row.
4. Classification may only narrow access, never widen it. Intersection only.
5. No SQL CHECK constraints (see section 9 reasoning).
6. Do not use `git commit --no-verify`.
7. Do not delete or reset the repository, and do not push without being asked.
8. Existing capabilities stay: chat, quote, focused/comprehensive analysis, gap
   analysis, recommendations, market intelligence, evidence reports,
   deliverables/WBS, watched-folder ingestion, admin.

## 13. Exact next action

Paste the prompt in section 9 into VS Code Claude Code and run Phase 1. Nothing
else is pending. The backlog is pushed, the working tree is clean, and no
production code is mid-edit.

## 14. How the completed Phase 1 report should be reviewed

This project has a documented history of reports that were technically worded
but false: a file split that was a 3-line re-export wrapper, `@ts-nocheck`
added to 5 files to silence type errors, an empty results file presented as a
clean audit, and a "no layout bug exists" claim contradicted by screenshots.
Review accordingly. Do not accept a claim because a file or route exists.

| Claim in the report | How to verify it |
|---|---|
| "Baseline was N passing" | `git stash` or check out the pre-change commit and run the suite |
| "All tests pass" | Run `python -m pytest -q` yourself and compare to the baseline number |
| "Permission tests are mutation-proven" | Delete the filter line, rerun, confirm the test actually fails |
| "New tables created" | `sqlite3` the test DB and run `.schema`, do not trust the migration code alone |
| "Migration is idempotent" | Run init twice against a copy and diff `.schema` output |
| "No data lost" | Compare `SELECT COUNT(*) FROM documents` before and after |
| "Frontend builds" | Run `npm run build` and read the exit code |
| "Server starts" | `curl` `/api/health` and `/openapi.json` yourself |
| "Files changed: X" | `git show --stat` on each new commit |

If any claim cannot be reproduced, record it in `docs/status-honesty-audit.md`
(24 entries as of this writing) per CLAUDE.md rule 7.
