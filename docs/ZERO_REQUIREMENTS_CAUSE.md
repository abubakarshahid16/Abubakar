# Why 252 of 272 standards have zero requirements

Investigation only. Nothing was fixed, and no production code, configuration
or database was changed. Date: 2026-09-20.

All work ran against a **disposable copy** made with SQLite's backup API, so
the write-ahead log was captured and the live database was never opened for
writing:

```
python scripts/backup_db.py backup backend/data/rag_intelligence.sqlite <tmp>
python scripts/backup_db.py verify <tmp>/rag_intelligence-20260920-022450-039676.sqlite
# integrity: ok | 45 tables | documents 274 | standard_requirements 3158 | jobs 279
```

## The cause, in one sentence

Requirement extraction is scheduled by exactly one code path - an explicit,
per-document admin API call - and nothing in ingestion, upload, the watch
folder or role assignment ever calls it, so the 252 standards were never
submitted for extraction at all rather than having been tried and failed.

## 1. The counts, with denominators

| | count |
|---|---:|
| COMPANY_STANDARD documents | 272 |
| with at least one `standard_requirements` row | **20 / 272** |
| with zero | **252 / 272** |
| requirement owners not classified COMPANY_STANDARD | 0 |
| of the 252, documents with an `extract_requirements` job, ever | **0 / 252** |
| of the 20, documents with an `extract_requirements` job | 5 / 20 |
| `extract_requirements` jobs in the whole table | **5 / 279 jobs** |
| `chunk` jobs in the whole table | 274 / 279 |

Every `extract_requirements` job ever recorded (all five, `done`):

```
doc_e9a01f9fac16  done  2026-09-18T22:35:03Z   HAS reqs
doc_cf435e90fd1b  done  2026-09-18T22:35:03Z   HAS reqs
doc_03f1f95b60dd  done  2026-09-18T22:35:03Z   HAS reqs
doc_36d7ebf343a0  done  2026-09-18T22:35:03Z   HAS reqs
doc_fab348551e50  done  2026-09-18T22:35:03Z   HAS reqs
```

The other 15 of the 20 have requirements but no job, created in two bursts
(`2026-09-19T08:51` and `09:32`), which is the signature of the synchronous
route `POST /api/standards/{id}/requirements/extract` - it extracts in the
request and writes no job row.

## 2. Was it ever scheduled? Executed?

No, for all 252. `enqueue_extraction` has exactly one caller in the codebase:

```
grep -rn "enqueue_extraction" backend/app/
  backend/app/standards.py:949  def enqueue_extraction(...)
  backend/app/main.py:2667      job_id = standards_mod.enqueue_extraction(document_id, actor=actor)
```

`main.py:2667` is inside
`POST /api/standards/{document_id}/requirements/extract-async`, which is
admin-gated and takes one document id.

```
grep -rn "enqueue_extraction" backend/app/ingest.py backend/app/classification.py \
                              backend/app/watcher.py backend/app/upload.py
  (no matches)
```

`ingest.py` only CONSUMES the queue (`next_extraction_job`, line 226). So
extraction is opt-in, per document, by an explicit request. Nothing enqueues
it as a consequence of a document arriving or of being given a role.

## 3. Were the 252 assigned COMPANY_STANDARD before or after ingestion?

**Unknown from the database, and it does not change the cause.**
`document_classification` has no created-at column; `confirmed_at` is NULL for
all 272, so the role cannot be dated from the data. It does not matter for
this question: no role-assignment path calls `enqueue_extraction`, so a role
assigned at any time would not have scheduled extraction either way. The
watch-folder path (`watcher.py`) maps a subfolder to a role and likewise never
enqueues.

## 4. Zero candidates, or candidates rejected by a gate?

Neither: nothing ran. To find out what WOULD happen, the real extractor was
run on the disposable copy for three of the 252. The corpus holds only the
SAES family (see section 5), so one SAES, one SAMSS and one other family could
not be chosen; three SAES sub-series were used instead.

| standard | reqs before | after | candidate sentences | no modal | too short | duplicate |
|---|---:|---:|---:|---:|---:|---:|
| SAES-A-105 (`doc_a835c3a15e04`) | 0 | **28** | 141 | 112 | 0 | 1 |
| SAES-B-005 (`doc_6f446a8190c1`) | 0 | **63** | 176 | 111 | 1 | 1 |
| SAES-G-006 (`doc_69fe30988a23`) | 0 | **20** | 37 | 15 | 0 | 2 |

The gate labels come from a replay of the extractor's own loop using its own
functions and constants (`_MANDATORY`, `MIN_REQUIREMENT_WORDS`,
`_requirement_parts`, `clause_number`, `_INLINE_CLAUSE`). The replay's
accepted count was cross-checked against the rows the extractor actually
wrote, and **agreed exactly in all three cases** - 28/28, 63/63, 20/20 - so
the labelling is not a separate implementation drifting from the real one.

First ten candidates carrying a modal, for SAES-A-105. Sentences are
identified by a sha256 prefix of the sentence; no standard text is reproduced.

```
 page clause     sha256[:12]    modal   verdict   gate
    4 1.2        8ece9e38de61   shall   accepted
    4 1.2        e992da8acec0   shall   accepted
    4 1.2        8adc01446144   shall   accepted
    8 5.1.4      439af3776a62   shall   accepted
    8 5.2.1      a1f8683d84bc   shall   accepted
    8 5.2.3      047045cf2b40   shall   accepted
    8 5.2.4      b2f44b7a9cc3   shall   accepted
    8 5.2.5      bbfd023071cf   shall   accepted
    9 5.2.5      bbfd023071cf   shall   rejected  duplicate of an earlier clause+sentence
    9 5.2.6      27f8073c6ffe   shall   accepted
```

The rejections are overwhelmingly `no mandatory modal` - ordinary prose,
headings and references, which is what that gate is for. No gate is holding
back a population of real obligations.

**SAES-A-105 yields 28 requirements the moment extraction is run.** That
matches the 28 "shall" sentences the task described, and it means the
emptiness is not a property of the document.

## 5. Were the 20 processed after the feature existed, and the 252 before?

No. Both groups were ingested in the same minute:

| | uploaded_at range |
|---|---|
| the 20 | 2026-09-18T21:22:01Z .. 21:22:19Z |
| the 252 | 2026-09-18T21:22:00Z .. 21:22:19Z |

Requirements for the 20 were created hours later (2026-09-18T23:04 through
2026-09-19T09:32), long after both groups had been ingested. The difference
between the groups is when somebody asked for extraction, not when the
document arrived.

## Comparison of the two groups

| | the 20 | the 252 |
|---|---|---|
| average pages | 37.3 | 28.4 |
| average size | 753 KB | 511 KB |
| documents needing OCR | 0 | 0 |
| status `ready` | 20 / 20 | 252 / 252 |
| family | SAES 20 / 20 | SAES 252 / 252 |
| classification `suggested_by` | none 18, pattern 2 | none 238, pattern 14 |
| `confirmed_at` set | 0 / 20 | 0 / 252 |
| extraction version recorded | none - `extraction_method` is `extracted` for all 3158 rows | n/a |

Nothing separates the groups by document shape, OCR, processing path or
family. The only difference that tracks the split is whether an extraction
request was ever made for that document.

## What is still unknown

1. **When each role was assigned.** No timestamp exists for it. It does not
   affect the cause, but it cannot be stated as fact.
2. **Who made the 20 requests, and why those 20.** The audit trail records
   `standard.extraction_queued` for the async five; the 15 synchronous ones
   leave no job row, and were identified from the creation-time clustering of
   their requirement rows, which is inference rather than a record.
3. **No extraction version is stored.** Every row says
   `extraction_method='extracted'`, so a re-run cannot be distinguished from
   the original by data alone, and "which version produced this row" is not
   answerable.
4. **Whether the 640 uncovered pages overlap the 252.** Not examined here;
   the retrieval audit raised it separately.

## A probe error worth recording

The isolation script printed `written=None low_confidence=None` because it
read return keys that do not exist - `extract_requirements` returns
`requirements` and `awaiting_verification`. The counts in this document come
from the row deltas in the database (0 -> 28, 0 -> 63, 0 -> 20), which the
replay independently agreed with. The `None` is a bug in the probe and is not
evidence of anything.

## What this means for a re-run

Extraction succeeds on the 252 when it is run: three of three produced
requirements, with clause and page attached, and no gate blocked them. A
backfill is therefore possible. Deciding and performing that backfill is out
of scope here and is deferred.

## SUPERSEDED, 2026-09-20 — the backfill was done

The deferral above no longer holds, and the cause itself has been fixed in
code. Recorded here rather than by editing the text, because the investigation
is a record of what was true when it was written.

All 272 standards were queued through the real admin endpoint and extracted:
**20 of 272 with rules became 272 of 272**, and 3,158 requirements became
34,938. The cause - nothing scheduling extraction - is now closed from both
ends: `ingest._queue_extraction_if_standard` queues a standard when ingestion
finishes, and `classification._queue_extraction_if_ready` queues one when a
READY document is given the COMPANY_STANDARD role. Section 2 above says
`enqueue_extraction` has exactly one caller. It now has three.

What the backfill then exposed is recorded in `status-honesty-audit.md`,
"The comparator that pointed the wrong way": the count going up was true and
was not the thing that mattered.
