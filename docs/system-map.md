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
| Choose the standards that apply to a submittal | `applicability`, `applicability_v2`, `applicability_reasoning`, `claude_selection`, `ai_applicability`, `clause_scope`, `division_claude`, `division_text` |
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
| `division_claude` | Choose the standards that apply to a submittal |
| `division_text` | Choose the standards that apply to a submittal |
| `same_value` | When two readings of a field are one value: the same number and unit with a plain note; a note that changes the meaning stays a second value |
| `label_match` | A split abbreviation ("tube o d") is joined before the roles table is read; a reading with no unit beside the same number with one is one value (switch `datasheet_label_join_enabled`) |
| `scope_type_words` | Does a part's construction already stand in the sheet's own equipment type or title (draft rule, off until the owner says yes) |
| `ai_engineering_check` | AI engineering check (kind C): observations a reviewer would raise, as DRAFTS |
| `ai_check_drafts` | The AI checks' drafts keep no status, are counted as "AI observations (draft, no verdict)", and an exact repeat is marked |
| `ai.json_reply` | ONE way to take a model's JSON answer out of a code fence (#455); the first module of the `ai/` folder (target structure) |
| `ai.output_limits` | ONE output cap per model-call route, and the named reply states `complete` / `truncated` / `unknown` (#456): a length-cut reply is never parsed as a whole answer |
| `ai_requirement_chunks` | #645 slice 3: the local model reads a held standard's chunks (tables too) and proposes single limits; code verifies quote, value, unit, comparator and condition; kept as DRAFTS (statement row + `clause_check_drafts`); off by default (`ai_requirement_extraction_enabled`) |
| `ai_requirement_tables` | #645 slice 2: a table row with no comparator in its words; the direction is read by code from the column header (or caption), the unit from the cell or header; the quote carries header + row, each taken from the chunk; same switch as `ai_requirement_chunks` |
| `ai_requirements` | AI clause to check (#645): proposes a check per undecided clause sentence, code verifies every part, kept as a DRAFT the engineer accepts (a versioned, confirmed limit) or rejects |
| `ai_numbers` | #845: a finished run's AI numbers (reader, matcher, AI check, wording) with their denominators, from stored data |
| `evidence_boxes` | #785: where each side of a finding sits and the box to draw on it (checklist clause page, value position, label) |
| `scan_quality` | #505: how well a scanned page was read (the recogniser's own confidence grouped clear / mixed / poor, or a named state), shown beside the citation on `/evidence` |
| `ai_task_runner` | The AI task runner (#644): small strict model tasks, run from a queue |
| `review_audit_rows` | #1525: reconciles, per CRS copy, the rows composed for a run with the rows the file prints and what was removed, for the audit report |
| `ai_call_ledger` | #1525: counts, per step and model, the AI answers a review job asked for fresh and the stored answers it reused, for the audit report; open only with REVIEW_AUDIT_REPORT_ENABLED on |
| `analysis` | The three engines joined to retrieval, the model and the access scope |
| `answer` | Answer a chat question from the documents |
| `answer_model_notice` | Order 238.2: the dashboard warning when the default 35B answer model is not installed, naming the earlier model |
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
| `blank_form` | A blank form (label lines, no value): the document kind never comes from a label |
| `chat` | Conversations, messages, and follow-up resolution |
| `chat_actions` | What a reader does WITH a chat answer: rate it, and file a drafted comment |
| `chat_answers` | The chat's non-document answers: general knowledge, rewrites, actions, records |
| `chat_claude_first` | Answer a chat question from the documents |
| `chat_comparison` | Chat-side comparisons: "compare X and Y" retrieves for EACH named side separately (plan requirement C3, docs/c |
| `chat_model` | The chat's model lane: which engine answers, what it is told, what it costs |
| `register_type_split` | #1087: the documents with no register type, split into awaiting (no role) and not in the register (a role is set), scoped to the caller |
| `chat_presentation` | What an answer says about itself, in the words the Chat screen shows |
| `chat_stream` | A streamed chat turn: its events, its Stop, and the sentence gate |
| `chat_tools` | Claude-first chat (2026-09-27): the tools Claude may call |
| `chat_web` | The chat's web lane: ask first, send one phrase, cite what came back |
| `chunker` | Step 3 - structure-aware chunking |
| `pdf_headings` | Step 3 - a PDF's section headings read from font size and weight (#1522, off by default) |
| `data_page` | Step 3 - a body-text or measured-values page is never set aside as front matter |
| `figure_page` | Step 2b - a drawing page with only a running header goes to recognition |
| `answer_prompts` | Wording variants of the local answer prompt, off by default; measured by `eval/answer_quality/` (order 189) |
| `citations` | Shared [S#] citation-marker syntax, used by both answer.py and synthesis.py |
| `cited_edition` | R7 (#771): a note when the edition year a submittal prints after a standard differs from the held library copy's, never silently the same |
| `equipment_title_block` | Owner decision 1 Nov (#1478): only the title block sets the equipment type; none or two types there = empty, marked engineer to confirm, with a Review note. Switch `equipment_from_title_block_enabled`, off by default |
| `claims` | Mechanical claim extraction and comparison. No model, no database, no network |
| `classification` | What a document IS. Never who may read it |
| `claude_api` | The four places a reviewer may ask Claude for a second pair of eyes |
| `claude_answer_cache` | The stored answer of every Claude call: the same request is never bought twice |
| `claude_approved` | Which documents the owner approved for the cloud model, and the refusal for any other (#806 S3) |
| `claude_models` | What a Claude model id accepts, and the models a run record names |
| `claude_auto_approve` | #1584: a document uploaded for review, and a standard its review cites, join the approved list by themselves unless blocked; behind `claude_auto_approve_reviews_enabled` |
| `claude_budget` | The two numbers that keep a $20 API credit from vanishing in one run |
| `claude_datasheet` | Read a contractor datasheet into facts |
| `claude_recheck` | Recheck findings: the model gives a SECOND OPINION on an engine verdict, and Python decides what that opinion |
| `claude_selection` | Choose the standards that apply to a submittal |
| `claude_spend` | What the Claude API has cost, and the refusal before it costs more: per review run USD 5 per step, USD 10 for AI clause review and USD 15 in all; USD 25 per standard, USD 100 a day, the total |
| `claude_spend_report` | What the Claude lane really cost per step, from settled ledger lines, and the USD 100 a day |
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
| `coverage_pair` | Plan change 6 B: one meaning of "checked": risk (wrong among decided) and coverage (decided of the rules the run states apply), checklist apart, for the bench, the board call and, behind ONE_CHECKED_DEFINITION_ENABLED, the CRS and the screen |
| `clause_coverage` | PF4 (#884): the run's applicable rules in exactly one state (checked / sent to the engineer / not checked), checklist-covered apart, read from the scope ledger |
| `crs_export` | CRS (Comment Resolution Sheet) generator - client CRS format |
| `crs_export_quality` | #1503: the CRS export's quality rules behind CRS_EXPORT_QUALITY_ENABLED - merge duplicate rows, drop empty ones, a page or "page not found" on every row, 350-character comments, the Internal sheet, trimmed standards sheet, Priority from a fixed list; export only |
| `crs_machine_words` | Order 152.2: finds machine wording (code names, model/engine names, internal phrases) in the contractor copy's machine-written cells; the issue gate refuses it |
| `crs_issue` | PF5 (#885): the contractor-copy gate (unread pages, undecided findings), the engineer's recorded decisions, and the archive of each issued copy with its sha256 |
| `crs_ai_drafts` | Make the AI / web drafts of one field one CRS row; a placeholder draft is no row |
| `crs_item_series` | Make a series of items (N1 to N8) one CRS row |
| `crs_blank_fields` | Make the blank fields no clause asks about one CRS row, in full sentences |
| `run_record` | Record on a review run its rulebook, models and ticks imported, and make the internal CRS's Run record sheet with the could-not-check list |
| `crs_checklist` | Make a checklist item held for the engineer a CRS row, and say when it is a draft |
| `recommendations` | A "should" sentence of a standard is stored as a recommendation with no limit; no review reads it (order 288.2) |
| `crs_ai_cell` | Order 233: the internal CRS copy's AI Review Comments cell is never blank; says why when the AI wording is missing (internal copy only) |
| `run_finishing` | Order 236: a run whose job is still writing the AI comments, numbers and wording reads as running, not completed |
| `table_cells` | Order 271.4: a standards-table cell as requirement fields, a number, a number with a unit or a range (moved out of `standards`) or, behind a switch, a text cell with no value |
| `model_metrics` | #503: per-model latency and error counts of the local model calls a review run makes, stored per run and model with the date (counts and seconds only) |
| `checklist_scope` | Order 235.2: whether a review checklist REPLACES its standards' library requirements (the valve one does; the pump one, which only asks that fields are stated, does not) |
| `cover_page` | Order 235 item 3: the text check that marks a page with no fields as a cover/notes page (read, not unread) when the picture reader cannot be asked |
| `clause_review` | #1477: AI clause review of a procedure or specification: one requirement at a time against 4 small passages, local model only, every quote verified on the stored page text, never a verdict (engineer to confirm), cached, time-budgeted; off by default |
| `clause_review_status` | #1477: the words of the clause review's outcome (counts with denominators; whole-document note "N of M reviewed, K not reviewed, first not reviewed"); pure, no model, no storage |
| `settings_ext` | #1477, #1495: settings kept out of `config.py` (a base of `config.Settings`, so the big file does not grow) |
| `clause_check_rank` | Order 235 item 1: which clause sentences get the per-run clause-check budget (fields the sheet states, then a safety clause, then standards it cites, then figures) and each standard's share |
| `crash_log` | Order 252: a native crash (bus error, segfault) leaves the stack of every thread in `<data>/logs/native-crash.log` |
| `pdf_guard` | Order 252: one process-wide re-entrant lock around short PyMuPDF blocks (MuPDF is not thread-safe) |
| `crs_carry` | K1 (code audit 26 Oct): an issued CRS number carries the engineer's confirmation only for the words they confirmed; other words under the same number need a fresh tick (the number stays) |
| `crs_reference` | Order 227: what a CRS Standard Reference says after the standard's name: its edition (stored on the finding or printed in the standard's own name; "edition not recorded" when unknown, never guessed), the clause words and the page |
| `crs_draft_lanes` | #1477: the words of the CRS draft rows (waiting sentences of the AI / web drafts, and the clause review's lane); pure constants |
| `crs_decider` | #892: who decided a finding (the confirmer, else the engineer who accepted it) for the CRS byline |
| `crs_mapping` | Write the CRS comment text |
| `crs_no_field` | A library requirement no field on the sheet answers is one grouped engineer note per standard, never a contractor row (order 245) |
| `crs_page_words` | What the CRS Page/Section cell says: the datasheet page and field, or "Not found on pages 1-N" with at most three tags (order 228.4) |
| `crs_numbers` | Permanent CRS comment numbers and everything that happens to a comment after it is issued: the contractor's re |
| `crs_wording` | AI-worded CRS comments, with a code lock on every number, unit, clause, page and standard |
| `crs_reply` | Read a contractor's returned Comment Resolution Sheet |
| `datasheet_ai` | Read a contractor datasheet into facts |
| `form_reader` | Read the form of a datasheet page with a model and verify every answer in code |
| `form_reader_fields` | Build a datasheet type's field list, schema and prompt from reference data |
| `form_reader_run` | Run the form reader over a datasheet for extraction |
| `reread_for_standards` | Read the sheet once more when the standards a review chose ask for fields the first read never asked (order 211 R2) |
| `own_value_limit` | A reference that states its own value ("the vessel MAWP of 12 barg") is a plain limit of that value |
| `severity_rule` | One rule for a severity word: a failed requirement is never minor |
| `datasheet_roles` | Which role a datasheet field name states when it fits several: the one the sheet's equipment type checks (#900) |
| `datasheet_coverage` | The reader-coverage line of a datasheet review: checklist fields read, and on the sheet but not read |
| `datasheet_checks` | Datasheet self-checks (kind B): what a datasheet says against ITSELF |
| `datasheet_inputs` | Datasheet INPUTS other than a PDF text layer: Excel, Word, scanned pages |
| `datasheets` | Read a contractor datasheet into facts |
| `dual_unit_form` | Reads "24.8 (109) m3/h (USGPM)" as its first system, "24.8 m3/h", when both halves are one quantity |
| `db` | SQLite storage. WAL mode, foreign keys on, one connection per thread |
| `degraded_read` | A degraded AI reading of a datasheet (mostly refused, timed out, stopped, unavailable) is recorded in counts and holds every checklist pass for the engineer (order 261.2) |
| `deferred_value` | A value the sheet defers to the contractor (By Contractor, TBA) is a query, never a verdict (owner decision D2, #1475) |
| `impossible_sign` | A value that should not be negative, printed negative, never gives a Pass; it becomes a Query (#1607) |
| `dashboard_pool` | The dashboard's heavy reads on their own few threads, single-flight (order 84-1) |
| `deliverables` | Revision-aware EPC deliverable and WBS records |
| `disciplines` | Raw discipline spellings, and the canonical value they collapse to |
| `doc_router` | The document-type router (W5b-02, #526) |
| `document_kind` | The kind of a document (datasheet, procedure, specification, contract...) from its title block and cover (#1474) |
| `kind_rules` | The document kind chooses the rule set: a non-datasheet gets no equipment datasheet checklist and no equipment-type standards (#1474) |
| `equipment_scope` | Rules written for another equipment type or document kind than the submittal's are left out of a review and counted; unknown scope stays in |
| `document_refs` | W1: the registry of everything that points at a document, and what a delete does |
| `docx_chunks` | Chunks for a Word document, built from its STRUCTURE (W5b-01, #525) |
| `intake` | One intake layer (#525, ONE_INTAKE_ENABLED): PDF, Word, Excel and image files read into one page shape; every unread page or refused file states its reason |
| `docx_pages` | A Word file's own page numbers from its saved markers, and its tables and pictures counted against what was read (WORD_PAGE_MARKERS_ENABLED) |
| `sheet_chunks` | Chunks for an Excel workbook (#525 slice 2, INTAKE_IMAGES_XLSX_ENABLED): each chunk cited by sheet and cell range |
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
| `field_vocabulary` | Order 259.5: the closed vocabulary of quantities (synonym canonicals + numeric checklist roles); a numeric limit is named against it once, offline (`scripts/name_numeric_limits.py`), a sheet fact by rule; names pair through `match_by_field_name` |
| `rule_cards` | Order 296: every checklist rule is a card tested with the real checking code (meets, breaks, unclear, and an at-the-limit case for a limit); `tested` or `draft` with the reason, a card may declare what it needs (a standard we do not hold) |
| `card_trust` | Order 306.1: which rule cards may decide a checklist verdict while the engineer's approval is pending - tested under the stricter rule (written cases, an at-the-limit case, a clause number, not weak), behind `tested_cards_decide_enabled`; `rule_trust.check_label` reads it |
| `rule_roles` | Order 262.1: which field of an equipment type's own form each numeric rule of a held standard limits - proposed offline (`scripts/propose_rule_roles.py`), checked by `field_vocabulary`'s four gates, kept as a DRAFT file in `reference/rule_roles/` with no document text; a review reads it only while the rule text still hashes the same |
| `statement_roles` | Order 263.1: a STATEMENT rule ("the pump shall have X") mapped to a TEXT field of the type's own form plus the value the clause requires - proposed offline (`scripts/propose_rule_roles.py`), kept in the same DRAFT file as hashes only, paired at run time through `match_by_field_name` (always NEEDS_ENGINEER_REVIEW, both sides shown) |
| `standards_converter` | Order 270.3: the sentences of ONE standard (SAES, ISO only) turned into checks offline (`scripts/convert_standards.py`) - Claude Sonnet through `ClaudeProvider` answers applicability, one field of the type's own form, comparator, limit, unit and the exact clause words; code proves every answer against the stored clause, the rest is "unproven: engineer, please look"; drafts (JSON + CSV, clause quotes) are written outside the repo and a review reads only the verified "yes" rows, only when `standards_converter_dir` is set |
| `converter_review` | Orders 270.3 and 274.1: the READING side of the standards converter - the verified "yes" rows of its drafts as field mappings (`rule_roles`) and, for a clause sentence it proved, a rule in the sentence's place (`ai_requirements.auto_use_rules`' road, `rule_trust` decides the verdict); empty unless `standards_converter_dir` is set; code re-checks every row against the stored sentence |
| `converter_gates` | Orders 295.7 b and c: the standards converter's proof gates that read the SENTENCE's surroundings - `in_example` (a worked example illustrates, it is not a requirement) and `quote_unreadable` (a quote, or the sentence it was cut from, that is OCR noise); pure functions, called by `standards_converter.verify`; `fold` is the one way converter text is compared |
| `standards_compiler` | #1584: Claude turns a held standard's pages into version 2 rules on a database copy; code verifies every quote, limit and unit on the cited page; stored apart and held until the owner approves, changing no verdict; the version 1 beside version 2 report; each run records the rule version it used |
| `claude_batch_run` | #1584: Message Batches for several standards in one batch: batch ids and reservations stored, so a crash resumes the poll without paying again; failed requests re-queued once, then counted; an optional fallback cancels an overdue batch and, once it has ended, sends the rest at the normal price |
| `claude_batch_store` | #1584: the state a Message Batches run keeps in the database it writes: request rows, batches, every raw answer |
| `compile_budget` | #1584: what the standards compiler may still spend, read from the ledger; a hold nothing owns is released after the longest a batch can run |
| `compiled_rule_proof` | #1584: the proof of one compiled rule: its quote on the cited page, its limit and unit inside the quote, its comparator in the quote's words, a scope after the limit kept as its condition; pure functions |
| `compiled_rule_pages` | #1584: a standard's pages read into sentences, clause headings and chunks sized to the output room of the request; pure functions |
| `compiled_rule_context` | #1584: why a proven compiled rule may still not stand alone: a table row, scope in a heading, caption or next sentence; a flag an approval path can refuse on |
| `compiled_rule_field` | #1584: whether a compiled rule's field name belongs to its quote: strict with a figure, one word without |
| `compiled_rule_shape` | #1584: whether a compiled rule may store its figure: an allow-list of plain sentence shapes; anything else keeps the sentence and no limit |
| `compiled_rule_rescue` | #1584: the rules still readable in a paid answer that does not parse as a whole; says whether anything was lost |
| `compiled_rule_report` | #1584: a standard's page text as the app cites it, where each page's text came from, its table rows, and version 1 beside version 2 with how the version 2 run ended; reads only, counts only |
| `rulebook_v2` | #805 plan change 6, part A: the rulebook's version 2 tables on a database copy: stable rules, append-only versions, applicability and exceptions apart, provenance, a person's decisions, trigger-written events, a snapshot per compile, the snapshot a run used; off by default; no verdict reads them |
| `rulebook_v2_check` | #805 plan change 6, part A: one rule's requirement against one submitted value: meets, does not meet or cannot tell; pure; not mentioned is never compliant |
| `rulebook_v2_ingest` | #805 plan change 6, part A: a compile's verified rows become rows of the version 2 tables, each quote checked again and what fails counted by reason; counts for the version-1-beside-version-2 table |
| `rulebook_v2_schema` | #805 plan change 6, part A: the statements of the version 2 tables and their guards, and the words they allow |
| `field_naming` | Canonical field names for printed labels and numeric requirements (#193 plan B4, orders 5.2 and 5.3). Behind ` |
| `front_matter` | Front matter: passages that describe a document rather than answer from it |
| `geometry_reader` | Geometry reader: tables and forms read from PDF positions (#193 section 5.1) |
| `geometry_blank_cells` | An empty ruled cell beside a label is a blank only when the geometry proves it (order 228.9) |
| `geometry_index_cells` | A side-by-side numbered form is read as two lists; a lone index number is never an answer (order 228.9b) |
| `page_columns` | A header line of unit-bearing names over lines of numbers gives label/value rows; stacked label lines in a cell are never joined (#1478, off by default) |
| `glossary` | Engineering synonyms: the words people type -> the words documents print |
| `held_standards` | Marks and counts the standards a review held for the engineer (equipment type unsure), with the caller's boundary |
| `heavy_lock` | One lock for the heavy jobs on a machine (#680) |
| `highlight` | Locating a quoted answer on the rendered page |
| `hooks_check` | Say at boot when this checkout's git hooks are not switched on |
| `ingest` | Background ingestion worker |
| `worker_review` | Order 234: the worker's review-job drain; a running review is busy, and its progress counts as worker activity (no false "Queue not moving") |
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
| `local_engine_bar` | A review on the Claude lane never loads the local engine, and says what it skipped |
| `match_claude` | The matcher's question through the one Claude lane |
| `match_rules` | Rules that decide WHICH containment hit a requirement may be paired with |
| `closing_noun` | Reads the quantity a sentence names LAST ("... of its travel") so a label that runs from it into the subject can be paired (#913) |
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
| `pump_kit` | #1478 preparation: the pump kit's name, data file and public names over `kit_core`; box list and DRAFT pump cards from held standards, read only behind `pump_kit_draft_enabled` (off by default); never decide |
| `at_limit` | #1475 finding: compares a value with a worked-out limit (factor or percentage) with float noise removed, behind `at_limit_precision_enabled` (off by default); local only, no model or socket |
| `percent_kind` | #1512: a value printed under a % label with a fraction-sized number ("0.30 %") is not decided on a percent card, it goes to the engineer; behind `percent_kind_check_enabled` (off by default); local only, no model or socket |
| `kit_core` | The shared mechanism of an equipment kit (#1478, #1480): data file, loader hook, tests, the held-for-the-engineer rule for every kit row; local only |
| `vessel_kit` | #1480 preparation (parked kit, milestone 58): box list and DRAFT vessel cards from held standards (SAES-D-001), read only behind `vessel_kit_draft_enabled` (off by default); every row held, never decide |
| `exchanger_kit` | #1481 preparation (parked kit, milestone 58): box list and DRAFT heat exchanger cards from the held standard SAES-E-004, read only behind `exchanger_kit_draft_enabled` (off by default); every row held, never decide |
| `nothing_read` | #1495: a review that read no value and no page text ends failed "nothing read" (switch off by default) |
| `page_ledger` | The page ledger (master order B3): every page accounted for, with a reason |
| `page_not_read` | Why a page has no reading in plain words, and the CRS note that names it (#1473) |
| `pairing_head` | A field is a clause's field only when the label stands in the subject's head, not in a complement (audit C5) |
| `pdf_flow` | #633 item 6: PDF text that wraps and continues on the next page, never dropped (layout only) |
| `pageimage` | On-demand page rendering |
| `passages` | Small-to-big: search small, show big |
| `playbooks` | Review a written procedure against a playbook (#679, W5b-04) |
| `spec_kit` | #1479 (preparation): a DRAFT must-contain list per discipline (`reference/spec_kit/`) looked up in a specification's own pages, no model; found = engineer row with verified quote, not found = ONE note; numeric limits cross-checked with a datasheet of the same number or tag; never a verdict; off by default. Also routes a parked KIND (`reference/kind_kits/`, drawing from SAES-A-202, #1484) behind `parked_kits_draft_enabled` |
| `transmittal_kit` | #1482: a transmittal's header fields, listed documents (revision, sheets) against the held documents' covers and page counts, and a required-submissions list named at run time (client data, local DB only); no model; engineer rows only, never a verdict; behind `transmittal_kit_enabled` (off by default) |
| `procedure_text` | A procedure submittal's own page text answers its requirements: engineer row with a verified quote, or missing; never compliant (#1476) |
| `procedure_crs` | Order 4c: the CRS fields of a procedure or other non-datasheet kind: no equipment type, the page from the verified quote, the suggested document number; behind `procedure_crs_fields_enabled` |
| `procedure_playbook_rows` | #1522 (b): a procedure's CRS rows from the matching review playbooks, as engineer rows (never compliant, no model), behind `procedure_playbook_rows_enabled` |
| `progress` | What the machine is doing right now, recorded when it actually happens |
| `provenance` | Which code read which input: provenance for extracted rows (issue #177) |
| `quality` | Content-quality gate |
| `unsupported_script` | A page written mostly in Arabic script is not searched and says so: "language not supported, engineer review" (#564) |
| `rates` | Throughput reporting |
| `reader_api` | Layer 1 for STANDARDS: the model READS one sentence, Python VERIFIES it |
| `reading_state` | What "ready" means: every page and picture read or listed as not read, from the ledger; one function for every kind of file (ONE_CHECKED_DEFINITION_ENABLED) |
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
| `held_findings` | A requirement the review held (service not stated, scope unsure) also becomes an engineer-review finding with its reason (order 210) |
| `held_reasons` | Order 161 C (163.4): a reason for EVERY finding held for the engineer (stored code, else the program's own leading code, else whether a datasheet field was paired), counted in the run summary; display and measurement only, no rationale, code or verdict changes |
| `paragraph_ids` | Order 161 C: the paragraph a CRS row cites, read from the standard's own numbering (the shape most of its headings share, plus the sub-paragraph in force) when its stored clause is a table number or missing; display only, never guessed, the stored clause is left as it was |
| `review` | Persistent workflow records for AI-assisted engineering reviews |
| `finding_query` | The one scope filter of the review-findings list and its count, so a page and its total agree (order 117 item 5) |
| `paging` | The fields every paged list response carries: `total` (the page's denominator), `limit`, `offset`; a bare-list route's page with its total in `X-Total-Count` (order 117 item 5) |
| `review_jobs` | P3: a review runs as a background job on the B11 queue, not inside the request |
| `review_progress` | #1494: the progress block of a running review (pages, elapsed, stall) from the jobs row; read-only, behind a switch |
| `review_recovery` | Put back, or cancel, the review jobs a dead process left running; at startup every claim of another process (order 231) |
| `review_audit` | One local AUDIT.md + AUDIT.json per finished review (pages, standards, rules, AI use, gates, CRS), behind REVIEW_AUDIT_REPORT_ENABLED (#1525) |
| `deferred_pass` | Step 6 - a Pass on a 'By Contractor'/TBA value (owner D2 = Query), one test for the bench and the audit |
| `review_trace` | Show what each step of a finished review produced (REVIEW_DEBUG console and per-run log, #791) |
| `risks` | Typed EPC risk register, kept separate from evidence-backed findings |
| `row_noise` | Page furniture and fragments that are not fields (#193 plan B4, item 3) |
| `page_reason_words` | Plain words for why a datasheet page gave no value (the stored page reason); the engine counts kept apart as detail (order 124 item 9) |
| `rule_trust` | Decide when an AI-compiled rule may be used: tier, family proof, second check, audit sample, trust labels |
| `rule_eval` | Table and formula rules, evaluated in code (owner order 2026-09-26, 2a + 2b) |
| `schemas` | Typed response models |
| `scope_ledger` | Every requirement in a review's scope ends in exactly ONE state, with a reason (#677) |
| `scope_quote` | A division's scope reading counts only when its quote is one real sentence (order 242.2) |
| `scores` | Scores that know which scale they are on |
| `search` | Hybrid retrieval: FTS5 + dense vectors, fused with RRF, then reranked |
| `clause_support` | Orders 180: a sentence that states no requirement is never a supporting clause; one naming a service the sheet does not state is held |
| `equipment_subtype` | Orders 180.1 item 5: a standard that governs one pump, compressor or exchanger type is required only when the sheet states that type; unstated is asked of the engineer, never "missing" |
| `standard_judgment` | Orders 180.1 item 6: a cited standard the run judged not applicable to the equipment is held for the engineer in the review run (not selected, so not compared or listed as support there) |
| `sentence_guard` | Where a sentence does NOT end |
| `service_scope` | Service-condition scope (#638, #677): a requirement that applies only in a service the submittal says it is NO |
| `sheet_page` | #967 item 5: the Sheet's datasheet page with every card's value underlined on it by the server (one router route; ids and states only in the URL) |
| `standard_clause_page` | The standard and page of the clause a checklist item cites, from the run's applicable standards; not located is said, never guessed (order 225) |
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
| `submittal_fill` | Order 206.1: a contractor datasheet's empty title and equipment type filled from its own heading (the line that says DATA SHEET), at READY and again when its review starts |
| `subject_scope` | What a requirement is ABOUT, and whether it applies to this submittal (#453) |
| `submittal_review` | Schema and scoped read paths for the AI submittal review workflow |
| `symbols` | Repair glyphs an old PDF's symbol font extracted as the wrong character |
| `synthesis` | Stage 3 and stage 4: the consolidated summary, and the advisory recommendation |
| `time_units` | The time rows of the one unit table: hours, minutes, seconds, milliseconds, days (#896) |
| `rate_units` | The flow-rate rows of the one unit table: kg/s, t/h, l/min, m3/s and their kin, exact factors only (#1290) |
| `read_elsewhere` | A checklist row MISSING for one equipment tag, while the field was read for another tag, becomes an engineer check that says where the value was read, never "not read" (order 307.1) |
| `table_gate` | Which requirements a review may check (#598) |
| `tables` | Structured rows and columns for chunks already identified as tables |
| `table_consistency` | #531: a numeric table checked against itself (overlapping or gapped bands, a Total that is not the sum, a column that is not its own declared formula); findings are cited questions for the engineer, never "consistent" |
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
| `word_flow` | #1473: a Word file read as `docx_reader` pages for the datasheet fact reader (PAGE_READ_BY_READING_ENABLED) |
| `word_pages` | What a reviewer is told about a Word file's pages, tables and pictures: real page, partial, or the section heading (WORD_PAGE_MARKERS_ENABLED) |
| `word_pictures` | A Word file's pictures read by the local OCR engine, stored per file; no Claude lane, no reader model (WORD_PAGE_MARKERS_ENABLED) |

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
| `rule_equipment_scope` | Which equipment type a stored rule is written for, read from its own clause wording or heading chain with quote, page and method; unknown stays unknown |
