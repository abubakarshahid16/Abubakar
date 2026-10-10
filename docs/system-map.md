# System map: one module per job (#725 F8a, #736)

Every module in `backend/app` is listed here exactly once, with the one job it does.
`scripts/check_system_map.py` (CI) fails when a module is missing, a listed module does not exist,
or a job is done by more than one module without being listed under **Known duplicates**.
`scripts/check_unused_modules.py` (CI) fails when a module is not reached from the app.
Tools that only scripts and tests use live in `backend/tools/`, outside the app.

## Known duplicates (to merge in #725 F8c, #736)

These jobs are done by more than one module today. Each row is a debt, not a design: F8c keeps one.

| Job | Modules |
|---|---|
| Read a contractor datasheet into facts | `datasheets`, `datasheet_ai`, `claude_datasheet`, `vision_reader` |
| Choose the standards that apply to a submittal | `applicability`, `applicability_v2`, `applicability_reasoning`, `claude_selection`, `ai_applicability` |
| Answer a chat question from the documents | `answer`, `chat_claude_first` |
| Write the CRS comment text | `crs_mapping`, `claude_crs_comments` |

## Modules

| Module | Job |
|---|---|
| `absence` | ONE RULE FOR ABSENCE (#450, #451): not found is never a positive outcome |
| `access` | Request-scoped authorisation. Computed once, server-side, per request |
| `acronyms` | Acronym expansions harvested from the documents themselves |
| `admin` | Administration: users, disciplines and document grants |
| `admin_explorer` | Read-only database explorer for the Administration page. Phase 8 |
| `ai_applicability` | Choose the standards that apply to a submittal |
| `ai_engineering_check` | AI engineering check (kind C): observations a reviewer would raise, as DRAFTS |
| `ai_task_runner` | The AI task runner (#644): small strict model tasks, run from a queue |
| `analysis` | The three engines joined to retrieval, the model and the access scope |
| `answer` | Answer a chat question from the documents |
| `answerability` | B8: the answer-level safety gate - does the evidence ANSWER the question? |
| `api_utils` | Shared API validation |
| `applicability` | Choose the standards that apply to a submittal |
| `applicability_reasoning` | Choose the standards that apply to a submittal |
| `applicability_v2` | Choose the standards that apply to a submittal |
| `assertions` | Compliance language a sentence asserts, and whether its evidence asserts it |
| `auth` | WHO a request is. `access.py` decides WHAT it may see |
| `blank_markers` | ONE HOME for "this datasheet cell says the value is not provided yet" |
| `chat` | Conversations, messages, and follow-up resolution |
| `chat_actions` | What a reader does WITH a chat answer: rate it, and file a drafted comment |
| `chat_answers` | The chat's non-document answers: general knowledge, rewrites, actions, records |
| `chat_claude_first` | Answer a chat question from the documents |
| `chat_comparison` | Chat-side comparisons: "compare X and Y" retrieves for EACH named side separately (plan requirement C3, docs/c |
| `chat_model` | The chat's model lane: which engine answers, what it is told, what it costs |
| `chat_presentation` | What an answer says about itself, in the words the Chat screen shows |
| `chat_stream` | A streamed chat turn: its events, its Stop, and the sentence gate |
| `chat_tools` | Claude-first chat (2026-09-27): the tools Claude may call |
| `chat_web` | The chat's web lane: ask first, send one phrase, cite what came back |
| `chunker` | Step 3 - structure-aware chunking |
| `citations` | Shared [S#] citation-marker syntax, used by both answer.py and synthesis.py |
| `claims` | Mechanical claim extraction and comparison. No model, no database, no network |
| `classification` | What a document IS. Never who may read it |
| `claude_api` | The four places a reviewer may ask Claude for a second pair of eyes |
| `claude_budget` | The two numbers that keep a $20 API credit from vanishing in one run |
| `claude_crs_comments` | Write the CRS comment text |
| `claude_datasheet` | Read a contractor datasheet into facts |
| `claude_recheck` | Recheck findings: the model gives a SECOND OPINION on an engine verdict, and Python decides what that opinion |
| `claude_selection` | Choose the standards that apply to a submittal |
| `claude_spend` | What the Claude API has cost, and the refusal before it costs more |
| `comparison` | Phase 5B: does this submittal meet the requirements that govern it |
| `condition_choice` | Which clause applies: conditions in a question and in a passage |
| `conditions` | B24 — can a requirement's condition be established from the submittal? |
| `config` | Settings from backend/.env and defaults |
| `context_budget` | Keep the evidence inside the model's context window, and say when it does not |
| `corpus` | Questions about the corpus itself, and counts that pretend to be about it |
| `coverage` | Which documents the question was about, and which of them the answer used |
| `crs_export` | CRS (Comment Resolution Sheet) generator - client CRS format |
| `crs_mapping` | Write the CRS comment text |
| `crs_numbers` | Permanent CRS comment numbers and everything that happens to a comment after it is issued: the contractor's re |
| `crs_reply` | Read a contractor's returned Comment Resolution Sheet |
| `datasheet_ai` | Read a contractor datasheet into facts |
| `datasheet_checks` | Datasheet self-checks (kind B): what a datasheet says against ITSELF |
| `datasheet_inputs` | Datasheet INPUTS other than a PDF text layer: Excel, Word, scanned pages |
| `datasheets` | Read a contractor datasheet into facts |
| `db` | SQLite storage. WAL mode, foreign keys on, one connection per thread |
| `deliverables` | Revision-aware EPC deliverable and WBS records |
| `disciplines` | Raw discipline spellings, and the canonical value they collapse to |
| `doc_router` | The document-type router (W5b-02, #526) |
| `document_refs` | W1: the registry of everything that points at a document, and what a delete does |
| `docx_chunks` | Chunks for a Word document, built from its STRUCTURE (W5b-01, #525) |
| `docx_reader` | A structure-preserving reader for Word (.docx) documents (W5b-01, #525) |
| `embedder` | Step 4 - local ONNX int8 e5-small embeddings |
| `errors` | Error codes and safe error reporting |
| `extract` | Step 2 - resumable page-batch extraction |
| `family_search` | A question that names a FAMILY of standards in general words ("what do the welding standards say about post we |
| `field_links` | Linking a datasheet field to a clause: synonyms, nozzle marks, and simple categorical values. CRS quick wins, |
| `field_naming` | Canonical field names for printed labels and numeric requirements (#193 plan B4, orders 5.2 and 5.3). Behind ` |
| `front_matter` | Front matter: passages that describe a document rather than answer from it |
| `geometry_reader` | Geometry reader: tables and forms read from PDF positions (#193 section 5.1) |
| `glossary` | Engineering synonyms: the words people type -> the words documents print |
| `heavy_lock` | One lock for the heavy jobs on a machine (#680) |
| `highlight` | Locating a quoted answer on the rendered page |
| `hooks_check` | Say at boot when this checkout's git hooks are not switched on |
| `ingest` | Background ingestion worker |
| `intent` | What the reader actually typed |
| `job_queue` | Claim, retry, poison and priority on the EXISTING tables (issue #177) |
| `keyword` | SQLite FTS5 keyword index |
| `lexical` | The lexical gate: is this passage plausibly about what was asked? |
| `ligatures` | Repairing ligatures that failed to extract |
| `live_guard` | The ONE way anything other than the server writes to a live database |
| `main` | The HTTP API (FastAPI routes) |
| `market` | Public market information: a fixture, labelled as one, that cannot pretend |
| `market_phrase` | The only text that may leave this machine, built by whitelist |
| `market_providers` | Three tiers of public information, one row shape, and no socket in sight |
| `market_transport` | The one place in this codebase that may open a socket to the public internet |
| `match_rules` | Rules that decide WHICH containment hit a requirement may be paired with |
| `metrics` | Everything the dashboard shows, and nothing it does not measure |
| `model_evidence` | Verification of a local model's quoted evidence (B5 bounded model assistance, owner-approved 2026-09-25) |
| `model_memory` | Free the memory the local answer models hold (#666) |
| `model_transport` | The one place in this codebase that may open a socket to the answer model |
| `notifications` | Fail-closed email notifications for operational EPC events |
| `numparse` | The one place numbers, signs and exponents are read (W2, issue #445) |
| `ocr` | Step 2b - resumable page-batch recognition for scanned pages |
| `orphan_guard` | B38: stop NEW findings being orphaned. Record, then refuse by default |
| `page_ledger` | The page ledger (master order B3): every page accounted for, with a reason |
| `pageimage` | On-demand page rendering |
| `passages` | Small-to-big: search small, show big |
| `playbooks` | Review a written procedure against a playbook (#679, W5b-04) |
| `progress` | What the machine is doing right now, recorded when it actually happens |
| `provenance` | Which code read which input: provenance for extracted rows (issue #177) |
| `quality` | Content-quality gate |
| `rates` | Throughput reporting |
| `reader_api` | Layer 1 for STANDARDS: the model READS one sentence, Python VERIFIES it |
| `reader_transport` | The one place in this codebase that may open a socket to the standards reader |
| `reasoning_provider` | One interface for "give this bounded packet to a model and tell me exactly what answered" |
| `reports` | Single-answer evidence reports, rendered from a frozen snapshot |
| `requirement_quality` | Two gates on what becomes a requirement: definitions and unreadable text |
| `requirement_split` | Every requirement in a run's scope is in ONE of three honest groups (#678) |
| `requirements_3b` | Phase 3B: structured requirements - limits, units, conditions, exceptions |
| `reranker` | Cross-encoder reranking, local and CPU-only |
| `review` | Persistent workflow records for AI-assisted engineering reviews |
| `review_jobs` | P3: a review runs as a background job on the B11 queue, not inside the request |
| `risks` | Typed EPC risk register, kept separate from evidence-backed findings |
| `row_noise` | Page furniture and fragments that are not fields (#193 plan B4, item 3) |
| `rule_eval` | Table and formula rules, evaluated in code (owner order 2026-09-26, 2a + 2b) |
| `schemas` | Typed response models |
| `scope_ledger` | Every requirement in a review's scope ends in exactly ONE state, with a reason (#677) |
| `scores` | Scores that know which scale they are on |
| `search` | Hybrid retrieval: FTS5 + dense vectors, fused with RRF, then reranked |
| `sentence_guard` | Where a sentence does NOT end |
| `service_scope` | Service-condition scope (#638, #677): a requirement that applies only in a service the submittal says it is NO |
| `standard_ids` | ONE matcher for standard identifiers (W3, #452; audit A02, A03) |
| `standards` | The Standards Library: clause hierarchy, atomic requirements, revisions |
| `standards_acquisition` | Standards beyond the client's own: WHERE to get a missing one, and a record of getting it |
| `standards_inventory` | Standards inventory (B5 part 2): family, edition/revision, licence status, cover-page backfill, and which stan |
| `states` | Document lifecycle state machine |
| `structured_search` | Small, scope-aware search over EPC workflow records |
| `subject_scope` | What a requirement is ABOUT, and whether it applies to this submittal (#453) |
| `submittal_review` | Schema and scoped read paths for the AI submittal review workflow |
| `symbols` | Repair glyphs an old PDF's symbol font extracted as the wrong character |
| `synthesis` | Stage 3 and stage 4: the consolidated summary, and the advisory recommendation |
| `table_gate` | Which requirements a review may check (#598) |
| `tables` | Structured rows and columns for chunks already identified as tables |
| `telemetry` | Measured rates and latencies, persisted |
| `understanding` | B6C: question understanding - structured, deterministic, retrieval-only |
| `upload` | Step 1 - streaming PDF upload |
| `vector_store` | The dense-search vector store: ONE interface, two EXACT backends |
| `vectorcache` | The exact numpy backend of the vector store: one memory-mapped matrix |
| `vision_reader` | Read a contractor datasheet into facts |
| `warmup` | Background warm-up at startup: models and acronym maps, off the request path |
| `watch_api` | GET /api/watch/status - what the watched drop folder is doing |
| `watcher` | Watched-folder auto-ingest |
| `web_standards` | Owner order 2d-2: for a standard the submittal CITES but the library does NOT HOLD, an OPTIONAL check against |
| `work_budget` | A hard work budget for a request that can grow with the library (#606) |
| `workbook` | Read an xlsx into sheets for a read-only preview. Standard library only |
