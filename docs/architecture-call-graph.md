# Production call graph — as the code is (B2 record)

- **Commit read:** `main` at `1b445af` (2026-09-24), clean tree. Nothing was run to produce
  this document; every row was read from code. Source trace: a read-only sweep of
  `backend/app/`, `backend/tests/` and `frontend/src/`, checked against spot reads.
- **Deployment state:** live backend on this PC runs `main` `f8f07d1` (the only later commit,
  `1b445af`, is docs-only), `AUTH_MODE=demo_required`, 127.0.0.1:8000.
- **Supersedes** the line references and counts in `docs/architecture.md` (written at
  `d5357a3`; 23 of its statements are stale — listed in §7). The invariants and trust
  boundaries described there still hold except where §3 and §7 say otherwise.

Legend: **LIVE** = reachable from a registered HTTP route or one of the two background
threads. **OFF** = wired but disabled by a config default. **DEAD** = no production caller.

## 0. Process shape

One FastAPI process (`run.py`). Routes: 108 `@app.*` in `main.py` plus one router,
`watch_api` (`main.py:204`, the only `include_router`). Startup (`main.py:91-172`) runs the
schema ensures and migrations, `fail_orphaned_review_runs`, `standards.recover_stale_extraction_jobs`,
then starts **exactly two background threads**: `IngestionWorker` (`ingest.py:90`) and
`FolderWatcher` (`watcher.py:363`).

## 1. Library processing

| Stage | Implementation | Production caller | Gate / config default | Tests | State |
|---|---|---|---|---|---|
| Upload | `upload.ingest` (`upload.py:237`): stream, hash, `jobs` row, classification suggestion | `POST /api/documents` (`main.py:317`), watcher `_handle` (`watcher.py:702`) | `max_upload_mb=512` | test_upload* , test_xlsx_upload | LIVE |
| Watcher | `FolderWatcher.scan_once` → `_handle` → `upload.ingest` → `_apply_role` → `classification.set_role(only_if_unset)` | startup thread | `watch_folder=""` = off; `watch_interval_seconds=300`. **The three `watch_*` settings are declared twice in `config.py`** (:407-453 and :476-522) | test_watch_folder | LIVE when configured (configured on this PC) |
| Worker loop | `IngestionWorker._run` → `process` (`ingest.py:360`), status-driven QUEUED → EXTRACTING → CHUNKING → INDEXING_KEYWORD → PARTIALLY_SEARCHABLE (OCR, embed) → READY | startup thread | `job_max_retries=3`, `job_retry_base_seconds=60` | test_stage_atomicity, test_job_queue_177, test_job_claiming_race | LIVE |
| Text | `extract.extract_document` (`extract.py:138`), PyMuPDF in a process pool, writes `pages` | worker; `POST .../extract` (`main.py:588`) | `extract_processes=1` | test_extract | LIVE |
| OCR | `ocr.recognise_document` (`ocr.py:274`), RapidOCR + PP-OCRv6 det/rec tiny ONNX, writes `page_ocr`; only pages flagged `needs_ocr`; runs AFTER the keyword index | worker | `ocr_dpi=150`, `ocr_processes=1`, `ocr_threads=1` | test_ocr | LIVE (0 scanned pages in this corpus — untested on real scans) |
| Chunking | `chunker.chunk_document` + `quality.py` gate, writes `chunks`, `exclusions` | worker; `POST .../chunk` (`main.py:598`) | `chunk_target_tokens=300`, overlap 60, max 480 | test_chunker, test_quality_gate | LIVE |
| Keyword index | `keyword.index_document`, FTS5 `chunks_fts` (`keyword.py:28`) + `chunks_vocab` | worker | — | test_keyword | LIVE |
| Embeddings | `IngestionWorker.embed_pending` (`ingest.py:578`) → `Embedder.embed_passages`; e5-small ONNX int8; float32 BLOBs in SQLite `chunk_vectors` | worker; `POST .../embed` (`main.py:618`) | `embed_model_dir`, `embed_batch_size=16` | test_embedder, test_vectorcache | LIVE |
| READY hooks | `_finish_if_embedded` (`ingest.py:716`): queue requirement extraction (COMPANY_STANDARD); extract facts, classify equipment type, classify metadata (CONTRACTOR_SUBMITTAL) | worker | keyed on `document_role` | test_ingest_fact_extraction, test_submittal_metadata_classification | LIVE — **see gap G1** |
| Requirement extraction | `standards.extract_requirements` (`standards.py:608`): deterministic sentence split + mandatory-verb regex, **no model**; queued via `enqueue_extraction`, claimed atomically by `next_extraction_job` (:1120), run by `run_extraction_job` (:1152), drained by the worker only when no document needs work (`ingest.py:300`) | READY hook, `set_role`, `POST .../requirements/extract-async` (`main.py:2693`), sync admin route (`main.py:2583`) | — | test_standards_3b, test_job_queue_177 | LIVE |
| Datasheet facts | `datasheets.extract_facts` (`datasheets.py:1843`): deterministic grid + text-block parsing; `replace=True` supersedes (ADR-0024). Vision tier `_pairs_from_vision_fallback` is a hard-coded `return []` | READY hook; `create_review_run` → `_extract_facts_if_none` | — | test_datasheets, test_179_layouts, test_b40_fact_orphan_guard | LIVE (vision tier DEAD) |
| Classification | `suggest` at upload; `classify_equipment_type_for_submittal`, `classify_metadata_for_submittal` from READY hooks only; `confirm` from `PUT /api/documents/{id}/classification` (`main.py:1119`) | as stated | — | test_classification_*, test_document_roles | LIVE — **see gap G1** |

**Page ledger (B3, ADR-0025).** `page_ledger` table + `page_ledger.py`: one row per page of
every document - native text status, OCR status, index status with the excluding rule,
layout/vision status (both "no stage yet"), and for a submittal whether fields were read
from the page and, if not, why. Refreshed by the ingest READY / no-searchable hooks, by
`extract_facts` (which now records its per-page outcome instead of discarding it) and by
every review run; read by `GET /api/documents/{id}/page-ledger` (scoped) and summarised on
the run as `page_coverage`. Before B3 page state was spread over `pages`, `page_ocr` and
`exclusions`, and the fact-parse outcome was not stored anywhere.

## 2. Engineering review

`POST /api/reviews/run` (`main.py:1866`, admin-gated, 409 if a run of the same document is
running) calls, in order:

1. `submittal_review.create_review_run` (`submittal_review.py:493`) — inserts the run
   (`running`), extracts facts if the document has no current facts.
2. `applicability.select(..., persist=True)` (`applicability.py:378`) — **deterministic, no
   model**: standards cited in the submittal, four attribute matches (equipment type,
   discipline, service, project), and `_match_semantic` (:291), which despite its name is
   **FTS5 keyword search only** over up to 12 distinctive terms. Cited-but-absent standards
   are recorded as missing.
3. `comparison.run_comparison` (`comparison.py:962`):
   - **Requirement inventory, not top-k:** every `standard_requirements` row of every
     applicable standard (`standards.list_requirements`). The hybrid top-k
     `standards.search_requirements` has **no caller** (DEAD).
   - **Pairing:** `match_by_containment` (:1288, deterministic) first; `match_by_model`
     (:1632) only if containment found nothing AND `settings.match_enabled` — **default
     False (OFF)**; otherwise the rationale is tagged `MODEL_DISABLED`.
   - **Verdict:** `compare` (:266) — deterministic unit arithmetic (`claims.normalise`);
     unit guard and ambiguity force `NEEDS_ENGINEER_REVIEW`.
   - **Citation check:** `create_finding` (:633) → `_citation_resolves` (:610): chunk
     exists, belongs to the document, covers the page.
   - `model_opinions` / `_reconcile` exist but the route passes no opinions — never runs.
4. Review code: `recommend_code` (:858) → `_store_run_outcome`; engineer code via
   `POST /api/reviews/runs/{id}/code` (`main.py:1663`).
5. CRS: `GET /api/reviews/runs/{id}/crs` (`main.py:3251`) and `/crs/preview` (:3297) →
   `_crs_content` → `crs_mapping.build_crs_rows` → `crs_export.build_crs` / `build_crs_view`.

**What this means, plainly: the live review makes no model call by default.** Findings come
from deterministic containment pairing plus deterministic comparison. There is no quote
validation on the production review path because no model output reaches a finding:
`quotes.py` (B23) has no importer in `app/`. Measured consequence on the regression
documents: issue #193 (290 current facts, 2 pairings, 0 COMPLIANT/NON_COMPLIANT).

## 3. Model and network layer

Every module that can open a socket:

| Module | Destination | Production caller | Gate | State |
|---|---|---|---|---|
| `model_transport.py` | `settings.ollama_url`, validated by `config.check_model_url` at settings load (:794) and before every request (:111) | `answer._call_model` (Tier 2 chat), `analysis.ollama_generate` (summary, recommendation), `comparison._ask_model_once`, `metrics` probes | `answer_model_allow_remote_host=False`, `answer_model_allowed_hosts=()` | LIVE, loopback only |
| `market_transport.py` | `market_allowed_hosts` | `POST /api/market/search` (`main.py:1369`) | `market_live_enabled=False`, `market_allow_public_egress=False` | OFF |
| `reader_transport.py` | Anthropic API | only `claude_api.py` | `standards_reader_enabled=False`, `..._allow_public_egress=False` | DEAD |
| `notifications.py:64` (`smtplib.SMTP`) | `smtp_host` | management-summary e-mail, deliverable/risk notifications | `smtp_enabled=False` | OFF — **not covered by `tests/test_socket_containment.py`** (gap G2) |

Models configured: `answer_model="qwen3.5:4b"` (Ollama 0.34.3 at 127.0.0.1:11434; installed
`qwen3.5:4b`, `qwen3.5:9b`, `mistral:7b`); embeddings e5-small int8 ONNX; reranker
ms-marco-MiniLM-L-6-v2 int8 ONNX; OCR PP-OCRv6 tiny ONNX.

**The Claude lane (revived 2026-09-25, #222):** `claude_api.router` is registered in `main.py`; its routes answer
409 `model_disabled` unless both standards-reader egress flags are on. `reasoning_provider.get_provider()` picks
`ClaudeProvider` only when `REASONING_PROVIDER=claude` AND both flags AND a key; otherwise `OllamaProvider`, with
the reason logged. Every Claude call leaves through `reader_transport` (the one socket), is priced and capped by
`claude_spend` (USD per step and total, ledger without text), and is cached by (model, prompt version, input hash).

## 4. Conversation

- Routes: `GET /api/answer` (`main.py:710`) → `answer.answer` (`answer.py:475`);
  `POST /api/conversations/{id}/ask` (`main.py:2374`) → `chat.ask` → `answer.answer`.
- History: `chat.resolve_followup` uses up to `FOLLOWUP_WINDOW` prior **user questions**;
  prior answers never reach retrieval or the prompt. The rewritten query is not stored
  (B9A work).
- Retrieval: `search.search` (`search.py:797`) = FTS5 BM25 + brute-force cosine over the
  `vectorcache` matrix, scope mask applied **before** top-k (:258-270), fused by RRF
  (`RRF_K=60`), identifier boost, then the local cross-encoder reranker (falls back to RRF
  order if the model file is missing). `search_candidates=30`, `rerank_candidates=16`.
- Tier 1 returns a verbatim passage without a model; Tier 2 calls Ollama; credibility floor
  `MIN_RERANK_SCORE=-3.0`; `validate_citations` and `strip_half_citation` check output.
- Analysis (`/api/analysis/*`) retrieves with `rerank=False, dense=False` (`analysis.py:517`).
- Chat reuses none of the review's evidence/validation services (B9's target).

## 5. Access control

`access.current_scope` (`access.py:280`): `unrestricted_scope` under `AUTH_MODE=disabled`,
empty scope for an anonymous caller under `demo_required`, otherwise `scope_for_user` (one
grant-table query). Applied as a mask before top-k in keyword and dense search, and as SQL
`_scope_clause` in review, standards and CRS. Classification can only narrow. System actors
(`run_extraction_job`, ingest fact extraction) use every document id, by design.

## 6. Gaps found (new issues)

- **G1 — role set after READY skips downstream work (#195).** `PUT .../classification` (`confirm`)
  setting `COMPANY_STANDARD` queues no requirement extraction (only `set_role` does);
  a `CONTRACTOR_SUBMITTAL` role set after READY by either route runs no fact extraction
  (lazy at review time) and **never** runs equipment/metadata classification.
- **G2 — socket containment incomplete (#196).** `notifications.py` opens an SMTP socket; the
  containment test's network roots omit `smtplib`; CLAUDE.md said only `market_transport`
  may open a socket (false; retraction: honesty audit entry 49).
- **G3 — dead and duplicate code (#197).** `quotes.py`, `extraction_schema.py`,
  `standards.search_requirements`, the vision no-op; duplicate definitions of
  `analysis.is_comprehensive` (:73, :313), `analysis._synthesise` (:717, :754), and the
  `watch_*` settings — the later definition silently wins.
- Existing issues covering the rest: #181 (reasoning on the review route), #180 (vision),
  #183 (title-block metadata), #182 (standards inventory), #193 (facts not pairing),
  #192 (pre-B40 orphans).

## 7. Target architecture (master order B2) vs. today

| Target step | Today | Stage |
|---|---|---|
| Durable jobs | Only requirement extraction is a queued job; every other stage runs inline in one worker thread | B11 |
| Page inspection and routing, page ledger | Ledger built (B3); OCR still routed by `needs_ocr` flag only | B3, B4 |
| Native / OCR / table-layout / selective vision | Native + OCR + rule-based table parsing; vision DEAD | B4, B7 |
| Cited facts, clauses, metadata | Yes, deterministic; metadata classifier from #176 | B4, B5 |
| Structure-preserving chunks, embeddings, keyword index | Yes | B6 |
| Classification → standards and edition applicability | Deterministic rules + FTS keyword; no edition model | B5 |
| Requirement inventory | Yes (all rows of applicable standards) | B5 |
| Evidence retrieval for review | Containment on field names; no retrieval per requirement | B6, B8 |
| Bounded AI reasoning + independent validation | OFF / DEAD (`match_enabled=False`, seam unused, `quotes.py` unused) | B8 |
| Findings, coverage report, CRS, engineer approval | Findings + CRS + engineer code: yes; coverage report: no single definition | B10 |
| Conversation: permitted history, cited answer | Yes, questions-only history, no query rewrite stored | B9, B9A |

Primary-source research behind these choices is in ADR-0019 (layout/tables: Docling,
DocLayNet), ADR-0020 (visually rich retrieval: ColPali), ADR-0021 (structured requirements:
CODE-ACCORD), ADR-0022 (retrieval/evaluation: Microsoft RAG guidance), ADR-0023
(queueing/backfill: AWS large-scale pattern). No component is replaced by this stage: B2
changes documentation only.
