# Standards extraction: complete storage audit

Read-only audit of `backend/data/rag_intelligence.sqlite`. No table was
written, no file in the project was modified except this document, nothing was
reprocessed and nothing was pushed. No PDF was opened; every identifier below
is a database value, a hash prefix or a count.

Date: 2026-09-20, 05:45 local. Live database opened `mode=ro` throughout.
Section 5 runs the real extractor against a **disposable copy** made with
SQLite's backup API; section 8 runs the answer path against the same copy, so
that asking the application a question could not write a conversation row to
the live database.

---

## 0. The brief's premise no longer holds, and this is stated first

The request is framed around "the 252 standards with zero
`standard_requirements`" and "the 20 with structured requirements". **That
population no longer exists.** Earlier the same night, all 272 standards were
queued through the admin endpoint and extracted.

| | at the time the brief describes | now |
|---|---:|---:|
| standards with `standard_requirements` | 20 / 272 | **272 / 272** |
| standards with zero | 252 / 272 | **0 / 272** |
| total requirement rows | 3,158 | **34,938** |

Sections 3, 4 and 5 are answered against reality rather than against the
assumed state, and every place where the change destroyed evidence is named.
The most important such loss is in section 4: the 15 standards that were
extracted synchronously were only ever identifiable by clustering
`standard_requirements.created_at`, and re-extraction rewrote every one of
those timestamps.

---

## 1. Schema

46 tables, **0 views**, 87 indexes, **0 triggers**.

`chunks_fts` is an FTS5 table with its own content store
(`chunks_fts_content`, `_data`, `_docsize`, `_idx`, `_config`); there are no
synchronising triggers, so FTS membership is maintained in application code.

### Columns matching the requested keyword list

| Table | Rows | Columns of interest |
|---|---:|---|
| `standard_requirements` | 34,938 | `clause`, `page`, `requirement_text`, `source_text`, `extraction_method`, `chunk_id`, `requirement_type`, `field`, `operator`, `value`, `unit`, `raw_value`, `raw_unit`, `condition`, `exceptions`, `table_row`, `subject` |
| `review_findings` | 16,168 | `requirement`, `requirement_id`, `requirement_source_text`, `standard_document_id`, `standard_clause`, `standard_page`, `citation_ids`, `governing_sources`, `match_method` |
| `submittal_facts` | 103 | `field_name`, `source_text`, `chunk_id`, `page`, `raw_value`, `raw_unit`, `normalized_value`, `bbox` |
| `chunks` | 27,216 | `page_start`, `page_end`, `section`, `text`, `content_hash`, `quality_flags`, `text_source` |
| `exclusions` | 4,365 | `rule`, `reason`, `text_sample`, `chunk_id`, `page_start`, `clause_headings` |
| `jobs` | 2,183 | `stage`, `state`, `pages_total`, `pages_done`, `retries`, `error_code` — **no payload and no result column** |
| `messages` | 691 | `payload` (JSON), `answer_type` |
| `reports` | 26 | `snapshot_json`, `snapshot_sha256` |
| `pages` | 7,930 | `text`, `char_count`, `needs_ocr` |
| `page_ocr` | **0** | — |
| `audit_events` | 6,571 | `action`, `resource_id`, `detail` |
| `stage_runs` | 4,470 | `stage`, `items`, `seconds` |

### Writers and readers, from source

| Table | Written by | Read by |
|---|---|---|
| `standard_requirements` | `standards.py` **only** | `comparison.py`, `standards.py`, `submittal_review.py` |
| `submittal_facts` | `datasheets.py` | `comparison.py`, `datasheets.py`, `submittal_review.py` |
| `review_findings` | `comparison.py`, `review.py` | `comparison.py`, `main.py`, `review.py`, `structured_search.py`, `submittal_review.py` |
| `exclusions` | `chunker.py`, `db.py` | `chunker.py`, `ingest.py`, `main.py`, `metrics.py` |
| `jobs` | `extract.py`, `ingest.py`, `ocr.py`, `standards.py`, `upload.py` | `extract.py`, `metrics.py`, `standards.py` |

There is exactly one writer of requirements. No second extraction store exists.

---

## 2. Storage map, all 272 COMPANY_STANDARD documents

| Stage | Count | Denominator |
|---|---:|---|
| extracted pages | 272 | / 272 |
| chunks | 272 | / 272 |
| retrievable chunks | 272 | / 272 |
| FTS rows | 272 | / 272 |
| chunk vectors | 272 | / 272 |
| `standard_requirements` | **272** | / 272 |
| candidate-requirement table | **n/a — no such table exists** | |
| rejected candidates persisted | **0** | rejections are not stored (see §6) |
| `exclusions` rows | 271 | / 272 |
| job rows of any kind | 272 | / 272 |
| `chunk` job | 272 | / 272 |
| `extract_requirements` job | **272** | / 272 |
| **failed** extraction job | **0** | / 272 |
| queued or running extraction | **0** | / 272 |
| extraction never scheduled | **0** | / 272 |
| `stage_runs` telemetry | 272 | / 272 |
| named in `audit_events` | 272 | / 272 |
| `page_ocr` rows | 0 | / 272 (no standard needed OCR) |
| `document_subjects` | 0 | / 272 |
| selected into a review run | 272 | / 272 |
| cited as the standard in a finding | 15 | / 272 |

Job rows for standards, by stage and state:

```
extract_requirements   done   1909 rows   272 documents
chunk                  done    272 rows   272 documents
```

1,909 extraction jobs across 272 documents is the record of seven re-runs
during the same night. Every one is `done`; none failed.

---

## 3. The 252 with zero requirements

**The category counts are all 0 / 252, because the population is 0.** Every
COMPANY_STANDARD document now holds requirements.

| Category | Count |
|---|---:|
| extraction never scheduled | 0 / 252 |
| scheduled but not run | 0 / 252 |
| ran and produced zero candidates | 0 / 252 |
| candidates produced but rejected by a gate | 0 / 252 |
| requirements stored somewhere else | 0 / 252 |
| migration or schema mismatch | 0 / 252 |
| duplicate or role-assignment path skipped extraction | 0 / 252 |
| unknown | 0 / 252 |

For the record, the classification that applied **before** the backfill, from
`docs/ZERO_REQUIREMENTS_CAUSE.md` and still supported by the `jobs` table's
history: all 252 fell in **extraction never scheduled**. `enqueue_extraction`
had a single caller - one admin endpoint - and no ingestion, upload, watch
folder or role-assignment path invoked it. That cause is now closed from both
ends, in `ingest._queue_extraction_if_standard` and
`classification._queue_extraction_if_ready`.

---

## 4. The 20 against the 252

**Partly unanswerable now, and the reason is a side effect of the backfill.**
Re-extraction runs in `replace=True` mode: it deletes a standard's unconfirmed
rows and writes new ones with new ids and new `created_at` values. Every
requirement row in the database was written between `2026-09-19T23:34:47Z` and
`2026-09-19T23:39:07Z`. The 15 synchronously-extracted standards were
identified by the creation-time clustering of their rows, so that evidence is
gone.

Five of the original 20 remain identifiable, because their `jobs` rows
survive:

| File | document_id | Pages | Size | OCR | Uploaded |
|---|---|---:|---:|---:|---|
| SAES-A-005.pdf | `doc_cf435e90fd1b` | 37 | 4,445 KB | 0 | 2026-09-18T21:22:01 |
| SAES-A-008.pdf | `doc_e9a01f9fac16` | 8 | 165 KB | 0 | 2026-09-18T21:22:01 |
| SAES-P-104.pdf | `doc_36d7ebf343a0` | 34 | 540 KB | 0 | 2026-09-18T21:22:13 |
| SAES-W-011.pdf | `doc_fab348551e50` | 57 | 595 KB | 0 | 2026-09-18T21:22:17 |
| SAES-Z-008 v2.pdf | `doc_03f1f95b60dd` | 49 | 1,234 KB | 0 | 2026-09-18T21:22:19 |

Against the population of 272:

| Attribute | Value |
|---|---|
| ingestion date | all 272 uploaded in a 19-second window, `21:22:00Z .. 21:22:19Z` |
| average pages | 29.1 |
| average size | 529 KB |
| OCR versus text layer | 0 of 272 needed OCR; `page_ocr` is empty |
| document family | SAES only; largest sub-series SAES-A at 43 |
| extraction version | `extraction_method` is `extracted` for all 34,938 rows - **no version is recorded**, so no re-run can be distinguished from an original by data alone |
| job type / status | 272 / 272 `chunk` done, 272 / 272 `extract_requirements` done, 0 failed |
| code path | one writer, `standards.py`; the async endpoint and the two new hooks all reach it |
| role assigned before or after ingestion | **NOT ANSWERABLE.** `document_classification` has no `created_at` or role-set timestamp, and `confirmed_at` is NULL for all 272 |

`suggested_by` for the 272: `none` 256, `pattern` 16. `none` is what the bulk
role endpoint writes, so the roles were assigned administratively after
ingestion for at least 256 of them - an inference from the writer's constant,
not a timestamp.

---

## 5. Three standards, three families, against the disposable copy

Copy: `rag_intelligence-20260920-054501-968172.sqlite`. Gate accounting is a
replay of the extractor's own loop using its own constants (`_MANDATORY`,
`MIN_REQUIREMENT_WORDS`, `clause_number`, `strip_page_furniture`), then the
real `extract_requirements` is run on the copy and the two are compared.

`rows before` is not zero because the copy already carries the backfill;
`replace=True` deletes and rewrites them.

### SAES-B-005.pdf — `doc_6f446a8190c1`

17 pages, 414 KB, sha256[:16] `6f446a8190c13e5a`

```
chunk                 done  2026-09-18T21:22:04 -> 21:29:31  retries=0
extract_requirements  done  x7, 2026-09-19T21:47:17 .. 23:35:48, retries=0, no error
retrievable chunks 43   sentences examined 176
  rejected - no mandatory verb 111    rejected - under 5 words 1    duplicate 1
  ACCEPTED 63          rows written 63          replay agrees: yes
citations: clause 62/63   page 63/63   source_text 63/63
awaiting_verification 1   contradicted_source 0
```

### SAES-Q-001.pdf — `doc_a4dea4631572`

19 pages, 447 KB, sha256[:16] `a4dea463157287f6`

```
chunk                 done  2026-09-18T21:22:14 -> 21:53:20  retries=0
extract_requirements  done  x7, 2026-09-19T21:47:23 .. 23:37:46, retries=0, no error
retrievable chunks 41   sentences examined 250
  rejected - no mandatory verb 71     rejected - under 5 words 0    duplicate 10
  ACCEPTED 169         rows written 171         replay agrees: NO (169 vs 171)
citations: clause 171/171   page 171/171   source_text 171/171
awaiting_verification 0   contradicted_source 0
```

The two-row difference is the replay's limitation, not a defect:
`_requirement_parts` splits a numbered list that survived PDF extraction as one
sentence into atomic obligations, and the replay does not model that split.

### SAES-T-018.pdf — `doc_df3a2e4156c4`

74 pages, 1,402 KB, sha256[:16] `df3a2e4156c41418`

```
chunk                 done  2026-09-18T21:22:16 -> 21:56:39  retries=0
extract_requirements  done  x7, 2026-09-19T21:47:23 .. 23:38:06, retries=0, no error
retrievable chunks 95   sentences examined 508
  rejected - no mandatory verb 493    rejected - under 5 words 0    duplicate 1
  ACCEPTED 14          rows written 14          replay agrees: yes
citations: clause 14/14   page 14/14   source_text 14/14
awaiting_verification 6   contradicted_source 0
```

**The dominant gate is "no mandatory verb" in all three** - 111 of 176, 71 of
250, 493 of 508. That gate exists to reject prose, headings and references, and
a 74-page telecommunications standard yielding 14 obligations is a plausible
result rather than evidence of loss. No candidate was rejected for length in
two of the three, and duplicates are in single figures except SAES-Q-001's 10.

---

## 6. Are results hidden in another table or JSON field?

**No requirement is stored anywhere `standard_requirements` does not hold it,
and rejected candidates are not persisted at all.**

- **`exclusions` is not a rejected-requirement store.** Its `rule` values are
  `content_quality_gate` (3,757), `page_classified_toc` (354),
  `page_classified_frontmatter` (227), `page_classified_index` (26),
  `page_yielded_no_chunk` (1). These are chunker and page-classifier
  exclusions, recorded before requirement extraction is reached.
- **A sentence rejected by `_MANDATORY`, by the word-count gate or as a
  duplicate leaves no row anywhere.** The counts in section 5 exist only
  because the replay recomputed them. `extract_requirements` returns
  `requirements`, `awaiting_verification` and `contradicted_source`, and the
  audit row records those three numbers and nothing per-sentence.
- **`jobs` has no payload or result column.** Nothing can be hidden there.
- **JSON columns**: `messages.payload` (372 non-null) carries retrieval
  telemetry - keys `passages`, `answer_passages`, `cited`, `coverage`,
  `lexical`, `reranked`, `timings`, `rejected_citations` and similar - and 253
  of them mention the word "requirement" inside quoted answer text. None
  contains a structured requirement. `reports.snapshot_json` (26) is a report
  snapshot. `review_findings.governing_sources` and `citation_ids` are
  citation lists, not rules.
- **`review_findings` holds 16,168 copies of requirement text** in
  `requirement_source_text`, with `standard_clause` and `standard_page`. These
  are findings produced by past review runs, not a second extraction store.

### The one material integrity finding

**All 16,168 findings now point at a `requirement_id` that no longer exists.**

```
review_findings with requirement_id set                     : 16168
requirement_id present in standard_requirements             :     0
requirement_source_text still matching a live row's text    : 16125 / 16168
```

Every finding predates the backfill (findings span `2026-09-19T00:42` to
`23:27`; every requirement row was written `23:34`-`23:39`). `replace=True`
deleted the rows those findings referenced and wrote new ones with new uuid4
ids. The **evidence** survives - each finding still carries its own copy of the
clause, page and source text, and 16,125 of them still match a live row by text
- but the **join** is broken, and any screen or query that resolves a finding
back to its requirement row will find nothing.

This is a consequence of the re-extractions performed earlier tonight. It is
recorded here rather than repaired, because the brief forbids modification.

Does the review engine read the copies? `comparison.py` and
`submittal_review.py` both read `review_findings`, and the finding carries
`requirement_source_text`, `standard_clause` and `standard_page` directly, so a
stored finding still renders with its citation. What cannot be done is
re-deriving a finding from its requirement row.

---

## 7. Integrity, read-only

```
PRAGMA integrity_check              : ok
PRAGMA foreign_key_check            : 1917 violations, ALL audit_events -> users
duplicate document sha256           : 0
orphaned chunks (no document)       : 0
orphaned chunk_vectors (no chunk)   : 0
orphaned requirements (no document) : 0
orphaned requirements (no chunk)    : 0
```

The 1,917 foreign-key violations are `audit_events.actor_user_id` referencing
users that have since been deleted - including 273 rows from a throwaway
administrator created and removed during tonight's backfill. An audit trail
outliving the account it names is the correct behaviour; deleting those rows to
satisfy a constraint would destroy the record of who did what.

Field completeness on all 34,938 requirement rows:

| Field | Missing |
|---|---:|
| `page` | 0 |
| `source_text` | 0 |
| `requirement_text` | 0 |
| `chunk_id` | 0 |
| `clause` | **4,544** (13.0%) |

225 of 272 standards have a clause on every row. `confirmed_by` is set on
**0** of 34,938 rows - no requirement in this library has been confirmed by a
human. 4,960 rows sit below the verification threshold of 0.75; the distinct
confidence values present are 0.4, 0.5, 0.6, 0.7 and 0.9.

Coverage: 7,930 pages and 27,216 chunks across 274 documents; 22,784 chunks are
in FTS and have vectors, so 4,432 chunks are non-retrievable by design (the
`content_quality_gate` exclusions above).

---

## 8. The four application answers

Run in-process against the disposable copy, unrestricted scope (274 documents).
Running them against the live application would have written `conversations`
and `messages` rows, which the brief forbids.

| Question | Answer source | Mode |
|---|---|---|
| "How many company standards are loaded?" | **database inventory** | `metadata` |
| "Which standards are available?" | **database inventory** | `metadata` |
| "What does SAES-A-105 clause 5.3.3 say about noise limits?" | **hybrid retrieval** | `hybrid` |
| "What noise limit values does the table in SAES-A-105 give?" | **hybrid retrieval** | `hybrid` |

The two corpus questions are answered by `corpus.py` from a scoped `COUNT`,
never by retrieval:

```
corpus payload: {"loaded": 272, "not_loaded": 0, "kind": "count",
                 "source": "database", "role": "COMPANY_STANDARD"}
answer: "272 company standards are loaded and readable by you."
```

**Neither SAES-A-105 question retrieved SAES-A-105.** Both cite a different
standard:

| Question | Cited passage | Supporting |
|---|---|---|
| clause 5.3.3 noise limits | `SAES-K-001.pdf`, section "5.3 Noise", `doc_f803065a10b9` | SAES-J-700 6.6.1, SAES-A-133 6.2.2 |
| the SAES-A-105 table | `SAES-K-001.pdf`, section "5.7.12.2 Ducting shall be size…" | SAES-F-007 6.9, SAES-B-009 5.7 |

The first answer is a *cross-reference to* SAES-A-105 quoted out of another
standard - "Noise shall comply with SAES-A-105" - and the second returns a duct
air-velocity table belonging to SAES-K-001. Coverage was reported honestly in
both cases (`complete: false`, 3 of 11 and 3 of 9 expected documents found),
so the system did not claim completeness it did not have.

**Neither answer used `standard_requirements`.** The five stored limits for
SAES-A-105 clause 5.3.3 - `<= 90`, `97`, `105`, `105`, `115 dB(A)` on page 9 -
exist in the database and were not consulted, because the question path is
retrieval and the structured rules are only read by the comparison engine.
That is a routing gap between two correct subsystems, not a missing rule.

---

## Conclusion

**A. Standards present in the database.** 272 of 274 documents carry the
COMPANY_STANDARD role. Complete. No duplicate hashes, no orphans,
`integrity_check` ok.

**B. Text extracted and searchable.** 272 / 272 have pages, chunks,
retrievable chunks, FTS rows and vectors. 7,930 pages, 27,216 chunks, 22,784
indexed and embedded. No standard required OCR. Complete.

**C. Requirements extracted anywhere.** 272 / 272, **34,938 rows**, in one
table with one writer. No candidate store, no JSON store, no job payload and
no second location exists; rejected candidates are not persisted anywhere, so
"what the extractor walked past" is not recoverable from the database.

**D. Structured requirements the comparison engine can use.** This is far
smaller than C and the difference is the substance of this audit:

| | rows |
|---|---:|
| all requirements | 34,938 |
| comparable types (`numeric_limit`, `table_row`, `relative_limit`) | 1,746 |
| `numeric_limit` carrying a `raw_value` | 1,659 |
| **... and a `subject`, which `match_by_containment` needs to pair it with a datasheet field** | **1,573** |
| ... with a normalised `value` | 1,041 |

**1,573 of 34,938 rows - 4.5% - can actually reach a datasheet**, contributed
by 218 of 272 standards. The remaining 54 standards hold requirements that
cannot currently be matched to anything.

**E. Requirements with exact clause, page and source citations.** 30,394 of
34,938 rows (87.0%) carry all three. `page` and `source_text` are present on
every row; `clause` is missing on 4,544. 225 of 272 standards have a clause on
every row. **`confirmed_by` is set on 0 of 34,938** - nothing in this library
has been confirmed by a human, so every row is a machine's guess presented as
awaiting verification, which is what the system claims it is.

### What must not be concluded from this

Extraction is **not** missing: every standard has rows, every extraction job
succeeded, and the replay in section 5 agrees with the writer. Extraction is
also **not** complete merely because chunks exist: only 4.5% of what was
extracted is in a shape the comparison engine can use, no row has been
confirmed by a person, and the accuracy of the 34,938 is unmeasured - there is
no gold set, and the `gold/` template added earlier today is empty.

Two defects found by this audit and deliberately not fixed: the 16,168
findings whose `requirement_id` no longer resolves, and the retrieval path's
failure to route a question naming SAES-A-105 to SAES-A-105.
