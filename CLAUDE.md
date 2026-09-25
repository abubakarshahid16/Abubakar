# CLAUDE.md — RAG Intelligence System

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
   owner-approved lane (owner decision 2026-09-25): the **Claude API**, only
   through `reader_transport.py`, only under the budget of **USD 5 per step /
   USD 20 in total** (enforced in `claude_spend`), and with **no document text
   in logs, GitHub issues, PRs or CI**. Every other outbound path for document
   content stays forbidden. The market search sends only the human-typed
   phrase, previewed and approved per query. Only four modules may open a
   socket, each behind a gate:
   `market_transport.py` (market lane, off by default), `model_transport.py`
   (local Ollama only — `ollama_url` validated by `config.check_model_url`),
   `reader_transport.py` (Claude API: the reasoning provider and the reader;
   off unless `REASONING_PROVIDER=claude` AND both `STANDARDS_READER_*` egress
   flags AND a key - owner decision 2026-09-25, USD caps in `claude_spend`) and
   `notifications.py` (SMTP, off by default). Known gap: the socket-containment
   test does not yet cover `smtplib` (honesty audit entry 49). Call graph:
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
6. **Tests are non-negotiable and must not be vacuous.** Every new test must fail
   when its feature is deleted — prove it by mutation. Vacuous tests are this
   project's documented recurring defect (`docs/status-honesty-audit.md`).
7. **When something this project stated turns out false, record the retraction**
   in `docs/status-honesty-audit.md`. It is at 56 entries. Several findings in
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

## Where to look

| Need | File |
|---|---|
| Full state, decisions, what's next | `docs/HANDOVER.md` |
| Architecture as the code actually is | `docs/architecture-call-graph.md` (current); `docs/architecture.md` (older, stale line refs) |
| The 134 review findings, prioritised | `docs/code-review/README.md` |
| Recorded false claims (56) | `docs/status-honesty-audit.md` |
| Review any change against the project's own failure modes | `/review` (`.claude/commands/review.md`) |
| Demo script and safe questions | `docs/HANDOVER.md` § Demo |
| Run it | `backend`: `python run.py` · `frontend`: `npm run dev` · Ollama must be up |
