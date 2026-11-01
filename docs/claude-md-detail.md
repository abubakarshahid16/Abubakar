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

## Heavy checks: one lock, batched (#680), paragraph before the last sentence

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

## Heavy checks: numbered item 4 (mutation runs)

```text
4. Mutation runs are for changed danger-zone modules only (rule 6):
   `python scripts/mutation_check.py --changed`, not the full registry.
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
