# Flags: one decision per on/off setting (#736)

Every boolean setting in `backend/app/config.py` is listed here once.
`scripts/check_flag_expiry.py` fails a pull request's CI when one is missing or a default
differs, and the **nightly** run on main fails when a **rollout** flag is past its
**decide by** date (order 46: a PR never turns red because of a date).

- **permanent**: a gate or operator setting that is meant to stay a switch. The note says why.
- **rollout**: a switch that exists while a path is proven. The decide-by date is at most 14 days
  after **since**. By that date the owner either makes it the default and removes the switch,
  removes the path, or extends it: a new `since` and a note saying why (one more window at most).

The rollout rows below were recorded on 2026-10-17 by #736, when this register was created; most
of these flags are older. Turning an AI step off, or replacing it with a rules-only path, still
needs the owner's written approval on #692 (CLAUDE.md top rule): expiry forces a decision, it
does not make one.

| Flag | Default | Kind | Since | Decide by | Note |
|---|---|---|---|---|---|
| `allow_unauthenticated_network_bind` | `False` | permanent | | | Safety override: serving the network with nobody signing in |
| `api_docs_enabled` | `False` | permanent | | | Route docs off the developer machine only on purpose |
| `ocr_use_cls` | `True` | permanent | | | OCR tuning measured in ADR-0005 |
| `answer_model_allow_remote_host` | `False` | permanent | | | Egress gate for the local-model URL (rule 1) |
| `procedure_path_enabled` | `False` | rollout | 2026-11-01 | 2026-11-14 | Procedure submittals: a procedure-type requirement is checked against the submittal's own text (engineer row with a verified quote, or missing); never COMPLIANT (#1476) |
| `datasheet_one_value_enabled` | `False` | rollout | 2026-11-01 | 2026-11-14 | Datasheet checks: a range printed twice (a plain note on one reading) is one value, not "two different values"; a combined "a / rating / c" label answers the text attribute it names (an engineer question or the blank marker, never COMPLIANT) (#1472) |
| `ai_applicability_enabled` | `False` | rollout | 2026-10-17 | 2026-10-31 | AI "does not apply" proposals per requirement |
| `ai_division_scope_enabled` | `True` | rollout | 2026-10-20 | 2026-11-03 | Scope of a standard's division read from its own scope sentence (#1182); off, nothing changes; a part the model did not read is held for the engineer |
| `scope_type_words_rule_enabled` | `False` | rollout | 2026-10-26 | 2026-11-09 | Draft (order 210 FIX 2): a part whose construction words are all in the sheet's equipment type or title applies without asking the model; OFF until the owner says yes |
| `ai_answer_reuse_enabled` | `True` | permanent | | | Reuse of a stored local AI answer to the exact same question (#1221, order 205). Off for the final test before anything goes to a client: every page is read fresh |
| `ai_clause_checks_enabled` | `True` | rollout | 2026-10-17 | 2026-10-31 | AI check proposals for undecided clauses (#645) |
| `rule_auto_use_enabled` | `False` | rollout | 2026-10-17 | 2026-10-31 | Proven rule families used without an engineer |
| `recommendation_queries_enabled` | `False` | rollout | 2026-10-28 | 2026-11-11 | A recommendation ("should") of a standard the datasheet names is raised as a query for the engineer (order 288.2); OFF, a review ignores recommendations |
| `match_enabled` | `True` | rollout | 2026-10-17 | 2026-10-31 | AI matcher (#794) |
| `tested_cards_decide_enabled` | `False` | rollout | 2026-10-29 | 2026-11-12 | Order 306.1: a relief-valve checklist card tested under the stricter rule (written cases, an at-the-limit case, a clause number, not weak) may decide while its engineer approval is pending; owner decides default on or remove |
| `deferred_value_is_query_enabled` | `False` | rollout | 2026-11-01 | 2026-11-15 | #1475, owner decision D2: a value the sheet prints beside By Contractor / TBA is a query for the engineer (never COMPLIANT, never NON_COMPLIANT) in the datasheet checks and the standards comparison; OFF, it is judged as before; owner decides default on or remove |
| `geometry_reader_enabled` | `False` | rollout | 2026-10-17 | 2026-10-31 | Geometry reader form path and vision reader |
| `field_naming_enabled` | `False` | rollout | 2026-10-27 | 2026-11-10 | Model-named canonical field names pair numeric requirements with sheet fields (order 259.5); measured by s2, then default on or removed |
| `answer_judge_enabled` | `False` | rollout | 2026-10-17 | 2026-10-31 | Chat answer judge |
| `applicability_reasoning_enabled` | `True` | rollout | 2026-10-17 | 2026-10-31 | Scope reasoning (#757) |
| `review_debug` | `False` | permanent | | | Operator debug switch |
| `review_debug_detail` | `False` | permanent | | | Operator debug switch |
| `crs_ai_wording_enabled` | `True` | rollout | 2026-10-17 | 2026-10-31 | AI CRS wording |
| `geometry_table_reader_enabled` | `True` | rollout | 2026-10-17 | 2026-10-31 | Geometry table reader |
| `table_text_cells_enabled` | `False` | permanent | | | Record a standards-table cell that is text, not a number, as a requirement with no value (order 271.4 fix B). Set for a standards re-extraction; it adds rows to a standard that has such cells |
| `page_read_by_reading_enabled` | `False` | rollout | 2026-11-01 | 2026-11-14 | A page counts as read when a text or picture reading came back, apart from fields found; Word reaches the fact reader (#1473) |
| `kind_chooses_rules_enabled` | `False` | rollout | 2026-11-01 | 2026-11-15 | The document kind chooses the rule set: a non-datasheet gets no equipment datasheet checklist and no equipment-type standards; unknown keeps today's path, marked (#1474) |
| `at_limit_precision_enabled` | `False` | rollout | 2026-11-01 | 2026-11-15 | A value exactly at a percent or factor limit ("1.1 x MAWP", "10 % above") is at it in every unit, not just under it by float rounding; switch on promptly, it removes a possible wrong Fail (#1475) |
| `percent_kind_check_enabled` | `False` | rollout | 2026-11-01 | 2026-11-15 | A value printed under a % label with a fraction-sized number ("0.30 %") is never decided on the percent cards (PSV-27/28/29); it goes to the engineer; switch on promptly, it removes a possible wrong approval (#1512) |
| `nothing_read_fails_enabled` | `False` | rollout | 2026-11-01 | 2026-11-14 | A review whose submittal has no fact and no page text or reading ends failed: nothing read (#1495) |
| `pump_kit_draft_enabled` | `False` | rollout | 2026-11-01 | 2026-11-15 | Draft pump kit cards from held standards (SAES-G-005) join the Centrifugal Pump checklist; draft only, never decide; preparation for #1478, proof waits for 2 real pump documents |
| `crs_export_quality_enabled` | `False` | rollout | 2026-11-01 | 2026-11-15 | CRS export quality (#1503): one row per section + clause, no empty rows, page or "page not found" on every row, comments at most 350 characters, Reasoning and Rule trust on an Internal sheet the contractor copy lacks, trimmed standards sheet, Priority from a fixed list; export only, no verdict changes |
| `vessel_kit_draft_enabled` | `False` | rollout | 2026-11-01 | 2026-11-15 | Draft vessel kit cards from held standards (SAES-D-001) join the Pressure Vessel checklist; every row held for the engineer, never decides; preparation for the parked vessel kit (#1480), proof waits for 2 real vessel documents |
| `exchanger_kit_draft_enabled` | `False` | rollout | 2026-11-01 | 2026-11-15 | Draft exchanger kit cards from the held standard SAES-E-004 join the Heat Exchanger checklist; every row held for the engineer, never decides; preparation for the parked exchanger kit (#1481), proof waits for 2 real exchanger documents |
| `datasheet_office_input` | `False` | rollout | 2026-10-17 | 2026-10-31 | Index workbooks and Word datasheets |
| `docx_input_enabled` | `True` | rollout | 2026-10-17 | 2026-10-31 | Word input |
| `startup_warmup` | `True` | permanent | | | Operator setting: model warm-up at start |
| `onnx_cpu_arena_rerank` | `True` | permanent | | | Machine-specific memory tuning |
| `onnx_cpu_arena_embed` | `False` | permanent | | | Machine-specific memory tuning |
| `market_live_enabled` | `False` | permanent | | | Egress gate for the market lane (rule 1) |
| `market_allow_public_egress` | `False` | permanent | | | Egress gate for the market lane (rule 1) |
| `standards_reader_enabled` | `False` | permanent | | | Egress gate for the Claude lane (rule 1) |
| `standards_reader_allow_public_egress` | `False` | permanent | | | Egress gate for the Claude lane (rule 1) |
| `claude_approved_list_enforced` | `True` | permanent | | | Stays on; the switch exists for the test suite (#806 S3) |
| `chat_web_enabled` | `False` | permanent | | | Egress gate: chat web search through the market lane |
| `review_ai_check_enabled` | `True` | rollout | 2026-10-17 | 2026-10-31 | AI engineering check (#799) |
| `review_web_standards_enabled` | `False` | permanent | | | Egress gate: standards web search through the market lane |
| `rule_parse_model_enabled` | `False` | rollout | 2026-10-17 | 2026-10-31 | Model rule parser |
| `smtp_enabled` | `False` | permanent | | | Egress gate for SMTP (rule 1) |
| `smtp_starttls` | `True` | permanent | | | TLS mode; exactly one is on (#440) |
| `smtp_ssl` | `False` | permanent | | | TLS mode; exactly one is on (#440) |
| `clause_review_enabled` | `False` | rollout | 2026-11-01 | 2026-11-15 | AI clause review of a procedure or specification submittal (#1477): local model only, code-verified quotes, rows are suggestions for the engineer and never in a headline; off, nothing changes |
| `spec_kit_enabled` | `False` | rollout | 2026-11-01 | 2026-11-15 | Specification kit (#1479, preparation): a DRAFT must-contain list per discipline looked up in the specification's own pages (code-verified quotes, no model), numeric limits cross-checked with a datasheet of the same number or tag; engineer rows only, never a verdict; off, nothing changes |
| `parked_kits_draft_enabled` | `False` | rollout | 2026-11-01 | 2026-11-15 | Parked kits (#1484 drawing, preparation): the specification-kit look-up routed by document kind, a DRAFT must-contain list for a drawing from the held SAES-A-202, no model; engineer rows only, never a verdict; transmittal and contract have no held standard and no kit; off, nothing changes |
| `document_kind_enabled` | `False` | rollout | 2026-11-01 | 2026-11-15 | Document kind from title block and cover, no body-text equipment fallback for non-datasheets (#1474); off, nothing is stored and nothing changes |
| `review_progress_bar_enabled` | `False` | rollout | 2026-11-01 | 2026-11-15 | Progress block on a running review (#1494): pages done of total, elapsed time, labelled time-left estimate, stall light; read-only from the jobs row; off, the screen shows the step line as before; owner decides default on or remove |
| `leading_dot_decimal_enabled` | `False` | rollout | 2026-11-01 | 2026-11-15 | A number written without its leading zero (".30", "-.5", ".5 mm") is read as the decimal it is (#1515); ".30" was read as 30 and ".5 mm" was dropped; ambiguous shapes (".5.3") are no value; owner should switch on promptly |
| `playbook_section_presence_enabled` | `False` | rollout | 2026-11-01 | 2026-11-15 | A playbook element is present only when the matching passage is its own section (cue in a heading or section title); a passing mention in another section is unclear, an engineer row (#1522); a heading counts only if it holds one of the element's cues, e.g. 'Study Team' alone is unclear; a loose heading with a generic cue ('Participants') still counts as present, a limit not fixed here; off, a cue in any passage counts as before |
| `procedure_playbook_rows_enabled` | `False` | rollout | 2026-11-01 | 2026-11-15 | A procedure's CRS gets one engineer row per element of each playbook whose title cue is in its cover lines (#1522 b): never compliant, 'found, engineer to confirm' with page and quote, 'unclear'/'missing' say so, a standard not held is never met, draft notice on each row; no match = no rows and one review note; no model; off, the CRS is unchanged. Limit: the cue is the playbook title's subject words in the first 12 lines of page 1 |
