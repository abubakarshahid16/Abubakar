# CLAUDE.md — RAG Intelligence System

> **#805 overrides this file and every other file, except the privacy and
> safety rules 1 to 5 in CLAUDE.md and the security controls in #806.** No
> issue, comment or plan overrides those; changing them needs the owner's
> written approval on #692 and #1584. #805 (PLAN ONE) is the only plan; where anything
> else here, in `docs/` or in `.cowork/` differs from it, #805 wins.
>
> **Top rule - AI-first (owner, 11 Oct 2026; #805 rule 1):** the review is
> AI-first. AI reads, understands and proposes; code verifies and decides
> pass/fail; the engineer decides. Switching any AI step off by default, or
> replacing an AI step with a rules-only path, needs the owner's written
> approval on #692 and #1584.

## Where we are (pointers only)

- The plan: #805 is the only plan. The bench `scripts/crs_bench.py` is the done-gate.
- Live state: `~/project/planner/WHERE-WE-ARE.md` (on the owner's Mac, outside the repo).
- Defect list: `docs/code-review/README.md`. Long passages moved out of this file: `docs/claude-md-detail.md`.

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
   `reader_transport.py`, only under the budget of **per review run USD 5 per step, except the AI clause
   review step USD 10, and at most USD 15 for one whole review run; USD 25 per
   standard, USD 100 per day and USD 500 for November** (owner, #1584, 2 Nov
   2026; the USD 500 ends on 30 Nov unless the owner says otherwise; enforced in `claude_spend`), and with **no
   document text in logs, GitHub issues, PRs or CI**. **The standards
   converter's Claude lane is off by owner decision of 28 Oct 2026 (order 277);
   its caps apply only when the owner opens it.** Until then the converter runs
   on the local engine only.
   The standards converter
   (order 270.3) sends STANDARDS text only, of the SAES and ISO families (API
   and ASME on hold), and never a datasheet, procedure or CRS. Every other
   outbound path for document content stays forbidden. In chat, the user may choose Claude and explicitly
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
   [continued verbatim in `docs/claude-md-detail.md`, section "Standing rule 7 (continued)"]
8. **Fix a claim in every home it lives in.** A third of the review findings are
   "fixed in one of two places" (a flag read in one file, a literal left in
   another). Before closing a fix, grep for the claim.
9. **"Super user"** is a display label only; the internal identifier stays `admin`.
10. **Dashboard stays a focused operational dashboard, not a metrics dump.**
    Exactly four primary cards; nothing else gets added to Dashboard without updating this rule first.
    [continued verbatim in `docs/claude-md-detail.md`, section "Standing rule 10 (continued)"]
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

## Mistakes not to repeat

One line per called-out mistake, kept in `docs/claude-md-detail.md`, section "Mistakes not to repeat". Read it before a push. When the owner calls out a mistake on #692 or #1584, add one line to that section in your next PR.

## Who does what

- **Claude Code in VS Code (this file's reader):** backend, git, GitHub.
- **Cowork (Claude in the desktop app):** frontend, tests, docs, designs,
  reviews, and VS Code prompts. Cowork may edit files VS Code is not touching.
- **The user (Ali):** approves, runs demos, flips `.env` flags, renames the
  GitHub repo, sends client questions. Prefers simple English, tables, ✅/❌.

## Tooling traps

In `docs/claude-md-detail.md`, section "Tooling traps". The ones that matter every session: Python 3.12 exactly; only the server writes the live database (start it with `python run.py`; any other writer calls `app.live_guard.prepare_live_write`); SQLite is WAL, so copy all three files; write regex patches to a file, not a heredoc.

## Heavy checks

One lock for P1, the changed-test run, the mutation run and the AI batch; details in `docs/claude-md-detail.md`, section "Heavy checks". Mutation runs are for changed danger-zone modules only (`python scripts/mutation_check.py --changed`). Never write a second waiter.

## Where to look

| Need | File |
|---|---|
| Full state, decisions, what's next | `docs/HANDOVER.md` |
| Architecture as the code actually is | `docs/architecture-call-graph.md` (current); `docs/architecture.md` (older, stale line refs) |
| The 134 review findings, prioritised | `docs/code-review/README.md` |
| Recorded false claims | `docs/status-honesty-audit.md` |
| (moved rows) | `docs/claude-md-detail.md`, section "Where to look: rows for review score, playbooks, scored model tier" |
| Review any change against the project's own failure modes | `/review` (`.claude/commands/review.md`) |
| (moved rows) | `docs/claude-md-detail.md`, section "Where to look: rows for release train and demo script" |
| Run it | `backend`: `python run.py` · `frontend`: `npm run dev` · Ollama must be up |

