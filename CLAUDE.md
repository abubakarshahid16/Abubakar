# CLAUDE.md — RAG Intelligence System

> **#805 overrides this file and every other file, except the privacy and
> safety rules 1 to 5 in CLAUDE.md and the security controls in #806.** No
> issue, comment or plan overrides those; changing them needs the owner's
> written approval on #692. #805 (PLAN ONE) is the only plan; where anything
> else here, in `docs/` or in `.cowork/` differs from it, #805 wins.
>
> **Top rule - AI-first (owner, 11 Oct 2026; #805 rule 1):** the review is
> AI-first. AI reads, understands and proposes; code verifies and decides
> pass/fail; the engineer decides. Switching any AI step off by default, or
> replacing an AI step with a rules-only path, needs the owner's written
> approval on #692.

Read this first, every session. It is short on purpose; the long version is
`docs/HANDOVER.md`, and the current defect list is `docs/code-review/README.md`.

## What this is

An offline, privacy-first document-intelligence system for engineering
documents. Engineers ask questions and get answers **quoted from their own PDFs
with document and page**, a cross-document summary, a gap analysis against a
chosen baseline, and an advisory recommendation. Runs entirely on one machine.
**Documents never leave it.** Client use case: **reviewing contractor
submittals** against specifications.

Product name everywhere: **RAG Intelligence System**. The old names (Nabaa, the
client's name) must not appear in code, docs or UI. The GitHub slug still
carries the client's name; only the owner can rename it.

## Standing rules — these are not preferences

1. **Privacy is the product.** No document text, filename, page reference or
   anything derived from a document may leave the machine - with ONE
   owner-approved lanes: the **Claude API**, only through
   `reader_transport.py`, only under the budget of **USD 5 per step /
   USD 20 in total** (enforced in `claude_spend`), and with **no document text
   in logs, GitHub issues, PRs or CI**. Every other outbound path for document
   content stays forbidden. In chat, the user may choose Claude and explicitly
   select the documents for that request; that selection is per-request consent
   for only those files. Local sends no file content to Claude; Claude without
   explicit document selection can answer general questions but gets no document
   content from the library or prior document-bearing chat history.
   Other Claude workflows retain the owner-approved document list. The market search sends only the human-typed
   phrase, previewed and approved per query. Only four modules may open a
   socket, each behind a gate:
   `market_transport.py` (market lane, off by default), `model_transport.py`
   (local Ollama only — `ollama_url` validated by `config.check_model_url`),
   `reader_transport.py` (Claude API: the reasoning provider and the reader;
   off unless `REASONING_PROVIDER=claude` (or `=per_task`, and then only for a
   step whose OWN engine setting says claude: `DATASHEET_AI_READER`,
   `MATCH_ENGINE` - owner decision 2026-10-12, #501) AND both `STANDARDS_READER_*` egress
   flags AND a key - owner decision 2026-09-25, USD caps in `claude_spend`,
   which the three `claude_api` review routes reach via `claude_spend.metered`) and the datasheet AI reader (`datasheet_ai`, with `DATASHEET_AI_READER=claude`) reaches the same way and
   `notifications.py` (SMTP, off by default; in the socket-containment test
   since #196). Known gap: the
   `claude_api` review routes check the two egress flags but not
   `REASONING_PROVIDER` (audit 2026-09-25 finding 1). Call graph:
   `docs/architecture-call-graph.md`.
2. **Never** commit `backend/.env`. Never print, log, paste or commit a secret.
   Never put a token in a URL. Keys live only in `backend/.env`.
3. **The client's register PDF (`Engineering Deliverables.pdf`) is confidential.**
   It may live in the local DB. It never enters git, is never copied into the
   repo, and no test depends on it.
4. **Honesty invariants, enforced in code:** no claim without a resolving
   citation; null renders as nothing (never 0); confidence is never "high";
   every count states its boundary (whose documents); "not mentioned" is never
   "compliant"; a guess is shown as a guess until a human confirms it; samples
   are labelled samples; no percentage without a denominator.
5. **Classification is NOT access control.** `document_classification` says what
   a document is about; the grant tables say who may read it. A filter may only
   NARROW what a caller may already read — intersection, never union.
6. **Tests are non-negotiable and must not be vacuous.** Every change ships with
   a test that fails without it (check it once by hand: revert the fix, see the
   test fail). **Mutation entries are required only in the danger zone**, where a
   wrong answer reaches an engineer, the live data, the network or the budget:
   `comparison.py`, `numparse.py` and the unit code in `claims.py`,
   `datasheet_checks.py` and `reference/datasheet_checks.json` (the #746
   checklist), `crs_mapping.py`, `crs_export.py` and `crs_numbers.py`,
   `live_guard.py`, `heavy_lock.py` and the live guards in
   `scripts/rehearse_requirement_reextraction.py`, the four socket modules of
   rule 1 (`market_transport.py`, `model_transport.py`, `reader_transport.py`,
   `notifications.py`) and `claude_spend.py`. Everywhere else ordinary tests are
   enough; do not add mutation entries. Existing entries stay and keep running.
   Vacuous tests are this project's documented recurring defect
   (`docs/status-honesty-audit.md`).
7. **When something the user sees turns out false, record the retraction** in
   `docs/status-honesty-audit.md`: screen text, CRS wording, reports, exports,
   and claims made to the owner in issues or PRs. Internal refactors, test-only
   changes and renamed helpers get no entry. Name a new entry after its PR:
   `- **A-<PR number> - ...**` (a second one in the same PR: `A-<PR number>b`).
   Existing numbered entries stay as they are. Several findings in
   `docs/code-review/` belong there.
8. **Fix a claim in every home it lives in.** A third of the review findings are
   "fixed in one of two places" (a flag read in one file, a literal left in
   another). Before closing a fix, grep for the claim.
9. **"Super user"** is a display label only; the internal identifier stays `admin`.
10. **Dashboard stays a focused operational dashboard, not a metrics dump.**
    As of the AI Submittal Review workflow (2026-09), this no longer means
    "no new tiles" literally - it means no UNNECESSARY tiles. Exactly four
    primary cards: Contractor Submittals, Active Standards, Reviews in
    Progress, Needs Attention. One `Upload Datasheet and Run AI Review`
    button. One compact Recent Reviews table. One warning banner shown only
    when there is a real issue (low memory, failed OCR, missing standards).
    Standards Readiness detail lives on the Standards Library page. Recent
    Intelligence Work (comprehensive analyses, gap analyses, market results)
    lives on the Analysis Hub. RAM/model/OCR/embeddings/latency/ingestion
    detail lives on System Health. Nothing else gets added to Dashboard
    without updating this rule first.
11. Merge commits, not squash. Conventional prefixes (`feat:`, `fix:`, `test:`,
    `docs:`). Issues, milestones, PRs with `Closes #N`. Free tools only.
12. **IDs are named after the PR, never "the next free number".** Mutation ids:
    `M<PR number>-01`, `M<PR number>-02`, ... with `phase=<PR number>`. Audit
    entries: `A-<PR number>`. Existing ids are never renumbered. A merge that
    only renumbers ids is not allowed.
13. **General fixes only, never per-layout** (owner order, 13 Oct 2026, #692).
    Never add code that recognises one datasheet's table shape, label
    spelling or layout; new layouts will keep arriving. Allowed: fixes true
    for any document (number/unit/comparator meaning, silent-loss reporting,
    verdict safety, output size, approved checklists, code quality). New
    layouts are handled by one path: the reader fills the equipment type's
    fixed field list with a page quote per value; code verifies the quote
    and compares with the approved rule; what the reader misses goes to the
    engineer or waits for a stronger reader. A reading fix is merged only if
    it also helps, or does not hurt, sheets it was not built on (invented +
    held-out totals).

## Mistakes not to repeat (26 Oct)

One line each; the fix is an order, and a machine now checks what it can.
When a mistake is called out on #692, add one line here in your next PR.

- Pushed unformatted code, so CI sent the PR back (order 215 R1; `.githooks/pre-push`).
- Formatted a whole old file: never whole-file format, only the lines you touched (order 216.4; `quality_ratchet.py format-check --base origin/main` is the test).
- Asked for review on a branch that was behind main (R2).
- The packer slept for hours while approved fixes waited (R4: s2 packs after 15 minutes).
- Doorbell answered only to "urgent" (R5: any mention).
- A pause also stopped the wake-ups, so an order was missed (order 211: pause stops work, never wake-ups).
- Plan tasks were closed without a before/after run (order 213: close only when every acceptance line is proven on main).
- Moved lines a mutation anchor quotes and pushed without `check_mutation_anchors.py`, so CI went red (s3, #1285; the pre-push guard now runs it).
- Added a second model pass without asking what it costs on the Claude lane (s3, #1288; a repeat read must be local-only).

## Who does what

- **Claude Code in VS Code (this file's reader):** backend, git, GitHub.
- **Cowork (Claude in the desktop app):** frontend, tests, docs, designs,
  reviews, and VS Code prompts. Cowork may edit files VS Code is not touching.
- **The user (Ali):** approves, runs demos, flips `.env` flags, renames the
  GitHub repo, sends client questions. Prefers simple English, tables, ✅/❌.

## Tooling traps that have already bitten

- Backend needs **Python 3.12 exactly**; `run.py` refuses others.
- The Cowork device shell is a **Linux VM** bridged to the Windows folder:
  Python 3.10, cannot reach Windows localhost, **cannot run the backend suite**.
  `npx`/`npm` from that VM installs **Linux** native binaries into
  `node_modules` and breaks `npm run dev` on Windows (happened once — fixed
  with `npm install lightningcss-win32-x64-msvc@1.32.0`). Do not run npm/npx
  against the repo from the VM. `node node_modules/typescript/bin/tsc` is safe.
- SQLite is **WAL mode**: the DB is three files (`.sqlite`, `-wal`, `-shm`).
  Copying only one loses documents. Never open the live DB from the VM
  (disk I/O error).
- **Only the server writes the live DB.** Start it with `python run.py` (it
  marks the process; uvicorn directly would be refused its own database).
  Any other process that must write `backend/data/rag_intelligence.sqlite`
  calls `app.live_guard.prepare_live_write(path, reason=...)`, which takes a
  verified online backup and runs a restore drill first; `db.connect()`
  refuses otherwise. Read-only work: `sqlite3 "file:...?mode=ro"`, or
  `live_guard.diagnostic_copy()`. A script run from a git worktree once wrote
  the main checkout's live DB (2026-09-24) - this is why.
- Shell heredocs eat backslashes in regexes. Write Python patch scripts to a
  file, or use quoted heredocs (`<<'EOF'`).
- `AUTH_MODE=demo_required` is on. `<img src>` cannot send the bearer token —
  page images are now fetched with the header (`useAuthedImage`).

## Heavy checks: one lock, batched (#680)

P1, the changed-test run, the mutation run and the AI task batch each need most
of the machine's memory. They share ONE lock file, `D:\project\.heavy-job.lock`
on the Windows PC (elsewhere the temp folder; `HEAVY_JOB_LOCK=<path>` moves it,
`HEAVY_JOB_LOCK=off` disables it, CI does). It names owner, kind and start time;
it is stale after 3 hours or when its process is gone. `run_p1.py`,
`scripts/test_changed.py`, `scripts/mutation_check.py` and the AI batch
(`backend/app/ai_task_runner.py`) take it themselves through
`backend/app/heavy_lock.py`; a job waits up to 30 minutes
(`HEAVY_JOB_WAIT_MINUTES`), then exits with code 75 and says who holds it.
Never write a second waiter.

1. GitHub CI is the first gate for every PR.
2. P1 on the PC runs ONCE per merge round on the merged result of a small batch
   of green PRs, plus per PR only when it touches retrieval, answer, review or
   eval code.
3. Every P1, test run and AI batch unloads its models at the end (#666).
4. Mutation runs are for changed danger-zone modules only (rule 6):
   `python scripts/mutation_check.py --changed`, not the full registry.

## Where to look

| Need | File |
|---|---|
| Full state, decisions, what's next | `docs/HANDOVER.md` |
| Architecture as the code actually is | `docs/architecture-call-graph.md` (current); `docs/architecture.md` (older, stale line refs) |
| The 134 review findings, prioritised | `docs/code-review/README.md` |
| Recorded false claims | `docs/status-honesty-audit.md` |
| The review score (recall, precision, false compliant, citations; answer-key format) | `eval/review/README.md`, `scripts/review_score.py` |
| Review playbooks (HAZOP, SIL procedures; data files, clause-cited, standard not held is never met) | `docs/playbooks.md` |
| The scored model tier of P1 (figures, clause, could-not-read; PC only) | `eval/p1ai/README.md` |
| Review any change against the project's own failure modes | `/review` (`.claude/commands/review.md`) |
| How a night's PRs become a release (roles, reviews, the Mac proof, merging) | `.claude/skills/release-train/SKILL.md` |
| Demo script and safe questions | `docs/HANDOVER.md` § Demo |
| Run it | `backend`: `python run.py` · `frontend`: `npm run dev` · Ollama must be up |

