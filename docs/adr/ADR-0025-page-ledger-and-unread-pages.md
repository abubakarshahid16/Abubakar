# ADR-0025 — Page ledger, and an unread page is never the contractor's omission

- **Status:** Accepted (master execution order stage B3, 2026-09-25)
- **Date:** 2026-09-24
- **Decision:** One `page_ledger` row per page of every document, rebuilt from the stage
  tables and carrying fact extraction's own per-page outcome. A review finding that found no
  value may call it the contractor's `MISSING_INFORMATION` only when every page of the
  submittal was read into fields; otherwise it is `NEEDS_ENGINEER_REVIEW` with reason
  `UNREAD_PAGES` naming the pages. #183 is fixed in the equipment classifier (title block read
  from page text), not in the chunker.

## Problem (measured, 2026-09-24)

- Page state lived in `pages`, `page_ocr` and `exclusions`; nothing said, per page, what
  happened and why. `datasheets.extract_facts` computed which pages yielded no fields and the
  reason, and discarded it.
- Corpus: 7,937 pages; 640 standard pages sit in no retrievable chunk, 607 with a page-level
  reason and ~33 with none. 0 pages need OCR (no scans in the corpus).
- After the #179 re-extraction the regression submittals yield fields from 5/7, 4/5 and 2/11
  pages. Every requirement no field answered was written "the submittal states no value",
  with action "Provide the missing value" (honesty audit entry 50).
- #183: the title block is removed by running-line stripping, not the front-matter rule
  (honesty audit entry 51).

## Decision

| Piece | What |
|---|---|
| `page_ledger` table (`db.py`, additive) | per page: native text status/chars, OCR status/engine/confidence/seconds, index status + excluding rule, layout status (`no_layout_stage`), vision status (`not_attempted`, #180), facts status/count/reason + who recorded it (`extraction` or `derived`), extractor version |
| `page_ledger.refresh` | idempotent rebuild from `pages`, `page_ocr`, `chunks`, `exclusions`, `submittal_facts`; keeps extraction's record; derives the rest with the reason stated as not recorded. Rebuildable - holds no evidence of its own |
| `extract_facts` | records each page's outcome (`facts` / `no_facts` + reason / `unreadable` + file condition) in the same transaction as the facts |
| Ingest | refresh at READY and at NO_SEARCHABLE_CONTENT (best effort, never fails an ingest) |
| Review | refresh + summary per run; stored on the run as `page_coverage`; `qualify_by_pages` on every no-value finding |
| API / UI | `GET /api/documents/{id}/page-ledger` (scoped, read-only, no page text); `page_coverage` on `ReviewRunSummary`; one line on the run card |
| #183 | `classification.title_block_lines`: first page's edge lines + running lines (the chunker's own edge definition), from `pages` not `page_ocr`; checked before the chunks. Chunker unchanged |

| CRS (`crs_mapping`) | UNREAD_PAGES findings are NOT individual rows (they are engineer work, and 55-79 per run today); ONE plain summary row "Pages not yet readable - needs engineer review ... not a comment to the contractor", naming the pages the run stored. The missing-information summary row now says what was checked ("not answered by any field read from it") instead of "have no value stated" |
| Screen wording (owner decision 5) | `findingLabel()`: an UNREAD_PAGES finding reads "Pages not yet readable - needs engineer review" in the findings table and detail; MISSING_INFORMATION reads "No value found in the fields read" (was "No evidence submitted"). There is no Simple View yet (B10); it will reuse `findingLabel` |
| Live-write guard (owner decision 3, after the B3 incident) | `app/live_guard.py`: `prepare_live_write` performs the A5 steps itself - online backup, integrity check, table-by-table comparison with the live file, restore drill into a disposable directory - and only then clears the process; `db.connect()` refuses a live-shaped database to any process that is neither the server (`run.py` marks it) nor cleared. Maintenance commands (`app.worker`, `seed_access`, `import_register`, `resetdoc`, the ledger backfill) call it; read-only scripts use `mode=ro`; diagnostics use `diagnostic_copy`. A static test forbids a raw read-write sqlite connection in `scripts/` outside the guard |

**Statuses:** no new status. `NEEDS_ENGINEER_REVIEW` already exists and already routes the
recommended code to Manual Review; the reason code `UNREAD_PAGES` is in the rationale, the
same way `UNIT_MISMATCH` and `AMBIGUOUS_MATCH` are.

## Consequences

- On today's regression documents almost every no-value finding becomes
  `NEEDS_ENGINEER_REVIEW` (every sheet has at least one page not read into fields), so their
  recommended code is Manual Review. That is the honest state of a 17 % recall extractor, not
  a regression; it reverses page by page as B4 raises recall.
- A blank cell ("by vendor") is never paired by the containment matcher
  (`comparison.py`, "categorical or blank: never matched"), so today it too reads as "no value
  found". Recorded on #193 for B4.
- The ledger is not yet a durable job ledger: per-page timing exists only for OCR, and retry
  state is per document (`jobs`). B11 owns that.
- Live rollout: the table is created by `init_db` on restart (additive); existing documents
  need a one-off `refresh` backfill (derived rows) - done under owner authorisation A5 after a
  verified backup and a restore drill.

## Not decided here

The single completeness formula (B10); OCR/vision routing from the ledger (B4, B7); the
running-line detection/stripping window mismatch found while tracing #183 (left open on the
issue).
