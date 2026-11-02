"""Settings kept out of `config.py` (it may only shrink): a base of `config.Settings`.

Clause review (#1477) and nothing-read (#1495) fields. They are read from the
environment exactly like every other setting (`Settings` inherits them).
"""

from pydantic import BaseModel, Field


class SettingsExt(BaseModel):
    #: #1584 standards compiler (`standards_compiler.py`, `scripts/compile_standards.py`): Claude turns a held
    #: standard into version 2 rules on a database COPY; code verifies every quote; the rules are held until the
    #: owner approves them and change no verdict. OFF: nothing changes. Env: STANDARDS_COMPILER_ENABLED.
    standards_compiler_enabled: bool = False
    #: The model it asks. Env: STANDARDS_COMPILER_MODEL.
    standards_compiler_model: str = "claude-sonnet-5-5"
    #: Standard families it may send. API and ASME by the owner's decision on #1584 (2 Nov 2026), for this compiler
    #: only (the old converter keeps its own list). Setting it can narrow the list. Env: STANDARDS_COMPILER_FAMILIES.
    standards_compiler_families: str = "SAES,ISO,API,ASME"
    #: The default of `--max-usd`: the owner's USD 100 a day, across every standard, read from the spend ledger.
    #: Env: STANDARDS_COMPILER_MAX_USD_PER_DAY.
    standards_compiler_max_usd_per_day: float = Field(100.0, gt=0)
    #: #805 plan change 6, part A: the rulebook's version 2 tables (`rulebook_v2.py`, `scripts/rulebook_v2.py`), on a
    #: database COPY. No verdict reads them; no rule is in force until a person approves it. OFF: nothing is read,
    #: created or written. Env: RULEBOOK_V2_ENABLED.
    rulebook_v2_enabled: bool = False
    #: AI clause review of a PROCEDURE or SPECIFICATION submittal (`clause_review.py`):
    #: one requirement at a time against the 4 most relevant small passages of the
    #: submittal, the LOCAL model only (owner decision D1: no Claude here), every
    #: quote verified by code on the stored page text, never a verdict. OFF: nothing
    #: changes. Env: CLAUSE_REVIEW_ENABLED.
    clause_review_enabled: bool = False
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
    #: reviewed: ..."), never a pass. Still the LOCAL model only; stored answers are
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
    nothing_read_fails_enabled: bool = False
    #: #1479 specification kit (preparation, `spec_kit.py`): a DRAFT must-contain list per
    #: discipline looked up in a specification's own pages, no model; numeric limits
    #: cross-checked with a datasheet of the same number or tag. Engineer rows only.
    #: OFF: nothing changes. Env: SPEC_KIT_ENABLED.
    spec_kit_enabled: bool = False
    #: #1472 (kept here so `config.py` does not grow): the datasheet checks read ONE value where
    #: a sheet prints a range twice (a plain note on one reading), and a combined "a / b / c"
    #: label answers each text attribute it names. OFF: nothing changes.
    #: Env: DATASHEET_ONE_VALUE_ENABLED.
    datasheet_one_value_enabled: bool = False
    #: A datasheet field the sheet gives is not reported missing or conflicting for two general reasons: a split
    #: abbreviation ("tube o d" for O.D.) is joined before the role table is read, and a reading with no unit
    #: beside a reading of the same number with one is one value. Never decides (see `label_match`). OFF: nothing
    #: changes. Env: DATASHEET_LABEL_JOIN_ENABLED.
    datasheet_label_join_enabled: bool = False
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
    transmittal_kit_enabled: bool = False
    #: #1482: comma-separated ids of the held documents that are the required-submissions list;
    #: empty skips that step with one note. Env: TRANSMITTAL_REQUIRED_LIST_DOCUMENT_IDS.
    transmittal_required_list_document_ids: str = ""

    #: #1474: the document KIND (router table `document_kinds`) chooses the rule set: a
    #: document whose kind is anything but datasheet gets no equipment datasheet checklist and
    #: no equipment-type standards, and its equipment type drives no review step (`kind_rules.py`).
    #: unknown / undecided keeps today's behaviour, marked. OFF: nothing changes.
    #: Env: KIND_CHOOSES_RULES_ENABLED.
    kind_chooses_rules_enabled: bool = False
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
    data_page_not_frontmatter_enabled: bool = False
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
    playbook_section_presence_enabled: bool = False
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
    playbook_presence_without_standard_enabled: bool = False
    #: #1522 (b) a review run of a document whose stored kind is `procedure` looks up the playbooks of
    #: that kind whose title cue is in the procedure's cover lines and adds one CRS row per element as an
    #: ENGINEER row (`procedure_playbook_rows`): never compliant, "found, engineer to confirm" with the page
    #: quote, 'unclear'/'missing' say so, a standard not held is never met. None matched: no rows and one
    #: review note. No model. OFF: the CRS is byte-identical. Env: PROCEDURE_PLAYBOOK_ROWS_ENABLED.
    procedure_playbook_rows_enabled: bool = False
    #: #1481 heat exchanger kit PREPARATION (parked, milestone 58): append the DRAFT exchanger cards of
    #: `reference/exchanger_kit_draft.json` (the held standard SAES-E-004 requires the value, not already in the
    #: checklist) to the Heat Exchanger checklist. Draft only, never decides, local only, every row held for the
    #: engineer. OFF: nothing changes. Env: EXCHANGER_KIT_DRAFT_ENABLED.
    exchanger_kit_draft_enabled: bool = False
    #: #1525 per-review audit report: `review_audit.py` writes AUDIT.md + AUDIT.json (pages read, standards,
    #: rules compared, AI use, gates, CRS) for each finished review, from what the run stored. Local files only,
    #: export only, no verdict changes, no model, no socket, no document text beyond page and clause numbers
    #: and stored quote snippets. OFF: nothing is written. Env: REVIEW_AUDIT_REPORT_ENABLED.
    review_audit_report_enabled: bool = False
    #: Folder the audit files go under (`<date>-<run id>/`). Empty = `~/project/mirror/proof`.
    #: Env: REVIEW_AUDIT_DIR.
    review_audit_dir: str = ""
    #: One intake layer (W5b-01, #525, part 1): extraction reads every file through `intake.read` (PDF and
    #: Word as today; Excel one page per visible sheet; an image one page waiting for OCR) and a file it
    #: cannot read is refused with a reason. Local only, no model, no socket. OFF: nothing changes.
    #: Env: ONE_INTAKE_ENABLED.
    one_intake_enabled: bool = False
    #: #525 slice 2 (with ONE_INTAKE_ENABLED on as well): the upload accepts PNG, JPEG and TIFF images
    #: (stored as picture-only PDF pages beside the original, so OCR reads them like a scanned page) and
    #: indexes .xlsx workbooks, each sheet chunked with a sheet + cell-range citation. Local only, no
    #: model, no socket. OFF: images refused and workbooks stored-not-indexed, as today.
    #: Env: INTAKE_IMAGES_XLSX_ENABLED.
    intake_images_xlsx_enabled: bool = False
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
    #: Order 4b: an expired sign-in (a 401) tells the reader so, once, on the sign-in form, and says
    #: unsaved decisions are kept; while signed in the page also asks `/api/auth/me` once a minute,
    #: because reads outside the gated routes answer an empty 200 instead of a 401. Sent to the page on
    #: the signed-in user (`Me.session_expired_notice`). OFF: the form with no reason and no extra
    #: request, as before. Env: SESSION_EXPIRED_NOTICE_ENABLED.
    session_expired_notice_enabled: bool = False
    #: Plan change 6 part B: one meaning of "checked" (`coverage_pair`). The CRS review notes and the
    #: screen's coverage lines print risk and coverage from the one function, in place of the clause
    #: coverage line (stored rows, checklist-covered rules added). The bench and the board call print
    #: the pair always. OFF: every screen and CRS word as before. Env: ONE_CHECKED_DEFINITION_ENABLED.
    one_checked_definition_enabled: bool = False
    #: Order 4c, 2 Nov: the CRS of a procedure or other non-datasheet kind. It never shows or stores an
    #: equipment type (`document_classification` keeps its value: subject gates still read it); a row's page
    #: cell comes from its verified quote; no document id in Item No: the document number or a suggestion
    #: marked as a guess, else NO-NUMBER. OFF: byte-identical, except that rows numbered while it was on
    #: keep printing NO-NUMBER and the reply guard stays for them. Env: PROCEDURE_CRS_FIELDS_ENABLED.
    procedure_crs_fields_enabled: bool = False
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
