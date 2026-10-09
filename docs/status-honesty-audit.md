# Status honesty audit

Every status, count and boolean the API exposes, what it is computed from, and
what it must never be taken to mean.

**Current review-baseline rule.** Engineering gap analysis may select a
baseline only through an active, configured type/discipline mapping and a
caller-scoped searchable document. A manual baseline overrides the mapping;
absence of a match remains “no baseline,” not evidence that a document is
authoritative. This is implemented in `app.review.resolve_baseline` and is
covered by `test_review_baselines.py`.

**Comparison intent.** `AnalysisRequest.comparison_type` accepts only the four
named engineering workflows and gap analysis echoes the selected value;
arbitrary labels are rejected rather than presented as governed workflows.

**Scheduled summaries.** A summary is “scheduled” only when the opt-in
configuration matches the current UTC window and a durable idempotency key is
reserved; `run_scheduled_summary` returns false when disabled, outside the
window, already sent, or unable to send with SMTP disabled.

**Why this document exists.** Twenty-nine separate times something in this
system has claimed what was not so - a status field, a count, a measurement,
twice a design document about the code it was written against, once a type that
could not describe its own API, once an evaluation harness measuring a different
layer than the one it was cited for, once the secret-scanning hook that the
privacy ADR depends on, and once the product's headline promise itself:

| # | The claim | The reality |
|---|---|---|
| 1 | `jobs.state = 'running'` written at upload, from step 1 | No worker existed. Nothing was running. |
| 2 | "11/11 terminal" reported to the client | Measured during a run corrupted by a second concurrent writer |
| 3 | `stalled: false` with six documents waiting | Computed from heartbeat freshness, which only proves the loop is spinning |
| 4 | `failed` on a fully embedded document | The chunk short-circuit did not advance the state, so a guard tripped |
| 5 | `ready` with nothing searchable | A document whose every chunk was excluded still reported ready |
| 11 | "50 call sites updated" and "no such string in the frontend" | Both counts were complete WITHIN a boundary the sweep chose for itself and never stated. Five more call sites were in `eval/`; the string was in the backend |
| 10 | Three green tests over code that was broken | Each had fixtures that could not produce the condition the test claimed to check. A vacuous test does not fail; it passes, which is worse |
| 9 | README: "Disk — ~2 GB" | 768 MB inside the clone, measured. Nobody had ever measured it; the figure was written from intuition and read as a specification |
| 8 | OCR raised coverage by **+12.5%** on NORSOK | It raised it by **+4.2%**. The "before" figure dropped every recognised CHUNK, which also drops pages that chunk merely spans — three pages were charged to OCR that OCR never read |
| 14 | `--tier generated`, documented at the top of the eval harness | The scorer could not read a generated answer: every field read `answer_passages`, which only the extract branch sets. Tier 2 rows scored zero passages and no pages, so the harness under-reported its own citation figure |
| 13 | The coverage design's six-value status enum, reviewed and approved | **None of the six was true of Q4**, the gold question the feature exists to measure. Reviewing a taxonomy against an example is not testing it against that example |
| 12 | The coverage design: the shortlist cut is "the one place candidates are dropped with no recorded reason" | `deduplicate()` and the pool builder drop silently too. A candidate lost to dedup is indistinguishable from one that never existed, so recording only the cut would have answered "was doc17 ever in the pool?" wrongly, with apparent evidence |
| 7 | A passing ordering test over a document that had `failed` | The test asserted the statuses it OBSERVED at every OCR invocation and never asserted where the document FINISHED. `partially_searchable -> chunking` was an illegal transition; the raise was swallowed by the broad handler in `process()`; every scanned document on a fresh machine landed at `failed`, green suite and all |
| 6 | "Quoted verbatim from the document" over OCR text | `AnswerCard.tsx:277` rendered the label unconditionally. 92 recognised chunks were retrievable, so a passage OCR had guessed off a page image could be cited as the document's own words, beside "quoted directly, no AI rewriting" |
| 15 | `current_document` and `last_error` were moved OFF `/api/health` "to the scoped `/api/metrics`" | **`/api/metrics` was not scoped.** It resolved an `AccessScope` via `Depends` and never passed it on. The fields moved from one unscoped route to another, and a comment recording a false reason is what made the move look like hardening |
| 16 | README: `npm run test` — **"279 tests"** | **496**, across 42 files. Understated by 217. Nobody re-measured it after the redesign and the auth work added whole test files |
| 17 | README: `python -m pytest -q` — **"887 tests, ~5 minutes"** | **1,174 passed / 3 skipped / 17 xfailed / 1 deselected** in **4m57s**, measured by CI at cd72bac. A local run of an earlier tree (5baf18e, four tests fewer) gave 1,170 in 5m44s with `--ignore` for the two parked test files. The count was understated by 287. The DURATION claim is retracted rather than replaced: three CI runs of the identical suite took 3m18s, 4m57s and 10m48s, and locally 5m44s idle against over 11 minutes contended. "~5 minutes" was not so much wrong as unsupportable - the spread is 3x on identical work, so the README now gives a range and says to check the count, not the clock. Both original figures were written once and never re-run |
| 18 | README stack table: the answer model runs at **`num_ctx`~1536** and **60-100 output tokens** | `backend/app/config.py` sets `num_ctx = 4096` and `max_output_tokens = 250`. The 1,536 figure is real but historical - it survives in `context_budget.py` as the value a past measurement was taken at, and the README kept quoting it as current configuration |
| 19 | README scope cuts: **"System view — four views"** | **Six** built views plus an Administration section, per `Shell.tsx`. Analysis and Reports were built after the line was written; a scope cut that stopped being a cut still read as one |
| 20 | README title and setup steps named **Nabaa**, and `git clone <repo-url> nabaa` | The product is the RAG Intelligence System. The `cd nabaa` was worse than a stale name: a reader following the README landed in a directory that the next command did not expect |
| 21 | `contracts/types.ts`: `Metrics.system?: SystemMetrics` | The type could not express the response the server sends. `/api/metrics` serialises `"system": null` for a non-admin, so every consumer typed against this contract was typed against a shape the backend never produces |
| 22 | `eval/score_analysis_gold.py`, run to confirm the analysis accuracy fixes | **It cannot confirm them.** It imports `app.keyword` and calls `search()` directly, so it measures the RAW retrieval layer, before the analysis-layer scoping, per-document cap and percentage recall. Its output still shows doc16 taking 18 of 24 slots and hiding its own p.18 answer - the defect a288653 fixed - because that layer really does still do that. A green run of it would have said nothing about the fix. `eval/verify_analysis_accuracy.py` was added to measure the layer that was actually changed |
| 23 | `test_recommendation_gate.py`: **"all 27 are expected to fail"** | **Eleven now pass.** The advisory-gate half of #90 was implemented; the docstring still described the whole module as unimplemented specification. `strict=True` is what caught it - the eleven went red on completion exactly as designed - but the prose had to be corrected by hand |
| 24 | `.githooks/pre-commit`, the compensating control ADR-0004 rests on | It failed OPEN two ways: a missing gitleaks printed a WARNING and exited 0, and before that an unguarded `$LOCALAPPDATA` under `set -u` aborted the hook entirely on any machine not exporting it. A control whose absence is invisible is not a control |
| 25 | README:14 and ADR-0002's Enforcement section: **"Client document content never leaves this machine"** | **The one rule had no enforcement point on the answer path's own socket.** `ollama_url` was an ordinary `.env` string (`config.py:106`) with a loopback DEFAULT and no validation, and four call sites - `answer.py:404`, `analysis.py:667`, `metrics.py:271,279` - each formatted their own URL from it and POSTed. The body carries `_build_prompt` / `synthesis.build_prompt` output, which is retrieved passage text verbatim, so `OLLAMA_URL=http://collector.example.net:11434` in `backend/.env` sent client document content to that host with no allowlist, no flag, no audit row and no log line. The four Enforcement controls do not touch it: the binding rule is INBOUND and the offline flags govern HuggingFace. Nothing had leaked - Ollama is on localhost in every deployment - but the promise rested on a default rather than a rule, and the socket-containment test could not see it: `test_market_no_document_leak.py:57` iterates a hand-written tuple of three market filenames, so the largest outbound lane in the system sat outside every guard. Now: `config.check_model_url` parses with `urllib` (never string splits - `market_providers._host_of`'s `?@` bypass is a test case), refuses a non-loopback host, embedded credentials and anything that is not a base URL, and runs TWICE - at startup, so a misconfigured machine does not boot, and again in `model_transport` immediately before every request, because `settings` can be reassigned after startup. A non-loopback host needs two explicit settings and writes an audit row. `test_socket_containment.py` asserts all of it over the WHOLE `app/` package by globbing, so the next module that opens a socket is red without anyone remembering to list it |
| 26 | `test_admin.py:554` `test_the_admin_capability_is_not_a_discipline`, and the `is_admin` shown on the admin screen | **The test never touched the column whose name it cites, and the gate it was supposed to guard read the wrong column.** `temp_storage` runs `db.init_db()` before `world` inserts its roles, so `init_db`'s corrective `UPDATE roles SET kind = 'capability' WHERE name = 'admin'` never saw them and the fixture's `admin` role carried the column default `'discipline'`. Every assertion in that test - and every one of the 44 others in the file, including `test_an_admin_reaches_every_route` - was satisfied by the NAME predicate alone, over a database in which admin was not a capability. Dropping `roles.kind` from the schema entirely would have left them all green. Meanwhile `admin.is_admin` really did read `roles.name`, so a row named `admin` with `kind = 'discipline'` was a full administrator to all seven `/api/admin/*` routes and an ordinary engineer to `AccessScope.is_admin` for the same request, and `list_users` reported `is_admin: true` for them. `main.py:185-192` had already NAMED this divergence as a hazard and closed it for `/api/metrics` only. Now: `is_admin`, `create_user`'s lookup and the listing all use `kind = 'capability' AND name = ?`; `make_role` takes a kind and writes it; and a new parametrised test walks the whole `ROUTES` table with every resource present, so a 404 can only come from the gate |
| 27 | `admin.py:442`, the self-deactivation guard: **"Without this the last admin can lock every user, including themselves, out of a system whose only other door is a terminal."** | **The guard did not hold under the shipped default, and the comment describes the outcome it permitted.** It read `if actor is not None and user_id == actor.get("id")` - keyed on WHO IS ASKING. Under `AUTH_MODE=disabled` (the default at `config.py:51`, asserted by `test_access_routes.py:311`) `current_admin` returns `None` for a caller presenting no identity, by design, so `DELETE /api/admin/users/<id>` with no Authorization header at all reached `deactivate_user` with `actor = None` and the `actor is not None` prefix skipped the refusal completely. Every account holding the admin capability could be deactivated by an unauthenticated local caller; switching to `demo_required` afterwards - the documented hardening step - then left `/api/admin/*` unreachable by anyone, with `seed_access.py` at a terminal as the only door. The same anonymous path also reached `POST /api/admin/users` and both grant routes, so document access could be widened or removed permanently, under a mode whose stated concession (`admin.py:206-213`) is argued only for READS. No test in `test_admin.py` could see any of it: `temp_storage` pins `demo_required`, under which the anonymous caller is 404'd before reaching the guard. Now: `_is_last_active_admin` asks whether an active administrator would REMAIN - a property of the corpus that mentions no caller and so cannot be skipped by having no identity - and the self-check is kept beside it |
| 28 | `watch_api.py:28`, the module docstring: **"Everything else in the payload is: whether the feature is on, how often it looks, when it last looked, and what it decided"** - and `recent_events`' own docstring, concluding that withholding `source_path` closed the leak | **"What it decided" was ten real client filenames, sent unscoped to every caller.** The route resolved an `AccessScope` and spent it on ONE field, `folder_name`; `recent_events()` took no scope and its query had no predicate. A caller with zero grants received the last ten watched-folder decisions in the same second `GET /api/documents` correctly returned `[]` for them - and `duplicate` additionally asserts that a document with that content is already in the corpus. Measured during the fix: the leaked `detail` string also carried the grant list (`granted to Mechanical, admin`). The docstring inspected the host PATH and pronounced the leak closed while the filename beside it was the leak - the same fixed-in-one-of-its-two-homes shape the review names as this codebase's dominant pattern. `test_watch_folder.py:549` and `:568` asserted the filenames were PRESENT; nothing asserted they were withheld. Now: `recent_events` takes the scope and filters on `document_id`, `WHERE 1 = 0` for an empty scope and no predicate for `unrestricted`, and rows whose `document_id` is NULL sit behind the capability gate |
| 29 | `coverage.py:26-33`: **"The gate runs exactly once, before any per-document reasoning, on the scope the request already had, and its verdict is final."** | **There was no scope.** `keyword.term_occurrences` and `keyword.indexed_count` took no `allowed_document_ids` parameter at all and counted over the whole `chunks_fts` table, so the lexical gate's verdict - and the user-visible refusal "none of the terms in this question appear in the indexed documents" - was decided partly by documents the caller has no grant on. A term present only in an unreadable document made the answer "it exists, just not for you" without saying so; a term absent everywhere made a claim about documents the caller cannot see. Either way a caller could test for a term's presence in the whole corpus, which is the disclosure `/api/health` was stripped for. The comment was precise about a property the code did not have - it named the right rule and then asserted compliance with it. The same unscoped counts also fed `acronyms.harvest`, so an unreadable document could supply the expansion that decided a caller's verdict, and the expansions are phrases lifted from that document's text. Now: both take `allowed_document_ids`, keyword-only with no default, and it is threaded through `lexical.assess`, `distinctive_terms`, `distinguishing_uncovered_terms`, `acronyms.harvest`/`equivalents`/`known_expansions`/`reverse_map` and `coverage`. An empty scope counts 0, which makes the gate ABSTAIN rather than claim absence |

| 30 | `/api/metrics` host/worker fields were gated with `scope.unrestricted`, which is intentionally true for anonymous document reads when `AUTH_MODE=disabled` | The route now separates corpus-wide aggregate counts from host telemetry. CPU/RAM/disk/model/worker identity is admitted only for the explicit `admin` capability; the default unrestricted read scope no longer fingerprints the machine. The regression test toggles the shipped default and asserts the host block is withheld. |
| 31 | `market_providers.check_host()` derived the authority by splitting strings, so a `?@` URL could pass the allowlist while targeting another host | Host validation now uses `urllib.parse.urlsplit`, rejects embedded credentials and non-HTTP(S) URLs, and compares the parsed hostname. A regression test reproduces the old bypass URL and requires refusal. |
| 32 | Deliverable reminders and escalation rules were computed and persisted, but the UI/API gave no indication that anyone had been notified | SMTP is now an explicit, fail-closed configuration. Overdue reminder creation and escalation-level changes send a configured email once per unique event; an operator-triggered daily summary uses the same path. Every successful (and failed) attempt records `audit_events.action = 'notification.email'`; disabled SMTP remains a no-op. `test_notifications.py` covers all three triggers, duplicate suppression, disabled mode, and incomplete configuration. |
| 33 | A deliverable exposed only one `owner_user_id`, so reviewer, approver and informed stakeholders could not be assigned or used for routing | `deliverable_stakeholders` now supports the four typed roles, migrates the legacy owner into `owner`, and exposes read/replace endpoints plus the Deliverables UI. Reminder routing resolves the configured escalation role to the matching stakeholder email when SMTP is enabled. `test_stakeholder_roles_migrate_owner_and_route_assignments` proves legacy preservation and replacement. |
| 34 | `wbs_code` was a sortable label only; selecting a WBS item could not show its child deliverables alongside linked review and escalation context | `deliverables.parent_id` now stores a validated hierarchy (with cycle protection). `/api/deliverables/{id}/workspace` and the Deliverables screen expose direct children, linked documents, review findings and escalation signals together. `test_wbs_parent_child_workspace_and_cycle_guard` proves the hierarchy and rejects cycles. |

| 35 | The model-matching design, §11: a `METHOD_MODEL_CHOICE` finding **"gets confidence 0.5 and label medium"**, listed as one of the thirteen tests that must exist | **The second half of that claim cannot be observed, and the first half is not stored.** `review_findings.confidence` holds the LABEL, not the number, and `_confidence_label` has two bands with "high" forbidden by rule 4 - so `CONFIDENCE_MODEL_ASSISTED` (0.5) and `CONFIDENCE_DETERMINISTIC` (0.9) both print `medium`. A mutation that gave a model-paired finding the deterministic confidence was written (M149) and **no test could detect it**, because nothing a reader or an assertion can see changes. The branch is kept - a guessed pairing must not claim 0.9 if the bands ever change - but it is not what distinguishes a model pairing on screen. `match_method` and the "Paired by model; engineer must confirm" rationale prefix are, and those are M147 and M150. M149 was withdrawn with the reason recorded beside it in `scripts/mutation_check.py` rather than kept green by an assertion that proves nothing. |

| 36 | The model tier of the requirement matcher, built and shipped ON, with the design's own gate ("zero false pairings on the known negatives") treated as a formality | **It failed the gate on its first run: six of the seven pairings it proposed were false friends, and three of those reported NON_COMPLIANT against the contractor.** A weld-cleaning distance of 25 mm paired with a corrosion allowance of 0 mm; an interpass temperature with a service temperature; a seawater cooling-water outlet with a vessel external design temperature. Every one cited correctly on both sides - 14 of 14 citations resolved on the PDFs - which is what makes a wrong pairing dangerous rather than obviously broken. The pattern behind all six: the pre-filter offers only same-dimension candidates, so on a temperature clause every candidate is a temperature and the model pairs on the WORD. **`match_enabled` now ships False** and the startup line says the tier is off. The gate is the thing that worked: it was written before the tier, it was run on the first opportunity, and it stopped the tier at the door. One genuine pairing was found that containment structurally cannot reach (a field name longer than the requirement subject), so the recall the tier was built for is real - the pairing is not. |
| 37 | The extractor's `numeric_limit`, applied to any sentence containing a comparator and a number | **Two shapes parse as a limit and are not one, and both produced a confident verdict.** SAES-D-001 9.2.5 - "temperatures greater than 260°C shall be in accordance with PIP VEFV1100" - is an APPLICABILITY TRIGGER: the 260 is the threshold at which another document takes over, and the engine reported NON_COMPLIANT because a submitted 60 °C is not greater than 260. SAES-D-001 14.3 - "at least 28°C warmer than the calculated dew point" - is a RELATIVE LIMIT: the 28 is a margin, the dew point is nowhere in the submittal, and the engine reported COMPLIANT because 95 >= 28. Both were stored as limits long before the model tier existed and containment could have paired either on another sheet; the tier is only what made them visible. Now `applicability_trigger` is never matched and `relative_limit` is matched but never compared, with the sentence quoted. Reclassified across the corpus: 1 and 2 respectively, each verified by hand. |
| 38 | `submittal_facts.field_name`, taken as what the datasheet calls a field | **One field was called `material 2`, which is the tail of "Design corrosion allowance for removable internal parts (material 2)".** The text-block path reads each line of a cell as its own cell and pairs strictly left to right, so a cross-reference column (`Figure 1`) took the label position, the real label became its value, and the orphaned bracket became a field name of its own once `normalise_field_name` dropped the brackets. That field is what the model tier paired with a weld-cleaning distance. Two generic causes fixed - a bracket-only cell continues the cell before it, and a cross-reference or dotted clause number introduces the pair that follows it, as a bare line number already did. Facts went 42 → 48, with all four vessel weights, all four corrosion allowances and the normal operating pressure and temperature recovered. **Separately, and not caused by this fix:** 10 of the original 42 facts were an index of standard drawings read as a form, with document designations (`VEFV1101M`) stored as UNITS. They were already dead - an earlier task's identifier rule rejects them - and had survived only because nothing had re-extracted the sheet since. A stored fact is only as current as the last extraction that wrote it. |
| 39 | Two mutations written for this work could not be detected, and neither means the test is vacuous | **M149**: a model-paired finding's confidence flipped from 0.5 to 0.9 and nothing could see it, because a finding stores the LABEL and `_confidence_label` has two bands - both print `medium`. **M172**: the clause-reference rule relaxed from two dots to one, and nothing could see it, because `is_field_label` already refuses a bare number at the label position, so skipping the cell and rejecting the pair emit the same nothing. Both branches are kept - each should be TRUE and not merely harmless - and both mutations were withdrawn with the reason recorded beside them in `scripts/mutation_check.py` rather than kept green by an assertion that proves nothing. **M197**: the `duplicate column` message test in `db.add_column_if_missing` removed, so every `OperationalError` is swallowed - invisible, because the column check that follows re-raises any error that left the column missing, which is every unrelated one. Kept because it states which failure is expected and keeps the swallow narrow. **The rule: when a mutation cannot be detected, the first question is whether the OUTPUT can distinguish the two versions at all.** If it cannot, the test is not vacuous and the mutation is not evidence of anything. |

| 40 | `submittal_review.ensure_schema` migrates by `if column not in existing: ALTER TABLE`, and every read path calls it | **That is a race, and it fires.** Two threads both read `PRAGMA table_info`, both see the column missing, and both issue the ALTER; the second dies with `sqlite3.OperationalError: duplicate column name: raw_value` at `submittal_review.py:205`. Found while adding two columns for ranges, and measured rather than assumed: `tests/test_access_routes.py` run as a file passed **7 of 10** with the new columns and **7 of 10** without them, so the defect is PRE-EXISTING and the two extra ALTERs do not measurably widen it. An earlier 5-of-5 against 4-of-5 looked like amplification and was noise - the same uncontrolled-observation trap entry 2 records, caught this time by running ten instead of five. The full suite passes when the race does not fire (2,190 passed) and reports one failure when it does; a green run is therefore not evidence that the race is gone. **FIXED, and the neighbour it explains is closed with it.** `db.add_column_if_missing` performs the ALTER, catches only `duplicate column`, and re-reads the column before accepting that failure as benign - so the thread that arrives second gets an answer instead of an exception, and a swallowed ALTER that did not happen still raises. Applied to every migration reachable from a request: `review`, `submittal_review` and `deliverables` (the last is called by `review.traceability`). `db.init_db` keeps the old shape and is left alone deliberately: it runs at startup and from the ingestion worker, which `main.lifespan` starts AFTER it, so no two callers reach it together - stated here so the exception is a decision rather than an oversight. **`test_two_concurrent_requests_never_share_scope` was the unexplained intermittent of three sightings, and it was this: `GET /api/documents` calls `review_status_for`, which calls `submittal_review.ensure_schema`, from two threads on a fresh database.** Measured after the fix: 20 of 20 clean runs of the whole file, against 7 of 10 before. |
| 41 | Phase 6 reported the engineer's final code as "live-verified" against the running backend | **It was verified as an admin, and shipped unusable for everyone else.** The route carried `Depends(admin.current_admin)` for the audit actor alone, and that dependency is a gate: it raises the admin surface's deliberately silent 404 for any non-admin. So the only caller who could record a code was an admin, and every engineer got "not found" about a run the same screen had just listed. Nine unit tests were green because they called the function, never the route (see "the verification that verified nothing", row 8). **FIXED:** `_actor_from_scope` resolves the name without deciding anything about permission - the route's own scope had already done that - and three route-level tests now sign in as a real non-admin with a real token and press the button. Mutation M221 puts the gate back and is DETECTED. |
| 42 | "`reviews.dashboard()` had no ShapeCheck" was recorded as a fixed defect in phase 6 | **The same defect was written again in phase 8, by the same author, one phase later.** `DatabaseSection` did `setTables(r.data.tables)` on any `ok` response; a body without a `tables` array put `undefined` into state, `.map` threw during render, and the WHOLE Administration page went blank over one section. `ok` means the request succeeded, NOT that the body is the shape the screen expects - and knowing that in phase 6 did not prevent it in phase 8, because the fix had been applied to one call site rather than turned into a habit. Caught by `App.admin.test.tsx` going from green to a completely empty `<body>`; the section's own tests all passed, because they mocked well-shaped responses. **FIXED** at the three edges where a body enters state, with an unusable body rendering as a FAILURE rather than as "no tables" - the second would be a claim about the database. **The rule: a `Result.ok` is a fact about the transport. Every place a response body becomes component state is a boundary, and every one of them needs the check - not just the one where it last went wrong.** |
| 43 | Phase 8's discipline overlay was reported applied, tested and mutation-proven (5/5) | **The path every document ingest takes was broken, and M1 had been silently inert for three phases.** Two defects, one root: each check looked only at the new thing. (1) Adding `discipline_canonical` to the suggestion `INSERT` gave it nine columns and eight VALUES - `8 values for 9 columns` - so every new document would have failed to classify. Fourteen tests were green over it because every one inserted its rows with SQL and none went through `classification.write_suggestion`; the same shape of miss as standing rule 15, one layer down. The column also existed only after an optional startup step, so the write path depended on a migration it never called, and 29 unrelated test setups failed on it. (2) Phase 7's step 0a replaced `"SELECT * FROM review_runs"` with a join, and M1 - the scope filter on `list_review_runs`, a PERMISSION mutation - anchored on the old line. The harness reported it as a harness error rather than a pass, which is the three-bucket verdict working; but only the new mutations were run after that change, never the whole harness, so nobody saw it for three phases. Both caught by the ONE full-suite pass at the end of the session. **FIXED:** the column is in `db.py`'s own table definition and migration; the INSERT has nine values; M1 is re-anchored and DETECTED; three tests now go through the real write paths, and one builds an old-shape database so the migration is actually exercised (entry 6's lesson). **The rule: after changing a line, run the WHOLE harness, not the mutations you just wrote - an existing mutation may have been standing on it. And a test that inserts its fixture with SQL cannot see a defect in the code that normally does the inserting.** |
| 44 | Phase 7 reported the CRS export "verified by opening the file": 15 gap rows, "one per cited-and-missing standard". Phase 6's Dashboard showed "21 of 21 cited standards are not in the library" | **Six of the fifteen gap rows were false, and the tile was false since phase 6.** Both computed "is this cited standard missing?" as `normalise_identifier(name) not in _match_referenced(...)` - but `_match_referenced` is keyed by DOCUMENT ID (`doc_a3df...`), not by identifier (`SAESL132`). An identifier never equals a document id, so EVERY cited standard was reported missing, always. The CRS therefore told a contractor that SAES-A-133, SAES-A-206, SAES-L-109, SAES-L-132, SAES-W-010 and SAES-W-016 were unavailable to the review while all six sat in the library. "Verified by opening the file" was true and insufficient: the rows were checked for PRESENCE and SPELLING - that is how `32SAMSS004` was caught - and never for TRUTH. No test had ever cited a standard that IS in the library, so the "not missing" direction was never exercised; every gap-row test used an empty library, where "missing" is always right. Phase 7 also copied the dashboard's inline check into the CRS helper, so one wrong rule became two. **Found by fact-checking the phase 10 demo script against the database**: it named SAES-L-132 as a PDF to keep handy, and the CRS called SAES-L-132 missing. **FIXED:** one home, `applicability.missing_references`, asked PER NAME of the same matcher selection uses. Verified on the live drum run: 9 gap rows, all genuinely missing; the tile reads 15 of 21. Mutations M248-M249 put the defect back and are DETECTED by a CRS test and a dashboard test that each cite one held and one missing standard. **The rule: a test that only ever exercises one answer to a yes/no question cannot see a check that always returns that answer. And a row in a document someone else will read is verified when its CLAIM is checked, not when it is found to exist.** |
| 45 | CLAUDE.md rule 4 lists "every count states its boundary" among the honesty invariants "enforced in code" | **For a generated answer it was enforced nowhere.** Asked how many standards there are, Document Q&A answered "there are 12 distinct standards" - from three retrieved passages, of a library holding 272. Two faults. (1) THE QUESTION WENT TO THE WRONG PLACE: a check existed for library questions, but it only knew the words "documents" and "files", so "standards" - the word this corpus is made of - fell through to retrieval, and the model reported what three passages showed as the size of the library. That check also pinned "There are 1 uploaded document" in its own test. (2) NOTHING CHECKED THE OUTPUT: the model can ignore a prompt, and no code looked at a generated count at all. **FIXED:** questions about the library go to a scoped COUNT (`corpus.py`) - on the live corpus, "272 company standards are loaded and readable by you", 0 passages searched; a question about both gets both in separate fields; and every count of DOCUMENTS in generated prose that does not say "retrieved" is bounded in place to the passages retrieved. **AND THE FIRST GUARD WAS ITSELF INCOMPLETE,** found only by running the real model: it wrote "**five** distinct standards", and a pattern tested on plain synthetic text let the Markdown bold hide the count. Mutation M263 restores that gap and is DETECTED by a test using the model's verbatim output. **The rule: a guard on model output is verified against the model's output, not against sentences written to look like it.** |
| 46 | Pipeline-repair task, commit `10a9812` and its own record in `CURRENT_STATE_AND_BLOCKERS.md` §15.1/§15.9 and GitHub issue #175: **"M-03: 0 -> 13 real facts. The actual regression is fixed"**, with I-06 and the pressure-vessel regression document's counts (55->268, 48->128) reported as evidence the same fix helped there too | **Reproducible, but overstated - the raw count was never checked for composition, and "fixed in the code" was conflated with "fixed in production."** An independent audit (a fresh Claude Code session, deliberately routed there for a second opinion rather than self-graded) re-ran the extraction against a disposable DB copy and reproduced 13/268/128 exactly - the number is real. But reading the actual rows: M-03's 13 "facts" are 9 blank template placeholders (correctly flagged `is_blank=1`, not fabricated, but not usable evidence either), of the remaining 4 two are an exact duplicate of the same datum ("300" under two near-identical labels), and one is badly garbled - a run of page-footer digits as the field label, several unrelated sentences spliced into the value. Honest count of clean, single-valued, correctly-labelled M-03 facts: **about 2, not 13.** I-06 fares differently but no better: 153 of 268 (57%) are exact duplicate `(field_name, field_value)` pairs, and 49 of 268 have a bare digit as `field_name` ("11") where the real label ("Viscosity at relieving temper.") was dropped by a dual-column table misalignment - confirmed against the raw PDF text. The pressure-vessel regression document has zero duplicates and zero digit-only labels, but 8 of 10 spot-checked facts have `field_label` polluted with a repeating page-header string (the client's own company-name banner) instead of the real row description - the values are correct and page-traceable, the labels are not. **Separately:** the 13/268/128 state was never written to the live database - it exists only as the stdout of a one-off validation script (`.cowork/part175-validation-report.py`) run against a disposable copy, exactly as the script's own safety constraints required, but nobody stated in the commit, the issue, or the final report that the live system still shows the pre-fix counts (0/55/48) until someone actually re-ingests. Both of these were within reach at the time: the fact-count/quote-verbatim spot-check that WAS done (Part 175's "14/15 verbatim-confirmed") checked whether a quoted string appeared on the cited page, never whether the extracted rows were duplicate-free, non-blank-majority, or correctly labelled - a different, narrower question than "is this a good fact." No post-fix score against the project's own gold set (`gold/M03-FIELDS.csv`, which scored the pre-fix extractor at F1 0.0000) was ever run to check whether accuracy, not just count, improved. **Not retracted: the underlying fix is real** - `pairs_from_table_shape` genuinely changed extraction behaviour, is mutation-proven, and the citation/page/quote fields are 100% populated and spot-check clean. **Retracted: the framing.** "0 -> 13 facts, the regression is fixed" implied a clean improvement large enough to matter; the honest statement is "0 -> ~2 clean, usable facts, plus 9 correctly-flagged blanks and 2 defects the count doesn't disclose," and the live system has not yet received any of it. |
| 47 | Issue #179 first pass, commit `3118037`: the numbered-row fix ("rows whose first cell is a bare line number go to `split_label_value`") left the valve sheet with "15 exact duplicates, identical values on different pages", and its code comment said `split_label_value` "already handles exactly this" | **The duplicate count was accurate and its verdict right, but the count measured the wrong thing, and the fix discarded data.** Checked pair by pair against the PDF (second pass, disposable DB copy): all 15 are the same value printed for a DIFFERENT valve tag on another page - legitimate, kept. The real duplicates were invisible to an exact `(field_name, field_value)` count: 8 facts were ONE printed cell read twice on the same page, once per reader, differing only in inner whitespace or cut at a line wrap. And compacting a numbered row before `split_label_value` threw away the column geometry, so `15 \| Over pressure % \| 21` lost its 21 as a "line number" on every page, and on the vessel sheet `6 \| 5.7 \| Design life : \| 25 \| years` made the clause the label. Fixed by reading numbered rows by column (`_serial_columns`), collapsing same-page double reads, and scoring with a harness that counts duplicates and spurious rows separately (`scripts/eval_extraction.py` breakdown). |
| 48 | `README.md:35` and `:59`: the vector store is **"LanceDB (brute-force)"** / **"LanceDB embedded, brute-force cosine"** | **Nothing imports `lancedb`.** Dense vectors are BLOBs in the SQLite `chunk_vectors` table, memory-mapped into one numpy matrix by `vectorcache.py`; "brute-force cosine" was true, the store was not. Already found by the code review (`docs/code-review/docs-conformance.md` H5, review item 42) and **left unfixed in the README**, so it was then repeated as fact in an engineering brief on 2026-09-24 and caught only when the Stage 1 research agent read the code. Fixed in both README lines. `lancedb==0.38.0` is still pinned in `backend/requirements.txt` and `lance_dir` survives in `config.py`; removing a dependency is left to the owner and is stated in the README rather than hidden. **The rule: a finding recorded in a review document is not fixed until the claim is corrected where readers actually read it.** |
| 49 | `CLAUDE.md` standing rule 1: **"Only `backend/app/market_transport.py` may open a socket."** with the note "Known violation to fix: `settings.ollama_url` is unvalidated", and `docs/architecture.md` §5 listing four socket modules (market_transport, answer, analysis, metrics) | **Both wrong, in opposite directions.** The master-order B2 call-graph trace (2026-09-24, `main` `1b445af`, read from code) found four socket openers: `market_transport.py`, `model_transport.py` (every Ollama call - answer, analysis, comparison, metrics now go through it), `reader_transport.py` (unregistered cloud lane) and `notifications.py` (`smtplib.SMTP`). The "known violation" had been fixed - `config.check_model_url` validates `ollama_url` at load and before every request - so the rule under-stated one lane and still reported a defect that no longer existed. The SMTP lane is off by default (`smtp_enabled=False`) but **is not covered by `tests/test_socket_containment.py`**, whose network roots omit `smtplib`: the rule every session reads first named one socket module while the test meant to enforce it could not see a fourth. Corrected in `CLAUDE.md` and flagged in `docs/architecture.md`; the containment gap is an open issue. **The rule: a rule that names "the only" X is a claim about the whole codebase and needs the whole-codebase check behind it - grep for every socket-opening import, not the one you remember.** |
| 50 | The review engine's own finding text: every requirement no extracted field answered was written **"the submittal states no value for this requirement"**, with required action **"Provide the missing value."** (`comparison.compare`, `_required_action`) - and a run whose only gaps were these was recommended "Approved with Comments", i.e. a CRS asking the contractor to supply them | **A claim about the document made from a fact about the extractor.** "No field answered it" was true; "the submittal states no value" was not established, because `datasheets.extract_facts` computed which pages yielded no fields - and why - and threw that away. Measured 2026-09-24 on the regression documents after the #179 re-extraction: the vessel sheet has fields from 2 of 11 pages, the pump sheet from 5 of 7, the valve sheet from 4 of 5; the remaining pages were read as text but never into fields, and the finding said "states no value" regardless - 74 such findings on the vessel run alone. NORTH-STAR 2.2 had already said "not retrieved never means not present" and that an omission finding must preserve the pages searched; the engine recorded neither. **FIXED (master order B3):** a page ledger records every page's outcome with its reason; a no-value finding on a sheet with any page not read into fields is `NEEDS_ENGINEER_REVIEW` with reason `UNREAD_PAGES` naming those pages, and on a fully-read sheet it stays `MISSING_INFORMATION` and names the pages searched. Mutations M450-M460. **The rule: "we did not find it" and "it is not there" are different sentences; a finding may only say the second when it can list where it looked.** |
| 51 | Issue #183 as filed: the title block is lost to the chunker's **front-matter rule** ("early page + few lines + short clauses -> frontmatter, not retrievable") | **Wrong cause.** Traced on the real pages (disposable copy, 2026-09-24): `classify_page` returns `prose` for every page of all three submittals and no front-matter exclusion exists on any of them - all 227 `page_classified_frontmatter` rows are on standards. The title block is lost to RUNNING-LINE STRIPPING (`chunker.detect_running_lines`): a short datasheet reprints its title on every page, so the book-header rule removes it from every page, page 1 included; on the PSV sheet the remnant then fails the quality gate (longest real-word run 5 < 6). A fix aimed at the stated cause would have changed standards' cover-page handling and fixed nothing. Also found: detection counts non-blank lines but stripping counts raw lines, so the two windows disagree (left open, recorded on the issue). **The rule: an issue's "likely cause" is a hypothesis; trace it on the real input before writing the fix it suggests.** |
| 52 | ADR-0024 (PR #191): **"Every reader of *current* facts filters `superseded_at IS NULL`"** | **True of `backend/app`, false of the repository.** The grep behind the claim covered the application package; the two scoring scripts - `scripts/eval_extraction.py` and `scripts/gold_pairs_score.py` - read every `submittal_facts` row. Found while measuring #193 (2026-09-24): after the #179 re-extraction each vessel field existed twice (current + superseded), the pairing scorer's matcher saw a tie on every one and paired nothing, and the scorer reported **recall 0/3, 0 false pairings** while production actually made **1 correct pairing and 1 false one** (recall 1/3, precision 1/2). A measurement tool that disagrees with the product in the flattering direction hid a false pairing. No published extraction score was affected: the only sheet scored after supersession (the pump sheet, "28/161") had no superseded rows. Both scripts now read current facts, compatible with copies that predate the column; test + mutations M480-M481. **The rule: "every reader" is a claim about the whole repository - grep `scripts/` and the tests' helpers too, not only the package you changed.** |

| 54 | B5 quality branch (`feat/b5-quality`, development run 2026-09-25): the new stage-limit rule read the welding standard **SAES-W-010** as limited to existing equipment and made it **NOT_APPLICABLE** to a new pressure vessel, and three independent re-reads agreed, so the three-agreeing-re-reads confirmation let it stand | **Wrong exclusion - the sentence says the opposite.** The quoted scope sentence NEGATES its reference to existing facilities (the standard is not applied retroactively to repair of existing facilities); the rule looked for the words "existing / in-service" and never for the negation. Three agreeing re-reads did not help, because all three were fed the same passage and the same rule decided each of them - agreement between reads of one sentence is not independent evidence about what that sentence means. Caught on the 3-sheet re-measure before any push; fixed by a negation guard (`_NEGATED`, mutation M674, DETECTED). Never reached `main` or a live review. **The rule: a cue word is not a claim until its sentence is checked for negation, and N agreeing re-reads of the same text by the same rule are one reading, not N.** |
| 55 | The same branch's commit `a9b0e37` and its report (section 16.46): **"stage limit: an un-negated in-service/existing quote excludes a NEW item"** - an in-service repair scope (SAES-D-008) was reported EXCLUDED for the new vessel as a valid decision | **Retracted: activity / stage is not an allowed exclusion ground** (owner decision 4c, 2026-09-25). A scope that covers existing equipment says what the standard is FOR, not that a new item falls outside it - the engineer decides whether an in-service repair standard matters to a new submittal. The asymmetric rule allows NOT_APPLICABLE only on an explicit exclusion naming the submittal, or an equipment / facility / number limit it clearly falls outside of. **FIXED:** the stage limit is still read (with the negation guard of entry 54), but it can only hold an inclusion as `APPLICABLE_CANDIDATE` - "scope covers existing equipment - engineer to confirm" - never exclude. Mutations M680 (stage limit excludes again) and M681 (candidate hold dropped) DETECTED; explicit exclusion quotes of the SAES-L-108 shape still exclude. **The rule: a new NOT_APPLICABLE ground is an owner decision, not an implementation detail - propose it, do not ship it.** |
| 56 | Document Q&A screen, `ChatView.tsx` (before 2026-09-25): the in-flight panel **"Working on this machine · 0s"** with its Searching › Ranking › Reading › Writing stages, and the shell's **"The backend is not running"** | **Two claims derived from something adjacent to the truth.** (a) The panel was shown when `askingIn === current` - true at rest, because both are null in a fresh chat - so the screen said work was running when nothing had been asked, and the empty-state hint beneath it never rendered. (b) The shell declared the backend "not running" on ANY failed health poll, including one that the server ANSWERED with an error, and on a single dropped request; the view was unmounted, so the transcript was lost and the screen rebuilt (and replayed its entrance animation) on the next good poll - the "blinking" reported before the demo. Reproduced in the running app: a 3 s backend drop removed the chat `<section>` (80 nodes) and rebuilt it 5 s later with the transcript gone. **FIXED:** the panel requires a request in flight for THIS transcript; offline needs a failed poll AND a failed re-check 1.5 s later, and only an unreachable backend counts; the chat stays mounted (hidden) through an outage. Tests in `ChatView.test.tsx` and `Shell.test.tsx` ("visual stability", "connection stability"); five mutations, five detected. **The rule: "waiting" is a request in flight, not two empty values being equal; "not running" is an unreachable server, not one missed reply.** |
| 57 | The live review route (`POST /api/reviews/run`) and `comparison.recommend_code`, before 2026-09-25: the code **"Approved - every evaluated requirement is met"**, and `applicability.py`'s own module claim that a cited standard missing from the library **"stays on the missing list ... and lowers completeness"** | **Three claims derived from something adjacent to the truth.** (a) "Every evaluated requirement is met" was the fall-through of the policy, reached with ZERO findings - no requirement extracted, none applicable - so silence read as approval. (b) The route called `select()` and threw its result away, so `reference_coverage` never reached the completeness gate and the missing references never reached the code: a sheet citing only standards the library lacks could be Approved. (c) A shared discipline and textual similarity APPLIED a standard, so every mechanical standard was compared against every mechanical datasheet. Found by the plan audit, confirmed in code. **FIXED (master order B5, live wiring):** nothing evaluated, or only NOT_APPLICABLE, is Manual; a cited standard not held is `MISSING_LOCALLY` and blocks every approval; the route passes the selection's coverage and missing references; discipline-only and similarity-only standards are considered, not applied, with the reason. Tests `test_b5_live.py`; mutations M730-M747, 18/18 detected. **The rule: an approval is a claim about what was checked, so it needs something that was checked - and a standard nobody could read was not.** |
| 58 | `chunker.classify_page` and the quality gate, before 2026-09-25: **"A page carrying a genuine clause is CONTENT however short it is"** | **False for the clauses densest in figures.** Both the front-matter guard and `quality.assess` measured a clause as the longest run of letter-words, and every number ended the run - so "a surface profile of 50 to 75 micrometres" or "the shaft AISI 4140 for all pumps" never reached six words and was dropped from retrieval as debris or front matter. No test caught it because every test page carried long plain sentences. Found by master order B6 (core retrieval verification): on the synthetic benchmark 12 of 15 clause pages were retrievable, and the three missing were the materials, surface-preparation and coating-thickness clauses. **FIXED:** a plain number followed by a lower-case word (its unit, or the rest of the sentence) no longer ends the run and does not count in it; a number followed by another number, by a capitalised label, or by nothing still breaks it, so a table's rows ("2 Set pressure") are not read as one sentence - the first version of the fix bridged row numbers too, and `test_b3_page_ledger` caught it in CI. The rule only ever lengthens a run, so nothing searchable before becomes unsearchable; the one class that becomes searchable beyond the figured clauses is a short labelled value with its unit ("Design pressure 23.5 barg"), which the gate had been discarding although it is exactly what an engineer searches for - `test_b3_page_ledger`'s "nothing searchable" fixture had relied on that and now uses bare tags and numbers. Tests `test_b6_measure_in_clause.py` and `test_every_clause_in_the_corpus_is_searchable`; mutations M765, M766, M768, 3/3 detected. Chunks already in the live database change only when a document is re-chunked. **The rule: a filter that decides what is searchable must be tested on the text engineers actually search - requirements full of numbers - not on prose.** |
| 59 | `GET /api/conversations/{id}` docstring, before 2026-09-26: reopening a conversation **"restores the citations"** - and the access model's promise that `allowed_document_ids` "is the whole authorisation decision" | **Not at reopen time.** Ownership was checked, grants were not: `chat.get_messages` returned every stored payload as written when the question was asked, so a document grant revoked afterwards still returned the cited passage, its filename and the answer prose that quotes it to the same user. Found during B9. Fixed: `get_messages` now takes the caller's scope (required, keyword-only) and withholds, whole, any assistant turn whose payload references a document outside it (`tests/test_b9_reopen_permissions.py`, mutations M829-M835). |
| 60 | The review workflow's governing rule (section 15, `record_engineer_code` docstring): **"The AI recommends and the engineer decides"** | **Not enforced on findings or the CRS.** `PATCH /api/reviews/findings/{id}` accepted `approved_by` / `approved_at` from the request body, so an approval could be recorded in anyone's name; `POST /api/reviews/findings` accepted `approval_status` / `disposition`, so a finding could be created already accepted; and the CRS printed the AI's recommended code with nothing saying no engineer had decided it. The code-decision audit write also swallowed its own failure, so a decision could stand unaudited. Found during B10. Fixed: approver is the authenticated caller; creation is always pending; the CRS states who decided the code; the audit row is written in the decision's transaction (`tests/test_b10_engineer_decisions.py`, mutations M844-M846, M848-M851). |
| 61 | `applicability.completeness` docstring: **"How much of this review could actually be performed"** | **A second, disagreeing formula.** The gate that sets the review code used fields read / nominal fields, weakest link; the selection used pages-with-a-fact / page count, multiplied - two numbers for one review - and with the page count unknown it divided the pages by themselves and reported extraction 1.0 for any sheet with one fact. Found during B10. Fixed: the selection computes only reference coverage and delegates to `comparison.completeness_for_run`, the one formula (M847; M313/M315 retired with the code they mutated). |
| 62 | Every stage report B4-B11 (`docs/FINISH-STATUS.md`, PRs #243-#254): each stage's mutations **"N/N detected"**, read as "the registry still guards everything" | **Each stage ran only its own new mutations.** The first full run of all 727 (final acceptance, 2026-09-26) found seven that no longer tested anything: M820 (B8's own - a later B8 fix changed its line), M46 (B11 rewrote `enqueue_extraction`), M62, M153 and M154 (B10 moved the override audit, dropped `approved_by` from the schema and added a second `if scope.user_id is None:`), M369 (B4/B7 renamed the geometry flag) - all reported ERROR, not applied - and M807 NOT DETECTED because B9's new context guard made the B6C line it mutates unobservable. Fixed: six re-anchored and detected again; M807 retired in favour of M843. The rule: a stage that edits a line any mutation anchors on must run the whole registry (or at least every mutation on the files it touched), not only its own. |
| 63 | Final real review (`docs/FINISH-STATUS.md`, PR #260): **"standards applied automatically: 0"** on all three datasheets, read as the automatic applicability result on real documents | **The automatic selection was never exercised.** The acceptance script uploaded the documents but never set their role, which the app assigns on the Documents page; `applicability._library` reads only documents marked COMPANY_STANDARD, so the library was empty and every cited standard reported missing. Found 2026-09-26 when the owner supplied a standard one datasheet cites and it was still reported missing. Re-run with roles set through the real admin route: that standard is applied automatically with its page evidence; the other two datasheets cite none of the held standards, so their rows stand. |
| 64 | Final acceptance item 12 (PR #255) and the final review table (PR #260): **"all 1355 standard citations ... against the cited page: 0 wrong pages"**, read as citations being correct | **Only the page was checked, never the clause.** An independent check (the nearest clause number printed above each requirement in the PDF) put the clause label right on 1,133 of 1,440 requirements (79%) across ten real standards. Two defects: every standard's revision-history table ("Summary of Changes" - paragraph, change type, description) was read as clause headings, so a table row's number (e.g. 14.1.5) labelled the Scope and history rows were stored as requirements; and a numbered "shall" sentence was taken as a titled heading, its line consumed into the section label and never read as a requirement. Fixed (`chunker.revision_history_regions`, `chunker._obliges`): 1,493 of 1,692 labels right (88%), wrong 209 -> 78, 254 more requirements read, 4 history rows no longer stored, no real requirement lost. The remaining 78 are partly the checker's limits (it takes the nearest printed decimal, e.g. a table value) and partly known residuals: a table's row number can still be carried as a clause. |
| 65 | `applicability.citation_evidence` (B5): the evidence for a citation is **"the page and the printed line"** | **Neither, for a chunk spanning pages.** It returned the chunk's first page and the chunk's first 200 characters - a prose chunk is one line - so on a real datasheet the published quote was the page header, did not contain the standard it was evidence for, and named page 4 for a citation printed on page 5. Fixed: the page is the one whose stored text carries the citation, the quote is that printed line (with its label when the line is a bare cell value), and a spanning chunk without page text claims no page. |
| 66 | P1 report (PR #256, `docs/FINISH-STATUS.md`): its mutations **"M865-M869 detected"**, with the registry otherwise as final acceptance left it | **P1 made M653 vacuous and did not see it.** P1 taught the unit grammar to join "bar a"; M653's test used exactly "bar a" as its example of a unit the quantity reader CANNOT join, so after P1 the test passed with the feature deleted. P1 ran the mutations on the files it edited (`claims.py`, `requirements_3b.py`), but M653 mutates `datasheets.py`, whose behaviour those edits changed - entry 62's rule, one step wider: a change to shared grammar must re-run the mutations of the modules that CALL it. Found 2026-09-26 running every mutation on the files the revision-history fix touched. Fixed: the test uses "mm H2O", still unjoinable, and asserts that it is; M653 detected again. |
| 67 | `market_phrase._strip_filenames` (market screen, and chat web search from PR #269): **"Remove every corpus filename, with and without its extension"** | **Not a file name typed with spaces.** It removed the exact name, the stem and the stem with every separator deleted, but a reader names `coating-inspection-plan.pdf` as "coating inspection plan", and that form passed the whitelist word by word and reached the outbound phrase. Nothing had leaked - both web lanes are off by default and have never been switched on - but the guard's own description was false for the commonest way a person types a file name. Found 2026-09-26 while building chat web search. Fixed: each name also matches as its parts in order with any mix of spaces, hyphens, underscores or dots (or none) between them, with or without the extension, case-insensitive. Tests type each variant through both the market route and chat web search; a mutation removing the new pattern is detected. |
| 68 | `page_ledger` / `datasheets._extract_facts` (B4): **a page's `facts_status` says whether it was read into fields** | **It said `no_facts` for pages that carried recorded, current facts.** B4 counted only the rule readers' facts toward the page outcome; a page filled only by the geometry or vision reader kept "no_facts" while its facts sat in `submittal_facts`. Found 2026-09-26 on an owner run of a real vessel datasheet (aggregate only: three pages with recorded facts read `no_facts`). Owner decision 2026-09-26, in two halves. (1) The ledger and the screen say a page with recorded current facts IS read, whichever reader wrote them: extraction counts every reader's facts for the page outcome (a page read only by the page reader carries a note saying so), and `refresh` promotes an older recorded `no_facts` while the page carries current facts (derived, so it drops back if they are superseded). (2) An ABSENCE on a page read only by the geometry/vision reader is still not the contractor's omission: `comparison.qualify_by_pages` keeps it NEEDS_ENGINEER_REVIEW with the reason "value not found by the page reader - engineer to check the page" (`PAGE_READER_ONLY`), because that reader is not known to find every field on a page; MISSING_INFORMATION from absence stays limited to pages the rule/text reader read (`page_ledger.TEXT_READER_METHODS`, an allow-list). Such findings are one summary row on the CRS, never a contractor comment each. M595's intent restored on the absence rule; M1021-M1025 added. |
| 69 | `datasheets.states_a_value` (#179): **"A quantity, an explicit blank, or a closed categorical answer - anything else is a caption"** | **Not for a designation, and not for a value printed after its unit.** "Shell material: SA-516 GR.70", "Design code: ASME VIII DIV. 1" and "Radiography: FULL" are real fields and were refused as captions; a process-data row printed label / unit / value was paired as label -> unit, so the unit was refused and the number never paired. Found 2026-09-26 by the owner-ordered filter audit, after a real vessel sheet (aggregate only) recovered 10-44 pairs per page and kept none; reproduced on synthetic layouts (`tests/synthetic_vessel_sheet.py`). Fixed narrowly: designations (a family prefix and a number) and six closed engineering words are answers; a bare unit followed by a number is read as the value with its unit. Names, places and document numbers are still refused (tested); free text such as a service name remains unread and is named as a gap in `docs/extraction-filter-audit.md`. |
| 70 | PR #285 (`93a78ae`): the page ledger carries a real, specific reason each page did or did not read into fields | **Computed, then thrown away before the readiness strip.** See the section "Readiness strip, 2026-09-27 (entry 70)" below. |
| 71 | `crs_mapping.build_crs_rows`: every CRS row says who the comment is by | **Blank for an unconfirmed AI or web item.** See "CRS export, 2026-09-27 (entry 71)" below. |
| 72 | `CLAUDE.md` rule 1: the Claude API lane runs only **"under the budget of USD 5 per step / USD 20 in total (enforced in `claude_spend`)"** | **Not for four of the five `claude_api` routes.** `claude_select_standards`, `claude_read_datasheet`, `claude_recheck_findings` and `claude_crs_draft` took their model call from `_model_call_or_409()`, capped only by `claude_budget`'s call count (200 per run). Their usage went to a separate `model_spend` table the USD total never read. Fixed on `fix/claude-dollar-cap-all-routes`: `claude_spend.metered` checks every call before it leaves and records it in the one ledger. |
| 73 | Commit `419ef4c`: fixed "datasheet checks silently checking nothing" and added "Centrifugal Compressor" / "Reciprocating Compressor" to the classifier | **False for exactly those two labels.** The mandatory table's key was "Compressor" and the lookup was verbatim, so both fell to the 2-field generic list instead of the 4-field compressor list. No test tried the new labels. Fixed on `fix/compressor-mandatory-checks`: lookup by family (`match_rules.sheet_kind_from_equipment_type`) and a test over every label the classifier can emit. |
| 74 | `rule_eval.judge`: **"<field> not stated on the datasheet"** means the datasheet does not state it | **Also said for a field stated twice with different values.** `_field` returned `None` for absence and for conflict alike, so a contradiction an engineer must reconcile was shown as a gap. Fixed on `fix/rule-eval-conflict-not-missing`: a conflict is `NEEDS_ENGINEER_REVIEW` with every value and its page. |
| 75 | `web_standards` docstring: **"NEVER COMPARED ACROSS EDITIONS"** | **The guard was never called.** `edition_differs` was unit-tested only; `run_check` did not know the cited edition. Fixed on `fix/web-standards-edition-guard`: the cited edition is read locally from the submittal, and a differing or unconfirmed edition is never compared. |
| 76 | `contracts/types.ts`: a null `disk_percent` renders as "not measured yet" | **It rendered as a green 0% bar and "0 B free".** The Disk card used `disk_percent ?? 0`; `WorkerPanel` likewise showed "pending 0" before worker data arrived. Fixed on `fix/disk-card-unmeasured`. |

The pattern is always the same: **a field derived from something adjacent to
the truth rather than from the truth itself.** Every entry below states what
it is derived from, so the next instance is easy to spot.

**Entry 15 is the only one where the hardening itself carried the lie.**

`/api/health` used to return `current_document` — a real document id the UI
joins against the document list to show a filename — along with free-text
`last_error` and `stalled_reasons`. That was correctly identified as a
privacy-boundary problem and correctly fixed: those fields were removed from the
one unauthenticated route.

**They were moved to `/api/metrics`, and the reason recorded for choosing that
destination was that `/api/metrics` is scoped. It was not.** The route took
`scope: AccessScope = Depends(access.current_scope)` and then called
`metrics_mod.snapshot(...)` without it. The parameter was resolved on every
request and discarded, so the corpus block was byte-identical for an
administrator, a four-document user and a user granted nothing — measured, all
three reporting 12 documents while `/api/documents` correctly returned 6, 4
and 0.

So the hardening **relocated the leak**. A document id that an unauthenticated
caller could previously read on `/api/health` became a document id that any
authenticated caller could read on `/api/metrics`, regardless of grants, and the
change was recorded as a security improvement.

The belief spread. **Seven comments in five files** described the endpoint as
"the scoped `/api/metrics`", including two inside
`test_health_never_exposes_a_traceback` — the test written to hold this exact
boundary. That test never called `/api/metrics` at all. It asserts what
`/api/health` does *not* say, which is real and still passes, and the word
"scoped" in it was an assumption it had no way to check.

This is the distinguishing feature: the earlier entries are fields derived from
something adjacent to the truth. This one is **a justification derived from
something adjacent to the truth** — a comment that made a real design decision
look safe, and was then cited by later work as though it were a verified
property. A count without a boundary reads as total; a comment without a test
reads as a guarantee.

**Entry 11 is the same shape twice, and both times the sweep was mine.**

When `search()` gained a required scope parameter I reported **"50 call sites
now pass `every_document_id()` explicitly"**. The number was exact and the
boundary was silent: I had swept `backend/`. Five more call sites lived in
`eval/`, and they surfaced only when the harness crashed with
`ask() missing 1 required keyword-only argument`. Had the parameter carried a
default, those five would have kept meaning "every document" and nothing would
have said so.

Hours later, asked to find copy claiming a shipped feature was missing, I
searched the frontend and reported the strings I found. **The false string was
in the backend**, in `metrics.warnings()` - the Dashboard renders whatever the
API sends, so the copy was never in the frontend at all.

Both reports were accurate inside their boundary and neither stated the
boundary. **A count without a boundary reads as total** - that is standing
rule 7 - and the fix in both cases was not a better search but naming the
territory first. The copy sweep now scans backend, frontend AND contracts, and
exempts comments rather than files, because a file-level exemption would have
re-admitted the very string it was written to catch.

**Entry 10 is a pattern rather than an accident, which is why it is recorded
as one.** Three tests in a single session were green over broken code, and all
three failed the same way: **the fixtures could not produce the condition the
test claimed to check.**

| Test | What its fixtures could not produce |
|---|---|
| `provenance.enumerated.test.tsx` | Only ever supplied passages that EXIST, so it could not see the verbatim label being claimed over a null passage — the exact defect it was written to prevent |
| `Shell.test.tsx` | Answered every endpoint with the health object, so `/documents` returned a non-array; the screen degraded to a spinner and the test asserted "Reading the queue" and called that success |
| `test_a_passage_too_far_below_the_primary_is_not_admitted` | Calls nothing. `_hit` is a pure factory, the `primary` candidate is never used, and the assertion compares a `separation` the test itself set to `0.89` against a constant |

The third is the purest form: a comparison between two literals, wearing a
test's name. It passed for years of commits because **a vacuous test does not
fail — it passes**, and a passing test is the thing nobody re-reads.

**It recurred within the hour, in the work that recorded it.** The
route-enforcement tests for the access scope uploaded two PDFs built from the
same template — identical bytes, therefore the same SHA-256, therefore
deduplicated by the upload path into ONE document. `visible` and `hidden` were
the same id, so every test using that fixture was asserting that a document
could not see itself. It passed. It was caught only by deliberately widening
the scope and finding that a test which should have failed did not.

The fixture now gives the two documents different text and asserts
`visible != hidden` with a comment saying why, so the vacuity cannot come back
silently. That assertion is the cheap form of the rule: **make the fixture
prove it can produce the condition, in the fixture.**

**Two of the three were found by something other than the test suite.** The
provenance one was found by reading the branch; the third by `ruff F841` on the
first lint run this codebase has ever had. The suite could not find them
because they were part of the suite.

The rule this implies is standing rule 7: **a test must be shown to fail
against the unfixed code, or it is not evidence.** Every fix in this session
that carries "proven by deliberate failure" in its commit message is that rule
being followed; these three are what it looks like when it is not. Writing the
test first is one way to get there, but not the only one — reverting the fix
and watching the test go red works just as well and is available afterwards.

**Entry 9 is the smallest here and the most ordinary, which is the point.**
The setup guide stated a disk requirement of "~2 GB". The measured figure is
**768 MB** in the clone — `.venv` 527 MB, weights 159 MB, `node_modules`
80 MB — plus ~3.4 GB for the Ollama model, which sits outside the repository
and was not mentioned at all. So the number was wrong in two directions at
once: 2.6× too high for what it covered, and silent about the largest thing a
reader actually has to find room for.

It is the same family as entry 8 — an unverified number stated with the
confidence of a measured one — and it survived for a simple reason: **nothing
depended on it.** No test reads a disk figure. No code path branches on it. A
reader with a modern disk would never notice being asked for 2 GB instead of
0.77, and a reader who *was* short of space would have been misled about the
one number that mattered. Wrong claims that nothing checks are the ones that
last longest, and a setup guide is made almost entirely of them.

Caught by measuring the finished clone rather than by anyone doubting it.

**Entry 8 is the first one that no check could have caught, and that is the
point of it.** Every other entry here is a check pointed at the wrong thing, or
a claim that stopped being true. Entry 8 is neither: it is **a number that
looks like the thing you need and is a different quantity wearing the same
units.**

Coverage "before OCR" was computed by removing every recognised chunk from the
index and re-counting covered pages. That sounds right, and it is arithmetically
flawless. It is also not coverage-before-OCR, because a chunk spans a page
RANGE. One NORSOK chunk covers pages 21–24:

| Page | Truth | What the wrong number assumed |
|---|---|---|
| 21 | already covered by another chunk | lost without OCR |
| 22 | **413 extracted characters of its own** | lost without OCR |
| 23 | genuinely blank — 0 extracted, 0 OCR boxes | lost without OCR |
| 24 | 0 extracted, 14 OCR characters | lost without OCR — **the only true one** |

Three of the four pages were charged to OCR that OCR did not read. The reported
gain was **+12.5%**; the real one is **+4.2%**. It would have overstated the
feature's value threefold **in the feature's own headline number** — the single
figure anyone would quote about this work.

**No automated check would have found it.** The number was internally
consistent: the same query, the same rows, the same arithmetic, reproducible to
the digit. A test asserting "coverage after ≥ coverage before" passes. A test
asserting the gain is positive passes. There is nothing wrong to detect unless
you already know what the number is supposed to count.

**What caught it was hand-checking the smallest document.** NORSOK is 24 pages
with 3 recognised — small enough to list every page and ask, of each one,
whether OCR really reached it. That is the whole reason it was chosen as the
first proof, and it paid for itself immediately. The lesson is standing rule 7:
a number is not a measurement until you can say what it counts, and the cheapest
way to find out is to check one case by hand.

**The same measurement produced a second instance of the same shape, hours
apart.** The "what is still missing" breakdown reported *21 pages uncovered
with no exclusion recorded* — which, if true, would have broken the standing
promise that nothing is dropped silently, and was minutes from being filed as
a defect against the pipeline. It was a defect in the query: it looked only at
`scope='page'` exclusions, and a page can also be uncovered because every
CHUNK on it was excluded. All 21 carried a chunk-scope `content_quality_gate`
row saying exactly why. Correct arithmetic over the wrong population, twice, in
one script. The count of silently-dropped pages is **zero**.

**Entry 7 is a DIFFERENT SHAPE from every other entry here, and that is why it
is worth its own paragraph.** Every earlier failed check could not see its
subject: a footer fixture that was itself a footer, a typecheck that ran over
zero files, a reranker judging a chunk on a fragment of itself, a TestClient
that never traverses the layer where the `Server:` header is written. The fix
in all of those was to point the check at the real thing.

Entry 7 saw its subject perfectly clearly and **asserted the wrong property
about it.** The test watched every OCR invocation, confirmed each one happened
while the document was answerable, and was completely correct about that. It
simply never asked whether the document survived. `process()` catches broadly
and records failure on the row, so the exception left no mark the test was
looking at — a green suite over a corpus where every scanned document had
failed.

The rule this implies is standing rule 7: **a test that asserts intermediate
state must also assert terminal state.** Steps are cheap to observe and are
what a test naturally reaches for; outcomes are what the user gets. Nothing in
this repository's working tree could have caught it either, because the
document that exercises the path was already ingested here. It took a clone
into an empty directory.

**Two smaller instances from the same clean-clone pass**, both the same family
— a claim that was true when written and quietly stopped being true:

- **`huggingface_hub` was an undeclared dependency.** `scripts/fetch_models.py`
  imports it directly; pip was getting it for free as a transitive of
  `tokenizers`. Nothing was broken, and nothing would be until a resolver
  chose differently — at which point model staging fails on a fresh clone,
  during setup, on a machine about to be air-gapped. **A dependency you did not
  declare is one you did not choose.**
- **README "Getting started" read "Not yet available — see `docs/` once
  `DEV-001` lands".** DEV-001 landed long ago. A placeholder that outlives its
  plan stops reading as a placeholder and starts reading as a fact, and a
  fresh clone had no instructions at all.

**Entry 6 is the sharpest instance, and it happened inside the feature built
to prevent it.** Provenance was stored (`page_ocr`), carried to `chunks`,
threaded through retrieval and passage expansion, and made a REQUIRED field in
`contracts/types.ts` so no caller could omit it — and the one screen where it
decides whether a sentence may be called the document's own words never read
it. Every layer was correct and the claim was still false.

The lesson is a rule, now standing rule 12: **a provenance field that no
assertion reads is decoration.** Storing it, typing it and requiring it are
not the safeguard; the safeguard is a test that fails when the label is wrong.
The test that now guards this asserts the ABSENCE of the verbatim label on
recognised text, not merely the presence of the OCR one — a presence-only
assertion passes happily while both labels sit on screen together. It was
proven by deliberate failure: forcing the old unconditional branch back makes
it fail.

---

## The verification that verified nothing

A second pattern, distinct from the one above and more dangerous, because the
first is a field that lies while the second is a **check that cannot see the
thing it judges**. Eight instances, all in this build:

| # | The check | Why it could not see | How it was caught |
|---|---|---|---|
| 1 | `Server:` header removal, asserted with TestClient | uvicorn writes that header at the HTTP protocol layer, **after** the ASGI app. TestClient never traverses it, so the assertion passed against a server that still sent it. | Reading the real response over the wire |
| 2 | Footer stripper, asserted against a synthetic page | Every line of the fixture was templated per page, so the fixture's own body text **was itself a repeating footer**. The stripper removed it correctly and the test demanded it fail to. | The test failing for the opposite reason to the one expected |
| 3 | `tsc --noEmit -p tsconfig.json` | `tsconfig.json` is a solution file with `"files": []` and project references, so it type-checked **zero files**. Every "typecheck clean" report was vacuous. | Noticing exit 0 on a file with an unterminated string literal |
| 4 | "Stale numbers are dropped on refresh", with fake timers | The timers were installed **after** the component had created its interval with real ones. Advancing them fired nothing; the test passed while asserting nothing. | Reading the test back after writing it |
| 5 | The cross-encoder's own rerank window | `rerank_max_tokens` was 256 against a `chunk_max_tokens` of 480, so a 486-token passage was scored on its first 256 tokens. The answer sat at token 350. It returned **−10.95** — correct about what it was shown, wrong about the passage. | Measuring a hypothesis that turned out to be false, and looking further |
| 6 | Two **migration** tests, 2026-09-18 (AI submittal review, phase 1) | The fixture calls `db.init_db()`, which builds the table from today's `SCHEMA` — already carrying the new columns. The `ALTER` path therefore never executed, and both tests passed **with the migration deleted**. They asserted the schema, not the migration. | The mutation harness: M6 and M7 reported `*** STILL PASSED ***` while 8 of 10 other mutations failed correctly |
| 7 | An **immutability** test, 2026-09-18 (phase 2) | It re-implemented `upload.py`'s `if final_path.exists()` branch *inside the test body* and asserted against its own copy, so no change to `upload.py` could ever fail it. Its `-k` expression was also wrong and selected a different test. Two independent ways one check was worth nothing. | Mutation M15 reported NOT DETECTED. Rewritten to call the real `upload.ingest()` |
| 8 | Nine tests for the **engineer's final review code**, 2026-09-19 (phase 6) | Every one called `comparison.record_engineer_code` directly, so none traversed the route - and the route depended on `admin.current_admin`, which is a GATE, not a lookup. It answers any non-admin with the admin surface's deliberately silent 404. The suite could not see it twice over: no test used the route, and `conftest` pins `AUTH_MODE=disabled`, under which `current_admin` waves an *anonymous* caller straight through. Nine green tests over a button no engineer could press. | Signing in to the running app as an ordinary non-admin and pressing it. The screen said "not found" about a run it had just listed |

**Number 3 recurred, on 2026-09-05, in this repository, to the person who wrote
this list.** CI was fixed to run `tsc -b` and carries a comment saying exactly
why. That did not stop `npx tsc --noEmit` being typed by hand, repeatedly,
across a whole session, with "typecheck clean" reported from it each time. The
command loads `tsconfig.json`, which has `"files": []`, and checks nothing.

It surfaced only when eleven untracked frontend files needed checking and the
listing came back empty - `--listFiles` printed no file at all, which is what a
vacuous check looks like when you finally ask it what it covered. Run properly
the eleven were clean. **Every conclusion was right and none of the evidence
was worth anything.**

This is standing rule 11 - **a documented hazard is not a guard** - demonstrated
against its own author. The hazard was written down, the CI path was fixed, and
the hand-typed path stayed open. The guard that would have caught it is the one
now applied everywhere else in this document: **ask a check what it covered
before believing it passed.**

Number 5 is the one to remember: **the evaluation recorded a retrieval failure
that was really a truncation failure.** The system was not bad at retrieval. Its
judge had read half the evidence.

**Number 6 is the cheapest lesson here, and it was only cheap because the
mutation was run.** Both tests were written deliberately, read plausibly, and
passed — and a reviewer reading them would have seen a legacy row inserted and
a migration called. What they could not see is that the table under them was
never old. The fix is to build the pre-migration table from an explicit DDL
literal and to **assert the old shape first**
(`assert "document_role" not in before`), so the test fails loudly the day it
stops testing a migration rather than passing quietly. Standing rule 8 exists
for exactly this, and the only reason it held is that the mutation step was not
skipped once the tests were green.

**A claim that was true of the build and false of the suite, 2026-09-18.**
Section 7 of `docs/AI_SUBMITTAL_REVIEW_HANDOFF.md` recorded that the navigation
relabel was unverified only in the sense that `npm run build` had not run on
Windows, the Cowork VM being unable to resolve the TypeScript binary. The build
does pass. What nobody ran was `vitest`, and it reports **63 failed / 512
passed** across seven files, `ChatView.test.tsx` failing 54 of 54 — the suites
that assert UI terminology, against a commit that changed UI terminology.

The retraction is not "the labels were wrong". It is that **"the only
outstanding check is the build" named one tool and implied the rest were
clean.** A session that cannot run the suite has not established that the suite
passes, and the honest sentence is "the tests have not been run on this
platform" rather than "the build is outstanding". Verified by stashing the two
phase 2 frontend changes and re-running at `9f75ba5`: the failures are
unchanged, so they are inherited, not new.

**"63 known pre-existing frontend failures" was itself a flaky number,
2026-09-18.** The retraction above is sound in substance - the failures are
inherited from the navigation relabel and the suite was never run on Windows
after it - but the FIGURE was quoted from one run's summary line as though it
were a stable property of the branch.

Measured properly: the stable set is **59**, in four files, reproducible when
those files are run alone. A full parallel run reports 59, 60 or 63 depending
on which load-sensitive tests happen to time out - the baseline run failed
`IngestionView.watch`, a later run failed `AnalysisModeScreen` and `LoginView`
instead, and every one of those passes in isolation.

The lesson is the one this document keeps relearning in new clothes: **a number
is not a measurement until you can say what it counts** (standing rule 9). Two
summary lines subtracted from each other look like a delta and are not one when
the suite is non-deterministic. The way to show "no new failure" is to run the
touched files in isolation and see them pass, which is what was finally done.

A ninth, in the mutation harness itself and caught by its own output,
2026-09-18: on a Windows console defaulting to cp1252 the harness could not
DECODE vitest's box-drawing characters, raised, treated the exception as a
non-zero exit, and reported **6 of 6 mutations DETECTED without a single test
having been consulted**. The file whose entire purpose is to catch checks that
cannot see what they judge had become one. Fixed with explicit UTF-8 decoding
and an ASCII-flattened summary line.

A tenth, in the same run: a mutation's replacement called a function that does
not exist, so the test would have failed with a `NameError` - the right verdict
for the wrong reason, and indistinguishable from a real detection in the
report. A mutation has to reproduce the DEFECT, not merely break the code.

**An eleventh, 2026-09-18 (phase 3A), and it is number 6 wearing different
clothes.** A permission test asserted an absence with
`await waitFor(() => expect(queryByLabelText("Superseded by")).toBeNull())`.
`waitFor` succeeds on its FIRST tick, and on that tick the tab under test is
still a spinner - nothing is on screen to find. So it asserted that the control
had not rendered **yet**, not that it never would, and it passed with the
permission check deleted. Mutation M38 reported NOT DETECTED.

The rule, stated generally because it keeps recurring in new forms:
**a check that runs before the thing it judges can exist will always pass.**
The migration tests of entry 6 ran against a table that was never old; this ran
against a screen that had not loaded. The fix has the same shape both times -
assert something POSITIVE first, so that the negative assertion is made at a
moment when failing was possible.

**A seventeenth, 2026-09-18 (phase 5A): the `NameError` mutation shortcut,
taken for a THIRD time.** Entry 10 recorded it, entry 12 recorded it recurring,
and M62 reached for it again - replacing an audit call with a call to a
function that does not exist, so the test fails with a `NameError` rather than
because the audit is missing. Right verdict, wrong reason, and in a report it
is indistinguishable from a real detection.

Three occurrences of one mistake, by one author, across four phases, with the
rule written down after the first. What finally changed was not another entry
in this file: the reasoning now lives **at the mutation**, in a comment the
next person to write one will be looking at. Entry 12 predicted exactly that
and it took two more phases to act on it. **A record only works where the
person about to make the mistake will read it.**

**A twenty-seventh, 2026-09-19 (table rows): a limit the standard never states,
matched against a real submitted value.**

SAES-D-001 6.2.2 says the internal design pressure "shall be according to the
following table". The table's first row boundary reads "Up to 6,900 kPa (1,000
psi)". The extractor read that as a requirement of **<= 6,900 kPa** - a limit
that appears nowhere in the standard - and in the first end-to-end review it
MATCHED the submittal's maximum operating pressure. SAES-E-014 7.2.4 is the
same table and did the same thing.

Two things stopped it becoming a confident wrong verdict, and neither was
understanding: the unit spellings differed (kPa against bar (ga)), so the unit
guard refused the comparison. The very next task on the list was to relax that
guard to compare by dimension - which would have converted bar to kPa and
produced a clean PASS against a threshold that is not a threshold.

So the honest reading of the first review's "0 NON_COMPLIANT" is not that
nothing failed. It is that **74 of 1,580 requirements were numbers lifted out
of lookup tables**, and the only thing between them and a verdict was a
spelling mismatch that was scheduled for removal.

The rule: **a number is not a limit until something says what it bounds.** A
sentence that defers to a table states no limit of its own, and a row boundary
is a cell. Both are now `table_row`, refused by `compare` with the row quoted
so an engineer reads the table rather than a verdict about it.

**A twenty-sixth, 2026-09-19 (matcher): two mutations reported DETECTED having
run no tests at all.**

M117 and M118 were added with `-k` expressions that matched nothing. pytest
collected zero tests, exited non-zero because zero were collected, and the
harness read a non-zero exit as "the tests failed" - which is what DETECTED
means. Both printed `49 deselected` and no pass or fail count, and both were
green.

This is the failure M62's comment predicted in writing - "fails for the right
verdict and the wrong reason" - arriving through a different door. That comment
warned about a mutation calling a function that does not exist; this was a
KEYWORD that selects nothing. Same outcome: a mutation that proves nothing,
reported identically to one that proves something.

**The harness needs to refuse a run that collected zero tests**, the same way
it already refuses an anchor that matched zero times. It has not been changed
here - the two mutations were repointed at tests that exist - and that is worth
recording as a known gap rather than a fixed one.

The rule: **a check that can pass without executing anything must assert it
executed something.** Entry 14 said this about tools; it applies to the tool
that verifies the tests.

**A twenty-fifth, 2026-09-19 (datasheet review): "units were not captured" was
wrong twice over, in opposite directions.**

I reported, from reading three fact rows, that **"units are dropped on the
fact side"**. Measured properly over all twenty numeric facts:

  * ten had `unit` NULL - the claim was right for those;
  * ten had `unit` POPULATED, with values like `VEFV1101M` - equipment tags
    from a bill-of-materials column, sitting in a column that reads as an
    engineering unit to everything downstream.

So the honest statement is neither "units are captured" nor "units are
dropped": **no fact carried a correct unit, and half of them carried a
confident wrong one.** The second half is the worse failure and my summary had
no word for it, because I had generalised from three rows that all happened to
be of the first kind.

Both come from the same place. The sheet writes units in three layouts, and
the extractor read one of them; the layout it read is also the one where any
word after a number becomes the unit, which is where the tags came from.

**The rule, and it is the third time this file has needed a version of it: a
sample of three is not a measurement of twenty.** Before writing "X does not
happen", count X over the whole population. Entry 20 was an absence asserted
where the code never ran; entry 24 was a claim read off a truncation; this one
is a rate inferred from the first three rows that came to hand. Same mistake,
three surfaces.

**A twenty-fourth, 2026-09-19 (extraction review): a defect reported from a
truncated string.**

I reported that SAES-P-104 stored `value=0.4 unit='%'` for text about NEMA
enclosures and wrote: **"No percentage exists in that text."** That was false.
The full sentence reads "...manufactured copper free cast aluminum (aluminum
with a maximum of **0.4% copper**), or plastic..." - the limit is real and the
extractor read it correctly.

What produced the error: the probe printed `requirement_text[:150]`, the
percentage sits at character 250, and I described the row from the truncation
rather than from the row. The genuine defect is different and milder - the
limit is attached to a compound sentence whose subject is the whole enclosure
clause, so it is scoped wrongly, not invented.

**The rule: quote from the value, never from the view of it.** A truncated
display is a rendering, and an assertion about what a document does NOT contain
cannot be made from one. This is the same shape as entry 20 - a claim about
absence, made where the absent thing could not have appeared.

**A twenty-third, 2026-09-19 (extraction review): `field` cannot be populated
deterministically, and saying so is the finding.**

`comparison._match_fact` joins a requirement to a submitted fact on `field`, by
EXACT EQUALITY against `datasheets.normalise_field_name(field_label)` - a
datasheet's form caption. `standard_requirements.field` is NULL on every row
because `requirements_3b.parse_limit` never returns the key.

The obvious rule - the noun phrase before the operator - was run over all 44
numeric_limit rows rather than judged by eye. It yields "the material stress in
the bottom parts of the vessel", "a pvc coated rigid steel conduit with a total
cover", "scale density shall be". These are descriptive clauses. **A datasheet
caption is never one of them**, so under exact equality none of the 44 could
match, and `submittal_facts` holds zero rows so there is not even a label
vocabulary to test a mapping against.

Populating `field` with them would be worse than leaving it NULL: the column
would read as usable, the "0 of 762 comparable" measurement would vanish from
view, and every requirement would still fall through to MISSING_INFORMATION.
The phrase is therefore stored in a new `subject` column, which nothing joins
on, and `field` stays NULL until section 14's model-side label matching - which
`_match_fact`'s own docstring already names as unbuilt - exists.

**The rule: when the honest answer is "this cannot be done deterministically",
the deliverable is that sentence, not a column full of plausible strings.**

**A twenty-second, 2026-09-19 (extraction review): `needs_ocr_pages = 0` does
not mean no page needs OCR.**

The corpus reports `needs_ocr_pages = 0` and `recognised_pages = 0` across
7,914 pages, which reads as "no page needs OCR". It means no page was
COMPLETELY BLANK of extractable text.

SAES-B-017 page 44 is the counter-example: 30 text spans, ONE embedded image,
and the string "CAR-SEAL OPEN" present in the drawing and in zero chunks. The
legend beneath the figure extracts perfectly, which is exactly why the page
looks healthy - the heuristic asks whether a page has any extractable text, and
this page has plenty. The text inside the raster is invisible to it.

So the flag detects blank pages, not unreadable content, and a figure carrying
a valve's operating state is exactly the content a submittal review would need.

**The rule: a zero is only as strong as the question that produced it.** Before
reading a count as "none", state what it counts - "pages with no extractable
text at all" and "pages containing unread text" are different measurements and
only one of them was ever taken.

**A twenty-first, 2026-09-19 (extraction review): a predicted noise rate of
~113, measured at 1.**

Before extraction ran, the estimate was that 369 revision-history chunks across
195 standards match phrasing like "Deleted the word...", of which **113 contain
"shall" and would pass `_MANDATORY`** - enough to justify building a filter.

Measured in the actual output over five standards and 718 statement rows:
**1 row (0.1%)**, and that one is a genuine requirement that happens to contain
the phrase "previous revision". The filter was not built, because the evidence
for it evaporated when the thing was run.

The prediction was not unreasonable - it counted chunks matching a phrase, and
that count was probably right. It was a count of the WRONG POPULATION:
extraction reads sentences within clause-numbered chunks, and revision-history
tables are largely not that. Two measurements of different things, one used to
size the other.

**The rule: a rate predicted from a proxy population is a hypothesis.** Say
which population was counted, and re-measure on the real output before acting -
the measured defects in that same output were page-footer contamination (5.3%)
and duplicate rows (7.1%), neither of which anyone had predicted at all.

**A twentieth, 2026-09-19 (document roles): a test that covered one of two
render paths and looked complete.**

`DocumentsView` renders `DocumentCard` from TWO places - once per register type
group, and once for the "awaiting a type" group. The new bulk-selection test
gave both of its fixture documents a null `doc_type`, so every assertion landed
in the awaiting-a-type branch and the typed branch was never rendered at all.
The test asserted "a non-admin is offered no selection" and passed; mutation
M82 made the checkbox render for everyone at the typed site and **the test
still passed**.

Nothing about the test looked partial. It named the right property, asserted
the right absence, and its fixtures were ordinary. The gap was that "no
checkbox" is trivially true for a branch that never rendered - and an ABSENCE
assertion cannot tell the difference between "the feature correctly withheld
it" and "that code never ran". The fix was one line of fixture: type one
document and leave the other untyped, so both sites render on every run.

This is the fourth species of vacuous test in this file - **the test was not
standing where the feature could fail it** - and it is the first instance where
the missing ground was a second copy of the same JSX rather than a missing
call. It was caught by the harness and by nothing else, on the first run, which
is the outcome entry 14's rule was written for.

**A rule that follows: an assertion that something is ABSENT must also prove
the code path ran.** Assert a sibling element that should be there, or render
the case twice and differ them. `expect(...).not.toBeInTheDocument()` is the
easiest passing test in any codebase, and it passes hardest when nothing
rendered at all.

**A nineteenth, 2026-09-19 (phase 5B): the flagship case was silently
unevaluable because of a character class.**

`datasheets.measure_value("95 dB(A)")` returned the unit `dB`, not `dB(A)` -
the unit regex excluded parentheses, so the A-weighting was dropped. The
comparison engine then behaved correctly and REFUSED to compare `dB` against a
`dB(A)` limit, because `claims.same_unit` rightly holds that A-weighting is
part of what the number means. Phase 4's own tests asserted that distinction
and passed; they simply never fed a parenthesised unit through the extractor.

The effect is the part worth recording: **every noise comparison - the worked
case the entire master plan is written around - would have returned
NEEDS_ENGINEER_REVIEW with a unit-mismatch rationale.** Honest, traceable, and
completely useless, and nothing in phases 3B or 4 would have surfaced it
because neither phase ever compared two values. It took the first component
that actually CONSUMED the extracted units to expose it.

Two things follow. **A test that exercises a value end to end is worth more
than any number of tests of the pieces** - this is the second phase-4
extraction defect found by a phase-5 test, after prose being parsed as
measurements. And **a unit is not a string**: `dB` and `dB(A)` differ by two
characters and mean different things, which is exactly why `claims` refuses to
convert between them, and exactly why an extractor that quietly truncates one
into the other is worse than one that fails loudly.

**An eighteenth, 2026-09-18 (phase 5A verification): a production defect found
by suite flakiness, and a failure rate quoted without checking what else was
running.**

`submittal_review.ensure_schema()` - called by every read in that module -
held a conditional `DROP TABLE` / `CREATE TABLE` migrating `submittal_facts`.
Three full-suite runs of one unchanged tree gave three different results: two
permission tests failed, then a clean run, then
`test_access_routes::test_two_concurrent_requests_never_share_scope` failed
alone. Different victims each run, with no random-order plugin installed and
no hash-seed sensitivity (probed at seeds 0/1/2), is the signature of lock
contention rather than of ordering or data pollution - DDL on one SQLite
connection blocks readers on other connections, and the concurrency test
failing is what identified the mechanism.

**This was a production defect, not a test defect.** The same DDL would block
concurrent readers in the running application exactly as it did in the suite;
the first request after startup to trigger the rebuild could have stalled
whatever else was in flight. The fix moved the rebuild to
`migrate_facts_to_per_document()`, called once from `main.lifespan`, and two
source-assertion tests hold the shape: no `DROP TABLE`/`DROP INDEX` in
`ensure_schema`'s body, and the migration function is actually called at
startup. Both are the `test_the_upload_module_guards_the_stored_path` idiom,
because a behavioural test cannot reliably catch a timing race that only
appears in some fraction of runs - which is exactly how this one survived a
prior green suite.

**The retraction is about the number, not the diagnosis.** "2 of 3 runs
failed" was reported as an observed rate. Whether those three runs had the
machine to themselves was never checked at the time - a `TaskStop` call on a
later, unrelated job was later found to leave its child process running, which
is the kind of thing that goes unnoticed exactly when nobody is looking for it.
**If a second suite was alive during any of runs 1-3, the observed rate is
inflated, and inflated in the one direction that looks like the bug**: DDL
contention manufactures the same symptom the diagnosis was hunting for. This
does not weaken the diagnosis itself - the mechanism is real independent of
what else was running, and the concurrency test failing is consistent either
way - but it means **2-of-3 must be read as an uncontrolled observation, never
as a measured baseline**, and every later calculation against it (what failure
rate N clean runs would clear) inherits that uncertainty. Ten clean runs clears
a true rate of 0.3 comfortably; it does not clear 0.1; and if the true rate is
lower than 2-of-3 suggested, ten clean runs is weaker evidence than the
arithmetic implies. State counts and denominators together, and say when a
denominator was not itself controlled for.

**A fifteenth, 2026-09-18 (phase 4), and it is a correction to entry 14's
neighbour.** Phase 3B reported "SAES-A-105 IS NOT IN THIS REPOSITORY" and built
its argument on it. That was true of the REPOSITORY and false of the MACHINE:
the file is in `~/Downloads`, along with the two real client datasheets, and phase
4 found it in about a minute by looking outside the repo. The 3B statement was
literally accurate and practically misleading - it read as "this file does not
exist here" when what was true was "nobody has ingested it". **Absence from a
corpus is not absence from the world**, and the honest sentence names which one
was searched.

**A sixteenth, same phase: the fourth species of vacuous test.** Mutation M56
deleted the label guard that stops a value being promoted into a field name,
and the test meant to cover it passed. The reason is new: the test was defended
by a DIFFERENT guard. Prose with no number and no blank marker is dropped by
the fact gate whether or not the label guard exists, so the test never observed
the thing it was named after.

The four species now on record, and the shape they share:

  * **entry 6** - a migration test run against a table that was never old;
  * **entry 11** - an absence asserted before the screen could render;
  * **entry 13** - a helper called directly instead of the behaviour using it;
  * **entry 16** - a case already held by a different guard, so deleting this
    one changed nothing the test could see.

All four are the same failure: **the test was not standing where the feature
could fail it.** Three of the four were found only by mutation, which is the
argument for the harness and also its limit - it finds them one at a time, and
only where somebody thought to write the mutation.

**A thirteenth, 2026-09-18 (phase 3B): a unit test wearing a behaviour test's
name.** `test_character_fragmentation_is_not_accepted_as_a_table` called the
predicate `tables._is_fragmented(...)` directly. That proves the predicate
works and says nothing whatever about whether the pipeline uses it - mutation
M47 deleted the call site in `parse_page_tables` and the test passed happily.

This is now the THIRD distinct species of the same disease, and they are worth
listing together because each looked fine to its author:

  * **entry 6** - tested a migration against a table that was never old;
  * **entry 11** - asserted an absence before the screen could have rendered;
  * **entry 13** - tested a helper instead of the behaviour that depends on it.

The common shape: **the test never put itself in a position where the feature
could have failed it.** A migration with nothing to migrate, an assertion made
too early, a predicate called outside the pipeline that consumes it.

**A fourteenth, same round, and it is a number this document itself would have
carried:** the measured table parse rate was reported as "33 of 98 pages" and
then "29", and both were wrong. They counted shapes that `find_tables()`
returned WITHOUT READING THEM. Reading them showed `['DE','F','I','N','IT',
'I','O','N']` - the word DEFINITION cut into columns by the white space between
its letters - and `['T','H','E','O','R','E']`. The true rate after gating the
fragments is **21 of 98**. Standing rule 9 again: a number is not a measurement
until you can say what it counts, and "shapes the library returned" is not
"tables that were read".

**A twelfth, in the same round:** the `NameError` mutation mistake of entry ten
was made again, in the same harness, by the same author, one phase later. It is
recorded separately rather than folded into entry ten because a defect that
recurs after being written down is evidence about the RECORD, not about the
defect: standing rule 11, a documented hazard is not a guard. The reasoning now
lives in a comment at the mutation itself, where someone writing the next one
will be looking, rather than only in this file.

A seventh, of the same family but caused by tooling rather than by design: a shell
heredoc silently turned `\b` into the literal byte it names, 0x08, **three
separate times**. Each produced a regex that could never match, inside a rule
that looked fully implemented and had never fired once. A 0x08 is invisible in
an editor, in `sed` output and in a diff, and is syntactically valid inside a
string literal. `backend/tests/test_source_hygiene.py` now fails the build on
any stray control character.

It earned its place within the hour. Writing the paragraph above, the heredoc
ate the `\b` **in the sentence describing `\b` being eaten** - a sixth
instance, in the document about the pattern. The guard failed the build
immediately, naming the file, the line and the byte. That is the whole
argument for it: the previous three were found by accident, days apart, after
shipping.

### A sixth, and the worst of them: CI never ran the tests

Found while writing this section. `.github/workflows/` contained
`secret-scan.yml` and nothing else - gitleaks and the no-client-data guard. So
**"CI green" on roughly ten pull requests meant "no secrets leaked"** and
nothing whatever about the 407 backend and 89 frontend tests. A failing test
could be committed and merged, and was: the source-hygiene guard was red in the
commit that introduced it.

Model weights are gitignored, which is presumably why no test job existed -
without them most of the backend suite does not fail, it SKIPS, and a skipped
suite reports success. `scripts/fetch_models.py` stages them and exits
non-zero on a partial staging, and the CI job verifies the staging BEFORE
running the suite, so a half-armed run cannot pass as a clean one.

`.github/workflows/tests.yml` now runs pytest, vitest, `tsc -b` and the
production build on every push and pull request.

### A seventh: a written-down trap is not yet a guard

A reprocessing script omitted the `__main__` guard that Windows `spawn`
requires. The project had this hazard **documented** — PyMuPDF must run in
processes, and Windows re-imports `__main__` in each child — and the script
still fell into it, deleting book4's extracted pages before dying.

The lesson is not "remember the guard". It is that **a trap written down in a
document is not in the path of the tool that falls into it.** Knowledge in
prose protects nothing; only a check in the execution path does.

### An eighth, and the first one caught by a check rather than by luck

A heredoc ate a `\b` and wrote a literal 0x08 backspace byte into a source
file. This had happened seven times before and every previous instance was
found by accident. The eighth was caught by `test_source_hygiene.py`, which
named the file, the line and the byte.

Recorded because it is the first time this class of bug was stopped by a guard
instead of by noticing. That is the whole point of the rule below, observed
working.

### A ninth: a result file that certified a corpus it never inspected

`eval/run_eval.py` stamped `"corpus": data.get("corpus")` on every result — a
static string copied out of the **questions file**. It described what the
questions were written against and was written to the result regardless of what
was actually ingested. The 4,346 ms result claims `"3 documents: NORSOK,
book1, book2"` whether or not a fourth 1,400-page document was present.

The cost was concrete. A reported **superlinear latency growth, 1,915 ms at 3
documents to 4,346 ms at 4**, could not be checked against the record, because
no stored result could say which corpus it ran on. Every one of nine runs was
unattributable. It had to be re-measured from scratch — and **the growth did
not exist**: retrieval grew x1.04 for x1.79 the chunks, and the change was
machine state across a 40-minute gap.

Replaced with `observed_corpus()`, read from the database at run time —
document count, chunk count, retrievable count, excluded count, vector count
and a hash of the document ids — kept as `corpus_observed` **alongside** the
static `corpus_declared`, so a mismatch between what the questions assume and
what the run saw is visible rather than silently resolved in favour of the
claim. `machine_state()` records free RAM and whether the answer model is
resident, because that moves the headline number further than the corpus does.

`test_eval_provenance.py` reinstates the old field and confirms four of its
six tests go red against it.

### A twelfth: the design premise that was wrong about its own pipeline

The multi-document coverage design named the 16-slot shortlist cut as **"the
one place in this pipeline where candidates are dropped with no recorded
reason"**. It was not the one place. `deduplicate()` discarded near-identical
candidates and returned a shorter list saying nothing about it, and the pool
builder skipped chunks whose row had gone or had been marked non-retrievable,
also silently.

The cost would have been a false answer to the question the telemetry was built
to answer. **A candidate lost to dedup is indistinguishable from a candidate
that never existed**, so a document that contributed candidates and lost them
all to duplicate-merging would have read as a document that matched nothing —
and "was doc17 ever in the pool?" would have been answered wrongly with
apparent evidence. All five drop reasons are now recorded under one slug
vocabulary.

### A thirteenth: a taxonomy reviewed against its example, never tested against it

The same design specified a six-value status enum for per-document coverage. It
was reviewed carefully and it reads well. **None of its six values was true of
Q4** — the gold question the entire feature exists to measure.

doc17 was retrieved, so not `expected_not_retrieved`. Shortlisted, so not
`expected_not_shortlisted`. Scored **+2.104 against a -3.0 floor**, so not
`retrieved_not_credible`. Not in `supporting`, and not `answered`, and plainly
not `searched_no_match`. Had the enum shipped as designed, Q4 would have been
filed under whichever value was least wrong, and the coverage report would have
made a false statement about the one case it was built for.

This is the same family as the vacuous fixture: **a structure that cannot
produce the condition it claims to cover.** The fixture could not produce two
distinct documents; the enum could not express the outcome it was designed
around. Reviewing a taxonomy against an example is not testing it against that
example — the test is to take the real case and try to write its row.

Fixed by a seventh value, `credible_not_cited`, which names the fact in the
reader's terms rather than the mechanism: this document had a passage that
passed the credibility floor, and the answer did not use it.

### A fourteenth: the harness could not score the tier it documented

`eval/run_eval.py` documents `--tier generated` at the top of the file. Its
scorer could not read a generated answer at all.

Every scored field - the cited pages, the cited document, the cited clause, the
passage count, the returned text - read `answer_passages` or `passage`, and
**both are set only by the extract branch**. A Tier 2 answer sets `passages`
plus `cited`. So a generated answer scored zero passages, no pages, no
document, and empty text: `retrieval_correct` and `citation_correct` came out
false however well it had answered.

It surfaced the moment a question pinned itself to Tier 2. Question 17 answered
correctly - the right table, page 597, clause 15.3, values read off the row -
and the harness recorded `wrong page, wrong clause, pages []`. Fixing the
scorer moved the citation figure from 10/11 to **11/11**, which means the
harness had been under-reporting itself, in the safe direction, for as long as
anyone had been able to run it that way.

Nobody saw it because the harness had only ever been run at `--tier extract`.
That is the third instance of the same shape in this build: **the harness could
not see the defect because every question it asked avoided the condition.** The
P&ID false refusal needed an answer below rank 1; the token budget needed
evidence that was not prose; this needed a question asked at Tier 2.

The fix is one function, `evidence_of(result)`, used by every field that
previously read the extract shape directly, with tests for both tiers.

### The rule this produces

**Before trusting a check, confirm it fails when it should.** Plant the defect
it exists to catch and watch it go red. Two of the first five passed for weeks;
none failed loudly; two were found only by accident. Of the fourteen instances
now recorded, exactly one — the eighth — was caught by an automated check.

The twelfth and thirteenth were caught by reading a design against the code
while implementing it, and by taking the real case and trying to write its row.
That is diligence, not a check, and it does not scale — which is why the
thirteenth produced a standing rule rather than only a fix.

Corollary: **guard the guard.** Every check whose scope can silently shrink to
nothing needs a companion test asserting it still sees something — that the
scanner finds files, that the fixture list is non-empty, that the query matched
rows. `test_source_hygiene.py` does both: one test plants a backspace byte and
requires it to be caught, another asserts the scan covers more than forty files
so an empty sweep cannot pass as a clean one.

---

## The comparator that pointed the wrong way

2026-09-20. Requirement extraction had never been scheduled for 252 of the 272
standards (`docs/ZERO_REQUIREMENTS_CAUSE.md`). Running it through the real
admin endpoint for all 272 took the corpus from 3,158 requirements to 34,938,
and the rules a datasheet value can actually be compared against from **195 to
1,736** (1,746 after `bf4f5ab`, later the same day). The count going up was
true. It was also not the thing that mattered.

**129 of the 1,731 stored limits, across 79 standards, carried an operator
pointing the opposite way to the sentence they cite.** "shall not be less than
45 m" was stored as `< 45`. The pattern that finds a comparator listed
`not less than` but nothing covering `not **be** less than`, so the scan walked
past the negation and matched the bare `less than` behind it. `no less than`
failed the same way. A third wording, "but in no case shall it be less than
190 L/s", puts four words between the negation and the comparative and defeated
even the widened pattern; three more rows were inverted that way.

A flipped comparator is worse than a missing rule, and it is worse in a
specific way this project has a name for: it is a **false claim with a
citation attached**. The row quotes the standard correctly, names the right
clause and page, and asserts the opposite of what the clause says. A
non-compliant value passes; a compliant one is failed. Nothing in the pipeline
downstream can detect it, because every field except the operator is right.

**How it was caught: by reading fifteen rows.** The verification that had been
planned was "do the standards have requirements now", and the answer to that
was 272/272 — a true statement, from a correct query, that would have carried a
broken comparator column into a client demo. It surfaced only because the
request was to show three real requirements from five random standards with
their source text, and the source text disagreed with the operator beside it
in four of the fifteen. The user found the same defect independently on a copy.

The same gap existed in `claims._COMPARATOR_WORDS` as in
`requirements_3b._LIMIT` - standing rule 8, a claim living in two homes, and
fixing one would have left every limit parsed through `claims.measurements`
still inverted.

Two rows remain knowingly wrong and are NOT this defect: SAES-L-410 18.5.3 and
SAES-L-850 5.18.2 store `<= 8` (no unit) for "the bend radius shall be not less
than eight diameters (8D) for lines up to 8-inch NPS". The limit is spelled in
words, which the number pattern cannot see, so the match landed on the
applicability condition instead. Wrong span, not wrong direction, and recorded
here rather than fixed at the same time.

### The rule this produces

**A count going up is not evidence that what it counts is right.** Row counts,
coverage figures and "n of n" totals measure presence. Correctness has to be
read, and it has to be read against the source the row cites, not against the
row's own other fields - every other field of these 129 was correct. Where a
stored field decides a verdict, at least one verification must put that field
beside the sentence it came from and compare them by eye.

---

## Document status

Single source of truth: `documents.status`. Legal transitions are declared in
`app/states.py` and enforced by `check_transition`.

| Status | Set by | Means exactly | Does NOT mean |
|---|---|---|---|
| `queued` | upload | The row exists and the file is on disk | That anything is processing it |
| `extracting` | worker | Page extraction is in progress or interrupted part-way | That any page is searchable |
| `chunking` | `extract_document` on completion | Pages are extracted; chunking pending or interrupted | That chunks exist yet |
| `indexing_keyword` | `chunk_document` on completion **and on short-circuit** | Chunks exist; keyword index pending | That search works |
| `partially_searchable` | worker | Keyword search works; vectors still arriving | Ready. Never labelled ready |
| `ready` | worker, only when `embedded_count >= chunk_count` **and** `chunk_count > 0` | Keyword + vector search both complete | That every page was extractable — check `needs_ocr_pages` |
| `no_searchable_content` | worker, when `chunk_count == 0` after processing | Processing finished; nothing is searchable. `error_message` states which cause | Failure. Processing succeeded; the document is empty of usable text |
| `failed` | worker, on exception | Processing raised. `error_code` + safe `error_message` | That the document is unusable forever — it is resumable |

**Terminal:** `ready`, `no_searchable_content`, `failed`.
**Answerable:** `partially_searchable`, `ready`. Nothing else may serve a query.

`indexed_at` is set **only** on reaching a terminal state, and is the field to
trust for "did this finish", not `status` alone.

---

## Counts on the document record

| Field | Computed from | Trap it avoids |
|---|---|---|
| `page_count` | `fitz` page count, read once at extraction | `null` until the manifest is read — never assume 0 |
| `pages_done` | `COUNT(*) FROM pages` | Not a percentage; compare against `page_count` |
| `chunk_count` | `COUNT` of chunks with `retrievable = 1` | **Retrievable only.** What search can actually see |
| `chunk_count_total` | `COUNT` of all chunk rows | Includes front matter, contents, index and gate-rejected rows |
| `embedded_count` | `COUNT(*) FROM chunk_vectors` after each batch | Progress against `chunk_count`, not `chunk_count_total` |
| `needs_ocr_pages` | `SUM(pages.needs_ocr)` | **Detection only.** OCR is not implemented; these pages are not searchable |
| `equation_pages` | `SUM(pages.equation_heavy)` | Flags the worst pages, **not all** pages whose maths degraded. Not exhaustive |

`chunk_count` and `chunk_count_total` differ on nearly every real document.
Reporting only one of them is how "19% of pages vanished" stayed invisible.

---

## Worker health — `GET /api/health` → `ingestion`

| Field | Computed from | Notes |
|---|---|---|
| `alive` | thread `is_alive()` | Proves the thread exists, nothing more |
| `current_document` | document id being processed, `null` when idle | Idle is not the same as stuck |
| `seconds_since_heartbeat` | time since the loop last iterated | **Only proves the loop is spinning** |
| `seconds_since_progress` | time since a document last reached a *terminal* state | The honest progress signal |
| `documents_completed` | counter, incremented on a not-finished → finished transition | Resets when the process restarts |
| `pending_count` | count of documents in a non-terminal state, plus answerable ones with vectors outstanding | A backlog is visible without querying SQLite |
| `oldest_pending_age_seconds` | age of the oldest pending document's `uploaded_at` | Distinguishes a fresh queue from a stuck one |
| `stalled` | `not alive` **or** heartbeat > 120 s **or** (`pending_count > 0` **and** `seconds_since_progress` > 180 s) | Reflects whether work is *moving* |
| `stalled_reasons` | which of the above fired | Never just a bare boolean |
| `last_error` | `{code, message, document_id, stage, at}` | **Response-safe only.** Full tracebacks go to `backend/data/logs/rag-intelligence.log` |

An idle worker with an empty queue is **not** stalled. A worker alive and
ignoring a backlog **is**.

---

## Booleans on chunks and pages

| Field | Computed from | Trap |
|---|---|---|
| `chunks.retrievable` | `kind in {prose, table}` **and** the content-quality gate passes | Excluded rows are kept and readable at `?retrievable=false` |
| `chunks.quality_flags` | the gate's rejection reasons | `null` when retrievable |
| `pages.needs_ocr` | usable characters < 100 | Detection only |
| `pages.equation_heavy` | equation-token density ≥ 0.25 | Conservative; flags the worst, not all |

---

## Error codes

`internal` is reserved for genuine unexpected failure. A caller's mistake
returns `not_found`, `invalid_parameter`, `unknown_parameter` or
`confirm_required`; a rejected upload returns `not_pdf`, `encrypted_pdf`,
`too_large` or `duplicate`. Codes are declared in `app/errors.py` and a test
asserts no client error ever reports `internal`.

---

## Standing rules

1. A field must be derived from the thing it claims, not from something
   adjacent to it.
2. Any state that can be reached must be reachable *out of* — every
   non-terminal status is resumable by a running worker, tested without a
   restart.
3. No count is published alone when a second count changes its meaning
   (`chunk_count` always alongside `chunk_count_total`).
4. No rate is published from a near-zero denominator — `app/rates.py` returns
   `null` instead.
5. No API response carries a traceback, a path or a line number.
6. **A measurement records the state it ran against, read from that state.**
   Corpus counts and machine state come from the database and the OS at run
   time, never from a static declaration. A result that cannot say what it ran
   against is not a measurement.
7. **When you report a count of things found, state where you looked.** A
   count without a boundary reads as total. "50 call sites" and "no matches in
   the frontend" were both true and both incomplete, and neither said so.
8. **A test must be shown to FAIL against the unfixed code, or it is not
   evidence.** A test that has never been watched failing is an assertion that
   the fixtures reach the code, and that assertion is usually untested.
9. **A number is not a measurement until you can say what it counts.** Before
   quoting a figure, name the unit and the population, and check one case by
   hand. An internally consistent wrong number passes every automated check
   there is.
10. **Observing a step is not observing an outcome.** A test that asserts
   intermediate state must also assert terminal state. Watching the right
   thing happen says nothing about whether it worked.
11. **A documented hazard is not a guard.** If a trap is worth writing down, the
   check belongs in the path of the tool that can fall into it.
12. **A taxonomy is not tested until a real case has been written into it.**
   Reviewing an enum against an example proves only that it reads well. Take
   the case the feature exists for, try to fill in every field, and require
   that exactly one value is true. A structure that cannot express its own
   headline case will not fail loudly — it will file that case under whichever
   value is least wrong.
13. **A provenance field that no assertion reads is decoration.** Storing,
   typing and requiring it are not the safeguard. Where provenance decides
   what a claim may say, a test must assert the ABSENCE of the stronger claim
   — presence-only assertions pass while both claims are on screen.
14. **A check that can run against zero inputs must assert it ran against more
   than zero.** The rule the fixtures already carry, applied to tools. A type
   checker with no files, a scanner with no paths, a test filter that matched
   nothing — each exits 0 and reads as a pass. Before believing a tool's clean
   result, ask it what it covered (`--listFiles`, a count, a non-empty
   listing), and make the harness ask so a person does not have to.
15. **A test that never crosses the boundary cannot see a guard that lives on
   it.** Calling the function is not exercising the route: dependencies,
   authentication and the mode the suite pins are all outside the function and
   all decide whether a real caller gets through. Where a feature has a user
   who presses a button, at least one test must arrive the way that user does —
   signed in as they are, under the mode production runs in. Nine tests of the
   engineer's final code were green while no engineer could record one.

## Phase 0, 2026-09-20: five claims this project made that the machine refuted

Recorded by Claude Code in VS Code on ABUBAKAR, 2026-09-20, during the Phase 0
recovery. Evidence and locators for all five are in
`.cowork/CURRENT_STATE_AND_BLOCKERS.md` sections 9.1–9.8. Nothing here was
deleted from the files that made the claims; it is relabelled there.

**First: "`claims.py` and `keyword.py` contain unresolved conflict markers, and
the backend could not start."** Stated in `.cowork/CURRENT_STATE_AND_BLOCKERS.md`
section 4, in V3 section 5.1, and in the Phase 0 prompt built from them. Measured:
**zero** conflict markers in either file, both parse as valid Python 3.12, no
marker anywhere in `backend/app/`, and the backend starts and serves
`/api/health` in about three seconds. What was true instead: both files had been
hand-resolved in the working tree and never `git add`-ed, so the index kept three
stages while the files on disk were clean. Three consumers repeated the claim
because each read it from the one before.

**Second: the merge that was not a merge.** Section 8 found `.git/AUTO_MERGE`
with no `MERGE_HEAD` and reasoned to "most likely a STALE file left by a merge
whose conflicts were resolved and committed". Both premises were right and the
conclusion was wrong: unmerged index entries *with* no `MERGE_HEAD` is the
signature of `git stash apply`, which writes `AUTO_MERGE` and never writes
`MERGE_HEAD`. There was no merge, stale or otherwise — an unfinished
`git stash apply` was sitting in the index. The inference was labelled as an
inference, which is why it cost nothing; had it been labelled a fact, the next
agent would have deleted a file that was load-bearing.

**Third: "272 or 273 standards."** It is **272**, and the question was decidable
in one query the whole time: `SELECT document_role, COUNT(*) FROM
document_classification GROUP BY 1` → `COMPANY_STANDARD` 272,
`CONTRACTOR_SUBMITTAL` 3, 275 rows in `documents`. The discrepancy survived
several documents because nobody ran it. Note also that the role does not live
where two audits looked for it: `documents` has no role column.

**Fourth: "P-1000001 previously selected standards, then selected zero."** Two
different documents were compressed into one bug. P-1000001 has **never** selected
zero: it went 10 → 10 → **6**, with findings 1,609 → 815, between
2026-09-20T09:01Z and 10:04Z. The run that selected zero is **DS-0000-DAS-M-01**,
a different submittal, which also extracted **0** `submittal_facts`. A bug report
naming the wrong document sends the fix to the wrong code.

**Fifth, and this one is the recurring defect itself: a guard test that guards
nothing.** `test_exact_glossary_phrase_outranks_repeated_scattered_words` reads as
the test for the "prioritize exact glossary phrases" feature of commit `8d30838`.
During Phase 0 that feature was found disconnected — `build_phrase_query` defined,
unit-tested, and called by nothing. The test was failing, which looked like the
test catching exactly that. It was not: it was failing on an unrelated `TypeError`
from a missing access-scope argument. With the feature reconnected and then
deliberately disabled again (`phrase = ""`), the test **passed**. bm25 already
ranks the glossary chunk first, so this test would pass with the feature deleted.
It has never protected anything. Entry fourteen and the eighth already say a test
must be watched failing; this one *was* watched failing, for the wrong reason,
which is a failure mode neither entry covers.

### The rule this produces

16. **A test watched failing is evidence only once you know which assertion
   failed.** "It goes red when the feature is broken" is the claim; "it went red
   while the feature was broken" is what a failing run shows, and the two differ
   whenever anything else in the path can also throw. Read the failure, not the
   exit status: if the test died before reaching its assertion — an import error,
   a `TypeError` in a helper, a fixture that never loaded — it has told you
   nothing about the feature. The proof is the other direction: with everything
   else working, remove the feature alone and require the assertion itself to
   fail.

17. **A claim repeated by three documents still has one source.** Each of the
   five above was carried forward by consumers who cited the document before
   them, and agreement between them was read as corroboration. Before acting on
   an inherited fact, find the command that produced it. Where no document can
   name one — no query, no path, no timestamp, no output — the fact is a rumour
   with footnotes, however many files repeat it.

## GitHub transfer, 2026-09-21: an audit finding that was itself false

Recorded by Claude Code in VS Code on ABUBAKAR, 2026-09-21, during Step 2 of the
GitHub transfer.

**"README.md never tells a fresh machine to run `npm install` for the frontend."**
Reported as a Part 0.4a hygiene finding of `.cowork/EXECUTE-GITHUB-TRANSFER.md`,
and carried by the owner into the Step 2 order as "README.md: add the missing
frontend npm install step". Measured when the fix was about to be written: the
README's *Getting started*, Step 3 "Frontend", already runs `cd frontend`,
`npm ci`, `npx tsc -b` and `npm run test`. `npm ci` is the stricter install from
the lockfile. The audit had searched for the literal string `npm install` and
read its absence as the absence of the step. **No README change was made**; adding
a second, looser install step would have been a regression. This is rule 17's
failure one hop earlier: the claim had a source command, and the command
answered a narrower question than the one the finding asked.

### The rule this produces

18. **A search that finds nothing proves only that its pattern is absent.** Before
   reporting "X is missing", name every form X could take (`npm install`,
   `npm ci`, `npm i`, `pnpm install`) and read the section where X would live.
   A grep is a lead, not a verdict.

## B34, 2026-09-22: the number guard blamed the evidence for standard names, and the harness could credit one mutation with another's verdict

Recorded by Claude Code in VS Code on ABUBAKAR, 2026-09-22.

**First: "carries a number no cited span contains: 4.0".** The analysis answer path
(`synthesis._cite`, used by Focused and Comprehensive summaries and by the advisory
recommendation) deletes any generated sentence carrying a number that no cited passage
contains. It exempted numerals that name a place - "doc17.pdf", "Section 4",
"Table 1" - but not a standard's own number. So "SAES-H-004 outlines a total system
minimum of 150 micrometers [S4]" was deleted, reported as containing the unsupported
quantity 4.0: the "004" of the standard's name. This corpus is Saudi Aramco standards;
the model names one in nearly every sentence. Reproduced live on 2026-09-21: a Focused
summary over the correct coatings passages (SAES-H-001, SAES-H-004) came back empty,
every sentence removed, and the user saw only a refusal. The reason string was a false
claim about the evidence - it said the passage lacked a value the sentence never stated.

**Fixed with a CLOSED grammar** (`synthesis._STANDARD_IDENTIFIER`), built from the
identifier shapes that occur in the indexed text: SAES-X-NN..NNNN (optional letter),
NN-SAMSS-NNN, SAEP-NN..NNNN, SABP-X-NNN, SAER-NNNN(N). Nothing looser. The grammar
removes the identifier's own text and never other tokens sharing its digits, so a
fabricated value disguised as a standard number - "per SAES-H-150, apply 150
micrometers" over a passage without 150 - is still rejected; two loosening mutations
(by value, and by letting the identifier swallow following text) fail that test.

**Second, found while proving the first: the mutation harness could report a verdict
belonging to a different mutation.** Python reuses a cached `.pyc` when the source's
size and whole-second mtime match. M296 and M297 each shortened `synthesis.py` by
exactly 23 characters within one second, so M297's test run executed M296's mutant and
reported **NOT DETECTED** for a mutation its tests do detect (confirmed by applying it by
hand: 2 failed). The same mechanism can equally produce a false DETECTED. Any past
verdict from two same-file, same-size-delta mutations run back to back was exposed to
it. **Fixed:** the harness runs pytest with `-B` and deletes the mutated module's cached
bytecode before each run; the whole harness was re-run after the fix.

### The rules this produces

19. **An exemption from a safety check is a closed list, measured from the data, with a
   test that a disguised violation still fails.** "Standard numbers are not
   measurements" is true of `SAES-H-004` and false of `150` written beside it; a rule
   that cannot tell them apart has disabled the check it was meant to refine.

20. **A harness verdict is evidence only if the run executed the code under test.**
   Stale bytecode, a cached build or a warm process can each run the previous state.
   Make the runner unable to reuse compiled state, not merely unlikely to.

---

## Standards inventory, 2026-09-24: `effective_date` was not stored as ISO, despite saying so

Recorded by Claude Code (Cowork, desktop app) on ABUBAKAR, 2026-09-24.

**The claim.** `standards_inventory.py`'s own module docstring, written the same
session, described `effective_date` as a field the cover-page backfill would store
alongside `document_number` and `revision`, each "a real fact... never guessed." What
it actually stored for the date was the cover page's own collapsed prose - `"18 August
2019"` - not `YYYY-MM-DD`. Nothing in the code or its tests asserted the ISO shape; the
tests checked only that *a* value and *a* page were recorded, which the prose form
satisfied just as well as ISO would have.

**How it surfaced.** The owner, reviewing the field-count report before approving the
live backfill, asked this system to confirm dates were stored as ISO with the original
quoted text kept - not asked to trust the earlier report. Querying the live database
directly showed every `effective_date` was prose, not ISO. The honest answer was "no,"
reported as such rather than reframed.

**Fixed** (`_to_iso_date`, PR #206): the extractor now parses all three cover-page date
spellings into `YYYY-MM-DD` and stores that, while the document's own words stay
unchanged in `effective_date_evidence`'s quote. The 230 rows already written in prose by
the first live backfill were corrected in place (`scripts/fix_effective_date_iso.py
--live`, under the same backup-first guard), re-deriving each ISO value from the SAME
stored quote via the SAME parser the extractor uses - not a second, independently
written parser that could itself disagree.

### The rule this produces

21. **A field's own name is not a test of its shape.** A test that checks "a value was
   recorded" passes whether that value is `"18 August 2019"` or `"2019-08-18"` -
   neither the code nor the tests caught the gap until the STORED FORMAT itself was
   checked, on request, against what the field's own documented contract promised.
   When a field name implies a specific representation (ISO date, a normalised key, a
   canonical unit), a test must assert the representation, not merely that something
   landed in the column.

---

## CRS export, 2026-09-27 (honesty audit entry 69): "issue to contractor" carried no gate at all

Recorded by Claude Code in VS Code on ABUBAKAR, 2026-09-27.

**The claim.** `docs/review-fixes-log.md` (2d, owner decision 2026-09-27) documents two
CRS export copies: "internal review copy" (default) and "issue to contractor", the
latter with the "AI Review Comments" column and every unconfirmed AI item removed. The
document reads as though "issue to contractor" is the copy safe to send outside the
building once an engineer has looked at the AI's unconfirmed items - but nothing in the
code ever asked whether an engineer had recorded a final code (`review_runs.
engineer_final_code`) on the run before allowing that copy out. `GET
/api/reviews/runs/{id}/crs?copy=issue` and the frontend's "Export CRS - issue to
contractor" button both worked identically whether or not `engineer_final_code` was
NULL - a run the AI had only recommended a code for, never one an engineer had signed,
could be exported and issued to a contractor exactly like a decided one, with the CRS's
own `recommended_code_status` correctly printing "not yet decided" but nothing refusing
the export itself. A search of the whole repository (backend, frontend, `docs/`,
`scripts/mutations/`) turned up no other place this gate was even partially enforced -
this was not a second, unfixed copy of an existing rule; the rule had never been written
into the software at all, only into the description of what the two copies contain.

**How it surfaced.** Owner order (2026-09-27): "Export CRS - issue to contractor" must
be blocked until `engineer_final_code` is set on the review run - stated as a
requirement to implement, not as something already believed broken, which is itself
notable: the gap had not been noticed until asked for directly.

**Fixed:** `export_review_crs` (`backend/app/main.py`) now refuses `copy=issue` with
HTTP 409 (`errors.CODE_NOT_DECIDED`) when the run's `engineer_final_code` is NULL; the
"internal" copy is unaffected. `ReviewRunsView.tsx` disables the "Export CRS - issue to
contractor" button under the same condition and shows "An engineer must record the
final code before issue." Both are proven by mutation (`M1130`, `M1131` in
`scripts/mutations/review_decisions.py`): reverting either change is DETECTED by
`test_the_issue_copy_is_refused_until_an_engineer_decides`
(`backend/tests/test_crs_endpoint.py`) or the new "SAFETY GATE" test in
`ReviewRunsView.crsPreview.test.tsx`, respectively.

### The rule this produces

22. **A rule documented as a copy's contents is not a rule enforced in the code that
   produces the copy.** `docs/review-fixes-log.md` said what "issue to contractor"
   leaves out; it never said what stops the export when the precondition for issuing it
   at all - an engineer's decision - has not been met, and neither did any route. A
   privacy- or safety-relevant distinction between two export modes needs its own
   gate and its own test, not just its own paragraph in a fixes log.

---

## Readiness strip, 2026-09-27 (honesty audit entry 70): the page ledger's own reason for an unread page was computed and then thrown away

Recorded by Claude Code in VS Code on ABUBAKAR, 2026-09-27.

**The claim.** PR #285 (commit `93a78ae`, "fix: page ledger reports the real vision-routing
decision, not a stale placeholder") fixed `page_ledger.py` so every page's ledger row
carries a real, specific reason it did or did not read into fields - "no label-value
pairs recovered from this page", "vision reader not run (page could not be rendered)",
"read only by the page reader", and so on - and `page_ledger.coverage()` has always
exposed these, keyed by page, as `not_read_reasons`. The reasonable reading of that fix
is that an engineer looking at "Read unread pages" on the review screen would now see
why each page was unread. They would not: `_readiness_payload` (`backend/app/main.py`)
read `pages.get("pages_not_read_into_fields")` for the page numbers and never once read
`pages.get("not_read_reasons")`, so the number reached `schemas.ReviewReadiness` and the
frontend and the reason - computed, correct, sitting right next to it in the same dict -
did not. The screen said a page was unread and nothing about why, the exact "not
mentioned" silence CLAUDE.md rule 4 forbids, for every submittal that has ever had an
unread page.

**How it surfaced.** Owner order (2026-09-27): the readiness payload must show a reason
per still-unread page, not a bare "unread" - traced from the PR #285 ledger fix through
`_readiness_payload` to the frontend and found to stop midway, at the route that builds
the API response.

**Fixed:** `_readiness_payload` now carries `pages.get("not_read_reasons") or {}` as
`unread_page_reasons`; `schemas.ReviewReadiness` and `contracts/types.ts` both gained the
field (the single source of truth for the frontend type, per CLAUDE.md rule 8); and
`ReviewRunsView.tsx`'s readiness strip prints one line per unread page naming its reason,
falling back to "reason not recorded" only when the ledger genuinely has none. Proven by
mutation (`M1133`, `M1134` in `scripts/mutations/review_screen.py`): reverting either
change is DETECTED by `test_an_unread_page_carries_its_own_reason_not_a_bare_unread`
(`backend/tests/test_review_screen.py`) or the new "HONESTY GROUP" test in
`ReviewRunsView.screen.test.tsx`, respectively.

### The rule this produces

23. **A value computed for a purpose is not delivered until it reaches the screen that
   purpose was for.** `page_ledger.coverage()` computing `not_read_reasons` correctly did
   not make the reason visible to anyone; the field has to be threaded through every
   layer between the computation and the pixel - the route's response dict, the response
   schema, the frontend's own copy of that schema, and the component that renders it -
   and a test should exist at the layer where the thread is likeliest to be dropped: the
   boundary between "the code that computes it" and "the code that returns it."

---

## CRS export, 2026-09-27 (honesty audit entry 71): an unconfirmed AI/web item's "Comment By" was blank, not "unconfirmed"

Recorded by Claude Code in VS Code on ABUBAKAR, 2026-09-27.

**The claim.** `crs_mapping.build_crs_rows` gives a kind C (`ai_engineering_check`) or
kind D (`web_standard_check`) item a `comment_by` of `"AI engineering check, confirmed by
<name>"` or `"Web check, confirmed by <name>"` once an engineer confirms it - but before
confirmation, `comment_by` was the empty string `""`. The row still existed, its text
still sat in the "AI Review Comments" column (`ai_review_comment`), and the sheet's
"Comment By" column for that row was simply blank. A blank cell in a byline column reads
as a rendering fault or an oversight, not as "this is a draft, not yet confirmed" - the
one thing that column exists to say. `backend/tests/test_review_ai_check.py`'s own
`test_an_unconfirmed_item_is_only_in_the_ai_column_of_the_internal_copy` asserted
`row["comment_by"] == ""` outright: the blank was not an oversight the tests missed, it
was the documented, intended shape.

**How it surfaced.** Owner order (2026-09-27): the "Comment By" column for an
unconfirmed AI-originated row must read "AI - engineer to confirm", never blank -
traced to `crs_mapping.build_crs_rows`'s AI/web engineering-check loop, the single place
`comment_by` is decided for these two kinds.

**Fixed:** `crs_mapping.py` gained `_AI_UNCONFIRMED_BY = "AI - engineer to confirm"` and
`_WEB_UNCONFIRMED_BY = "Web check - engineer to confirm"`, and an unconfirmed kind C or D
row's `comment_by` is now one of these rather than `""`. Proven by mutation (`M1132` in
`scripts/mutations/review_ai_check.py`): reverting the change is DETECTED by the new
`test_an_unconfirmed_items_comment_by_is_never_blank`
(`backend/tests/test_review_ai_check.py`).

**Found in the same code while fixing this, and left as found-but-not-fixed:** two
mutation entries in `scripts/mutations/review_ai_check.py` (`M1034`, `M1038`) have had
stale anchors since an earlier, unrelated refactor merged the kind C and kind D origin
checks - they currently report a harness ERROR, not a verdict. Re-anchoring `M1038` to
the current text additionally reveals its own test does not detect it:
`build_crs_rows` already drops every rejected finding at its own top (`findings = [f for
f in findings if not _rejected(f)]`, before any per-origin loop runs), so the inner
`f.get("approval_status") == "rejected"` check the mutation targets is dead code -
removing it changes nothing a test can observe. Fixing this needs a design decision
(delete the dead inner check, or find what the outer filter does not already cover)
outside this task's scope; `M1034` was re-anchored (it is not dead code - it still
decides which prefix a CONFIRMED row gets) and confirmed DETECTED.

### The rule this produces

24. **"Not yet confirmed" is a state, and a state is not the same as nothing.** A field
   that identifies WHO said something is never correct left blank for a row that exists
   and has content - the fix is not "leave it empty until an engineer acts," it is "say
   whose draft it is now, and say whose confirmation it carries once someone gives one."
   A test that asserts the blank as the intended shape (as this project's own test did)
   turns the defect into a specification; read what a test proves as carefully as what
   it merely permits to pass.

## Follow-up audit, 2026-09-27 (honesty audit entries 72-76): five claims the code did not keep

Recorded by Claude (Cowork) on 2026-09-27, from a static audit of `main` at `9ac07cf`
whose five findings were each re-verified against the code before fixing. Each fix is
on its own branch, with a test proven by mutation (the test fails with the fix
reverted). Nothing here was run against the live database.

- **72 - the USD cap.** The most serious: real money. Four Claude routes could spend
  past the owner's USD 5 per step / USD 20 total limits, and their spend was booked in a
  ledger the limit never read. Two ledgers for one budget is the defect; one wrapper
  (`claude_spend.metered`) inside `_model_call_or_409(step)` now serves every route.
  Still open and recorded in `CLAUDE.md`: these routes do not check
  `REASONING_PROVIDER=claude` (audit of 2026-09-25, finding 1).
- **73 - compressor checklists.** A fix for "a label the table does not know gets
  nothing" introduced two labels the table did not know. The new test enumerates the
  classifier's own vocabulary, so the two lists cannot drift apart without a failure.
- **74 - conflict reported as absence.** Rule 4 ("not mentioned is never compliant")
  has a mirror image: "contradicted is never not-mentioned".
- **75 - the edition guard.** A safety guarantee written in a docstring and tested as a
  helper, but not in the path. `edition_differs(None, ...)` returns False, meaning "not
  proven different", which is not "same"; `edition_confirmed_same()` is now the only
  way into `compare()`.
- **76 - null as 0.** The CPU card beside it already had the guard; the Disk card did
  not. The same `?? 0` sweep found `WorkerPanel`.

### The rule this produces

25. **A helper that exists and is tested is not a guarantee until the path calls it,
   and a limit is not a limit until every caller meets it.** Three of these five
   (72, 73, 75) are the same shape: the protective code was written, tested in
   isolation, and not reached by the route that needed it. When recording a guarantee,
   name the route that enforces it and test through that route.

## Entry 77, 2026-09-29: the CRS said two things about its own columns that practice contradicts

- **77 - "Final Resolution belongs to the contractor", and "Item No" as a reference.**
  `crs_export.CONTRACTOR_COLUMNS`, both `build_crs` docstrings, the preview route and
  `schemas.CrsPreviewRow` all stated that Contractor's Response AND Final Resolution
  "belong to the contractor" and are "ALWAYS empty". Checked against CRS guides and
  document-control systems: only the reviewer closes a comment, so Final Resolution is
  the company's column. Separately, Item No was 1..N and renumbered on every export,
  and the digest reference changed with every review run, so neither was the
  "permanent and never reused" comment ID the practice requires. Fixed together:
  `crs_numbers` gives an engineer's comment `CRS-<submittal no>-001` in Item No (minted
  by the write routes, never the export, which still writes nothing), and Final
  Resolution prints its Open/Closed status, closed only by a signed-in reviewer. Every
  home of the old claim was corrected (rule 8). The on-screen preview repeated the
  claim in markup: it hard-coded both reply columns as empty cells, so a reply or a
  closure would never have shown on screen even once the data existed. It now
  renders what the server's sheet says, like every other column.

### The rule this produces

26. **A claim about what a column MEANS is a claim about the domain, and needs a
   source.** "Belongs to the contractor" was written as fact and repeated in five
   places without anyone checking how the industry uses the column.

## Entry 78, 2026-09-29: "tsc clean" was reported from a check that checks nothing

- **78 - the wrong typecheck, reported as passing.** The CRS reply-loop commit
  (`7ba3da5`) and its VS Code prompt reported "`tsc --noEmit -p .` clean". That command
  checks ZERO files here - `frontend/tsconfig.json` is a solution file with `"files": []`
  - which `.github/workflows/tests.yml` already says in a comment. CI's `npx tsc -b`
  failed PR #327 at once on a real error: `CrsCommentControls.tsx` read `row_kind`, a
  field `contracts/types.ts` never declared. Fixed in the next commit, with `tsc -b`, the
  lint, the production build and the bundle budget all run locally first - the CI job's
  own steps, not a remembered shortcut.

### The rule this produces

27. **Run the CI job's own commands, copied from the workflow file, before calling a
   change clean.** A check from memory can pass because it checks nothing.

## Entry 79, 2026-09-29: "the submittal number, captured at upload" - nothing captured it

- **79 - the CRS's "Submittal No." read a field no upload fills.** `_crs_content`'s
  docstring, `crs_export.HEADER_FIELDS`' comment and a test helper all said the number
  came from `transmittal_number` "captured at upload". No upload captures it: the only
  place it is set is an optional field in the metadata editor. Measured on the owner's
  real database (counts only): 0 of 3 submittals had it, while 3 of 3 had a
  `document_number` the classifier had read from the datasheet's own page (matching the
  filename every time). The sheet printed a blank beside a number it already held, and
  the permanent comment numbers of PR #327 were keyed on the same empty field. Worse,
  a transmittal number changes with every submission, so even when filled it would have
  started a new comment sequence on every resubmittal and broken carry-forward.
  Fixed: comments are numbered by the DOCUMENT number (fixed per document once its
  first comment is numbered, so a later edit cannot renumber an issued comment); the
  header prints a number an engineer recorded, else the document number and revision.

### The rule this produces

28. **Before building on a field, count how often it is actually filled on real data.**
   A field that exists in the schema is not a field anything populates.

## Entry 80, 2026-09-29: "only one thread migrates, so no statement can be told the schema changed" - a reader was

- **80 - PR #332 said its lock closed the migration race (#325).** Its commit message
  and the comment on `db._migration_lock` said that with one migrator at a time "no
  statement can be told the schema changed by a sibling thread". It was measured only
  against migrators racing migrators (`test_migration_race`, 1,500 calls, 0 failures).
  An hour after merge, `main` 35e4c2c failed on `test_access_routes.py::
  test_two_concurrent_requests_never_share_scope`: a plain `SELECT` in
  `access.scope_for_user` (access.py:147) told "database schema has changed" while the
  other request thread ran a first-time migration (traced: about 40 CREATE/ALTER
  statements on a fresh database). A reader takes no migration lock, and must not.
  Fixed: every connection the app opens is a `SchemaRetryConnection`, whose `execute`
  re-runs a statement SQLite rejected with SQLITE_SCHEMA - safe because the statement
  had not run - bounded, and raising past the limit. The lock stays: it keeps two
  migrators apart, which it does.

### The rule this produces

29. **A concurrency fix is tested against every kind of party to the race, not only the
   kind that was seen failing.** "Migrators cannot overlap" is not "no statement can be
   told the schema changed".

## Entry 81, 2026-09-29: "a confirmed comment always keeps its number and its name over a re-run's draft" - a test that passed by landing in the same second

- **81 - after a re-run, a confirmed CRS comment was printed as the machine's draft.**
  PR #327's `test_the_number_survives_a_re_export_and_a_re_run` confirmed a comment and
  re-ran the review inside one second. Finding timestamps have one-second resolution and
  the CRS reads findings `ORDER BY updated_at DESC`, so the confirmed finding and the
  re-run's fresh draft about the same field TIED, and the row that merges them took its
  "Comment By" from whichever SQLite returned first. The test passed about 19 times in 20
  (it failed once on CI, 2026-09-29, and 1 in 20 locally). Every REAL re-run happens a
  second or more later, where the order is not a tie: the newer draft always led, and
  the engineer's permanent number was printed beside "AI Review" instead of "AI Review,
  confirmed by <name>" - reproduced deterministically by making the confirmation older.
  Fixed: a confirmed finding leads its group whatever the order; the test now makes the
  confirmation older than the re-run, as in real use, and fails every time without the
  fix (M1370). An edited comment was never affected: its own wording is never grouped.

### The rule this produces

30. **A test that orders by a timestamp must control the timestamps.** Two steps inside
   one second are a tie, and a tie is a coin toss that usually lands the easy way.

## Entry 82, 2026-09-29: the client's company name was in shipped code and docs - the naming rule was not checked before merge

- **82 - CLAUDE.md's standing rule ("the client's name must not appear in code, docs or
  UI") was violated by a feature that merged the same day it was written.** Commit
  `474926c` (Cowork, `feat/standards-acquisition`, 2026-09-29) introduced
  `backend/app/standards_acquisition.py` and its test with the client's company name
  in their module docstrings, and the commit's own message and the PR title repeated
  it. Neither the PR's own CI (gitleaks scans for secrets, not names) nor the reviewing
  session's read of the diff caught it before merge; it was found afterward, by grep,
  while investigating an unrelated gitleaks false positive on the same branch. A wider
  sweep of the whole repository (`git grep -i`) found the name already present, as prose,
  in 38 more files predating this commit - a standing, unenforced gap, not a one-off.
  Fixed in `fix/remove-client-name`: every prose/docstring occurrence found by the sweep
  replaced with neutral wording ("the client", "the client's own"); the small set that
  must keep the literal string to function - the GitHub repository slug (owner-only to
  rename, per this same rule), a weak-password blocklist entry, a market-search
  allow-list token, a privacy leak-check test, and the page-footer regex that matches
  the client's own real, literally-printed document boilerplate - kept and named, with
  its reason, in that PR's description. History was NOT rewritten: `474926c` and every
  commit built on it (through the four-pieces and last-lines merges) still carry the
  name in git history; no force-push. `.githooks/pre-commit`'s client-identifier scan
  (section 2b) could have caught this in NEW lines at commit time, but ships disabled
  by default (no `.githooks/client-identifiers.local` on this machine) and was silent
  throughout.

### The rule this produces

31. **A naming or privacy rule stated in CLAUDE.md is not enforced by being stated.**
   Either a CI gate checks it on every PR, or it is found later by someone reading for
   something else - as this one was. `.githooks/client-identifiers.local` existing and
   being populated is the difference between those two, and it does not exist yet.

## Entry 83, 2026-09-30: "old chunks are detected stale" - the mutation meant to prove it never could

- **83 - M1240 ("CHUNKER_VERSION not bumped: old chunks are not detected stale") was
  NOT DETECTED, and could not be.** Its target,
  `test_chunking_quality.py::test_chunks_from_the_previous_chunker_are_stale`,
  computes a signature with `CHUNKER_VERSION - 1` and asserts it differs from the
  stored one. Whatever number the file holds, that number minus one differs from it,
  so the test passes when the version is NOT bumped - exactly the defect M1240
  describes. Measured 2026-09-30 by running the harness on `main` (`fa4bd28`):
  `M1240 [NOT DETECTED] ... 1 passed`. The entry was re-anchored from "6" to "7" in
  `fix/chunking-last-lines` (Cowork, 2026-09-29) without the record showing it was
  re-run and detected. Found while bumping the version to 8 for context notes.
  Fixed in `feat/context-notes-and-tables`: a new test pins the floor the feature
  needs (`int(CHUNKER_VERSION) >= 8` - a chunk made before the chain existed must
  read as stale), M1240 re-targeted to it and re-run: DETECTED. The old test is kept:
  it still proves the signature carries the version.

### The rule this produces

32. **A mutation re-anchored is a mutation not yet proven.** Changing an anchor or a
   replacement is a new claim; run `scripts/mutation_check.py --only <id>` and record
   DETECTED before saying it holds.

## Entries 84-90, 2026-09-30: a whole-system audit (seven parallel reviews and an end-to-end run on synthetic documents)

Each finding below was reproduced by running code before it was fixed on `fix/audit-2026-09-30`; each fix has a test that fails without it and a mutation that proves the test (M1430-M1553, 172/172 DETECTED at integration, with every re-anchored older mutation re-run).

- **84 - "verified" did not mean the number was on the page.** A one-word quote ("the") passed the citation check (`model_evidence`); `verify_claims` never checked a sentence's figures, and a comment in `answer.py` said the Claude-lane quote check "already covers" the figure check - false; the passage side was never stripped of clause/table numbers, so "clause 6" supported "6 mm"; a 1% "rounding" tolerance accepted 17.4 for 17.24; the image-page notice announced points that had been removed.
- **85 - the CRS could state false breaches.** Equipment-specific exceptions were documented and never applied (no production caller passed the equipment); "shall not", "or", ceilings and "not required" were misread; untagged datasheet fields counted as missing per tag; the one-field-per-line "Label : value" layout was misread; engineer rejections and acceptances were lost on re-run (only `confirmed_by` was kept); a test (`test_an_open_comment_is_carried_forward...`) certified the defect of issuing a rejected, never-issued comment; the rationale "unit 'mm' and 'mm' cannot be compared" was false; Excel cells could become live formulas and one control character failed the whole export.
- **86 - re-processing claims.** The chunker said it deleted only orphaned vectors and deleted all of them; `embed_pending` claimed legacy vectors were upgraded whenever processed; `ocr.py` said "one page failing is one page failing" while an engine failure failed the document; `ocr.py` and `docs/code-review/ingestion.md` claimed a `jobs.last_completed_batch` checkpoint nothing wrote; `reindex_chunking.py` said "every chunk is re-embedded", true only because of the vector bug; finishing a document marked every job of it done.
- **87 - the USD caps.** "Enforced before a call leaves" was false under concurrency (10 threads took a USD 5 step to 5.80); failed and cut-off calls wrote no ledger line; Claude-first chat's `cost_usd` showed the last call only; "spending cap would be exceeded" was shown for network and HTTP errors.
- **88 - security and privacy.** `docs/limitations.md` called the CI client-document guard "verified by deliberate failure tests" while it only checked extensions and its exclusion path matched nothing - PNG, CSV and JSON with real document names, a tag and quoted clause text reached the PUBLIC repository (owner action: repository visibility and history); `.gitleaks.toml` allow-listed all of `.env.example`; `config.py` said "never 0.0.0.0" with nothing enforcing it; a deliverable PATCH wrote before returning 404; a password reset did not end existing sessions; DNS rebinding reached the whole corpus in the default mode.
- **89 - chat.** The redesign log said the web phrase is "built from your one question only" while consent showed Claude's phrase and sent another; the withhold-on-revoke claim was false for rewrites of stopped answers, which were also labelled "General knowledge"; Claude-first put prior turns (with quoted document text) in the system prompt; Claude-first ignored the conversation's document scope.
- **90 - mutations that proved nothing.** Found while re-running the registry: M474, M1038, M450, M589, M566, M573, M797, M910, M1269, M1279 have anchors that no longer match (harness error - never applied), and M476, M803, M911 are NOT DETECTED. Each reported a feature as protected that it no longer protected. Not fixed in this change; listed so they are not counted as coverage. Fixed (2026-10-01): all 13 re-run first and found exactly as listed, then repaired. Ten stale anchors or targets re-pointed at the current code (M474 keyword, M450, M476, M589, M566, M573, M797, M910, M1269, M1279) and M1038 re-anchored on the real rejection filter (the old anchor was a redundant inner check; the new one removes the rejection before both guards). M476 was also guarding a dead argument (`build_crs_rows` ignores `unread_pages`; the Review notes carry the pages). The three NOT DETECTED were vacuous tests: M803 (dotted numbers with no letter are never furniture since audit F2, so the guard was only reachable by a lettered clause number - new test), M911 (the gap tolerance of audit F4 closed the test's one-number gap by itself - gap widened), M476 (re-anchored, existing test then detects). All 13 are now DETECTED. A sample run of the registry then found three more stale anchors of the same kind (M587, M1022, M1270), re-anchored and DETECTED; the other ~1350 mutations were not re-run, so more may exist. Remains: the redundant inner `rejected` check in `crs_mapping.py` is still in the code, and `build_crs_rows` still takes an unused `unread_pages` argument.

### The rule this produces

33. **An audit of the whole system finds what feature-by-feature tests do not.** Every entry above had passing tests. Run the end-to-end synthetic run and the full mutation registry before a release, not only the tests of the feature being changed.

- **91 - the requirements API could not return what the extractor stores.** `schemas.RequirementType` (and `contracts/types.ts`) listed three requirement types while `requirements_3b` also stores `applicability_trigger`, `relative_limit` and `table_row`; `requirements_3b`'s own comment pointed at the schema as its vocabulary. A standard holding any such row would fail its requirements list with a 500 (found 2026-09-30 by the frontend contract-drift test; not reproduced against the live database). Fixed: the schema, the TypeScript type and a new `STORED_REQUIREMENT_TYPES` agree, pinned by `tests/test_requirement_types_contract.py` (M1615) and the frontend contract test. M1638 (which mutated the old one-line TypeScript type) was re-anchored to the new last line and re-run: DETECTED.
- **92 - "reads datasheets" was true for about half the values, and nobody had measured it.** A made-up benchmark of 14 datasheets (`scripts/datasheet_bench.py`, answer key in `backend/tests/fixtures/synthetic/datasheets/`) measured today's production reader at 80 of 137 values (58%): 0 on an unruled "Label : value" sheet, free-text answers, a scanned page, Excel and Word. The AI readers that could read these existed but were off (vision) or unreachable from any screen (Claude text reader). The Claude reader's unit gate, described as accepting "a unit the code knows", rejected real units (kg/h, Nm3/h, ms, weeks, months), so a correct reading would have been thrown away; a PDF grid value that lost its unit ("75" for "75 kW") would have been confirmed by an AI reading that proved the unit. Fixed on `feat/datasheet-any`: shared unit grammar, unit columns in Excel/Word rows, the merge keeps the proven unit, and the AI reader and Office input sit behind `DATASHEET_AI_READER` / `DATASHEET_OFFICE_INPUT` (off). Not yet measured with a real model: an "oracle" run (a fake model proposing the answer key) reached 136 of 137, which proves the pipes, not any AI. Also found: M450, M780 and M785 error at HEAD (anchors), adding to entry 90's list; not fixed here. ADDENDUM (2026-09-30, `feat/datasheet-fix1`): the unit-loss sentence above undersold it. The rules reader ITSELF reported those grid values without their unit in production (no flag): all 13 wrong values the rules reader produced (7 on the motor grid sheet, 6 on the transmitter sheet) came from `datasheets.pairs_from_table_shape`, which used a Units column only in the two-tag layout, so "75" was stored for a 75 kW motor; it was not something only an AI reading could have caused. Also, the AI reader's "do not report a blank" was a sentence in the prompt only: the gate (`claude_datasheet.accept`) did not refuse a "By Vendor" value, and the `ai-only` benchmark reader showed 7 such cells as values; hybrid looked clean only because `create_fact` happens to blank them on storage. Both are fixed in code now; measured numbers are in the commit message.
- **93 - "CI green on main" was not stable: the chat could send a question before it knew which engine to use.** `ChatView` started with no engine chosen (`model` = null) and only filled it when `/chat/models` answered; `send` read that render-time value. A question asked in that gap went out as a local quotation (`tier: extract`, no engine named) instead of the Claude default, so the same click could produce a different kind of answer depending on how fast the server replied. The chat end-to-end test pressed Enter right after the screen opened and therefore raced the engine list; it passed on a calm machine (12 of 12 here) and failed on GitHub's runner after the datasheet merge, turning `tests` red on `main`. It was not caused by that merge (no frontend file changed in it); reproduced here by delaying the mocked engine list by 1.5 s. Fixed in `fix/chat-engine-race`: `send` waits for the engine list (at most 3 s; a failed or missing list falls back to the old behaviour), and reads the engine from a ref so a hand-picked engine also reaches it. Pinned by three vitest cases and M1790-M1794; the e2e scenario with the delayed list now passes. The earlier note in PR #356 that a chat timing flake "passes alone" should have been treated as this defect, not as noise.
- **94 - Datasheet AI, "one value per fact" (2026-09-30).** The local AI returned whole sentences as values ("16 weeks from purchase order, ex works"), which the benchmark scored wrong. A first fix that changed the AI's prompt and made the second reading read the page bottom-up was measured on the owner's PC and was WORSE (ds07 hybrid 4/9, 11 facts dropped as model_unstable, 7 field_not_in_quote); it was written without a real model to test on and was removed. What stayed is code only: after the AI answers, a value is trimmed to one quantity with its conditions kept as a qualifier, and two conditions become two facts. The full local benchmark then caught a bug in that trimming (a steel grade "316L SS" was split into 316 litres plus a note; ds06 gained a wrong value); fixed and pinned by a test and a mutation. Also recorded: two identical temperature-0 readings of a page agree with themselves, so "two runs must agree" adds almost no safety for the local engine; unchanged, decision pending. The valve sheet's warranty states two values, so the key now expects both (137 to 138). "ASME Class 600" was reported where the key wants "Class 600" (a prefix word). Fixed (2026-10-01): `atomise` now moves a bare standards-body acronym (two to six capitals) that sits directly before "Class N" or "Cl. N" into the qualifier, so the value reads "Class 600"; nothing else about a value changes (a standard number, a suffix, a lower-case word or a steel grade is left as printed), pinned by tests with invented acronyms and mutation M1809. Not re-measured on the local model or the owner's benchmark: the fix is code only and its effect on the ds07 score is unverified.
- **95 - Claude chat 400 (2026-10-01).** Questions that made Claude search several times failed with a 400 on the owner's PC. The fake Claude transport in the tests never checked what it was sent, so the loop passed every test while sending three request shapes the API refuses: no tools defined after the tool cap (history still held tool blocks), a thinking block sent back without its signature, and thinking switched off after round 1. Fixed and pinned by shape tests and mutations M1820-M1824. Not proven against the live API until one real call on a synthetic question succeeds. Cost note: thinking now stays on for every round of a thinking turn.
- **96 - Compare view mixed two standards' text (2026-10-01).** The screen split one answer by paragraph position, so a side with a multi-paragraph answer showed under the wrong standard and the second side's citation numbers pointed at the first side's passages. Fixed: per-side text and numbering, tests added.
- **97 - Counts missed misspelt nouns (2026-10-01).** The count router matched exact words only, so a typo sent a library count to retrieval. Fixed with a conservative repair.
- **98 - Claude failure shown as a local-model failure (2026-10-01).** A failed Claude answer was shown as "The local answer model is not running" with an `ollama serve` tip, because a failed answer did not record which engine failed and the screen hardcoded the local wording. Fixed: failed answers store the engine, the screen names it, and tests cover both directions. Turns stored before this change have no engine and keep the old wording.

- **99 - Compare header and 'against' (2026-10-01).** (a) "Compare A against B" with no topic searched for the word "against" and showed both sides as not found: the connecting-word list had no "against", "from" or "than", so the word became the topic. Fixed; a compare with no real topic now asks for one. (b) The header said "Checked 1 standard" for a two-sided compare, because it counted only documents that produced passages, not the sides searched. It now reads, from the real per-side results, "Searched 2 standards, found text in 1" ("none" when nothing was found), and names a typed document the reader cannot read; single-document and ordinary headers are unchanged and pinned by a test. A side the reader may not read is no longer reported as "not found in the pages read" (it is "not among the documents you can read"; each side now carries a `searched` flag). (c) Citation-numbering investigation: no backend bug existed. `_renumber`, `source_start`/`source_count` and the API source list agreed in every case tested (one side empty in either order, both sides found, repeated citations, multi-digit numbers); those cases are kept as regression tests. One real screen bug was found and fixed: the comparison card drew each side's text as plain text, so bullets and bold showed as raw asterisks; it now uses the same markdown renderer as the ordinary answer. The exact cause of the "1 ... 1, and 1 ... 5" markers on the owner's screen was not reproduced from code and is unverified. Tests: backend/tests/test_compare_honesty.py, frontend AnswerComparison.test.tsx, mutations M1846-M1849 and M1851-M1880 (M1850 was already taken).

- **100 - Family questions skipped per-standard search (2026-10-01).** A question that named a family of standards in general words, such as "the welding standards", was searched in one pass over everything the reader may read, so one standard's passages could crowd another's out of the shared top-k and a standard that was never searched on its own could be reported silent on a topic it does cover. Per-standard search existed only for standards the reader named by designation. Fixed: the family phrase is resolved by code from the AI-read scope records and the app's own search over the standards the reader may read (no taxonomy, no model call, at most 8 standards), each is searched on its own budget through the same per-side path as a named comparison, and the answer says which standards were searched and that membership is a guess until a person confirms it. Fewer than two standards found says so and falls back to the ordinary search.

- **101 - Silent Claude-to-Local downgrade (2026-10-01).** With Model = Claude selected, an answer written by the local model looked identical to a Claude answer: `reasoning_provider.get_provider` gives the local engine whenever Claude cannot be used (provider switch, egress flags, key, a failed first call in `chat_claude_first`) and only logged it. The code even said "the answer says which engine wrote it", and it did not. Fixed: `chat.ask` records `requested_provider` and a code-written `provider_note` (the real cause, or "Claude was not used" when it is unknown) whenever the reader chose Claude and the local model produced the answer, both are stored and lifted like `provider`, and the answer card shows a calm note. Which engine answers is unchanged. Turns stored earlier have no record of what was asked for and render as before.

- **102 - A standard that covers the topic was reported silent, and quotes were cut at "P-No." (2026-10-02).** Found on the owner's library in a family question about post weld heat treatment. (1) A side was shown as "Not found in the pages read" although its search found the right page at rank 2: the lexical gate judged a word "common" when it sat in more than a quarter of the chunks it was looking at, and `chat_comparison` looks at ONE standard, so a standard that discusses the topic on 10 of its pages had its topic words ruled out as "common to the whole document", the gate saw 1 of 2 distinctive terms, and the side was refused. The more a standard covered the topic, the likelier it was called silent. Fixed for comparison sides: commonness is now judged across what the caller may read (never wider than their grants), through `lexical.commonness_against`. The ordinary single-document path is unchanged and still judges inside the document; whether it has the same flaw is not measured. (2) Four places cut text at every full stop followed by a digit, so a quote ended at "P-No." and the next began "1 materials is not permitted". `sentence_guard.NOT_AN_ABBREVIATION` now keeps "No.", "para.", "Fig.", "approx." and a few others from ending a sentence in `answer.py` (two splitters), `claims.py` and `chat_stream.py`. `chunker._SENTENCE_SPLIT` has the same flaw and is NOT changed: it decides where stored chunks begin, so it needs the library re-process (owner's chunker v9 decision). (3) The eight standards searched for a family question were ranked by scope-record hits then name, so two standards that only mention welding in their scope took slots from a standard that has the topic on its page; each candidate is now probed for the topic on its own and ranked by that first. Tests: backend/tests/test_compare_commonness.py, test_sentence_abbreviations.py, test_family_search.py; mutations M1930-M1938.

- **103 - OCR text was called verbatim, a check that never ran was shown as clear, and 'this machine is offline' was shown when it was not (2026-10-02).** Found by a code review of the batch. (1) The PDF report labelled a passage 'verbatim' unless it was recorded as OCR; text with no recorded provenance got the claim. The label now says verbatim only for text explicitly recorded as extracted (`reports._extract_label`), matching the screen. (2) A confidence check that was never computed (coverage when completeness was unknown) was stored as fired=False and drawn as 'clear'. `ConfidenceCheck.fired` is now three-state: True fired, False checked and clear, None not checked; the screen shows 'not checked', merging lets a real fire beat a clear beat a not-checked, and the API/contract types allow null. (3) The market line 'this machine is offline' was a literal copied into four responses; it is now one `analysis.market_line()` and shows only when the market lane state is known. Tests: test_reports.py, test_synthesis.py, test_not_implemented_market_line.py, RecommendationCard.test.tsx, AnalysisModeScreen.test.tsx; mutations M1940-M1946. Not fixed in this batch: review findings 32, 30, 20, 21, 27, 16 and three that could not be classified.

- **104 - A standard was reported silent on a topic because it did not print its own number (2026-10-02).** Found on the owner's library after batch C: the comparison side for one standard still said 'Not found in the pages read' although its search ranked the right page 2nd of 14. A read-only diagnosis (counts only) showed the question 'What does <designation> say about <topic>' made the standard's own designation a third distinctive term; three terms cross `LONG_QUESTION_TERM_COUNT`, so the gate demanded two shared terms, and the answering page can only supply the topic (a standard prints its number on its cover, not on the page that answers). The page shared 1 of 2 and was refused. This is a second gate from the commonness one fixed in entry 102; entry 102 was incomplete for this case and I had said so too early. Fixed in `lexical.assess`: in a ONE-document scope (document_id set, or exactly one allowed document) the document's own designation, matched by file name, counts as shared for every passage of that document; in any wider scope there is no credit. Not measured: whether the ordinary single-document path with a named standard is affected the same way outside comparison (the credit applies there too when the scope is one document). Tests: backend/tests/test_lexical_own_designation.py; mutations M1950, M1951.

- **105 - Entry 104's fix was too narrow and did not clear the owner's retest (2026-10-02).** After entry 104 was merged, the owner's retest on the real library still showed the standard as 'Not found in the pages read'. Entry 104 credited a document's own designation only when exactly one document was in scope; a comparison side holds every document of a standard (a re-issue or duplicate upload can make it more than one), so the credit may never have applied. The credit now applies when EVERY document in scope is named by that designation (`lexical._scope_wholly_named`), and not when any other document is in scope. A new end-to-end test through `chat_comparison.compare` (a standard that prints its number on its cover only) fails without the credit and passes with it; the earlier tests called `lexical.assess` directly and so could not show the difference. Retest after merge (owner, 2026-10-02): SAES-W-017 now shows its text. Not isolated: whether entry 104's version or this one made the difference (the earlier retest may not have run restarted code). A read-only count showed each of four standards maps to ONE document, so the 'two files' case was not the owner's cause. Tests: backend/tests/test_lexical_own_designation.py; mutations M1950-M1952 (M1950 and M1951 re-anchored).

- **106 - Two more wrong 'Not found' / empty-bullet cases from the owner's retest (2026-10-02).** (1) A side for a standard whose file name is `<BODY>-<TAIL>` was refused 'does not appear anywhere in the indexed documents' with five strong hits: `distinctive_terms` finds the designation twice, whole (word scan) and as the tail the identifier pattern matches, and only the whole one equalled the file name, so the tail counted as a missing named subject. An identifier-shaped fragment of the designation (at least `MIN_FRAGMENT_LENGTH` normalised characters) now counts as naming the document, only when every document in scope carries that designation. (2) In Claude-written comparison bullets a citation written AFTER the full stop (`<claim>. [S1 "quote"]`) was split from its sentence by `answer.verify_claims`; the claim, uncited and carrying a figure or acronym, was dropped and the lone marker kept, so the reader saw only a number. `_join_stranded_citations` puts a citation-only fragment back on the sentence before it; an unsupported figure or an unverified quote still removes the claim (tests). Found by the owner's screenshots and a read-only diagnosis by counts (no document text). NOT fixed or measured: the side for a second standard (SAES-A-206) still says 'Not found'; the read-only run could not load the vector index, so retrieval ran keyword-only and the result is inconclusive (the document has the acronym but not the spelled-out phrase). Tests: backend/tests/test_lexical_own_designation.py, backend/tests/test_verify_claims_stranded_citation.py; mutations M1953-M1955.

- **107 - The word gate counted filler words and plain decimals as subjects the passage must contain (2026-10-02).** `lexical.distinctive_terms` treated words such as "say", "says", "mention", "according", "describe" and "provide" as distinctive terms, and a plain decimal such as 2.5 matched the identifier pattern. A good passage could be refused because it did not repeat a filler word or a number from the question. Found by the whole-system audit; the filler list and the decimal case were reproduced with tests that fail before the fix. Fixed: the missing filler words are in `STOPWORDS`, and plain two-part decimals are neither terms nor named subjects (designations and three-part clause numbers still count). Not measured on the owner's library. Mutations M1960 to M1966.

- **108 - A requirement lost its condition when the sentence used "where" or "if", or had a comma in the condition (2026-10-02).** `requirements_3b.parse_condition` cut the condition at the first comma, capped it at 80 characters, and returned nothing for a sentence with no "shall" or "must" and for the word "if". A conditional requirement could therefore be stored as unconditional. Found by the whole-system audit. Fixed: where, if, when and unless open a condition, commas inside it are kept, and a sentence that cannot be parsed still returns nothing (never an invented condition). Not run against a real standards corpus. Mutations M1970 to M1977.

- **109 - 17 mutations tested nothing, and nothing could notice (2026-10-02).** Seventeen mutation anchors no longer matched the code (M1109 among them), so those checks never ran. Found by the whole-system audit. All 17 were re-anchored and detect their bug; `scripts/check_mutation_anchors.py` now fails if any anchor matches zero or more than once, with a unit test and a CI step. Open: M1002 reports NOT DETECTED and is probably an equivalent mutant (the later atomic claim still refuses the second search); it needs a test or retirement. The same pass fixed two frontend defects (the Documents background refresh dropped loaded pages; the side panel stole focus on every refresh, did not restore it on close and did not trap Tab).

- **110 - Any reader could delete a document, and several routes ignored the grant rules (2026-10-05).** The whole-system audit found that `DELETE /api/documents/{id}` and the extract, chunk, embed and index-keyword routes needed only a read grant; that review findings, the CRS preview and the CRS export showed a standard's text, clause, page and filename to a user who held only the submittal; that deliverables and risks with no document id were open to every identified user, and an inferred expectation or overdue risk from an admin-only document was returned to others; that `POST /api/reports` skipped the conversation-owner check; that the four Claude review routes ignored `REASONING_PROVIDER`; that a torn spend-ledger line was skipped and could lift the USD cap; and that several routes exposing corpus-derived content answered without a sign-in. Each was reproduced with a failing test first. Fixed: admin-only for the destructive and pipeline routes, standard-derived fields withheld when the standard is not readable, a document-less deliverable needs admin or a grant, source-document scope on expectations and risks, an owner check on reports, the provider check on the Claude routes, a torn ledger line counts at the cap, and identity required on the listed routes (`/api/health` and the login calls stay open). `python-multipart` bumped to 0.0.32 (advisory not confirmed; the venv needs a reinstall). Not covered: a finding whose standard document was deleted still shows its text; other surfaces that can show a finding (structured search, chat actions) were not checked. Mutations M1980 to M1989.

- **111 - Numbers were read wrongly, so a false 'compliant' was possible (2026-10-05).** `claims.parse_value` read a Unicode minus as positive (-29 became 29), joined separate digit groups ('34 3' became 343), and read '4.000' as 4.0; the figure checker accepted a number from anywhere on the page whatever its unit or sign, and accepted 'shall exceed' against 'shall not exceed'; a requirement 'Noise' did not match a field 'Noise level', so the contractor was told a value was missing; compound units such as mm/s were cut to mm (a length); two different upper limits were labelled 'agreement'. Each was reproduced with a failing test first. Fixed: signs and dashes normalised, space groups only as thousands, an ambiguous three-decimal value goes to engineer review, figures with a unit must match a number bound to the same quantity, polarity is checked against the quote, field names match tolerantly with a unit check, compound units parse whole, and different limits are 'possible conflict'. Behaviour change to expect on real sheets: more values with exactly three decimals go to engineer review, and gap analyses show more conflicts. Other number parsers (`rule_eval`, `condition_choice`, one in `datasheets.py`) were not changed. Mutations M1990 to M1999.

- **112 - Review and standards screens kept the previous item's state, and a bad reply locked the chat (2026-10-05).** Opening review run B showed run A's final code; saving finding B could send finding A's edited text; the 'Superseded by' select snapped back; a non-JSON reply left the chat unable to send and the analysis unable to start; there was no error boundary; Documents search and filters applied only on the next poll; lists were cut at 20 rows with no stated boundary; dashboard warning links reloaded the page and signed the reader out; the login footer said nothing leaves the machine; the vision reader did not say it sends page images to Claude; and a failed Reports load showed 'No reports yet'. Each was reproduced with a component test first. Fixed, with pale review colours replaced by theme tokens. Not run in a real browser. Two chat mutations (M1790, M1792) were re-anchored after the change moved their code.

- **113 - A standard that does mention a term was reported as silent, because abbreviations were not matched to their spelled-out form (2026-10-06).** Found by testing the running app against the real library: a question using an abbreviation about one named standard was refused with "none of the indexed documents mention this topic", while that standard defines the abbreviation and has a clause about the spelled-out term. Three causes, reproduced on invented data: the acronym harvest skipped any expansion with a hyphenated capitalised word; the keyword side required the standard's own designation to be printed inside a passage, which standards do not do; and the reranker scored a short definition passage below the fixed floor. Fixed at class level: hyphenated expansions are harvested, a small built-in list of single-meaning abbreviations adds expansions only for a term typed in capitals, expansions only ever ADD match terms, the designation of the one scoped document is soft, and a scoped refusal now names the document and its passage count instead of claiming a library-wide search. Not yet confirmed on the real library after merge.
- **114 - The chunker made a clause sentence into a section title, indexed a revision-history table as requirements, and left the title page unsearchable (2026-10-06).** Found on the same real standard. (1) A numbered clause whose first words sat on the line after its number became the section label and the chunk body kept only the tail. (2) The "Summary of Changes" table became chunks labelled with a paragraph number plus a change-type word (a fake section). (3) The title block was classified as front matter, so the document's own title was not searchable inside it. Fixed with a sentence-likeness rule for headings, a new excluded page kind with a recorded reason for change tables, and a single bounded title-page chunk. `CHUNKER_VERSION` is now 10. Nothing re-chunks on startup; existing documents keep their stored chunks until an admin re-chunks them or `reindex_chunking.py --apply` is run. Not yet confirmed on the real library.
- **115 - A checked answer kept hollow leftovers (2026-10-06).** After the claim checker removed unverifiable points, the answer kept a lead-in ending in a colon or "e.g." with nothing after it, bare citation numbers, and filler such as "Let me confirm directly." Found on screen in the running app, so it was a real defect, not a paste artifact. Fixed deterministically in `answer.verify_claims`: marker-only lines, narration that promises an action, and lead-ins whose content is gone are dropped; the "N of M points" count reflects what remains; an answer left with nothing becomes the honest insufficient-evidence answer. The streaming call applies only the sentence-level rules. An unscoped refusal now states how many documents the reader could search. CI on the first r3 branch found two pre-existing tests broken by this batch, which the related-tests list had missed: filler narration was being dropped from text written before a tool call (audit 2026-09-30 requires that text to stay), now fixed so narration is dropped only from the last round and never in the streaming call; and a scope-leak test that used a built-in abbreviation as its probe, now probing with an invented abbreviation defined in one document only, so the leak check is meaningful again. The built-in list is not document data and expands the same for every caller.
- **116 - In Claude mode a question that named a standard still searched every standard (2026-10-06).** Found by testing the running app after the R3 merge: the same question about one named standard was answered correctly in Local model mode (scoped to that standard, quoted its definition) but in Claude mode the scope shown was a different standard, the named standard was not among the sources, and the answer said it was not the standard for the topic. Cause: `chat.claude_scope` narrowed Claude's tools only by a selected or conversation document, never by the document the question names, which the old pipeline already honoured (`_document_answer`). Fixed: a document or set of documents the question names (`understood`) now narrows the Claude lane, only ever narrower, an @-picked set and a selected document still win, and a named document the reader cannot read adds nothing. Not yet confirmed on the real library after merge; whether Claude then finds the clause on the spelled-out term depends on its own search words (the abbreviation expansion from entry 113 applies inside the narrowed scope). Tests: backend/tests/test_claude_scope_named_document.py; mutation M2041; M1527 re-anchored.
- **117 - A refused Claude answer did not say what was removed or why (2026-10-06).** After the scope fix (entry 116) the same real question was refused in Claude mode as "0 of 1 points found on the page" (then "0 of 0"), with the right standard searched and its pages 5 and 15 read. The reader, and I, could not tell whether the model wrote uncited points, quotes that were not on the page, or something the filler rules removed, so the cause is NOT yet known. Fixed only the visibility: `answer.verify_claims` takes an optional `dropped` list and records each removed point with its reason, and the Claude lane stores it with the answer as `removed_points` (not shown as an answer). Probes on invented data showed a quoted point passes, a point with an acronym or figure and no quote is removed by design, and a standard's own designation in the sentence is not read as a figure. Not a fix for the refusal. Tests: backend/tests/test_removed_points_recorded.py; M1454, M1458 and M1108 re-anchored.
- **118 - When every point Claude wrote failed the checker, the reader got a bare refusal although the document answered (2026-10-06).** Same real question as entries 116 and 117: after the scope fix Claude searched only the named standard and read the pages that hold the answer, yet every point it wrote was removed by the claim checker, so the reader saw "I cannot determine this" while Local model mode, asked the same question, quoted the standard word for word. The reason Claude's points failed is still unknown (entry 117 now records it on every such answer). Class fix, independent of the cause: `chat_claude_first._finish` no longer builds a refusal when nothing verified; it hands the turn to the existing pipeline (scoped, gated, quoting the document), the same hand-off a failed Claude call already used, and the answer carries a notice and the removed points. A genuine absence still ends in the pipeline's own honest refusal. Nothing unverified is shown in either case. Tests: backend/tests/test_removed_points_recorded.py; mutation M2042; the two older tests that expected the bare refusal were updated to the new contract. Not yet confirmed on the real library.
- **119 - "Signs and dashes normalised" (entry 111) was true of one parser only; four other number readers still dropped or kept the wrong sign (2026-10-08, W2, issues #445 to #449 and #203).** Entry 111 listed the Unicode minus as fixed and named three other parsers as not changed. It did not say that the claim extractor (`claims.extract_measurements`) read "U+2212 29 mm" as +29 mm and dropped "-29 mm" entirely, or that the reader value gates (`reader_api._value_in_quote`, its copy in `claude_datasheet`, and the AI check's substring test) accepted the value 5 for a quote saying "-5" or "2.5" while their docstring said they were "tolerant of printing and of nothing else". Also: `quality.normalise_text` used NFKC, which turned "10 to the minus 6" written with superscripts into "10-6" and "10 squared" into "102"; the CRS-comment, recheck and AI-check number gates read U+2212 5 as 5; `synthesis` read the 10 of 10^-6 as 10; `rule_eval.verify_numbers` stripped every sign and read "1,5" as 15. Fixed: one module (`app/numparse.py`) now owns number, sign and exponent reading; every caller listed above uses it; text extraction uses NFC plus an explicit character map instead of NFKC (what the map keeps and what it no longer rewrites is listed in `numparse.CHARACTER_MAP`); a test fails if a second number reader is added. Behaviour change to expect: a negative measurement written with a plain "-" is now extracted (it used to be dropped), the gates are stricter about sign and decimals, and newly extracted text keeps superscript exponents as "^". Stored text from before this change is not rewritten (no re-index was run). NOT changed, named so nobody assumes otherwise: `datasheets.py` and `condition_choice.py` still fold U+2212 themselves, `geometry_reader.py` has its own size grammar, the unit table and comparator vocabulary stay in `claims.py`, and `P1` could not be re-measured in the build sandbox (model weights unavailable). Tests: backend/tests/test_w2_number_parser.py; mutations M2101 to M2120; M1990 to M1993 and M1026 re-anchored.
- **120 - Eleven gates said "every number / every unit is checked" and each had a hole the 7 Oct audit found (2026-10-08, W2, #449).** B02: the claim extractor dropped ranges ("10-40 C") and read a typographic or en-dash minus as plus (the minus part is entry 119). B03: two documents printing the same sentence "design 10 bar, test 15 bar" were labelled a possible conflict, because quantities printed in ONE sentence were compared with each other; now a quantity conflicts only when no quantity of the same dimension in the other row agrees with it. B11: "5 in the vessel" was read as 5 inches, and `Pa` was not a unit. C-H3: the CRS-comment gate erased the clause by plain replace, so the clause "5" turned "typically 56 bar" into "6 bar", an allowed number; it now removes whole tokens only. H07: the synthesis number gate was a bag of numbers with no unit ("6 bar" passed over "6 mm"), and stripped `R10`, `V2` and "Part 6 bar" as references; it now checks the unit when the span prints the number with another unit, and strips revision shorthand only in a revision sentence. A09: the AI check's pass/fail word list missed "satisfies", "conforms", "adequate", "violates" and similar. A10: the AI check matched a clause to a standard by loose substring (`API` for `API 610`). A14: `assertions` ignored polarity ("required" supported "not required"; "compliant" was supported by "non-compliant"). A16: `condition_choice._number` read "1,500" as 1.5 (the audit said 500; the code gives 1.5). M2: the datasheet reader gate accepted a whole-page quote, a unit not in the quote, and a field label matched by one four-letter word. Also changed: `3.175` and other three-decimal values are decimals; only `d.000` stays ambiguous, so entry 111's "more values go to engineer review" is reversed for them. Not fixed: units are still not converted in the synthesis unit check (6 mm vs 0.6 cm is an unsupported number, not a unit match); two quantities printed in one sentence are never compared with each other, so a sentence that contradicts itself is not flagged. Tests: backend/tests/test_w2_audit_fixes.py; mutations M2121 to M2143.
- **121 - Three-decimal values were read one way for every document, and entries 111 and 120 each picked a rule that was wrong for some documents (2026-10-08, W2, owner decisions).** Entry 111 sent every d.ddd value ("3.175", "1.500") to engineer review because it might be an EU thousands group; entry 120 reversed that for all but d.000 because 3.175 mm is a normal size. Both were a single rule for every document, and neither was right: a document that writes its thousands with dots writes its decimals with a comma. Now decided per document: if the document writes a comma as a decimal mark anywhere (a comma followed by one or two digits, or four or more, not a list such as "1,2,3"), a three-decimal dot value in it is ambiguous and goes to engineer review; otherwise it is a decimal, including "4.000". The document is the one the value came from: a datasheet's own chunks at extraction, the evidence items of the same filename in claim extraction, and the submittal or standard document at comparison. Two further owner decisions in the same change: (a) "5 -10 mm" (a space before the dash only) is neither a range nor a negative; it is kept as one unreadable quantity and goes to engineer review (entry 120 had read it as a range); (b) the datasheet reader gate (entry 120, audit M2) now accepts a unit that appears only in the column header of the value's own column, and says so on the fact (`unit_from: column_header`); it refuses only when the unit is in neither the quote nor that header. Also corrected from entry 120: the "quote too broad" rule had a three-line limit that refused an ordinary quote on a sheet that prints each label and value on its own line (CI caught it on commit 2f562e0 in `test_datasheet_production_bench`); only a quote over 240 characters or over half the page is too broad now. Two old tests encoded behaviour that was changed on purpose and were updated: `test_r2_numbers_parse` (three decimals ambiguous in every document; now only in a decimal-comma document) and the production-bench cross-row reading (its quote stopped at the value and omitted the unit, which the unit rule now refuses; the fixture quote now includes the unit, assertions unchanged). Not done: the column-header rule for a sheet that is neither pipe-delimited nor one cell per line is a heuristic (a header-like line with no number within 30 lines above), which is why the fact records where the unit came from; the per-document comma test reads the text of the chunks stored for that document. Tests: backend/tests/test_w2_audit_fixes.py; mutations M2140 to M2151.
- **122 - Three screens and routes did more than their labels said, and one request could keep the whole backend busy for minutes (2026-10-08, W7 P0, #606 #607 #608 #478).** (1) Quote mode was labelled "The document's own words. ~2 seconds. No model involved." but ran the full Gap analysis route on every document; on the live library it ran for more than ten minutes. Measured on a throwaway database of 283 invented documents and then on a copy of the live data by a second session: the cost was not the clustering but a corpus-wide database read per extracted claim (`claim_terms` -> `distinctive_terms` -> `known_expansions` -> `harvest` -> `_signatures`, 596 claims = 596 reads, 17 s here) plus the acronym document maps built inside the request (21 s cold on 40,293 chunks). Fixed: one read per call, maps built only by the startup warm-up and a background rebuild after a document finishes indexing (never inside a request; a run says how many maps were not ready), identical concurrent requests share one run, and the run has a time, evidence and claim budget that returns a partial result with `truncated: true` and the reason. (2) `GET /api/risks` ran risk detection on every request: it read every finding, asked the database one question per finding, created risks and sent one email per risk, so the Deliverables screen waited forever. Detection is now a background job plus an admin POST, set-based, with one rate-limited digest email per run. (3) Two more GET routes wrote: every deliverables read re-ran an owner backfill, and `GET /api/management/reminders` inserted reminder events and emailed; both moved to the writers and the background job. A test now walks every parameterless GET route against a database that refuses INSERT, UPDATE and DELETE. (4) The Deliverables screen waited for all five of its requests together; each panel now loads on its own. (5) Quote mode no longer switches Gap analysis on; it shows "Quoted evidence". NOT VERIFIED: the live 10-minute total freeze (health and other routes unresponsive) did not reproduce in either session; the measured cost and the removal of repeated work are verified, the freeze mechanism is not. NOT DONE: routes with a path parameter are not in the GET walk; the claim-merging step is still pairwise in the number of facets and is bounded by the budget rather than made linear. Tests: backend/tests/test_w7_gaps_freeze.py, test_w7_risks_read_only.py, test_w7_get_routes_read_only.py; frontend DeliverablesView.independent.test.tsx and AnalysisModeScreen.quoteMode.test.tsx; mutations M2301 to M2320.
- **123 - A test named for granting the uploader's discipline asserted the opposite (2026-10-08).** `test_upload_requires_identity.py` says in its docstring that an upload is granted the admin capability AND the uploader's own discipline roles, "because otherwise an engineer's upload vanishes from their own screen", and `test_the_grant_names_the_admin_capability_and_the_uploaders_discipline` is named for that. Since commit 3b76390 (2026-09-11) the route granted the admin capability only and the test asserted `{admin}`, so the name and the docstring stated a rule the code did not follow, and every engineer's upload was visible to no discipline until an administrator granted it (issue #609: 8 such documents on the live library). Fixed for #609: an upload names at least one discipline, defaulting to the uploader's own, the API refuses one with none before storing anything, and the test now asserts the admin capability plus the discipline. Tests: backend/tests/test_w1_crs_draft_and_upload_discipline.py; mutations M2406 to M2409. The existing orphans keep their grants; the owner decides those. Numbered 123: #567 added 119 to 121 and #612 added 122.

- **124 - A cited standard held in the library was reported missing, and "API 65" counted as API 650 (2026-10-08, W3, #452, audit A02 A03).** The live app check found a PSV datasheet citing "API RP 520 Pt-1": the API 520 Part I document was in the library, but the review never used it and the missing-standards list named it, because the matcher compared punctuation-free strings ("APIRP520PT1" against "API520I...") with an exact key and then a prefix rule, and neither string was a prefix of the other. The same prefix rule, the other way round, made "API 65" and "API 6500" the held API 650 (`"API650".startswith("API65")`), and `chat_comparison` used a substring test with the same effect. Three more homes of the claim "this standard is / is not in your library" were also wrong: the chat tool `list_cited_standards` looked an identifier up in a dict keyed by document id, so it called EVERY cited standard "cited but not held"; `select` rebuilt its own missing list from the identifiers that survived selection (the collision `missing_references` was written to prevent); and chat's deferral check and the Claude selection gate each compared exact keys, so a held standard written another way counted as absent. Now one module, `backend/app/standard_ids.py`, parses family, number and part with one general shape (issuing body + whole number + optional part or division, year ignored; proven on bodies no bug report named: IEC 61511-1, BS EN 13445-3, ISA 84.00.01, ISO 10418:2019, ASME B31.3-2022), with special shapes only for API, ASME B-series and BPVC sections, ISO, NACE and the SAES/SAMSS company series; every equivalence (NACE MR0175 = ISO 15156, BS EN = EN, ANSI/ISA = ISA, API's RP/Std/Spec words) lives in the editable file `backend/app/reference/standard_identifiers.json`, not in code and every lookup uses it through `applicability.find_standard` and `missing_references`. NOT DONE: the citation reader (`datasheets.referenced_standards`) is unchanged, so a spelling it does not detect is still not a citation; a library file whose name carries no recognisable identifier still matches only by its exact name. Tests: backend/tests/test_standard_matcher.py and test_b8_answerability.py (`test_a_deferral_to_a_held_standard_written_another_way_is_not_another_document`); mutations M2601 to M2616.
- **125 - "Running extraction twice does not double every requirement", "table values are parsed", and "definitions and unreadable text are not requirements" were each false for standards tables and junk text (2026-10-08, W2b part 1, issues #594 to #597).** A copy of the live database showed 106,832 requirements with about 57% repeated text (one standard: 25,556 rows, 716 distinct texts), 94.7% of `table_value` rows with an empty value and unit, and no operator on any of them. (1) `standards.extract_table_values` always inserted a new row with a new random id and never looked for an existing one, so a table printed again on another page, or read again, became another requirement; the "seen" guard and the replace-on-rerun described in `extract_requirements` covered sentences only. Table cells now carry an identity (standard + table header + row key + column + the value as written) and a repeat adds its page to `evidence_pages` of the one row instead of writing a second (`create_requirement` upserts). (2) A cell with no unit lost its number and a decimal comma after a zero ("0,030") was read as 30 by numparse's thousands rule; the cell reader now uses numparse, fixes that one shape locally (numparse itself is unchanged and still has the gap: a follow-up), takes `<=`/`>=` from a "max"/"min" header and records `unit_from: column_header`. (3) A clause in a "Terms and definitions" section, and a sentence that only defines a word ("Shall: a verb ..."), are stored as `definition`, are not counted as requirements and are not compared. (4) Text that fails a quality test (mirror glyphs, mostly non-Latin letters, mostly symbols, reversed words, too few word-like words) is kept with `quality_reason = text_quality`, held below the verification threshold and kept out of reviews until a human confirms it. The words test is a short built-in list, not a dictionary, so it can miss garbled text and can flag a short run of unusual technical words; it is an extractor guess, labelled as one. Existing rows are NOT changed: re-extraction is #599 and needs the owner's go. Mutations M2501 to M2518.
- **126 - A review compared every table cell of every standard in scope, so one datasheet got thousands of "value not found by the page reader" checks about grades, sizes and materials it never mentioned (2026-10-08, W2b, issue #598).** `comparison.run_comparison` took "evaluate every applicable requirement" literally: each `table_value` cell became a check, and a cell with no matching field ended as `NEEDS_ENGINEER_REVIEW`. Session 2 measured 6,884 of 6,900 checks on one PSV review (92.6% needing an engineer), 53% to 92% of each submittal's findings across three submittals. That told engineers 6,000 times to look at a page for a value nobody had asked for, and buried the real findings. A table cell is now a check only when the submittal has a field that answers it: the row key (a grade, UNS number or size) matches a field name or value, or, for a table the sheet cannot select by row at all, the column field matches a field name. Matching compares normalised words; no standard or material is named in code. Cells not checked are COUNTED, one grouped line per standard with the tables behind it, stored on the run (`table_values_not_compared`) and shown on the run screen. Definitions and unconfirmed garbled text (#596, #597) are never checks, and `table_row` sentences (271 live rows, paired by subject, rules ride on them) are not filtered. The matching rule is a design choice, not a measurement of how often it is right: a row key that appears in no submitted field is not compared even when the table would have applied, which is why the cells are counted and shown, not hidden. Mutations M2701 to M2711.
- **127 - The Documents page said a document was "reading scanned pages" while the OCR worker was idle, and it made one classification request per document on every load (2026-10-08, W7, issue #611 and the Documents page requests issue).** (1) `documentStatus.presentStatus` labelled a finished document with unread scanned pages "reading scanned pages", a claim of work in progress that the document list cannot support: the record holds page counts, not whether a worker is busy. Live app check 2026-10-08: documents with 1 page waiting showed it while the worker was idle. The label now says only what the record says: "finished, N pages waiting for OCR", in a neutral tone. (2) The comment on `useDocumentClassifications` said "there is no bulk route today" and the hook fanned out `GET /documents/{id}/classification` once per document, about 100 requests on every page load. `GET /api/documents` now carries each document's classification (`classification_mod.of_documents`, two queries however many documents), for exactly the rows the caller's scope already selected, so nothing is added to what a caller may read; a never-classified document gets the same empty record as the single route. Mutations M2901 to M2905. Not measured: the page-load time before and after, only the request count.
- **128 - "Off the request path" (entry for #478 and #612) did not mean "cannot slow a request": background work and a per-call HTTP client were still taking CPU from every request (2026-10-08, W7, issue #626).** The owner saw `/api/health` take 7 to 9 s on an idle app. The investigation on the live process did not reproduce the slow window, but found one real per-request cost and two unbounded background loops: (1) every `GET /api/metrics` built a new `httpx.Client`, and with it an SSL context, to reach the local Ollama over plain HTTP (24 of 54 busy samples in 30 s, about 0.5 s of CPU), and asked Ollama twice on every dashboard refresh (every 15 s); (2) `risks.detect_automatic_risks` scanned about 133,000 findings in one unbroken loop on its own thread, which holds the interpreter lock against the request threads for as long as it runs; (3) the acronym warm-up and the risk job logged nothing about when they started or how long they took, so nobody could say from the log what was running when the app was slow. Fixed: the metrics probe shares one client (per-call timeout and host check unchanged) and its answer is believed for 30 s (keyed on host and model; a refused host is never cached); the detection scan works in batches of 1,000 with a 0.05 s pause between them; the risk job, the acronym warm-up and each startup warm-up step now log their start, end and duration. Not shown: that this removes the 7 to 9 s. The cause of that was not found (the window was not reproduced), so the three fixes remove three known costs and the new log lines are what will name the next one. Mutations M3001 to M3010.

- **129 - "Every applicable requirement is evaluated" applied rules written for other equipment to the submittal in front of it (2026-10-08, W3, issue #453).** Applicability was decided per STANDARD (is this standard in scope for the submittal) and never per CLAUSE. Live app check 2026-10-08: SAES-J-600 clauses 8.7, 8.8 and 8.9.3, written for steam-turbine casing relief, were applied four times each to gas-service relief valves, and a NACE laboratory test-environment clause was applied to a relieving temperature; after the table filter (#598) a PSV review still had 541 checks, 504 of them statements. A requirement now has a subject read from its own wording before its "shall" and, if that names no equipment, from the nearest heading that does, using ONE shared, editable vocabulary (`reference/equipment_vocabulary.json`, equipment and component types with spellings). A submittal's equipment is read from its classification, then its title, then its equipment fields. A requirement is a check when its subject fits, when it has no specific subject, or when either is unclear (a component such as a flange or pipe never excludes; a spelling listed under two types matches both; an unknown submittal equipment keeps everything). Requirements about a different equipment type are counted and grouped on the run ("N requirements not applied: they are about X, this submittal is Y"), never dropped silently. This is a heuristic on wording and headings, not a reading of the clause: a clause that is general in meaning but names another machine before its verb is not applied, which is why the lines name the clauses and can be expanded. The earlier model-verdict gate for NOT_APPLICABLE (`applicability_v2`) is a different mechanism and is unchanged. Not measured: how many of the 541 checks this removes; that needs the copy of the live data. Mutations M3101 to M3113.
- **130 - IEC, EN, ISA and ISO-part citations in a datasheet were never seen, so they were neither matched nor listed missing (2026-10-08, W3, #623).** Entry 124 recorded the one matcher and left the citation reader NOT DONE; that gap was real. `datasheets.referenced_standards` was a list of families, so "IEC 61511-1", "BS EN 13445-3", "ANSI/ISA-84.00.01" and an ISO part never reached the matcher: a review did not use such a standard when it was held and did not report it missing when it was not. The same list, read case-insensitively, also took ordinary words as standards ("rated en 1200 rpm" became EN 1200). Now the reader is `standard_ids.find_citations`, the matcher's own grammar (special shapes for API, ASME, ISO, NACE, SAES/SAMSS; a general shape of issuing body + series + number + part/sub-part/year for every other body), with the issuing bodies and TEMA's class letters in the editable `backend/app/reference/standard_identifiers.json` - bodies, never standards. A citation must stand on its own (not inside a tag or a document number), a general-shape body must be written in upper case, and short API/SAES/SAMSS numbers in prose stay numbers. NOT DONE: a body missing from the file is still not read in running text; an all-hyphen code from a listed body ("PIP-1234-01") is read as a citation, because it cannot be told from one written with hyphens ("IEC-61511-1"). ALSO FOUND in the live app the same day (/api/standards/missing): (1) "ASME B16.47" was listed missing while the library held a file named "asme-b16-47-2011-..." with no title or number set - the ASME B shape needed a dot, and the general shape read "-47" as Part 47 (which also made a bare "ASME B16" match that file). Dot, hyphen, space and underscore between number groups are now spelling for every family (both readings of a short trailing group are tried), while numbers stay whole (API 65 is still not API 650). (2) "CMP" and "HVAC" were listed as missing standards: the requirement side (`requirements_3b.cited_document`) takes any upper-case designation after "in accordance with"; the missing list now keeps only what the citation reader recognises as a standard (an issuing body and a number). Tests: backend/tests/test_citation_reader.py; mutations M2801 to M2813, and M52, M102, M103, M1314, M2602 re-anchored.
- **131 - "Not found is never compliant" was true of the comparison arithmetic and false in nine places around it (2026-10-08, W3, issues #450 and #451).** A read-only survey of the review, the review code, the CRS and the chat compare found paths where a step that did not complete, or data that was absent, ended as a better outcome or as silence. Fixed, each with a test that fails without it: (1) a chat compare side that was stopped, refused, out of budget, unsupported or raised was written as "not found in the pages read", i.e. as a search that found nothing; it now says "could not be checked: <reason>", draws no verdict, marks the comparison incomplete, no side after a Stop is searched, and one side raising no longer aborts the others (B01, #451); the Documents-style screen shows the reason. (2) a requirement whose field pairing failed (the pairing model unavailable, malformed, unstable or out of budget; a unit or domain rule refused the only candidate; a table rule unreadable) was MISSING_INFORMATION, "left for the contractor"; it is now an engineer's question that says the check could not be completed. (3) `_recommend_code` let any status it did not list (None, CONDITIONAL, a future status) fall through to "Approved: every evaluated requirement is met"; an unrecognised status now forces Manual Review. (4) a run whose only findings were blanks got "Approved with Comments", a better code than the same run with no findings (Manual); it is Manual unless something was confirmed as met. (5) requirements nobody could check were hidden behind blanks: with both, the code was "with comments"; the out-of-scope branch now comes first. (6) a standard in scope that held no requirement at all (extraction never ran) contributed nothing and could be approved over; it now forces Manual and is named. (7) `applicability_with_reasons` called a standard NOT_APPLICABLE when both profiles existed but shared no filled field; that is UNKNOWN. (8) a failed scope-reasoning call was skipped with no record, so a model that was down for every standard read as "scope checked, nothing excluded"; the standard is now UNKNOWN with the reason. (9) a model-drafted CRS comment on a MISSING or NEEDS_ENGINEER row could say "complies" or "no comment" and be accepted; it is now thrown away, and the best review code cannot be recorded on a run with no recommendation without a reason. Existing tests that encoded the old behaviour were updated with the reason stated, none weakened. NOT fixed, listed in the follow-up issue: the condition gate's NOT_APPLICABLE on absence, datasheet self-checks that skip silently, the AI check and web check leaving no record when they fail, a failed run keeping partial findings, analysis gaps that drop an unreadable named document, the PDF export. Mutations M3301 to M3318.
- **132 - "1 of 1 point found on the page" was shown, green, over a foreword; and one describing word refused a question its documents answer (2026-10-09, W5, #602 and #610).** (1) `chat_presentation.verification` said its count is given "only where it is literally true", and for a quoted (extract) answer it counted every quoted passage as a point found. A quoted passage is on its page by definition, so the count could only ever be "n of n": a standard's foreword or revision history, which repeats a bolting question's every word and states none of its requirements, was quoted as the answer and shown with the green tick (seen with the local model on a real standard). The words were on the page; the claim that a point of the answer was found there was false. Now front matter (headings in the editable `backend/app/reference/front_matter.json`, read by `app/front_matter.py`) is ranked below a document's clauses, a refusal says so when it is all that matched (after one wider search of that document's own clauses), it is never a second passage, and it is counted in the total but never as found, unless the question asks about it. (2) `lexical.assess` refused "ASME-certified liquid service relief valves" with "ASME-certified does not appear in the indexed documents" while the same question without the word was answered from the right clause: a capitalised hyphenated word was treated as the named subject. A hyphenated qualifier is now set aside when the word after it is in the documents, and the answer names it ("was not found in the documents searched ... nothing here confirms it"); the model is asked the question without it. NOT DONE: the Claude lane's quote check (`verify_claims`) still counts a point whose quote is in front matter as found; the front matter it is shown is now ranked last, but the count itself was not changed. "Answers the question" is judged as "is not front matter" for the tick, not as a reading of the passage. Measured on invented text only (P1 version 3, 41 of 64); not yet re-checked on the real standard where #610 was seen. Tests: backend/tests/test_chat_honesty_602_610.py; mutations M3211 to M3225, M919 re-anchored.
- **133 - "UNS N06625 does not appear anywhere in the indexed documents" was said of a standard whose tables list it; and entry 132's NOT DONE (front matter counted as found on the Claude lane) was true (2026-10-09, W5, #639).** (1) The refusal named a term as absent from the library while the sour-service standard's own material tables held it. Checked read-only on the live database (counts only): the table text WAS indexed - every searchable chunk holding the code is in the index, six of them tables - so the index was not the cause. The gate was: the question wrote "UNS N06625", the standard's tables print the bare code "N06625" under their UNS column, and only the whole phrase (and its hyphenated and joined spellings) was ever looked for, in the keyword query, the lexical gate's presence and cover checks, and the identifier boost. Now an identifier also matches without an optional prefix listed in the editable `backend/app/reference/identifier_prefixes.json` (UNS, ASTM, ASME, AISI, SAE, NACE), only when what remains is a code holding a letter and a digit - "API 610" still never becomes "610". (2) Entry 132 left the Claude lane's count (`verify_claims`) counting a point quoted from a foreword or revision history as found. It is now counted in the total and never as found, is not reported as removed (it is shown), and an answer whose every point quoted front matter is refused with that reason rather than "could not be found on the page" - the quotes were on the page. NOT DONE: a quoted passage that small-to-big expansion joins across pages cites its first page with the last page as `page_end`; the row is inside the cited span but the first page shown is not the row's page. The prefix list is a list: a prefix not in it is still read as part of the identifier. Measured on invented text (P1 version 4, 43 of 66). Tests: backend/tests/test_table_identifiers.py; mutations M3501 to M3511; M1108, M1458, M1538 re-anchored.
- **134 - A sheet, a run or a check that could not finish still looked finished (2026-10-08, W3, issue #633, the rest of #450).** Entry 131 fixed the verdict paths; these are the outputs around them. (1) The CRS workbook, preview and issue copy for a run that failed, was stopped or left large parts unchecked printed no sign of it: a failed run exported an empty sheet and a blank code. Every export now carries one list of the parts that could not be checked (`absence.unchecked_parts`: the run did not complete, findings are partial, standards with nothing to check, standards-table values not compared, requirements not applied to this equipment, requirements held back for unreadable text, unread pages, a failed AI or web check) and a "REVIEW INCOMPLETE: N part(s) could not be checked" notice above the code, in both copies; the internal copy lists each part on the Review notes sheet. (2) An AI or web check that was asked for and raised, or could not run, was only logged: the run now stores "<check> could not be checked: <reason>" (the error TYPE only, never its text) and the run card shows it. (3) Findings committed before a later step failed were left on a failed run with no sign they were partial; the run now records `partial` and the count, and the card says no code was recommended. (4) The review code ignored the table values and requirements it did not compare: a run where those are half or more of what was in scope can no longer be recommended Approved or Approved with Comments; it is Manual Review, with the counts. The 50% limit is a policy choice, not a measurement: owner decision 2026-10-09 is to keep 50% for now; it lives in `reference/review_thresholds.json` (read by `absence.unchecked_share_limit()`, a bad value falls back to 0.5, never to no limit) and is tuned in W8 with real numbers from the contractor submittals. Every incomplete CRS shows the unchecked share as "N of M requirements in scope (P%)" with its denominator, or says the share is not known when the run never reached the comparison. (5) Datasheet self-checks skipped silently: the revision-block check that could not run (no page text, or no equipment type) is stored on the run and listed among the parts that could not be checked (not as a finding, so a sheet with no equipment type does not always carry one more engineer question), a consistency pair that could not be compared (two values under one name, not numbers, different scale or basis) now says "could not be checked" as an engineer's question, a missing revision block is qualified by unread pages like every other absence, and an engineer-to-check finding no longer reads "None." as its action. (6) The PDF export cut a long finding off at a fixed box with no sign; the box is sized to the text and a marker is drawn if it still does not fit, and an empty report says it is not a statement that the document is acceptable. (7) Analysis summary and gaps answered a question that named an unreadable document as if it had been examined; both results now list `named_documents_not_read` (the screen does not show it yet). NOT done, still open in #633: recheck failures stored on the finding, the screen line for `named_documents_not_read`, the condition gate's NOT_APPLICABLE on absence, a recheck or crs-draft `stopped` flag in the response, and the three small items under "Smaller items" in the survey. Existing datasheet-check tests that asserted "no result at all" for a pair that cannot be compared were changed with the reason stated. (8) Nine places in backend/app caught `Exception` and did `pass` (two classification audit writes, the ingest stall diagnosis, two boot sweeps in main, the progress listener, the rule table re-read, the scope search, the stage timing): each now logs the failure (error TYPE only). A guard test fails if any broad `except Exception` has an empty body again. Where one of them loses a source for a result (rule table re-read, scope search) the result still says only what it already said ("the table could not be read" when no rule results); the scope record does not yet say its search source failed, still open. The mutation harness kept its backup next to the source and one was committed mid-run with the half-mutated file (code only, no client data); the backup now lives in a temp directory outside the repo and `*.mutbak` is in .gitignore. Mutations M3401 to M3436.
- **135 - A chat comparison said a standard the library holds was "not among the documents you can read" (2026-10-09, W5, issue #636).** "Compare ASME B16.5 and ASME B16.47: which flange size range does each standard cover?" came back with three sides: "ASME-B16.5" ("not found in the pages read"), "B16.5" and "B16.47" ("not among the documents you can read"), although both standards were in the library and state their size ranges. Three faults: (1) the sides were the documents' own designations ("ASME-B16.5", "B16.5-2020") while the missing list was the reader's typed tokens ("B16.5"), compared by a private flat-string test, so one standard appeared as a found side and again as a missing one; (2) the topic was cut by removing the matched names as text, so a name spelled differently in the file left "ASME B16.5 and ASME :" in the topic, every side was asked about the other standard too, and the search came back empty; (3) a standard filed as several documents, or in two spellings, was not guaranteed to be one side. Now `chat_comparison.resolve_sides` groups the documents by the standard's identity from the shared matcher (`standard_ids`), never by title: one standard is one side holding every file; two editions (a year printed in the file name, `standard_ids.edition_of`) are two sides, each labelled with its edition, and a copy with no printed year is its own "edition not stated" side; a typed standard is missing only when no readable document is that standard; the topic is the question with every citation the shared reader finds removed. Mutations M3901 to M3908. **The rule: a count of "sides" or "missing" must come from one identity, not from two spellings of it.**
- **136 - "A figure with a unit is held to its unit" (audit N4) let "11%" pass over a page stating 11.0 psi, and let psig pass for psia (2026-10-09, W4b, #653).** Live, local model: the cited page printed a worked example label-style - "Allowable overpressure, psi (kPa) 11.0 (76)" - and the model wrote "up to 11%". `answer._figure_occurrences` only read a unit written AFTER a number, so the page's 11.0 looked bare, and a bare page figure grounds any claim by design (a table cell's unit is a column away). The sentence was shown as the document's. Separately, `_unit_value_matches` compared units after stripping the gauge/absolute suffix, so "100 psia" passed over "100 psig" - an atmosphere apart. And the summary lane (`synthesis.first_unit_conflict`) kept its own second copy of the unit check, with neither rule. Now: a recognised unit closing a row label just before its number (after a comma, semicolon, colon or line start, with its bracketed alternative for the bracketed value) binds to it; gauge never matches absolute; a removed sentence records why, and a unit mismatch is shown as "the unit does not match the source"; the summary lane asks the same function. ALSO CHANGED, BY OWNER ORDER ("16 psi matches 110 kPa"): the same quantity in another unit of the same kind now grounds a figure when the conversion agrees at the sentence's PRINTED precision ("0.30 mm" over "280 um" is still removed; "0.28 mm" is kept). The synthesis lane's stated rule that any conversion is a fabrication was replaced in its three homes (module doc, `_cite`, `ground_numbers`). NOT DONE: a table cell whose unit is only in a column header (no label before it) still grounds any claim; "mm" and other two-letter lower-case units are not read as a label's unit (they are English words too often). Tests: backend/tests/test_w4b_653_unit_aware_figures.py; mutations M4001 to M4012; M1454 and M1996 re-anchored.
- **137 - "Features no longer evict each other's model" justified a 30-minute keep-alive that held the memory after every call (2026-10-09, W7, issue #666).** The default `OLLAMA_KEEP_ALIVE=30m` was argued from the 23.6 s cold load and from the demo pause, and the comments said only that it kept the model warm. Nobody counted what a model left resident for 30 minutes after EVERY call costs the next job: it blocked both owner PC sessions for about two hours in one day. Now: the interactive default is "5m" (still the setting `OLLAMA_KEEP_ALIVE`); a batch keeps its own window and unloads at the end (the AI task runner, #644); the P1 runner unloads every model it used when it finishes, on an error and on Ctrl+C (`model_transport.models_used`, `model_memory.unload_used`); and an administrator has `POST /api/admin/models/unload` and a "Free model memory" button on the models panel (`model_memory.free_all`, which reports what Ollama still holds, not what was asked). A longer warm window is still one setting away for a machine that wants it; the demo-pause case in docs/benchmarks.md is therefore a setting decision, not a default. Mutations M4201 to M4214. **The rule: a keep-alive is a loan of memory; state what it costs the next job, not only what it saves the next call.**
- **138 - "6364 of 6891 (92%) requirements were not compared" blended three different things, and the 50% approval rule acted on the blend (2026-10-09, W3, issue #678).** The unchecked share added standards-table values with no field to answer them (they apply, and were not checked), requirements about other equipment (they do not apply), and counted stored rows rather than requirements (5,559 of the 6,350 skipped table cells were repeats). So a run could be pushed to manual review because many requirements did not apply to its equipment, and the sentence told an engineer nothing they could act on. Now every requirement in a run's scope is in ONE of three groups: checked, applies but not checked, does not apply, each repeat (same standard, same text) counted once, each group with its reasons (`requirement_split`; table cells keep a reason code: `row_label_not_on_sheet`, `column_not_on_sheet`, `other_row_matched`, `no_label`; unreadable text; other equipment). The approval rule and the sheet's "incomplete" notice use only "applies but not checked", out of the requirements that apply; requirements that do not apply are shown and never count against a run. A run stored before this keeps its counts and says "no reason recorded". The #633 tests that pinned the blended sentence were changed on purpose. Mutations M4418 to M4437. **Not measured:** how the numbers change on the live library (the cloud has no copy of it); the first live run will show it. **The rule: a share must say what it is a share of, and a group of requirements that do not apply is not a group of failures.**
- **139 - "Awaiting a type" read as "a type is coming"; for most documents nothing was ever going to assign one (2026-10-09, W5b, issue #526).** The Documents page showed "Awaiting a type" on 275 of 283 documents of the owner's library. The label says a type is pending; the only thing that ever typed a document was the register match (a datasheet-shaped list of equipment), so a procedure, a study, a report, a FEED document or a letter would have waited for ever, and the review treated every document as if it were a datasheet. Now `doc_router` reads the file name, the title lines, the body of the first three pages and the shape of the text, with generic cues in `reference/document_kinds.json`, and does one of two things: one kind clearly leads, so it is stored as a SUGGESTION (shown as "Datasheet? guessed, not confirmed"), or nothing is clear, so the kind stays EMPTY and the card says "Kind unclear, engineer to choose". A kind a person confirmed is never overwritten. The evidence is cue numbers and scores, never document text. Mutations M4301 to M4316. **Not measured:** how often the guess is right on real documents (the tests use invented ones), and the cue list is a first version. Documents already in the library are typed only after an admin runs `POST /api/admin/document-kinds/route` once. The confirm is admin-only, like the rest of classification. A second false-claim candidate found while testing: mutation M4303's first version removed a guard that a second line already covered, and was reported NOT DETECTED until the mutation removed both lines. **The rule: a label that promises a future state needs something that will produce it.** Numbered 139 because 137 is #672 and 138 is reserved by #678 (PR #685); renumber if the merge order differs.
- **140 - `answer_model_present` on /api/health claimed more than it checked (2026-10-09, W7, issue #656).** The field name says an answer model is present; the code only tested that a model NAME is set (`bool(settings.answer_model)`), so with Ollama stopped or the model not pulled the field was still true. The route cannot check Ollama without a socket on an unauthenticated route, so the field was renamed to say what is checked: `answer_model_configured`, in the route, the schema, the client type, the badge ("Answer model configured" / "No answer model configured", which already said so) and the docs that name it. Older review documents keep the old name because they quote the old route. Not done: whether the model is actually loaded or reachable is not reported on this route. Mutations M4901 to M4903. **The rule: a field name states what was checked, not what the reader hopes.**
- **141 - "The router types every document, or asks" was true for the six kinds it knew and wrong for the commonest document in the library (2026-10-09, W5b, issue #693).** Entry 139 said a document is either suggested a kind or left for an engineer. Run on a scratch copy of the library (counts only), the admin route-all action routed 282 of 283 documents: all 111 "procedure" suggestions were documents already classified COMPANY_STANDARD, and none of the 280 standards was suggested as a standard, because the kind list (datasheet, procedure, study, report, FEED, letter) had no "standard". The tests used invented documents of the six kinds only. Now the vocabulary has a "standard" kind (generic cues: the words of a standard, and the document's recorded role as one cue among the others), `router_version` is "2" so suggestions made by version 1 are re-read, and a kind a person confirmed is still never overwritten. Not measured: how the 170 "ask the engineer" documents split after this; the first admin re-run will show it. Mutations M4921 to M4926. **The rule: a classifier's test set must include the commonest class in the real library, not only the classes its author thought of.**
- **142 - The re-extraction rehearsal reported "0 duplicates" while 57% of the rows repeated (2026-10-09, W6, issue #673).** `rehearse_requirement_reextraction.py` (#652) printed `duplicate_table_cells_active` = 0 and `duplicate_sentences_active` = 0 before and after. On a copy of the library, counted plainly (active rows with the same standard and requirement text), 61,189 of 106,832 rows (57.3%) repeated before and 729 of 46,374 (1.6%) after. The table-cell count grouped by `identity_key`, which is NULL on every row written before #594; the sentence count grouped by clause as well as text, so a repeat under another clause was not counted. The script therefore said "none" for exactly the rows #599 cleans up. Now it also prints `repeated_rows_active`, `repeated_table_cell_rows_active` and `repeated_rows_including_superseded` (same standard, same text), and a line "repeated rows before/after: N of M active rows" with its denominator; the two narrow counts are kept. Not done: the plain count treats two rows with identical text as repeats even when they are two different clauses that legitimately say the same thing; the figure is an upper bound on what cleaning will remove. Mutations M4931 to M4935. **The rule: a "none found" is only as wide as the grouping key; test it with rows the old key cannot see.**
- **143 - "Every numeric cell of every parsed table becomes a requirement" dropped the cells of tables that write the unit in the cell, and read only one table per page (2026-10-09, W2b, issue #695).** The #645 pilot found 0 of 7 hand-labelled table rows. The extractor's own doc said each numeric cell is a requirement; the cell test (`cell_value`) accepted only a bare number, so "50 mm", "0.5 %", ">= 5 mm" and "90 dB(A)" were not values and were skipped without a count, the commonest layout of a limits table. Separately, a page with two tables gave both table chunks the largest table, so the smaller table's rows were never read and the larger one's were read twice. Now a number with its own unit is a value (the cell's unit wins over the column header's and is recorded as `unit_from: cell`; an unknown unit leaves the value NULL, never 0), each table chunk reads the table whose cells appear in its own text (the largest is the fallback), and the extraction result says where cells went: `cells_skipped` = no row label / empty / not a number. Found on invented ruled tables; **not confirmed to be the cause of the pilot's 0 of 7**: the labelled sections are on the PC, so session 1 re-scores them on the copy after merge, and `cells_skipped` will show what is still lost. Still not read: ranges ("10-20", "10 to 20"), cells in a merged row-span, and text-valued cells ("Grade B"). Mutations M4941 to M4949; M2506 re-anchored. **The rule: a count of what an extractor skipped belongs in its result, or the next gap is found by a pilot.**
- **144 - A requirement "cited its page" but cited the first page of its chunk, which may not be the page the sentence is on (2026-10-09, W6, issue #660).** `extract_requirements` recorded `page_start` of the chunk for every sentence. A chunk can span two pages, so a clause that begins on page N+1 cited page N: the citation resolved (the page is inside the chunk) and was wrong, and a "found on the page" check could call a correct quote missing. Now the chunk's own pages are searched for the start of the sentence (letters and digits only, so line breaks, hyphens and spacing do not matter) and the requirement cites that page; a sentence found nowhere keeps the first page; a requirement met again by a re-extraction is moved to its real page. Not done: a sentence that runs over the page break cites the page it STARTS on (no page range is stored); table cells still cite the page their table was read from; the screens do not show "pp. N to N+1"; rows written before this keep their page until the next re-extraction (#599 on the PC). Found on invented text; the share of live requirements affected is not measured (no library copy in the cloud). Mutations M4951 to M4957. **The rule: a citation that resolves is not a citation that is right; test it on the case where the two differ.**
- **145 - "Re-extraction never deletes a requirement" (#640) was true of re-extraction and not of re-chunking, which still deleted them, guarded by a refusal (2026-10-09, W6, issue #659).** `chunker.chunk_document` deletes the document's chunks and `standard_requirements.chunk_id ... ON DELETE CASCADE` took every requirement of those chunks with it, confirmed ones included. `orphan_guard` refused the re-chunk when findings cited them, but an acknowledged re-chunk still deleted, and so did every re-chunk of a standard no review had cited yet. Now the requirements are detached from their chunks before the delete (so the cascade has nothing to take) and put back after the new chunks exist: the same chunk id when the chunk is unchanged, else the new chunk on the requirement's page that holds its sentence; an unconfirmed requirement with nowhere to go is superseded (kept, marked, findings still resolve it by id, the #640 rule); a table cell that loses its chunk is superseded for the next extraction to rewrite; a confirmed requirement is never superseded and stays active with no chunk link (its citation does not resolve until a re-extraction re-points it), and the audit row counts it (`requirements.rechunked`: same_chunk, repointed, superseded, confirmed_unlinked, history_unlinked). A re-chunk is no longer refused; the old test that asserted the refusal was changed for that reason. Not measured: how many live requirements a re-chunk would supersede (no copy of the library in the cloud; rehearse on a copy first, #599); the text match is by letters and digits within the requirement's page, so a sentence the new chunker cut differently is superseded, not re-pointed. Mutations M4961 to M4967; M329 and M1460 re-anchored. **The rule: a guard that refuses a destructive step is not a fix for it; when the step is not needed, remove the destruction.**
- **146 - "Every fact in a drafted CRS comment is re-derivable from the finding" checked numbers and the cited standard, and let any OTHER standard through (2026-10-09, W4b, issue #648).** The gate's own header said rules 2 to 4 make every fact in the comment re-derivable by something that cannot imagine. It checked that the clause and the finding's standard code were cited and that every number was among the inputs, but a comment could add "contrary to API 610" or an action "in accordance with ASME B31.3" that the model had never been given, and pass. Now `accept` reads every standard the comment or action names (`standard_ids.cited_standards`) and refuses the draft with the named reason `standard_not_in_inputs` unless that standard is the finding's own or is cited somewhere in the inputs (the requirement's wording, the submitted text), compared by identity (`API-610` is `API 610`; `API 650` is not `API 610`). The prompt says so too. Second half of #648 (same entry): a sentence of the draft that says something the finding's own quotes do not is now refused too, with the named reason `claim_not_in_quotes`: every word of four or more letters must be in the finding's inputs (requirement, submitted value, field, citation, status) or in a short generic reviewer vocabulary (`reference/crs_comment_vocabulary.json`: submitted, required, stated, revise...), and a sentence with two or more words that are neither (a material, a fault, a cause the model supplied) is thrown away; one stray word is tolerated as style. It is a lexical check, not a reading of meaning: a wrong claim made only of words from the evidence (for example swapping which value exceeds which) passes it and is held back only by the status check and the two-run agreement; the vocabulary is a first version and a legitimate draft may be refused for want of a word (the draft is lost, the machine comment is kept). Measured on invented findings only. Mutations M4971 to M4976 and M4991 to M4998. **The rule: when a gate says "every fact", list the kinds of fact it reads; the kinds it does not read are the open claims.**
- **147 - "The rehearsal script refuses the live database" was the whole safety story for the #599 clean-up, and there was no approved way to run it live (2026-10-09, W6, issue #711).** The approved script took only a copy, and the app has no re-extract-all (280 standards, one at a time), so the only options were editing the guard or 280 manual runs. A guarded `--live` mode now exists, and it refuses unless every one of these holds: `--db` is THIS checkout's live file (not a copy, not another checkout's live-shaped file); `--i-have-a-backup <file>` names a backup that passes `backup_db.verify` and whose table counts equal the live file's; the backend is not running (another process holds the file open, or something listens on the API port, or the check cannot be made, each refuses); `live_guard.prepare_live_write` passes (its own verified backup and restore drill) and clears only this process, revoked at the end. It deletes nothing (supersede, #640; confirmed rows untouched) and is judged SAFE only if confirmed rows, unresolved findings and the total row count did not worsen. The default (copy) mode and its refusal are unchanged. Tested on a temp database at a live-shaped path with the script pointed at it; the real live file was never opened. NOT done: the live run itself (owner replies "go 599 A", then stops the backend; session 2 runs it); "the backend is not running" is two signs and not a proof (a backend on another port that has the file closed would not be seen); psutil must be able to look (otherwise the run refuses). Mutations M6001 to M6014. **The rule: a guard that only refuses leaves the work undone or invites its removal; build the guarded path and test every refusal.**
- **161 - "Heavy work runs in the durable worker, `app/worker.py`" named a file the app never imported, and nine modules in the app were used by nothing (2026-10-09, #725 F8a, issue #736).** `docs/plan-conformance-audit.md` R086 cited `app/worker.py` as evidence that heavy work is dispatched to processes. An import graph walked from `main.py` (lazy imports included) shows no app code imports it: it is a command-line bench runner. The same walk found eight more modules in `backend/app` that nothing in the app reaches: `ai_datasheet`, `extraction_schema` and `quotes` (deleted with their tests and mutation entries), and `datasheet_offline`, `review_score`, `blind_test`, `ai_requirements`, `scope_records` (scoring, bench and pilot tools that scripts use, moved with `worker` to `backend/tools/`). R086 now cites `ingest.py` and `extract.py`. Nothing the server runs changed. CI now fails when a module in `backend/app` is not reached from the app (`scripts/check_unused_modules.py`) and when `docs/system-map.md` does not list every module once with one job per module (`scripts/check_system_map.py`); the four jobs still done by several modules are listed there as known duplicates for F8c. Mutations M6801 to M6806. **The rule: "the app uses X" is a claim about the import graph; check it from the entry point, not from the file's name.**
