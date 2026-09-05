# Changelog

Notable changes, newest first. Dates are the date the work landed on `main`.
Figures here are measured; where a number is not measured this file says so
rather than rounding a guess into a fact.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project has not yet cut a versioned release, so changes are grouped by
the day they merged.

## [Unreleased]

### Added
- The evaluation harness drives `chat.ask` inside one conversation, so it
  measures the path a person actually uses rather than answering each question
  in isolation. Isolated mode remains available as a diagnostic.
- A measured upload ceiling (512 MB), enforced during the stream and aborting
  before the file is fully read, with tests for both rejection and acceptance.
- The reachability sweep, run for the first time: **98.5%** of retrievable
  chunks can be reached by some query. The 33 that cannot are numerical tables
  whose rarest token is a word like "time".
- `docs/backlog-issues.md` — twelve entries, each with its evidence: ten open
  gaps, one correction, and one closed as a measurement error.

### Fixed
- Follow-up resolution borrowed terms based on word count rather than
  dependence, so a short but self-contained question asked after an unrelated
  one was rewritten before retrieval saw it. Measured over 200 shuffled
  orderings of the eval set: **72 of 200 (36%)** returned a confident answer
  where a refusal was correct, and it was the only failure in any of them. The
  gate is now grammatical completeness — a question carries terms only if it
  contains an anaphor, opens as a continuation, or is a bare noun phrase with
  no finite verb. Verified by replaying the 72 known-bad orderings (72/72 pass)
  plus 50 fresh ones (50/50) — 122 orderings, which is not the same
  measurement as the original 200.
- A settle guard that failed documents which were progressing. One OCR round
  costs three passes of the status loop and rounds double, so a scanned
  document legitimately needed more than the ten passes allowed. It now counts
  churn rather than iterations, and the recorded reason names the stage that
  stopped rather than the loop that noticed.
- "Quoted verbatim from the document" shown when provenance was unknown. The
  predicate is now positive: verbatim only when the text is known to be
  extracted, never as the fallback for everything not recognised.
- Unguarded response shapes that white-screened three views. Fixed once at the
  API client boundary rather than at each call site.

### Known
- `"what about system 2"` does not return an answer about system 2, with or
  without term-carrying. The canonical example for the feature is one of the
  cases it does not rescue. See `docs/backlog-issues.md` entry 11.
## 2026-09-05

### Added
- **OCR for scanned pages** (RapidOCR / PP-OCRv6, in a subprocess, offline).
  Page coverage across a 2,583-page corpus rose **94.0% → 96.3%**. Recognised
  text is labelled as recognised rather than presented as a quotation.
- `eval/coverage.py`, and the three measurements OCR was built to justify.
- An alphabet guard that rejects scripts the corpus cannot contain, after the
  first recogniser emitted CJK characters for English pages.
- A PR template requiring an explicit `Closes` line; the branch convention
  written down, including that it lapsed.

### Changed
- Coverage is attributed per page by that page's own text source. The previous
  definition dropped every recognised chunk, which also dropped pages a chunk
  merely spanned — reporting **+12.5%** against a true **+4.2%**.
- Setup documentation corrected after a clean-clone run: Ollama install and
  pull commands added, and the disk figure replaced with a measured breakdown
  (768 MB in the clone, plus ~3.4 GB for the answer model).

### Fixed
- OCR failed on every scanned document; found by a clean clone, not by a test.
- OCR text was labelled "quoted verbatim from the document".
- Stale vectors: 4,787 → 0 in one worker cycle after re-chunking.

## 2026-09-04

### Added
- Ingestion view, dashboard rebuild, and CPU/RAM readings that state what they
  measured rather than implying a window they never had.
- A vector-matrix cache; every search result records what corpus it ran
  against.
- Chat memory: conversations and messages, with prior **answers** excluded
  from evidence by construction.
- Two-tier answering — Tier 1 quotes the source with no model involved; Tier 2
  is an explicit, opt-in local generation.
- Hybrid retrieval: SQLite FTS5 and dense vectors fused by Reciprocal Rank
  Fusion, then reranked by a local cross-encoder.
- Structure-aware chunking, streamed PDF upload, resumable page-batch
  extraction.

### Changed
- The reranker's window was widened to cover a whole chunk. It had been
  scoring 480-token chunks on their first 256 tokens, so a table with its
  answer at token 350 was judged on text that did not contain it. Cost
  **+650 ms** median; bought retrieval 9/10 → 10/10 and citation 8/9 → 9/9.

### Fixed
- Substituted ligatures in extracted text; stale ground truth now fails loudly
  rather than passing quietly.
- Eight UI defects from an audit, most of them one bug wearing three faces.

## 2026-09-04 — initial

- Repository initialised with governance templates, secret scanning, a
  client-data guard in CI, and the privacy boundary recorded as ADR-0002.
