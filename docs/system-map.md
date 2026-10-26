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
| Choose the standards that apply to a submittal | `applicability`, `applicability_v2`, `applicability_reasoning`, `claude_selection`, `ai_applicability`, `clause_scope`, `division_text` |
| Answer a chat question from the documents | `answer`, `chat_claude_first` |

## Modules

| Module | Job |
|---|---|
| `absence` | ONE RULE FOR ABSENCE (#450, #451): not found is never a positive outcome |
| `access` | Request-scoped authorisation. Computed once, server-side, per request |
| `acronyms` | Acronym expansions harvested from the documents themselves |
| `admin` | Administration: users, disciplines and document grants |
| `admin_explorer` | Read-only database explorer for the Administration page. Phase 8 |
| `ai_applicability` | Choose the standards that apply to a submittal |
| `clause_scope` | Choose the standards that apply to a submittal |
| `division_text` | Choose the standards that apply to a submittal |
| `ai_engineering_check` | AI engineering check (kind C): observations a reviewer would raise, as DRAFTS |
| `ai.json_reply` | ONE way to take a model's JSON answer out of a code fence (#455); the first module of the `ai/` folder (target structure) |
| `ai.output_limits` | ONE output cap per model-call route, and the named reply states `complete` / `truncated` / `unknown` (#456): a length-cut reply is never parsed as a whole answer |
| `ai_requirements` | AI clause to check (#645): proposes a check per undecided clause sentence, code verifies every part, kept as a DRAFT the engineer accepts (a versioned, confirmed limit) or rejects |
| `ai_numbers` | #845: a finished run's AI numbers (reader, matcher, AI check, wording) with their denominators, from stored data |
| `evidence_boxes` | #785: where each side of a finding sits and the box to draw on it (checklist clause page, value position, label) |
| `ai_task_runner` | The AI task runner (#644): small strict model tasks, run from a queue |
| `analysis` | The three engines joined to retrieval, the model and the access scope |
| `answer` | Answer a chat question from the documents |
| `answerability` | B8: the answer-level safety gate - does the evidence ANSWER the question? |
| `api.documents` | Routes: upload, list, read and delete documents, the ingest steps and the bulk role change (moved out of main.py, order 73) |
| `api.document_classification` | Routes: what a document is - classification, kind, the playbook review |
| `api.document_files` | Routes: a document's pages, page images, original file, workbook, chunks, excluded text and page ledger |
| `api.deliverables` | Routes: the deliverables register, expected deliverables, history, stakeholders, workspace and alerts; management reminders, summary and schedule, escalation rules and the report (moved out of main.py, order 79a) |
| `api.standards` | Routes: the standards library - list, inventory, missing and cited standards, provenance, OKF concepts, clauses, requirements and their extraction, tables, conflicts, the verification queue, clause checks, revisions and supersede (moved out of main.py, order 79a) |
| `api.admin` | Routes: users, disciplines, grants, the model unload, the read-only database explorer and the document-kind routing run (moved out of main.py, order 79a) |
| `api.crs_archive` | Routes: a run's CRS record - who decided what, when and why (order 95 piece 6a), and the issued contractor copies (moved out of main.py) |
| `api.run_summary` | Routes: GET /api/reviews/runs/{id}/summary - the CRS-first screen's tiers, counts and "How this was reviewed" (order 95); GET /api/reviews/runs/{id} - one run (order 109); GET /api/reviews/runs - every run or one page, with its total (order 117 item 5); GET /api/reviews/runs/counts - the tier counts of many runs in one call, the same as each run's summary counts (order 117 item 5) |
| `api.run_standards` | Routes: GET /api/reviews/runs/{id}/standards - the standards a run compared against and why, one page with its total (order 117 item 5); POST /api/reviews/runs/{id}/standards/override - the engineer adds or removes a standard (P2). Moved out of main.py |
| `api.review_templates` | Routes: GET /api/reviews/templates and GET /api/reviews/baseline-rules - the lists, each with an optional page and its total (order 117 item 5) |
| `api_tags` | The API description grouped by area (one tag per route) with every file response typed; documentation only (order 69) |
| `api_utils` | Shared API validation |
| `applicability` | Choose the standards that apply to a submittal |
| `applicability_reasoning` | Choose the standards that apply to a submittal |
| `applicability_v2` | Choose the standards that apply to a submittal |
| `assertions` | Compliance language a sentence asserts, and whether its evidence asserts it |
| `auth` | WHO a request is. `access.py` decides WHAT it may see |
| `auth_session` | The browser's sign-in (order 164.2): HttpOnly cookie, CSRF layers, where Secure is set, sign-out that ends the token on the server |
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
| `answer_prompts` | Wording variants of the local answer prompt, off by default; measured by `eval/answer_quality/` (order 189) |
| `citations` | Shared [S#] citation-marker syntax, used by both answer.py and synthesis.py |
| `claims` | Mechanical claim extraction and comparison. No model, no database, no network |
| `classification` | What a document IS. Never who may read it |
| `claude_api` | The four places a reviewer may ask Claude for a second pair of eyes |
| `claude_approved` | Which documents the owner approved for the cloud model, and the refusal for any other (#806 S3) |
| `claude_budget` | The two numbers that keep a $20 API credit from vanishing in one run |
| `claude_datasheet` | Read a contractor datasheet into facts |
| `claude_recheck` | Recheck findings: the model gives a SECOND OPINION on an engine verdict, and Python decides what that opinion |
| `claude_selection` | Choose the standards that apply to a submittal |
| `claude_spend` | What the Claude API has cost, and the refusal before it costs more |
| `company_standard_confirm` | Hold a non-admin's Company standard for an administrator's confirmation before reviews use it (#620) |
| `comparison` | Phase 5B: does this submittal meet the requirements that govern it |
| `comparators` | The one vocabulary of limit-direction words: which way does a sentence say a limit points (#915) |
| `condition_choice` | Which clause applies: conditions in a question and in a passage |
| `conditions` | B24 — can a requirement's condition be established from the submittal? |
| `condition_stated` | #899 (PF2): an UNKNOWN condition is settled by a trusted field that names the equipment and says the qualifier ("Valve type: Conventional" establishes "a conventional valve"), or by a field named for the thing that states none ("Internal lining: None" rules out "an internal lining is specified"); negation, placeholders, untrusted values and conflicts decide nothing |
| `config` | Settings from backend/.env and defaults |
| `context_budget` | Keep the evidence inside the model's context window, and say when it does not |
| `corpus` | Questions about the corpus itself, and counts that pretend to be about it |
| `coverage` | Which documents the question was about, and which of them the answer used |
| `clause_coverage` | PF4 (#884): the run's applicable rules in exactly one state (checked / sent to the engineer / not checked), checklist-covered apart, read from the scope ledger |
| `crs_export` | CRS (Comment Resolution Sheet) generator - client CRS format |
| `crs_machine_words` | Order 152.2: finds machine wording (code names, model/engine names, internal phrases) in the contractor copy's machine-written cells; the issue gate refuses it |
| `crs_issue` | PF5 (#885): the contractor-copy gate (unread pages, undecided findings), the engineer's recorded decisions, and the archive of each issued copy with its sha256 |
| `crs_ai_drafts` | Make the AI / web drafts of one field one CRS row; a placeholder draft is no row |
| `crs_item_series` | Make a series of items (N1 to N8) one CRS row |
| `crs_blank_fields` | Make the blank fields no clause asks about one CRS row, in full sentences |
| `crs_carry` | K1 (code audit 26 Oct): an issued CRS number carries the engineer's confirmation only for the words they confirmed; other words under the same number need a fresh tick (the number stays) |
| `crs_mapping` | Write the CRS comment text |
| `crs_numbers` | Permanent CRS comment numbers and everything that happens to a comment after it is issued: the contractor's re |
| `crs_wording` | AI-worded CRS comments, with a code lock on every number, unit, clause, page and standard |
| `crs_reply` | Read a contractor's returned Comment Resolution Sheet |
| `datasheet_ai` | Read a contractor datasheet into facts |
| `form_reader` | Read the form of a datasheet page with a model and verify every answer in code |
| `form_reader_fields` | Build a datasheet type's field list, schema and prompt from reference data |
| `form_reader_run` | Run the form reader over a datasheet for extraction |
| `severity_rule` | One rule for a severity word: a failed requirement is never minor |
| `datasheet_checks` | Datasheet self-checks (kind B): what a datasheet says against ITSELF |
| `datasheet_inputs` | Datasheet INPUTS other than a PDF text layer: Excel, Word, scanned pages |
| `datasheets` | Read a contractor datasheet into facts |
| `db` | SQLite storage. WAL mode, foreign keys on, one connection per thread |
| `dashboard_pool` | The dashboard's heavy reads on their own few threads, single-flight (order 84-1) |
| `deliverables` | Revision-aware EPC deliverable and WBS records |
| `disciplines` | Raw discipline spellings, and the canonical value they collapse to |
| `doc_router` | The document-type router (W5b-02, #526) |
| `document_refs` | W1: the registry of everything that points at a document, and what a delete does |
| `docx_chunks` | Chunks for a Word document, built from its STRUCTURE (W5b-01, #525) |
| `docx_reader` | A structure-preserving reader for Word (.docx) documents (W5b-01, #525) |
| `embedder` | Step 4 - local ONNX int8 e5-small embeddings |
| `engineer_feedback` | Engineers' accept / edit / reject decisions as precision per standard and rule |
| `errors` | Error codes and safe error reporting |
| `export_status` | #633 items 6-7: what an export says about its run - run code and status, 'Run <status>: <reason>', unread pages, missing standards |
| `extract` | Step 2 - resumable page-batch extraction |
| `facet_memo` | The facet merge rule asked once per pair of facet versions (#615) |
| `family_search` | A question that names a FAMILY of standards in general words ("what do the welding standards say about post we |
| `field_copies` | One datasheet field read more than once: the same value (or all blank) is one field; different values, or a value beside a blank, stay the engineer's question (order 142 fix C, #1185) |
| `field_links` | Linking a datasheet field to a clause: synonyms, nozzle marks, and simple categorical values. CRS quick wins, |
| `field_naming` | Canonical field names for printed labels and numeric requirements (#193 plan B4, orders 5.2 and 5.3). Behind ` |
| `front_matter` | Front matter: passages that describe a document rather than answer from it |
| `geometry_reader` | Geometry reader: tables and forms read from PDF positions (#193 section 5.1) |
| `glossary` | Engineering synonyms: the words people type -> the words documents print |
| `held_standards` | Marks and counts the standards a review held for the engineer (equipment type unsure), with the caller's boundary |
| `heavy_lock` | One lock for the heavy jobs on a machine (#680) |
| `highlight` | Locating a quoted answer on the rendered page |
| `hooks_check` | Say at boot when this checkout's git hooks are not switched on |
| `ingest` | Background ingestion worker |
| `intent` | What the reader actually typed |
| `job_progress` | "Page x of y" while a review job reads its datasheet; display only (order 95 piece 3b) |
| `job_queue` | Claim, retry, poison and priority on the EXISTING tables (issue #177) |
| `fts_index` | SQLite FTS5 keyword index |
| `lexical` | The lexical gate: is this passage plausibly about what was asked? |
| `ligatures` | Repairing ligatures that failed to extract |
| `live_guard` | The ONE way anything other than the server writes to a live database |
| `main` | The HTTP API (FastAPI routes) |
| `market` | Public market information: a fixture, labelled as one, that cannot pretend |
| `market_phrase` | The only text that may leave this machine, built by whitelist |
| `market_providers` | Three tiers of public information, one row shape, and no socket in sight |
| `market_transport` | The one place in this codebase that may open a socket to the public internet |
| `match_rules` | Rules that decide WHICH containment hit a requirement may be paired with |
| `method_notes` | Order 159: marks the notes on HOW a pairing was made, so the engineer's copy keeps them and the contractor's copy leaves them off |
| `metrics` | Everything the dashboard shows, and nothing it does not measure |
| `model_evidence` | Verification of a local model's quoted evidence (B5 bounded model assistance, owner-approved 2026-09-25) |
| `model_memory` | Free the memory the local answer models hold (#666) |
| `model_transport` | The one place in this codebase that may open a socket to the answer model |
| `notifications` | Fail-closed email notifications for operational EPC events |
| `numparse` | The one place numbers, signs and exponents are read (W2, issue #445) |
| `ocr` | Step 2b - resumable page-batch recognition for scanned pages |
| `okf` | OKF v1 (#513): one cited concept per standard, clause, requirement and equipment type, from stored facts only; no link without a resolving citation (`docs/okf.md`) |
| `orphan_guard` | B38: stop NEW findings being orphaned. Record, then refuse by default |
| `page_ledger` | The page ledger (master order B3): every page accounted for, with a reason |
| `pdf_flow` | #633 item 6: PDF text that wraps and continues on the next page, never dropped (layout only) |
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
| `required_values` | A value the reader recorded as the purchaser's requirement is never the contractor's submitted value (#882, A-1246) |
| `requirement_quality` | Two gates on what becomes a requirement: definitions and unreadable text |
| `requirement_split` | Every requirement in a run's scope is in ONE of three honest groups (#678) |
| `requirements_3b` | Phase 3B: structured requirements - limits, units, conditions, exceptions |
| `reranker` | Cross-encoder reranking, local and CPU-only |
| `review_tiers` | Order 95: each finding of a run in ONE tier (comment / needs you / met or not applicable) with a reason word; rules from reference/review_tiers.json, the data the screen reads too (order 133); display only |
| `review_counts` | Order 152.2: the CRS sheet's counts in ROWS (comments, needs you, met), the findings behind the comment rows, Review notes and removed, from the run's findings and the file's grouping, each with its unit; the run summary sends it as `sheet`; display only |
| `held_reasons` | Order 161 C (163.4): a reason for EVERY finding held for the engineer (stored code, else the program's own leading code, else whether a datasheet field was paired), counted in the run summary; display and measurement only, no rationale, code or verdict changes |
| `paragraph_ids` | Order 161 C: the paragraph a CRS row cites, read from the standard's own numbering (the shape most of its headings share, plus the sub-paragraph in force) when its stored clause is a table number or missing; display only, never guessed, the stored clause is left as it was |
| `review` | Persistent workflow records for AI-assisted engineering reviews |
| `finding_query` | The one scope filter of the review-findings list and its count, so a page and its total agree (order 117 item 5) |
| `paging` | The fields every paged list response carries: `total` (the page's denominator), `limit`, `offset`; a bare-list route's page with its total in `X-Total-Count` (order 117 item 5) |
| `review_jobs` | P3: a review runs as a background job on the B11 queue, not inside the request |
| `review_trace` | Show what each step of a finished review produced (REVIEW_DEBUG console and per-run log, #791) |
| `risks` | Typed EPC risk register, kept separate from evidence-backed findings |
| `row_noise` | Page furniture and fragments that are not fields (#193 plan B4, item 3) |
| `page_reason_words` | Plain words for why a datasheet page gave no value (the stored page reason); the engine counts kept apart as detail (order 124 item 9) |
| `rule_trust` | Decide when an AI-compiled rule may be used: tier, family proof, second check, audit sample, trust labels |
| `rule_eval` | Table and formula rules, evaluated in code (owner order 2026-09-26, 2a + 2b) |
| `schemas` | Typed response models |
| `scope_ledger` | Every requirement in a review's scope ends in exactly ONE state, with a reason (#677) |
| `scores` | Scores that know which scale they are on |
| `search` | Hybrid retrieval: FTS5 + dense vectors, fused with RRF, then reranked |
| `clause_support` | Orders 180: a sentence that states no requirement is never a supporting clause; one naming a service the sheet does not state is held |
| `equipment_subtype` | Orders 180.1 item 5: a standard that governs one pump, compressor or exchanger type is required only when the sheet states that type; unstated is asked of the engineer, never "missing" |
| `standard_judgment` | Orders 180.1 item 6: a cited standard the run judged not applicable to the equipment is held for the engineer in the review run (not selected, so not compared or listed as support there) |
| `sentence_guard` | Where a sentence does NOT end |
| `service_scope` | Service-condition scope (#638, #677): a requirement that applies only in a service the submittal says it is NO |
| `sheet_page` | #967 item 5: the Sheet's datasheet page with every card's value underlined on it by the server (one router route; ids and states only in the URL) |
| `standard_labels` | How a review names its standards: library file name, recorded number and title |
| `slot_options` | #882: a heading over options that each have a drawn slot is filed as "<heading> - <option>", not as the heading's value and a fragment |
| `standard_ids` | ONE matcher for standard identifiers (W3, #452; audit A02, A03) |
| `standards` | The Standards Library: clause hierarchy, atomic requirements, revisions |
| `standards_acquisition` | Standards beyond the client's own: WHERE to get a missing one, and a record of getting it |
| `standards_inventory` | Standards inventory (B5 part 2): family, edition/revision, licence status, cover-page backfill, and which stan |
| `stated_value` | Order 124 item 9: a long stated value is quoted in a finding's text as a marked excerpt ending " …", never a raw table chunk; verdicts still use the whole value |
| `statement_asks` | Orders 180.1 item 2: a plain statement paired with a blank field supports the row only if it asks the sheet to state something |
| `states` | Document lifecycle state machine |
| `stored_paths` | A stored file's path, relative to `data_dir`, resolved on read (order 121 C) |
| `structured_search` | Small, scope-aware search over EPC workflow records |
| `subject_scope` | What a requirement is ABOUT, and whether it applies to this submittal (#453) |
| `submittal_review` | Schema and scoped read paths for the AI submittal review workflow |
| `symbols` | Repair glyphs an old PDF's symbol font extracted as the wrong character |
| `synthesis` | Stage 3 and stage 4: the consolidated summary, and the advisory recommendation |
| `time_units` | The time rows of the one unit table: hours, minutes, seconds, milliseconds, days (#896) |
| `table_gate` | Which requirements a review may check (#598) |
| `tables` | Structured rows and columns for chunks already identified as tables |
| `telemetry` | Measured rates and latencies, persisted |
| `understanding` | B6C: question understanding - structured, deterministic, retrieval-only |
| `upload` | Step 1 - streaming PDF upload |
| `vector_store` | The dense-search vector store: ONE interface, two EXACT backends |
| `vectorcache` | The exact numpy backend of the vector store: one memory-mapped matrix |
| `vision_reader` | Read a contractor datasheet into facts |
| `warmup` | Background warm-up at startup: models and acronym maps, off the request path |
| `fact_api` | POST /api/reviews/facts/{id}/confirm - an engineer confirms one datasheet value (#473) |
| `watch_api` | GET /api/watch/status - what the watched drop folder is doing |
| `watcher` | Watched-folder auto-ingest |
| `web_standards` | Owner order 2d-2: for a standard the submittal CITES but the library does NOT HOLD, an OPTIONAL check against |
| `work_budget` | A hard work budget for a request that can grow with the library (#606) |
| `workbook` | Read an xlsx into sheets for a read-only preview. Standard library only |

## Target structure (planner order 71c on #692; the design for #736)

The table above is where each job lives **today**. This is where it is going. It is reached step by step
on the Mac: each move is one PR with before/after proof (review moves need the T2 proof on the 7
invented sheets, order 64), never one big-bang move.

```
backend/app/
  api/          one router file per area: documents, review, crs, chat, analysis, auth, admin, watch
                (main.py keeps only app setup; today it holds most of the 168 operations)
  review/       reader, facts, applicability, comparison, crs   (_extract_facts and _run_comparison split here)
  knowledge/    standards library, clause index, reference graph (layer 4, the OKF idea)
  chat/         answer, summary, prompts
  ai/           model clients, Claude gate, spend guard, the one JSON parser (#455)
  core/         config, security, database, logging, jobs
  schemas/      request and response models
backend/tests/  same folders as app/, one test file per module
frontend/src/
  features/     one folder per screen area: review, documents, chat, analysis, admin
  shared/       buttons, layout, hooks
  api/          one client file per area (today api/client.ts is one file)
docs/           architecture (this map), decisions, security, runbooks
scripts/        dev and ops tools only; never scratch
```

PR #1065 (#1064) tags the API description by these same areas, plus `standards` and `management`,
which are areas of their own today.

**Rules.**
- No file over 800 lines and no function over 80 lines. `scripts/quality_ratchet.py check` (CI) fails a
  NEW backend file or function over the limit, and a listed one that grows. Today's long ones are
  listed in `eval/quality/long_code.json` (34 files, 99 functions on 17 Oct 2026) and may only shrink:
  after a split, `python scripts/quality_ratchet.py record-long-code` moves the bar down in the same PR.
- `ruff format`, file by file (order 79d): `scripts/quality_ratchet.py format-check` (CI, pull requests)
  fails a NEW Python file that is not formatted, and a changed one that moves further from the formatter.
  An untidy file is never reformatted whole; the lines a PR touches are. Code a split moves into a new module (80% or more
  of its lines deleted elsewhere in the same PR) keeps its formatting, so the move stays verbatim.
- One module per job, no copies (the known duplicates above are debts with a date).
- Tests mirror the app folders.
- Scratch and proof output never live inside the repo.

**Order on the Mac, week 1:** `api/` first (no logic change, lowest risk), then `core/` and `ai/`, then
`review/` (T2 proof per move), then the frontend `api/` and `features/`.
