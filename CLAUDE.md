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

## Where we are (facts only; the live state is in the files named here)

- Live state, read first: `~/project/planner/WHERE-WE-ARE.md` (rewritten daily), then the day's `mirror/daily/<date>.md`.
- The plan: #805 (PLAN ONE, plan change 9 applied); Cycle 1 is milestone 56, Cycle 2 is milestone 57, Parking is milestone 58.
- Cycle 1 runs 1 to 8 Nov 2026 (build); Cycle 2 runs 9 to 15 Nov 2026 (prove on real documents).
- The done-gate is the bench: `scripts/crs_bench.py`. It decides "done", not a builder's say-so.
- The measure is standard rules decided Pass/Fail by code on real documents with 0 wrong verdicts; query/engineer rows do not count.
- Design: recognise kind, read every page, find rules, AI review clause by clause, code verifies every quote, kit checks decide, engineer approves.
- A fix is general, never per-layout (rule 13); the converter's Claude lane stays off (rule 1).
- Moved long passages of this file: `docs/claude-md-detail.md`.
- The current defect list: `docs/code-review/README.md`; recorded false claims: `docs/status-honesty-audit.md`.
- When this header and the planner file differ, the planner file and #805 win.

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
   `reader_transport.py`, only under the budget of **USD 5 per step, USD 25 per
   converted standard / USD 500 in total for November** (owner, #805 plan
   change 4, 28 Oct 2026; it was USD 20 in total; the USD 500 ends on 30 Nov
   unless the owner says otherwise; enforced in `claude_spend`), and with **no
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
   [continued verbatim in `docs/claude-md-detail.md`, section "Standing rule 6 (continued)"]
7. **When something the user sees turns out false, record the retraction** in
   `docs/status-honesty-audit.md`: screen text, CRS wording, reports, exports,
   and claims made to the owner in issues or PRs. Internal refactors, test-only
   [continued verbatim in `docs/claude-md-detail.md`, section "Standing rule 7 (continued)"]
8. **Fix a claim in every home it lives in.** A third of the review findings are
   "fixed in one of two places" (a flag read in one file, a literal left in
   another). Before closing a fix, grep for the claim.
9. **"Super user"** is a display label only; the internal identifier stays `admin`.
10. **Dashboard stays a focused operational dashboard, not a metrics dump.**
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
    [continued verbatim in `docs/claude-md-detail.md`, section "Standing rule 13 (continued)"]

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
- A new fixture PDF was silently ignored by `.gitignore` (`*.pdf`) and never pushed, so CI failed: after `git add`, check `git ls-files` / `git status` shows the file, and use `git add -f` for fixtures (PR 1294).
- Approved a PR from its code while it made an existing mutation entry blind (#1355 and M2513: a new rule caught the sentence the old test used, so the entry no longer failed): before approving a change to a module that has mutation entries, apply those entries by hand and run their tests (PR 1369).
- Moved lines a mutation anchor quotes and pushed without `check_mutation_anchors.py`, so CI went red (s3, #1285; the pre-push guard now runs it).
- Added a second model pass without asking what it costs on the Claude lane (s3, #1288; a repeat read must be local-only).
- Approved a danger-zone label change from the gate alone (#1446, cloud-2 caught it): a tested-card verdict printed "proven" on the CRS because the words are built from the stored label; before approving, follow the value from where it is set to the cell the engineer reads.
- Pushed a new `backend/app` module without `check_system_map.py` and `check_unused_modules.py`, so CI sent two PRs back (#1447, #1449): run both before the push.

## Who does what

- **Claude Code in VS Code (this file's reader):** backend, git, GitHub.
- **Cowork (Claude in the desktop app):** frontend, tests, docs, designs,
  reviews, and VS Code prompts. Cowork may edit files VS Code is not touching.
- **The user (Ali):** approves, runs demos, flips `.env` flags, renames the
  GitHub repo, sends client questions. Prefers simple English, tables, ✅/❌.

## Tooling traps that have already bitten

- Backend needs **Python 3.12 exactly**; `run.py` refuses others.
  [continued verbatim in `docs/claude-md-detail.md`, section "Tooling traps: Cowork VM item (continued)"]
- SQLite is **WAL mode**: the DB is three files (`.sqlite`, `-wal`, `-shm`).
  Copying only one loses documents. Never open the live DB from the VM
  (disk I/O error).
  [continued verbatim in `docs/claude-md-detail.md`, section "Tooling traps: only the server writes the live DB (continued)"]
- Shell heredocs eat backslashes in regexes. Write Python patch scripts to a
  file, or use quoted heredocs (`<<'EOF'`).
- `AUTH_MODE=demo_required` is on. `<img src>` cannot send the bearer token —
  page images are now fetched with the header (`useAuthedImage`).

## Heavy checks: one lock, batched (#680)

[continued verbatim in `docs/claude-md-detail.md`, section "Heavy checks: one lock, batched (#680), opening paragraph"]

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

