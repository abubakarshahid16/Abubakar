# CLAUDE.md detail (moved text)

Passages moved verbatim out of `CLAUDE.md` (issue #1485) to keep it under 200 lines. Nothing here is changed; each block continues the rule or item named in its heading. Rules 1 to 5 and the #805 block were not moved.

## Tooling traps: WAL item (continued)

```text
- SQLite is **WAL mode**: the DB is three files (`.sqlite`, `-wal`, `-shm`).
  Copying only one loses documents. Never open the live DB from the VM
  (disk I/O error).
```

## Tooling traps: heredoc and AUTH_MODE items

```text
- Shell heredocs eat backslashes in regexes. Write Python patch scripts to a
  file, or use quoted heredocs (`<<'EOF'`).
- `AUTH_MODE=demo_required` is on. `<img src>` cannot send the bearer token —
  page images are now fetched with the header (`useAuthedImage`).
```

## Heavy checks: numbered item 2 (P1 batching)

```text
2. P1 on the PC runs ONCE per merge round on the merged result of a small batch
   of green PRs, plus per PR only when it touches retrieval, answer, review or
   eval code.
```

## Heavy checks: numbered item 4 (mutation runs)

```text
4. Mutation runs are for changed danger-zone modules only (rule 6):
   `python scripts/mutation_check.py --changed`, not the full registry.
```

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

## Tooling traps: Cowork VM item (continued)

```text
- The Cowork device shell is a **Linux VM** bridged to the Windows folder:
  Python 3.10, cannot reach Windows localhost, **cannot run the backend suite**.
  `npx`/`npm` from that VM installs **Linux** native binaries into
  `node_modules` and breaks `npm run dev` on Windows (happened once — fixed
  with `npm install lightningcss-win32-x64-msvc@1.32.0`). Do not run npm/npx
  against the repo from the VM. `node node_modules/typescript/bin/tsc` is safe.
```

## Tooling traps: only the server writes the live DB (continued)

```text
- **Only the server writes the live DB.** Start it with `python run.py` (it
  marks the process; uvicorn directly would be refused its own database).
  Any other process that must write `backend/data/rag_intelligence.sqlite`
  calls `app.live_guard.prepare_live_write(path, reason=...)`, which takes a
  verified online backup and runs a restore drill first; `db.connect()`
  refuses otherwise. Read-only work: `sqlite3 "file:...?mode=ro"`, or
  `live_guard.diagnostic_copy()`. A script run from a git worktree once wrote
  the main checkout's live DB (2026-09-24) - this is why.
```

## Heavy checks: one lock, batched (#680), opening paragraph

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
Never write a second waiter.
```
