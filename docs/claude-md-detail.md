# CLAUDE.md detail (moved text)

Passages moved verbatim out of `CLAUDE.md` (issue #1485) to keep it under 200 lines. Nothing here is changed; each block continues the rule or item named in its heading. Rules 1 to 5 and the #805 block were not moved.

## Standing rule 6 (continued)

```text
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

## Standing rule 13 (continued)

```text
    for any document (number/unit/comparator meaning, silent-loss reporting,
    verdict safety, output size, approved checklists, code quality). New
    layouts are handled by one path: the reader fills the equipment type's
    fixed field list with a page quote per value; code verifies the quote
    and compares with the approved rule; what the reader misses goes to the
    engineer or waits for a stronger reader. A reading fix is merged only if
    it also helps, or does not hurt, sheets it was not built on (invented +
    held-out totals).
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
