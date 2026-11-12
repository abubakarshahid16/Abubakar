# CLAUDE.md — RAG Intelligence System

> **#805 overrides this file and every other file, except the privacy and
> safety rules 1 to 5 in CLAUDE.md and the security controls in #806.** No
> issue, comment or plan overrides those; changing them needs the owner's
> written approval on #692 and #1584. #805 (PLAN ONE) is the only plan; where anything
> else here, in `docs/` or in `.cowork/` differs from it, #805 wins.
>
> **Top rule - AI-first (owner, 11 Oct 2026; changed 3 Nov 2026 17:55 PKT, #1584;
> #805 rule 1):** AI reviews and judges like a senior engineer; code verifies
> every quote and does every number comparison; the engineer signs. A verdict
> (Pass, Fail, Missing) counts as decided only with evidence: a quote from the
> document AND from the clause, both verified by code, numbers compared by code,
> 0 wrong verdicts. Switching any AI step off by default, or replacing an AI
> step with a rules-only path, needs the owner's written approval on #692 and
> #1584.

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

Product name everywhere: **RAG Intelligence System**. The old names (the earlier
project name and the client's name) must not appear in code, docs or UI. The GitHub slug still
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
   converter's Claude lane is open (owner, 3 Nov 2026, #1584; it was off from
   28 Oct, order 277); its caps are those above.** The standards converter
   (order 270.3) sends STANDARDS text only, of the SAES, ISO, API, ASME and NACE
   families (owner, 3 Nov 2026, #1584), and never a datasheet, procedure or CRS. Every other
   outbound path for document content stays forbidden. Standing approval (owner decision of
   12 Nov 2026 afternoon, recorded on #1584): with
   `CLAUDE_AUTO_APPROVE_REVIEWS_ENABLED=true` the paper under review and the rule books of the rules the AI
   reviewer asks join the approved list automatically. The routes are exactly these four: (1) a file uploaded as a contractor submittal, or given that role later, is approved when it is uploaded or when the role is set; (2) the paper a review is started on is approved when the review starts, if its role is none or contractor submittal; (3) a rule book (a document classed as a standard) that the AI reviewer asks rules from is approved just before it asks, if the paper qualifies and the book is inside the access of the user who started the review; (4) a rule book that a review cites, or that governs its equipment type, is approved when the review starts or records it. Any other document a review cites (a specification, a drawing, another datasheet, a procedure) is not approved automatically: the review shows "not sent: this document is not a rule book; the owner approves it". Nothing else is approved automatically: no library-wide approval, and chat uses its own per-request consent. The register is blocked by its file name
   (built in, any case, spacing, extension or copy suffix) and by checksum when the file is held; The name block is by file name: a register renamed before it was uploaded is recognised only by its checksum when that file is held, and accented or look-alike letters in a name are not matched. the block list
   (`claude_blocked_hashes.json`) also holds the files, by name or checksum, that the owner marks; the switch needs no
   block file, but a block file that cannot be read turns it off; the switch is off by default. In chat, the user may choose Claude and explicitly
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
   `MATCH_ENGINE`, `VISION_READER_ENGINE`, `CRS_AI_WORDING_ENGINE`,
   `REVIEW_AI_CHECK_ENGINE`, `AI_CLAUSE_REVIEW_ENGINE`, `AI_DIVISION_SCOPE_ENGINE`,
   `AI_ENGINEERING_REVIEW_PASS_ENGINE` and, for the AI reviewer (rule review and
   general review) alone, `AGENT_REVIEW_ENGINE` - owner decision 2026-10-12, #501;
   AI reviewer 12 Nov 2026; under per_task a normal review whose own engine
   settings are all local runs exactly as under ollama, no local-engine bar; owner
   decision of 12 Nov 2026, recorded on #1584 (comment 6806441133, item 5), to be
   confirmed there by the owner; no new outbound path) AND both `STANDARDS_READER_*` egress
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

14. **Less waste (owner order, 12 Nov 2026, standing).**
    (a) Related PRs are combined into ONE branch and tested once: GitHub checks and the bench gate run once on the
    combined head, and the main tree after the merge must equal the tested tree.
    (b) ONE light review (one reviewer, one pass, no hand reverts) for layout, wording, docs and tests. A FULL fresh review
    (attack, hand reverts, mutation entries where the danger zone is touched) for anything on the verdict path. The PR
    text says which depth was used and why.
    A FULL fresh review for anything that can change a verdict or a CRS cell, spend money, change the live data, or change what leaves the machine, whether or not the file is on the list; the list only decides where style stops block.
    The lead runs the mutation check of ALL changed danger-zone modules on the COMBINED head before the merge (a per-PR
    run cannot see stale entries that only the combination causes).
    (c) The Windows test job (`tests-windows.yml`) is off: it runs only by hand (`workflow_dispatch`).
    (d) Style stops (formatting of touched lines, file over 800 lines / function over 80 / complexity, the ruff lint
    baseline) stop only for files on the verdict path, the one list in `scripts/verdict_path.py` (rule 6's danger zone
    plus the code that decides or words a verdict or decides what leaves the machine). For every other file they print a
    WARNING naming the file and the number. Tests, mutation anchors, system map, unused modules, flag register, no client
    data, no test-sheet names, no second number reader, gitleaks and contract types stop everywhere.

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

## Heavy checks: one lock, batched (#680)

```text
P1, the changed-test run, the mutation run and the AI task batch each need most
of the machine's memory. They share ONE lock file, `D:\project\.heavy-job.lock`
on the Windows PC (elsewhere the temp folder; `HEAVY_JOB_LOCK=<path>` moves it,
`HEAVY_JOB_LOCK=off` disables it, CI does). It names owner, kind and start time;
it is stale after 3 hours or when its process is gone. `run_p1.py`,
`scripts/test_changed.py`, `scripts/mutation_check.py` and the AI batch
(`backend/app/ai_task_runner.py`) take it themselves through
`backend/app/heavy_lock.py`; a job waits up to 30 minutes
(`HEAVY_JOB_WAIT_MINUTES`), then exits with code 75 and says who holds it.
```
Never write a second waiter.

1. GitHub CI is the first gate for every PR. The Windows job is manual (rule 14c). Related PRs ride one branch and
   are checked once on the combined head (rule 14a).
2. P1 on the PC runs ONCE per merge round on the merged result of a small batch
   of green PRs, plus per PR only when it touches retrieval, answer, review or
   eval code.
3. Every P1, test run and AI batch unloads its models at the end (#666).
```text
4. Mutation runs are for changed danger-zone modules only (rule 6):
   `python scripts/mutation_check.py --changed`, not the full registry.
```

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

