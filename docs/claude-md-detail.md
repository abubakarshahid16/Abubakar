# CLAUDE.md detail (moved text)

Passages moved verbatim out of `CLAUDE.md` (issue #1485) to keep it short. Nothing here is changed; each block continues the rule or item named in its heading. Rules 1 to 5 and the #805 block were not moved.

## Standing rule 7 (continued)

```text
   changes and renamed helpers get no entry. Name a new entry after its PR:
   `- **A-<PR number> - ...**` (a second one in the same PR: `A-<PR number>b`).
   Existing numbered entries stay as they are. Several findings in
   `docs/code-review/` belong there.
```

## Standing rule 10 (continued)

```text
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
```

## Tooling traps: AUTH_MODE item

```text
- `AUTH_MODE=demo_required` is on. `<img src>` cannot send the bearer token —
  page images are now fetched with the header (`useAuthedImage`).
```

## Where to look: rows for review score, playbooks, scored model tier

```text
| The review score (recall, precision, false compliant, citations; answer-key format) | `eval/review/README.md`, `scripts/review_score.py` |
| Review playbooks (HAZOP, SIL procedures; data files, clause-cited, standard not held is never met) | `docs/playbooks.md` |
| The scored model tier of P1 (figures, clause, could-not-read; PC only) | `eval/p1ai/README.md` |
```

## Where to look: rows for release train and demo script

```text
| How a night's PRs become a release (roles, reviews, the Mac proof, merging) | `.claude/skills/release-train/SKILL.md` |
| Demo script and safe questions | `docs/HANDOVER.md` § Demo |
```


## Mistakes not to repeat (26 Oct)

One line each; the fix is an order, and a machine now checks what it can.
When a mistake is called out on #692 or #1584, add one line here in your next PR.

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
  [continued verbatim in `docs/claude-md-detail.md`, section "Tooling traps: AUTH_MODE item"]
