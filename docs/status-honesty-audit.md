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
| 58 | `chunker.classify_page` and the quality gate, before 2026-09-25: **"A page carrying a genuine clause is CONTENT however short it is"** | **False for the clauses densest in figures.** Both the front-matter guard and `quality.assess` measured a clause as the longest run of letter-words, and every number ended the run - so "a surface profile of 50 to 75 micrometres" or "the shaft AISI 4140 for all pumps" never reached six words and was dropped from retrieval as debris or front matter. No test caught it because every test page carried long plain sentences. Found by master order B6 (core retrieval verification): on the synthetic benchmark 12 of 15 clause pages were retrievable, and the three missing were the materials, surface-preparation and coating-thickness clauses. **FIXED:** a plain number followed by a word on the same line no longer ends the run (it does not count in it either); a number next to a number, or ending its line, still breaks it, so a table's rows are not read as one sentence (the first version of the fix bridged row numbers too - `test_b3_page_ledger` caught it in CI). Tests `test_b6_measure_in_clause.py` and `test_every_clause_in_the_corpus_is_searchable`; mutations M765-M767, 3/3 detected. Chunks already in the live database change only when a document is re-chunked. **The rule: a filter that decides what is searchable must be tested on the text engineers actually search - requirements full of numbers - not on prose.** |

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
