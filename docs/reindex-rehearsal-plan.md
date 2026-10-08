# Reindex + re-calibration rehearsal plan (Part C, refusal-calibration-2026-09-29)

> **Version 8 note (2026-09-30).** The run started on 2026-09-29 measures
> CHUNKER_VERSION 7. `feat/context-notes-and-tables` moves the chunker to 8
> (heading chains for search; see `docs/limitations.md`). Once it merges,
> repeat this plan on version 8 with the SAME questions, so 7 and 8 are
> compared like for like, before the live re-process.

**Status: not run yet. Waiting for the other session to report "LAST-LINES
MERGED" (CHUNKER_VERSION 7).** This file only records the plan and the exact
commands - written and stopped per owner instruction (2026-09-29), not
executed.

## Why this exists

Refusal calibration on the real corpus (`eval/refusal_calibration.py`, see
`docs/limitations.md`) found 66 of 166 present-question instances answered
from a chunk stating a different value, and 43 of those 66 didn't even have
the correct chunk in the top 5 retrieved candidates. `reindex_chunking.py`'s
own changelog says CHUNKER_VERSION 6 fixed "a heading with nothing under it,
and the heading lines of a contents page... kept in chunk text instead of
nowhere" - a plausible explanation for some of those 43 misses (a
heading-only chunk with no real content is unfindable by any question about
it). CHUNKER_VERSION 7 (from the other session's in-progress branch) may fix
more of the same shape. This rehearsal measures whether reindexing to the
current chunker actually recovers any of the 43.

## Preconditions before running this

1. The other session reports "LAST-LINES MERGED".
2. Confirm the version bump actually landed on `main`:
   ```
   git -C D:\project\Rag_chatbot log --oneline -1
   python -c "import sys; sys.path.insert(0,'backend'); from app import chunker; print(chunker.CHUNKER_VERSION)"
   ```
   Expect `7`. If it still prints `6`, the merge hasn't reached this checkout
   yet - pull `main` into a fresh worktree first.
3. Confirm the live database is not mid-write (server can stay running - this
   rehearsal never opens the live file for writing, only `diagnostic_copy()`,
   which uses SQLite's backup API against the live file read-only).

## Exact commands

All from a fresh worktree on `main`, `backend/` as the working directory
unless noted. `$COPY` is the path `diagnostic_copy()` prints - capture it,
every later step reuses that same file.

**Step 1 - one read-only copy of the live database (WAL-safe):**
```powershell
$env:REASONING_PROVIDER = "ollama"
python -c "
import sys; sys.path.insert(0, '.')
from pathlib import Path
from app import live_guard
from app.config import settings
copy = live_guard.diagnostic_copy(Path(r'D:\project\Rag_chatbot\backend\data\rag_intelligence.sqlite'))
print(copy)
"
```
Save the printed path as `$COPY`. This is the only file every later step
touches - the live file is never opened again after this line.

**Step 2 - rebuild every stale chunk, on the copy only:**
```powershell
python ..\scripts\reindex_chunking.py --db $COPY --apply --acknowledge-orphaned-findings
```
- `--db $COPY` is a plain temp path, not live-shaped
  (`live_guard.is_live_shaped` checks the exact `backend/data/rag_intelligence.sqlite`
  shape), so `--apply` skips the live-write clearance dance and writes
  directly to the copy - confirmed safe by reading the script, not assumed.
- `--acknowledge-orphaned-findings` is included so every stale document is
  rebuilt, not just the ones with no findings citing their requirements -
  the point of the rehearsal is a complete reindex, and this is a throwaway
  copy, so the protection that flag lifts has nothing to protect here.
- Expect this to report close to 283 of 283 documents stale (whatever it was
  under CHUNKER_VERSION 6, likely all of them again under 7 - extraction and
  chunking are deterministic per document, not incremental).
- Each rebuilt document is left at `indexing_keyword` - not yet searchable.

**Step 3 - the real ingestion worker, pointed at the copy, one call per
document (no server, no hand-made embedding pass):**
```powershell
python -c "
import sys; sys.path.insert(0, '.')
from pathlib import Path
from app import db
from app.config import settings
settings.db_path = Path(r'$COPY')
db.reset_connection()
db.init_db()
from app.ingest import IngestionWorker
conn = db.connect()
doc_ids = [r['id'] for r in conn.execute('SELECT id FROM documents').fetchall()]
worker = IngestionWorker()
for i, doc_id in enumerate(doc_ids, 1):
    result = worker.process(doc_id)
    print(i, len(doc_ids), doc_id, result.get('error') or 'ok')
"
```
`IngestionWorker.process(doc_id)` is resumable and drives a document forward
from whatever state it is currently in (`app/ingest.py:389`) - the same
method the test suite calls directly (e.g. `tests/test_correctness_fixes.py`'s
`upload()` helper), not a simulation of the worker. This is the step with the
real, currently-unmeasured cost: keyword indexing plus re-embedding every
chunk in the corpus. (Since 2026-09-30 a re-chunk keeps a vector whose chunk
id, section and heading chain are unchanged; for the CHUNKER_VERSION 8
re-process that is still nearly every chunk, because the chain goes from NULL
to set and every heading-v1 vector is upgraded - so the estimate stands.)

**Step 4 - re-run the calibration against the reindexed copy:**
```powershell
cd ..
$env:DB_PATH = "$COPY"
python -u eval\refusal_calibration.py --present 55 --seed 20260929 --log-path gold\refusal_calibration_log_v7.jsonl
```
The script always takes its own fresh `diagnostic_copy()` of whatever
`settings.db_path` resolves to at start - pointing `DB_PATH` at `$COPY` means
it takes a copy-of-the-copy (cheap, and keeps the already-reindexed copy
untouched for a second look if needed). Same `--present 55 --seed 20260929`
as the 2026-09-29 run, so the two runs are the same question set on
different chunkings - a fair before/after.

**Step 5 - the one extra number this rehearsal exists to answer:** of the 43
present-question instances whose correct chunk was not in the top 5 before
(recorded in `gold/refusal_calibration_log.jsonl`, `answered_really_wrong`
rows with `expected_score` below the 5th-highest `top5_scores` value, or
`None`), how many now have it in the top 5. This needs the OLD log's 43
`item_id`s matched against the SAME items regenerated from the NEW chunking
(`find_present_items` is seeded and stratified over `COMPANY_STANDARD`
documents, not chunk ids - a document's item is stable across a rechunk even
though its `chunk_id` changes). A short script for this comparison should be
written at rehearsal time, once the actual log shapes from both runs are in
hand - not written blind now.

## Time estimate - genuinely uncertain, stated as a range

No step here has been run, so this is order-of-magnitude, not a measurement:

| Step | What it does | Rough estimate |
|---|---|---|
| 1. diagnostic_copy | SQLite backup API, ~420 MB | under 1 minute |
| 2. reindex_chunking --apply | re-extract + rechunk ~283 documents | 5-20 minutes (CPU text work, no embedding) |
| 3. IngestionWorker.process x283 | keyword index + re-embed every chunk (~40,000 chunks corpus-wide) | **30 minutes to several hours** - this is the real unknown; embedding throughput for this local ONNX model on this machine has not been benchmarked at this scale in this session |
| 4. calibration re-run | same as the 2026-09-29 run | ~45-50 minutes (measured last time at --present 55) |
| **Total** | | **roughly 1.5 to 4+ hours** |

Step 3 is the wide part of the range and the one worth measuring rather than
guessing further - recommend running it as a background task with per-document
progress printed (as the script above already does), so a stall is visible
long before hour three rather than discovered at the end.

## What this rehearsal must NOT do

- Never open `backend\data\rag_intelligence.sqlite` for writing - every step
  above operates on `$COPY` only.
- Never run `reindex_chunking.py --apply` without `--db $COPY`.
- Never commit `$COPY`, its path, or any document text this rehearsal reads.
- Report counts only (per CLAUDE.md rule 1 and rule 4): how many of the 43
  are recovered, not which documents or clauses.
