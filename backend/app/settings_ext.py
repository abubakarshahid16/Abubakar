"""Settings kept out of `config.py` (it may only shrink): a base of `config.Settings`.

Clause review (#1477) and nothing-read (#1495) fields. They are read from the
environment exactly like every other setting (`Settings` inherits them).
"""

from pydantic import BaseModel, Field

#: Settings that change a review's answer only when moved off their default. They join
#: `config_version` only then, so adding one leaves every recorded hash and baseline as it was.
ANSWER_AFFECTING_WHEN_CHANGED = ("ai_division_scope_engine",)


def answer_affecting_when_changed(settings) -> dict:
    """The settings above that are off their default, for `config_version`."""
    fields = type(settings).model_fields
    return {
        k: getattr(settings, k)
        for k in ANSWER_AFFECTING_WHEN_CHANGED
        if getattr(settings, k) != fields[k].default
    }


class SettingsExt(BaseModel):
    #: #1584 standards compiler (`standards_compiler.py`, `scripts/compile_standards.py`): Claude turns a held
    #: standard into version 2 rules on a database COPY; code verifies every quote; the rules are held until the
    #: owner approves them and change no verdict. OFF: nothing changes. Env: STANDARDS_COMPILER_ENABLED.
    standards_compiler_enabled: bool = False
    #: The model it asks. Env: STANDARDS_COMPILER_MODEL.
    standards_compiler_model: str = "claude-sonnet-5-5"
    #: Standard families it may send. API, ASME and NACE (cited as ISO 15156 / NACE MR0175) by the owner's decision on #1584 (2 Nov 2026), for this compiler
    #: only (the old converter keeps its own list). Setting it can narrow the list. Env: STANDARDS_COMPILER_FAMILIES.
    standards_compiler_families: str = "SAES,ISO,API,ASME,NACE"
    #: The default of `--max-usd`: the owner's USD 100 a day, across every standard, read from the spend ledger.
    #: Env: STANDARDS_COMPILER_MAX_USD_PER_DAY.
    standards_compiler_max_usd_per_day: float = Field(100.0, gt=0)
    #: Division scope's OWN engine (owner decision, 2 Nov 2026): `claude` reads a standard's
    #: part scopes on the Claude API (`division_text.claude_reader`), under the provider
    #: switch, both egress flags, the approved and block lists, the answer cache and the USD
    #: caps. Anything else stays on the local model; in a Claude-lane run that is skipped and
    #: listed as not checked. Env: AI_DIVISION_SCOPE_ENGINE.
    ai_division_scope_engine: str = "ollama"
    #: #805 plan change 6, part A: the rulebook's version 2 tables (`rulebook_v2.py`, `scripts/rulebook_v2.py`), on a
    #: database COPY. No verdict reads them; no rule is in force until a person approves it. OFF: nothing is read,
    #: created or written. Env: RULEBOOK_V2_ENABLED.
    rulebook_v2_enabled: bool = False
    #: #805 plan change 6: a review reads the approved version 2 rules for the document's equipment type beside version
    #: 1 (`rulebook_v2_review.py`). Needs RULEBOOK_V2_ENABLED and the tables, so a database copy today. OFF: a review
    #: reads none of it and is byte-identical. Env: RULEBOOK_V2_REVIEW_ENABLED.
    rulebook_v2_review_enabled: bool = False
    #: #805 order 3 Nov STEP 5: the register of every edition of a standard with its issue date
    #: (`standard_editions.py`), on a database COPY. The pure choice of edition needs no switch. OFF: nothing is read,
    #: created or written. Env: STANDARD_EDITIONS_ENABLED.
    standard_editions_enabled: bool = False
    #: #805 plan change 6: a second call per compiled rule names its field from the equipment type's fixed list
    #: (`rule_field_naming.py`, `scripts/name_rule_fields.py`). "off" sends nothing; "claude" goes through
    #: `reader_transport`, under the compiler's gates and caps. Env: RULE_FIELD_NAMING_ENGINE.
    rule_field_naming_engine: str = "off"
    #: #1584, the proof run only: a rule forbidding a material decides through the owner-signed grade table
    #: (`material_reference.py`), and each finding says it is not engineer-confirmed. Env: MATERIAL_REFERENCE_ENABLED.
    material_reference_enabled: bool = False
    #: Who proposes that table: "off" sends nothing. One call, no document text. Env: MATERIAL_REFERENCE_ENGINE.
    material_reference_engine: str = "off"
    #: Sonnet, not Haiku: one short call, and a wrong family is what a verdict would rest on. Env: MATERIAL_REFERENCE_MODEL.
    material_reference_model: str = "claude-sonnet-5-5"
    #: #805 plan change 6, the owner's to turn on: an owner's written note on a context-dependent rule lets that rule
    #: decide, and the finding says so. It lifts the context flag only, never an unverifiable condition or a low reading
    #: confidence. OFF: such a rule is a Query. Env: OWNER_NOTE_LIFTS_CONTEXT_FLAG_ENABLED.
    owner_note_lifts_context_flag_enabled: bool = False
    #: The model of that step. Env: RULE_FIELD_NAMING_MODEL.
    rule_field_naming_model: str = "claude-haiku-5-5"
    #: AI clause review of a PROCEDURE or SPECIFICATION submittal (`clause_review.py`):
    #: one requirement at a time against the 4 most relevant small passages of the
    #: submittal, on the local model unless its engine says otherwise, every
    #: quote verified by code on the stored page text, never a verdict. OFF: nothing
    #: changes. Env: CLAUSE_REVIEW_ENABLED.
    clause_review_enabled: bool = True
    #: The clause review's OWN engine (owner order, 2 Nov 2026). `claude`: every applicable requirement by
    #: Message Batch (`clause_review_claude.py`), under the provider switch, both egress flags, the approved
    #: and block lists, the answer cache and the USD caps. Anything else: the local model, with its limit.
    #: Env: AI_CLAUSE_REVIEW_ENGINE.
    ai_clause_review_engine: str = "ollama"
    #: How often the idle worker asks the API about a batch. Env: CLAUSE_REVIEW_BATCH_POLL_SECONDS.
    clause_review_batch_poll_seconds: float = Field(300.0, gt=0)
    #: Hours after which nothing new is sent and an ask never sent is counted so. The API ends a batch by 24 h.
    #: Env: CLAUSE_REVIEW_BATCH_WAIT_HOURS.
    clause_review_batch_wait_hours: float = Field(26.0, gt=0)
    #: Days a sent ask's result is still read, because it may be paid for (the API keeps results about 29 days). After
    #: that it is charged at its worst case, marked estimated. Env: CLAUSE_REVIEW_BATCH_READ_DAYS.
    clause_review_batch_read_days: float = Field(29.0, gt=0)
    #: The time allowed per page of the document; the run stops cleanly when
    #: pages x this is spent and names the requirements not reviewed. Measured
    #: minutes per page is recorded on the run. Env: CLAUSE_REVIEW_SECONDS_PER_PAGE.
    clause_review_seconds_per_page: float = Field(90.0, gt=0)
    #: At most this many requirements per run (the rest are named as not reviewed);
    #: 0 = no count cap. Env: CLAUSE_REVIEW_MAX_REQUIREMENTS.
    clause_review_max_requirements: int = Field(60, ge=0)
    #: Whole-document clause review: the 60-requirement count cap is lifted and the run
    #: is bounded by ONE time budget instead; what the budget leaves unread is named
    #: ("N of M reviewed; K not reviewed (time budget of T s reached); first not
    #: reviewed: ..."), never a pass. This mode is the LOCAL model; stored answers are
    #: reused. OFF: the count cap and the per-page budget behave as before.
    #: Env: CLAUSE_REVIEW_WHOLE_DOCUMENT_ENABLED.
    clause_review_whole_document_enabled: bool = False
    #: Seconds for the whole clause review of one run in whole-document mode. Default 7200
    #: (2 h): a local call with thinking is about 20 to 60 s (timeout 600 s), so this reads
    #: roughly 120 to 360 requirements, and it stays under the 3 h stale limit of the heavy
    #: lock. Checked between calls, so one call started near the end can overrun it by up to
    #: clause_review_call_timeout_s (600 s): worst case about 7800 s. Env: CLAUSE_REVIEW_TIME_BUDGET_S.
    clause_review_time_budget_s: float = Field(7200.0, gt=0)
    #: Seconds one local call may take, and its output cap (thinking is on, and
    #: its tokens count). Env: CLAUSE_REVIEW_CALL_TIMEOUT_S, CLAUSE_REVIEW_NUM_PREDICT.
    clause_review_call_timeout_s: float = Field(600.0, gt=0)
    clause_review_num_predict: int = Field(6000, ge=512)
    #: #1495 (kept here so `config.py` does not grow): a review whose submittal has
    #: no current fact AND no page text or reading ends failed "nothing read", never
    #: completed. Pages read with no datasheet field are NOT failed. OFF: nothing
    #: changes. Env: NOTHING_READ_FAILS_ENABLED.
    nothing_read_fails_enabled: bool = True
    #: #1479 specification kit (preparation, `spec_kit.py`): a DRAFT must-contain list per
    #: discipline looked up in a specification's own pages, no model; numeric limits
    #: cross-checked with a datasheet of the same number or tag. Engineer rows only.
    #: OFF: nothing changes. Env: SPEC_KIT_ENABLED.
    spec_kit_enabled: bool = False
    #: #1472 (kept here so `config.py` does not grow): the datasheet checks read ONE value where
    #: a sheet prints a range twice (a plain note on one reading), and a combined "a / b / c"
    #: label answers each text attribute it names. OFF: nothing changes.
    #: Env: DATASHEET_ONE_VALUE_ENABLED.
    datasheet_one_value_enabled: bool = True
    #: #1607: `scripts/crs_bench.py` also runs the planted-defect sheets on its own copy and
    #: prints the table. Printed only: the gate does not read it until the baseline is
    #: stable. OFF: the bench runs no scorer. Env: PLANTED_DEFECTS_BENCH_ENABLED.
    planted_defects_bench_enabled: bool = False
    #: A datasheet field the sheet gives is not reported missing or conflicting for two general reasons: a split
    #: abbreviation ("tube o d" for O.D.) is joined before the role table is read, and a reading with no unit
    #: beside a reading of the same number with one is one value. Never decides (see `label_match`). OFF: nothing
    #: changes. Env: DATASHEET_LABEL_JOIN_ENABLED.
    datasheet_label_join_enabled: bool = True
    #: #1484 (parked kits, preparation): the same look-up routed by document KIND for a kind a held
    #: standard covers (drawing, from SAES-A-202): a DRAFT must-contain list, no model, engineer
    #: rows only. Transmittal (#1482) and contract (#1483) have no held standard and no kit.
    #: OFF: nothing changes. Env: PARKED_KITS_DRAFT_ENABLED.
    parked_kits_draft_enabled: bool = False
    #: #1482 transmittal kit (`transmittal_kit.py`): for a transmittal, header fields not stated, its
    #: table of listed documents read by code, the listed revision and sheet count compared with the
    #: held document, and a required-submissions list named at run time (CLIENT DATA, read from the
    #: local DB only). No model; engineer rows only, never a verdict. OFF: nothing changes.
    #: Env: TRANSMITTAL_KIT_ENABLED.
    transmittal_kit_enabled: bool = True
    #: #1482: comma-separated ids of the held documents that are the required-submissions list;
    #: empty skips that step with one note. Env: TRANSMITTAL_REQUIRED_LIST_DOCUMENT_IDS.
    transmittal_required_list_document_ids: str = ""

    #: #1474: the document KIND (router table `document_kinds`) chooses the rule set: a
    #: document whose kind is anything but datasheet gets no equipment datasheet checklist and
    #: no equipment-type standards, and its equipment type drives no review step (`kind_rules.py`).
    #: unknown / undecided keeps today's behaviour, marked. OFF: nothing changes.
    #: Env: KIND_CHOOSES_RULES_ENABLED.
    kind_chooses_rules_enabled: bool = True
    #: Standards by ROLE and document KIND (`kind_standards.py`, `reference/standard_roles.json`, owner order 3 Nov): a
    #: procedure or study leaves out equipment design standards and says so in the run note; the method standards it
    #: needs, when not held, are named once. OFF: nothing changes. Env: STANDARD_ROLES_BY_KIND_ENABLED.
    standard_roles_by_kind_enabled: bool = False
    #: Rules by equipment scope (`equipment_scope.py`): a rule whose own scope (its single-equipment
    #: standard, or its document kind) names a DIFFERENT equipment type or
    #: kind than the submittal's is left out and counted in a note; unknown scope stays in. Narrowing
    #: only. OFF: nothing changes. Env: RULES_BY_EQUIPMENT_SCOPE_ENABLED.
    rules_by_equipment_scope_enabled: bool = False
    #: Rule equipment scope on extraction (`rule_equipment_scope.py`): each extracted rule's
    #: equipment type is read from its own clause wording or heading chain and stored in
    #: `standard_requirements.equipment_type` with a quote, page and method; unknown stays empty.
    #: Local only, no model, no socket. OFF: nothing changes. Env: RULE_EQUIPMENT_SCOPE_EXTRACT_ENABLED.
    rule_equipment_scope_extract_enabled: bool = False
    #: Optional local-model pass of `scripts/reextract_rule_equipment_scope.py` for clauses the code
    #: left unknown (local Ollama via `model_transport` only, code verifies the quote). OFF.
    #: Env: RULE_EQUIPMENT_SCOPE_MODEL_ENABLED.
    rule_equipment_scope_model_enabled: bool = False
    #: #1478 pump kit PREPARATION: append the DRAFT pump cards of `reference/pump_kit_draft.json`
    #: (a held standard requires the value, not already in the checklist) to the Centrifugal Pump
    #: checklist. Draft only, never decides, local only. OFF: nothing changes. Env: PUMP_KIT_DRAFT_ENABLED.
    pump_kit_draft_enabled: bool = False
    #: #1475 finding: a value exactly AT a percent / factor limit ("1.05 x operating pressure",
    #: "10 % above", "110 % of the MAWP") can read just under it in some units by float rounding and
    #: fail wrongly. ON: the limit comparison ignores float noise (1e-9 relative), never wider.
    #: The owner should switch this on promptly: it removes a possible wrong Fail. OFF: nothing
    #: changes. Env: AT_LIMIT_PRECISION_ENABLED.
    at_limit_precision_enabled: bool = False
    #: #1512: a value printed under a % label with a fraction-sized number ("0.30 %": 0.30 % or the
    #: fraction 0.30 = 30 %?) is never decided on the percent cards (PSV-27, PSV-28, PSV-29); it goes
    #: to the engineer with the reason. The owner should switch this on promptly: it removes a possible
    #: wrong approval. OFF: nothing changes. Env: PERCENT_KIND_CHECK_ENABLED.
    percent_kind_check_enabled: bool = False
    #: #1503 CRS EXPORT QUALITY (`crs_export_quality.py`): one row per section + clause, no
    #: empty rows, a page or "page not found (reason)" on every row, comments at most 350
    #: characters, Reasoning and Rule trust on an Internal sheet the contractor copy lacks,
    #: the standards sheet without "Considered, not applied", "not in your library" by kind,
    #: Priority from the fixed list. EXPORT ONLY: no verdict, status or finding changes.
    #: OFF: nothing changes. Env: CRS_EXPORT_QUALITY_ENABLED.
    crs_export_quality_enabled: bool = False
    #: #1503 remainder, needs the switch above: rows with no page merge on one clause when
    #: they print the same reason (a safety tick stays its own row), a comment that was only the
    #: "not yet proven" flag counts as no comment, more spellings of a material standard, and
    #: the screen shows the Internal sheet. EXPORT ONLY. OFF: as #1509 left it.
    #: Env: CRS_EXPORT_QUALITY_STRICT_ENABLED.
    crs_export_quality_strict_enabled: bool = False
    #: #1503 owner decision (`crs_one_row.py`): rows with the same clause, problem, value and
    #: verdict are one row listing every tag, page and sentence; a "did not reference X" row goes when
    #: nothing in scope requires X, counted and named in Review notes. On, the export views of
    #: the two switches above merge nothing more. Findings are never touched. OFF: as it was.
    #: Env: CRS_ONE_ROW_PER_PROBLEM_ENABLED.
    crs_one_row_per_problem_enabled: bool = False
    #: Owner order 3 Nov (item 14): ONE note at the top of the INTERNAL CRS copy, saying the rules used are
    #: drafts checked by code unless the row's Rule trust text says a person approved it, and that an engineer must confirm. Export text
    #: only; no row, verdict or number changes. OFF: the sheet is as it was. Env: CRS_RULES_NOTE_ENABLED.
    crs_rules_note_enabled: bool = False
    #: Owner 3 Nov 11:40 (a): with the switch above, rows with the same problem, field, value, verdict and page are
    #: one row whatever the clause or standard; the merged row lists every reference, tag and page. OFF: the
    #: clause is part of the key, as merged in #1648. Env: CRS_ONE_ROW_IGNORE_CLAUSE_ENABLED.
    crs_one_row_ignore_clause_enabled: bool = False
    #: #1591: on that export, a row with no page says the section or field it is about and why it
    #: has no page, never "page not found". A page still comes only from a verified quote. Needs
    #: CRS_EXPORT_QUALITY_ENABLED. OFF: nothing changes. Env: CRS_PAGE_CELL_FIELD_ENABLED.
    crs_page_cell_field_enabled: bool = False
    #: #1480 vessel kit PREPARATION (parked, milestone 58): append the DRAFT vessel cards of
    #: `reference/vessel_kit_draft.json` (a held standard requires the value, not already in the
    #: checklist) to the Pressure Vessel checklist. Draft only, never decides, local only, every
    #: row held for the engineer. OFF: nothing changes. Env: VESSEL_KIT_DRAFT_ENABLED.
    vessel_kit_draft_enabled: bool = False
    #: #1515 a number written without its leading zero (".30", "-.5") is the decimal it is, in
    #: `numparse.parse_value` and in `claims.extract_measurements` (".5 mm" was dropped); a stranded
    #: or glued dot (".5.3", "x.5") is no value. OFF: ".30" reads as 30 and ".5 mm" is dropped,
    #: as before. Env: LEADING_DOT_DECIMAL_ENABLED.
    leading_dot_decimal_enabled: bool = False
    #: Kit proof 1 Nov: a page whose lines are mostly measured values (a datasheet page) is never set
    #: aside as book front matter because of a copyright footer, so the fact reader sees it. OFF: the
    #: footer decides as before. Takes effect when a document is (re)chunked.
    #: Env: DATA_PAGE_NOT_FRONTMATTER_ENABLED.
    data_page_not_frontmatter_enabled: bool = True
    #: #1478 kit proof 1 Nov: a line carrying a front-matter marker ("Copyright ... All rights
    #: reserved.") that repeats on three or more pages is the document's running footer, so it is
    #: not counted as front-matter evidence on any page; a vendor sheet's drawing pages under it were
    #: set aside and never read. OFF: the footer counts as before. Takes effect when a document is
    #: (re)chunked. Env: RUNNING_FOOTER_NOT_FRONTMATTER_ENABLED.
    running_footer_not_frontmatter_enabled: bool = False
    #: 1 Nov proof of IOGP S-619 (public vessel spec): 25 of 85 pages are a drawing (one picture over
    #: 47 % of the page) under a 100-150 character running header; the router needs 50 % coverage, so
    #: they were never recognised and the chunker dropped them. ON: a page where one picture covers a
    #: quarter and the text layer is furniture only (300 characters or less) goes to recognition.
    #: OFF: unchanged. Takes effect on a new upload or `scripts/reroute_ocr.py`.
    #: Env: FIGURE_PAGE_OCR_ENABLED.
    figure_page_ocr_enabled: bool = False
    #: 1 Nov proof of a public filled pump sheet (#1478): the duty-point table (a header line of names with
    #: bracketed units, lines of numbers under it) gave no fact, and three stacked label lines in one table cell
    #: were joined into one jumbled label. ON: a header line of unit-bearing names with numbers under it gives one
    #: label/value per number (row number kept when several rows); a cell of three or more short capitals-only
    #: label lines is unreadable (no row keyed from it). OFF: unchanged. Plain code, no model.
    #: Takes effect on the next extraction. Env: PAGE_COLUMN_ROWS_ENABLED.
    page_column_rows_enabled: bool = False
    #: #1522 a playbook element (`playbooks._match`) is "present" only when the matching passage is
    #: the element's OWN section (a cue in its heading or section title); a passing mention in the
    #: body of another section becomes "unclear" (an engineer row), never "present". OFF: a passage
    #: holding a cue of every group is present wherever it sits, as before.
    #: LIMITS: a heading counts only if it holds one of the element's cues; e.g. 'Study Team' alone is
    #: unclear (recall lost on purpose). A loose heading holding a generic cue ('Participants',
    #: 'Safety report summary') still counts as present; not fixed here.
    #: Env: PLAYBOOK_SECTION_PRESENCE_ENABLED.
    playbook_section_presence_enabled: bool = True
    #: Owner decision 1 Nov (#1522): with PLAYBOOK_SECTION_PRESENCE also on, a playbook element whose
    #: standard is NOT held still gets the section-presence check. Missing: "Section not found: <element>.
    #: Required by <standard clause> per the draft HAZOP checklist (not yet engineer-approved); standard not
    #: held, its text is not quoted; engineer to confirm." (SIL: "draft SIL checklist"; "approved" only once
    #: an engineer signs the playbook off.) Found: the page and the section heading, content not checked,
    #: engineer to confirm. Unclear stays unclear, and so does an element with no section of its own that one
    #: passage elsewhere states in full (never "Section not found"); an unclear row quotes that passage (at
    #: most 15 words, verified on the cited page's text, else says no quote was verified). A document with no section
    #: heading read (e.g. a PDF chunked without headings): could not be checked. The state stays
    #: standard_not_held: never met, never compliant. LIMIT: a removed section whose content is still
    #: stated in full elsewhere is "unclear", not "not found".
    #: OFF (or presence off): "<standard> is not in the library" as before.
    #: Env: PLAYBOOK_PRESENCE_WITHOUT_STANDARD_ENABLED.
    playbook_presence_without_standard_enabled: bool = True
    #: #1522 (b) a review run of a document whose stored kind is `procedure` looks up the playbooks of
    #: that kind whose title cue is in the procedure's cover lines and adds one CRS row per element as an
    #: ENGINEER row (`procedure_playbook_rows`): never compliant, "found, engineer to confirm" with the page
    #: quote, 'unclear'/'missing' say so, a standard not held is never met. None matched: no rows and one
    #: review note. No model. OFF: the CRS is byte-identical. Env: PROCEDURE_PLAYBOOK_ROWS_ENABLED.
    procedure_playbook_rows_enabled: bool = True
    #: #1481 heat exchanger kit PREPARATION (parked, milestone 58): append the DRAFT exchanger cards of
    #: `reference/exchanger_kit_draft.json` (the held standard SAES-E-004 requires the value, not already in the
    #: checklist) to the Heat Exchanger checklist. Draft only, never decides, local only, every row held for the
    #: engineer. OFF: nothing changes. Env: EXCHANGER_KIT_DRAFT_ENABLED.
    exchanger_kit_draft_enabled: bool = False
    #: #1525 per-review audit report: `review_audit.py` writes AUDIT.md + AUDIT.json (pages read, standards,
    #: rules compared, AI use, gates, CRS) for each finished review, from what the run stored. Local files only,
    #: export only, no verdict changes, no model, no socket, no document text beyond page and clause numbers
    #: and stored quote snippets. OFF: nothing is written. Env: REVIEW_AUDIT_REPORT_ENABLED.
    review_audit_report_enabled: bool = True
    #: Folder the audit files go under (`<date>-<run id>/`). Empty = `~/project/mirror/proof`.
    #: Env: REVIEW_AUDIT_DIR.
    review_audit_dir: str = ""
    #: One intake layer (W5b-01, #525, part 1): extraction reads every file through `intake.read` (PDF and
    #: Word as today; Excel one page per visible sheet; an image one page waiting for OCR) and a file it
    #: cannot read is refused with a reason. Local only, no model, no socket. OFF: nothing changes.
    #: Env: ONE_INTAKE_ENABLED.
    one_intake_enabled: bool = False
    #: A Word file's real pages (`docx_reader`): its saved page markers number its blocks, its tables
    #: and pictures are counted against what reached the reader, and an embedded picture goes to the
    #: local OCR engine (`word_pictures`; no Claude lane, no reader model). No markers: the section
    #: heading is shown in the page cells, but comment text can still say a part number is a page, so
    #: this must not go on for Word files with no markers. OFF: reading parts as before, nothing recognised,
    #: nothing stored. Env: WORD_PAGE_MARKERS_ENABLED.
    word_page_markers_enabled: bool = False
    #: #525 slice 2 (with ONE_INTAKE_ENABLED on as well): the upload accepts PNG, JPEG and TIFF images
    #: (stored as picture-only PDF pages beside the original, so OCR reads them like a scanned page) and
    #: indexes .xlsx workbooks, each sheet chunked with a sheet + cell-range citation. Local only, no
    #: model, no socket. OFF: images refused and workbooks stored-not-indexed, as today.
    #: Env: INTAKE_IMAGES_XLSX_ENABLED.
    intake_images_xlsx_enabled: bool = False
    #: #525 slice 3 (with ONE_INTAKE_ENABLED on as well): every page of every file is stored as numbered
    #: text and table blocks with a hash and one citation form (`intake_blocks`), and recognition keeps a
    #: scanned page's table grid from where its lines sit. Additive: nothing reads the blocks yet. Local
    #: only, no model, no socket. OFF: nothing is stored. Env: INTAKE_BLOCKS_ENABLED.
    intake_blocks_enabled: bool = False
    #: #645 slice 3 (`ai_requirement_chunks.py`): the LOCAL model reads a held standard chunks
    #: and proposes single limits; code verifies every field; drafts only.
    #: OFF: nothing is read or stored. Env: AI_REQUIREMENT_EXTRACTION_ENABLED.
    ai_requirement_extraction_enabled: bool = False
    #: #645 slice 3: a quote from a chunk ACROSS pages is cited to the one page whose own text holds
    #: it whole (none or several: refused, as before); accept checks it there again. No new model call.
    #: OFF: such a quote is refused (page uncertain). Env: AI_REQUIREMENT_QUOTE_PAGE_ENABLED.
    ai_requirement_quote_page_enabled: bool = False
    #: #645 slice 4: a run of the extraction above reads only chunks this model has not read yet
    #: (a chunk with an unread passage is read again), so runs walk the whole standard; the answer
    #: says how many chunks are left. No new model call. OFF: the first chunks every run, as before.
    #: Env: AI_REQUIREMENT_EXTRACTION_RESUME_ENABLED.
    ai_requirement_extraction_resume_enabled: bool = False
    #: Owner decision 1 Nov (part of #1478): ONLY the title block (`classification.title_block_lines`) sets
    #: the equipment type; a section or panel heading in the page body never does (a pump sheet's 'MOTOR
    #: DATA' panel made it a Motor). None or two different types in the title block: the type is NULL,
    #: marked 'engineer to confirm', with a Review note; no checklist is chosen. The standards step still runs with no equipment term: the
    #: first 5 standards the sheet's own words match are kept and say so, the rest are named as not checked. No
    #: type is taken from the body: no heading, title or field reads as the equipment. OFF: unchanged.
    #: Env: EQUIPMENT_FROM_TITLE_BLOCK_ENABLED.
    equipment_from_title_block_enabled: bool = False
    #: #1476/#1522 (owner, 1 Nov): a PDF's section headings are also read from how a line is set
    #: (`pdf_headings`): a font larger than the body, or bold where the body is not, on a short title-like
    #: line standing alone with body text after it; or, in body type, a short line opening with a dotted
    #: section number (1.2, A.1). A lone '1.' never. Part of the chunk signature: ON marks every stored PDF stale until re-chunked.
    #: OFF: nothing is read, chunks and signature byte-identical. Env: PDF_HEADING_DETECTION_ENABLED.
    pdf_heading_detection_enabled: bool = False
    #: Order 4b: an expired sign-in (a 401) tells the reader so, once, on the sign-in form, and says
    #: unsaved decisions are kept; while signed in the page also asks `/api/auth/me` once a minute,
    #: because reads outside the gated routes answer an empty 200 instead of a 401. Sent to the page on
    #: the signed-in user (`Me.session_expired_notice`). OFF: the form with no reason and no extra
    #: request, as before. Env: SESSION_EXPIRED_NOTICE_ENABLED.
    session_expired_notice_enabled: bool = False
    #: #1592 items d and e: the CRS notice names each part that could not be checked by what it is,
    #: and the internal copy says in plain words why rows say ENGINEER TO TICK. Words only: no row,
    #: verdict or count changes. OFF: nothing changes. Env: CRS_PLAIN_NOTES_ENABLED.
    crs_plain_notes_enabled: bool = False
    #: Test B / HAZOP (part of #805): the playbook review indexes attachment, appendix, annex, table and item titles
    #: at review time (in memory, nothing stored), so an element whose section is an attachment is found; a title
    #: is about an element only through a cue that is not a generic title word; a partial own-section hit says
    #: "the closest section", never "a section of its own was found". OFF: as it was. Env: SECTION_INDEX_ENABLED.
    section_index_enabled: bool = False
    #: Owner 3 Nov (test B): a part printed alone in a materials list ("IMPELLER: <material>") or a seal stated in a
    #: sentence fills its field (impeller / shaft / casing material, seal type) when ALL of `part_name_roles`'s
    #: strict rules hold, in the form reader's label gate and in the stored-facts check. OFF: as it was.
    #: Env: FORM_PART_NAME_ROLES_ENABLED.
    form_part_name_roles_enabled: bool = False
    #: Owner order 3 Nov 11:40 (item 14c): the contractor copy never tells the contractor that an engineer
    #: must confirm or check anything: wording about the engineer is cut from its comments, and a code check
    #: (`crs_export_quality.engineer_words_in`) names any left. Internal copy unchanged.
    #: OFF: as it was. Env: CRS_CONTRACTOR_NO_ENGINEER_WORDS_ENABLED.
    crs_contractor_no_engineer_words_enabled: bool = False
    #: Owner 3 Nov 12:20: a cited standard is never called "does not appear to apply" on the table's word
    #: alone (the table lists what a standard governs, not what its scope clause excludes: a pressure-vessel
    #: standard can apply to a pump's package). With no scope shown to exclude the equipment, it is a Query for
    #: the engineer (`declared_check`). OFF: as it was. Env: STANDARD_SCOPE_NOT_NO_ENABLED.
    standard_scope_not_no_enabled: bool = False
    #: Owner 3 Nov 11:40 (b): a value the sheet gives that only a DRAFT rule checks, with nothing found, writes no
    #: CRS row; it is listed on the internal-only sheet "Compliance list" as "No issue found (draft rule)".
    #: Findings are untouched. OFF: as it was. Env: CRS_COMPLIANCE_LIST_ENABLED.
    crs_compliance_list_enabled: bool = False
    #: Owner order 10 Nov, step 4 (#805 Cycle 2): which sheet shows a row, by the stored hold reason (`crs_routing`).
    #: R1 a "did not reference X" row stays only when the held project specification requires X with a verified quote;
    #: R2 a check held because its applicability condition is not stated and R3 a check held for two values under a
    #: draft rule, with a stated value, go to the internal "Compliance list" with the reason; R4 a cited standard that
    #: does not appear to apply is named in the Review notes, not a comment; a draft-rule Pass held as `rule_not_proven`
    #: is listed as "No issue found (draft rule)" (`compliance_list._draft_pass`). No verdict changes. OFF: as it was.
    #: Env: CRS_ROUTING_BY_HOLD_REASON_ENABLED.
    crs_routing_by_hold_reason_enabled: bool = False
    #: Owner order 11 Nov (#805), owner answer: on the CONTRACTOR copy only, the rows held because the sheet marks
    #: a value as deferred ("By Contractor", "TBA"; hold reason `deferred_marker`) are ONE query row asking for the
    #: confirmed figures, each field still named with its tag and page (`crs_by_contractor`). The internal copy keeps
    #: one row per field; a row with the engineer's own words, a contractor reply or a closed number keeps its own
    #: row. Export only, no verdict changes. OFF: as it was. Env: CRS_BY_CONTRACTOR_ONE_ROW_ENABLED.
    crs_by_contractor_one_row_enabled: bool = False
    #: Owner order 11 Nov, step 2 (#805): paper kind first. Every paper gets one kind of a closed list (datasheet,
    #: procedure, contract, drawing, test record, other) from its own cover and title words (`paper_kind`), before
    #: the equipment type; a procedure or a contract keeps an equipment type only as a SECONDARY label, never the
    #: main one. Classification only, never access control (rule 5). No model. OFF: as it was.
    #: Env: PAPER_KIND_FIRST_ENABLED.
    paper_kind_first_enabled: bool = False
    #: Owner 3 Nov: on the export-quality path, an internal-copy row whose comment is only the "AI suggestion
    #: awaiting an engineer's decision" sentence leaves the CRS sheet; its AI words go to the Review notes.
    #: Needs CRS_EXPORT_QUALITY_ENABLED. OFF: as it was. Env: CRS_DROP_PLACEHOLDER_ROWS_ENABLED.
    crs_drop_placeholder_rows_enabled: bool = False
    #: #1608 (plan change 6 G): at the end of each comparison the run stores its rulebook (version used, rules applied,
    #: fingerprint) and the ticks imported; the internal CRS gets a "Run record" sheet with those, the run's models and
    #: the could-not-check list, which says so when empty (`run_record`). OFF: nothing stored, no sheet.
    #: Env: RUN_RECORD_ENABLED.
    run_record_enabled: bool = False
    #: Plan change 6 part B: one meaning of "checked" (`coverage_pair`). The CRS review notes and the
    #: screen's coverage lines print risk and coverage from the one function, in place of the clause
    #: coverage line (stored rows, checklist-covered rules added). The bench and the board call print
    #: the pair always. Also what "ready" means (`reading_state`): vectors complete and every page and
    #: picture read or listed as not read. OFF: every screen and CRS word as before. Env: ONE_CHECKED_DEFINITION_ENABLED.
    one_checked_definition_enabled: bool = False
    #: #1568: a page recognition failed on because the stored file could not be opened holds the document
    #: at partially_searchable with the reason (`reading_state`, `page_not_read.is_file_error`), and the OCR
    #: pools carry the parent's data directory to their workers (`stored_paths.pool_options`). Any other recognition
    #: failure stays as it was. Works with ONE_CHECKED_DEFINITION_ENABLED on or off. OFF: byte-identical,
    #: and at the next start a document it held goes back. Env: OCR_FILE_ERROR_HOLD_ENABLED.
    ocr_file_error_hold_enabled: bool = False
    #: Owner's text on #1584: a rule the owner approved (`approval.tier == "owner"`) may decide a verdict, labelled
    #: "AI-built, quote-verified, owner-approved" (`rule_trust.tier_for_approved`), never "engineer-approved". Code
    #: still compares a read value; a safety-tier COMPLIANT keeps the engineer's tick and, until ticked, no Approved
    #: code. On with no such rule in a run, and OFF, the run's output is byte-identical.
    #: Env: OWNER_APPROVED_RULES_DECIDE_ENABLED.
    owner_approved_rules_decide_enabled: bool = False
    #: Owner order 3 Nov (item 14): a rule an ENGINEER approved may decide Pass, Fail or Query like an
    #: owner-approved one, labelled engineer-approved. Needs the switch above. A draft, a rejected or an
    #: unsigned rule never decides. OFF: only the owner's approval decides. Env: ENGINEER_APPROVED_RULES_DECIDE_ENABLED.
    engineer_approved_rules_decide_enabled: bool = False
    #: #1638: a checklist `required` row only asks that a field is stated. ON: it counts for
    #: no approval and is not a decided rule, and is named "stated, not checked". OFF: a
    #: Pass like any other. Env: PRESENCE_NOT_PASS_ENABLED.
    presence_not_pass_enabled: bool = False
    #: Part of #805, 3 Nov: two DRAFT relief-valve process items (fluid phase, sour service; the
    #: governing relief case is already PSV-S05) are added to the checklist. They carry status "draft
    #: (engineer to approve)": a missing value is "Not stated ... Contractor to provide", a stated value
    #: gives no verdict, sour service stated "yes" is a Query for materials. OFF: the checklist is
    #: byte-identical. Env: DRAFT_PROCESS_ITEMS_ENABLED.
    draft_process_items_enabled: bool = False
    #: Order 4c, 2 Nov: the CRS of a procedure or other non-datasheet kind. It never shows or stores an
    #: equipment type (`document_classification` keeps its value: subject gates still read it); a row's page
    #: cell comes from its verified quote; no document id in Item No: the document number or a suggestion
    #: marked as a guess, else NO-NUMBER. OFF: byte-identical, except that rows numbered while it was on
    #: keep printing NO-NUMBER and the reply guard stays for them. Env: PROCEDURE_CRS_FIELDS_ENABLED.
    procedure_crs_fields_enabled: bool = True
    #: Models that REJECT `temperature` (400 "deprecated for this model", measured on
    #: claude-sonnet-5, 2026-09-25). Prefix match on the id, so "claude-opus-5" also covers
    #: claude-opus-5-5. Sonnet 5.5 and Haiku 5.5 refuse any non-default value, and the value
    #: sent is never the default. The API version in use (2023-06-01) bars it only per model.
    claude_models_without_temperature: tuple[str, ...] = (
        "claude-sonnet-5",
        "claude-opus-5",
        "claude-haiku-5",
        "claude-opus-4-7",
        "claude-opus-4-8",
        "claude-fable-5",
        "claude-mythos-5",
    )
    #: The ONLY models still sent `thinking.budget_tokens` (`claude_models.thinking_for`).
    claude_models_with_thinking_budget: tuple[str, ...] = (
        "claude-haiku-4-5",
        "claude-sonnet-4-5",
        "claude-opus-4-5",
        "claude-opus-4-1",
        "claude-opus-4-0",
        "claude-sonnet-4-0",
    )
    #: These models think by default and that output counts inside `max_tokens`, so a short
    #: cap (the reader's 512, the matcher's 200) could be spent before any answer. Theirs is
    #: raised to `claude_min_output_tokens` (`claude_spend.output_cap`; billed by use, and the
    #: budget gate's worst case sees it). Env: CLAUDE_MIN_OUTPUT_TOKENS.
    claude_models_thinking_by_default: tuple[str, ...] = (
        "claude-sonnet-5-5",
        "claude-opus-5-5",
        "claude-haiku-5-5",
    )
    claude_min_output_tokens: int = Field(4096, gt=0)
    #: The standards reader's and datasheet reader's model. Empty: `claude_reasoning_model`.
    #: The process environment wins over `backend/.env`. Env: STANDARDS_READER_MODEL.
    standards_reader_model: str = ""
    #: #1584 (owner decision, 2 Nov): a document uploaded for review joins the Claude approved list by itself
    #: (`claude_auto_approve`), and so does a standard its review cites or that governs it; a blocked hash and the
    #: register file (rule 3) never do. `<data_dir>/claude_blocked_hashes.json` must hold the owner's register hash:
    #: absent, unreadable or empty, nothing carrying a document is sent. It sends nothing by itself: the Claude
    #: lane's own gates stay. OFF: no hook writes and an automatic row does not count; blocks still apply.
    #: Env: CLAUDE_AUTO_APPROVE_REVIEWS_ENABLED.
    claude_auto_approve_reviews_enabled: bool = False
    #: Lock 2 (QA order 1.2, 2 Nov): a DRAFT checklist does not mark the requirements of the standards it cites
    #: "not used". They stay in scope, rule by rule; each verdict carries its own trust label even with
    #: RULE_AUTO_USE off, so an unproven rule is held for the engineer. A signed checklist governs as before. More
    #: rules reach the matcher, inside its existing per-run caps. OFF: as before.
    #: Env: DRAFT_CHECKLIST_KEEPS_STANDARDS_ENABLED.
    draft_checklist_keeps_standards_enabled: bool = False
    #: #805 plan change 6 E (`claude_spend_report`): each review run's spend per step in its record and audit. OFF:
    #: nothing is written. The USD 100 a day does not read this: it always binds (owner, #1584).
    #: Env: CLAUDE_COST_CONTROLS_ENABLED.
    claude_cost_controls_enabled: bool = False
    #: Owner, #1584 (2 Nov 2026, 15:05 PKT): inside one review run the AI clause review step has USD 10 (other steps
    #: `claude_budget_usd_per_step`), and the whole run at most USD 15, its steps together.
    #: Env: CLAUDE_BUDGET_USD_CLAUSE_REVIEW, CLAUDE_BUDGET_USD_PER_RUN.
    claude_budget_usd_clause_review: float = Field(10.0, gt=0)
    claude_budget_usd_per_run: float = Field(15.0, gt=0)
    #: The day cap; it can only narrow the owner's USD 100 (`claude_spend_report.day_cap`). Env: CLAUDE_BUDGET_USD_PER_DAY.
    claude_budget_usd_per_day: float = Field(100.0, gt=0)
    #: Lane 6 (owner order 3 Nov 2026): the AI engineering review pass PROPOSES removals, additions, rewordings and a
    #: document-understanding note; code accepts only what it verifies (`ai_review_proposals`). OFF by default.
    #: Env: AI_ENGINEERING_REVIEW_PASS_ENABLED, AI_ENGINEERING_REVIEW_PASS_ENGINE ("ollama" local, or "claude" only when
    #: every document of the review is on the approved list), AI_ENGINEERING_REVIEW_PASS_TIMEOUT_S.
    ai_engineering_review_pass_enabled: bool = False
    ai_engineering_review_pass_engine: str = "ollama"
    ai_engineering_review_pass_timeout_s: float = 300.0

    #: Agent proof test (#1690, part of #805): a lead reviewer agent loop (`agent_loop`) with tools. OFF by default.
    #: Env: AGENT_REVIEW_ENABLED. Claude calls go only through reader_transport and claude_spend.metered.
    agent_review_enabled: bool = False
    #: Owner order 13, 12 Nov 2026 (point 10): the class "AI verdict, two readers agree" for the AI reviewer. After the first reader
    #: answers, a second reader of a different model family answers the SAME question independently (it never sees the first
    #: answer); a line is of the class only when both verdicts agree, code verified both readers' quotes and no guard objects.
    #: Internal copy only; never a Pass or a Fail. OFF (default): no extra call and the stored lines are exactly what they were.
    #: Switch it on only if 0 clear wrong on the answer key and the planted copies (owner). Env: AGENT_REVIEW_TWO_READER_VERDICT_ENABLED.
    agent_review_two_reader_verdict_enabled: bool = False
    #: Owner order 13 (lead, 12 Nov): the word "AI verdict: not stated" of the same class. Needs the switch above on too. A second model
    #: of another family reads EVERY page whole and, without seeing the first answer, finds no value; code's own absence search
    #: (`agent_review_absence.prove`) finds none either and every page is read. Never a Fail, never in the contractor copy. OFF: as the
    #: switch above alone. Env: AGENT_REVIEW_TWO_READER_ABSENCE_ENABLED.
    agent_review_two_reader_absence_enabled: bool = False
    #: Owner order 13 (lead, 12 Nov): the class "Not checked on this paper" (word "Needs a drawing or a calculation"). Needs the first
    #: switch on. A line whose first-reader reason code is `needs_drawing_or_calc` and which a second reader of another family, asked
    #: independently, also finds cannot be checked on this paper, both clause quotes verified, leaves the Queries for the sheet of lines
    #: that are not item rows. Never a decision, never in the contractor copy. OFF: as the first switch alone.
    #: Env: AGENT_REVIEW_TWO_READER_OTHER_PAPER_ENABLED.
    agent_review_two_reader_other_paper_enabled: bool = False
    #: The AI reviewer's OWN engine (owner, 12 Nov 2026: "ONLY the new AI reviewer uses Claude"), named like its siblings
    #: (`match_engine`, `crs_ai_wording_engine`, ...). "ollama" (default): the reviewer's Claude lane is closed. "claude":
    #: the lane opens for the AI reviewer (rule review and general review) under REASONING_PROVIDER=per_task or claude, with
    #: both egress flags and a key; the approved-document list and the USD caps still apply on every call. Under
    #: REASONING_PROVIDER=ollama it changes nothing (the master switch is checked first). Env: AGENT_REVIEW_ENGINE.
    agent_review_engine: str = "ollama"
    #: Owner order 13, C4 (12 Nov 2026): before the AI reviewer closes a line as "the paper does not state this", a second,
    #: different model reads the whole stored text of the page(s) where the field would stand (per silent line at most 1 re-read, 1 lead re-ask, the normal second opinion and the context check of a Fail
    #: line, same spend reservation and caps); a quote that code verifies on that page is decided again by the same gate.
    #: OFF by default; the lead turns it on after a paid trial shows no wrong answer. Env: AGENT_REVIEW_REREAD_SILENT_ENABLED.
    agent_review_reread_silent_enabled: bool = False
