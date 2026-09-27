# AI Submittal Review fixes - log (owner order 2026-09-26)

The owner's order "AI Submittal Review - make it produce real comments" lives in
the owner's local `.cowork/` folder (not in git). This log is the repository's
record of what each PR delivered, for the owner to paste into CURRENT_STATE
section 16. No client text, document numbers or standard text here.

Owner priority for the PRs: step 0 (page ledger), 2d, then 1 (wording 2g, pill
contrast, picker/panel), then 2 (CRS Review notes 2f + grouping 2e), then 4
(datasheet self-checks 2c), then the extraction filter audit, 2a+2b, the screen
redesign (section 3), and 2d-2 (web standards).

## Step 0 - page ledger (honesty audit entry 68)

- A page with recorded current facts reads as **read** in the ledger and on the
  screen, whichever reader wrote them.
- A requirement not found on a page read **only** by the geometry/vision reader
  stays **Needs engineer review** ("value not found by the page reader -
  engineer to check the page"). It never becomes the contractor's missing
  information, and it is one summary row on the CRS, not a comment each.
- DB migration: **none** (no new column; the ledger is recomputed).

## 2d - AI engineering check (kind C), behind `REVIEW_AI_CHECK_ENABLED`

- **Off by default.** Even when on, it needs the Claude lane
  (`REASONING_PROVIDER=claude`, both `STANDARDS_READER_*` egress flags and a
  key). Spend is booked to the step `review_ai_check` and checked against the
  USD caps before the call leaves.
- **When it runs:** at the end of a review job, after the comparison has decided
  the suggested code. It can also be re-run on demand with
  `POST /api/reviews/runs/{id}/ai-check`, which answers counts only, never text.
- **What Claude sees:** the datasheet's extracted fields, its page text, the
  names of the cited standards, and for the held standards the clause numbers
  that were read.
- **The gate** (`ai_engineering_check.accept`) refuses an item, with a named
  reason, when:
  - its datasheet value is not on the page it cites;
  - it uses a number that is not on that page;
  - it cites a clause that cannot be verified from a held standard;
  - it quotes a sentence that is not on the page;
  - it uses a pass/fail word;
  - its confidence is above medium.
- **Kept items** are stored as pending, unconfirmed findings with no compliance
  status (`origin = 'ai_engineering_check'`). They never move the review code.
- **On the screen:** "AI engineering check - not from the standard text -
  engineer to confirm".
- **On the CRS** (owner decision 2026-09-27):
  - a new last column, "AI Review Comments", holds each unconfirmed item, with
    COMPANY Comments left empty;
  - confirming the item moves its text to COMPANY Comments, with Comment By
    "AI engineering check, confirmed by <name>";
  - a rejected item is not on the sheet.
- **Export CRS** offers two copies:
  - "internal review copy" (the default): includes the "AI Review Comments"
    column;
  - "issue to contractor": that column and every unconfirmed row are removed.
  - The file name says which copy it is.
- **Not in this PR:**
  - the optional public-web lane for 2d; it comes with 2d-2;
  - CRS re-import (no importer exists yet); confirmation is done on the
    screen.
- DB migration: **none**. The existing `origin` column is reused, and no new
  table or column is added.

## Item 1 - plain wording (2g), readable pills, picker = panel

- **Plain words.** The recommendation's reason is now what an engineer says,
  for example "Checked 177 datasheet fields on 5 of 7 pages. 25 standards the
  datasheet cites are not in your library (the first five named, then "and 20
  more"), so a review code can't be suggested yet."
  - The engine's technical sentence (the nominal field estimate, engine
    identifiers) is kept word for word under **Details** in the code panel.
  - Runs stored before this change get their plain sentence from the same
    stored counts, so existing runs read plainly too.
  - The CRS prints the plain reason. Its "Applicable standards" sheet says
    "Not in your library - upload required" instead of `MISSING_LOCALLY`.
  - Reasons that were already plain are unchanged, including the owner's own
    wording "Manual review: N requirements require other documents".
- **Pills.** Status pills use theme tokens that meet WCAG AA in both themes.
  - The yellow "Needs engineer review" pill measures 7.8:1 on the light theme,
    up from unreadable pale text on white.
  - A test computes the contrast of every pill from `index.css`.
  - Not changed here: the review screen's red and green *alert boxes* still
    use pale text; they are listed as a follow-up.
- **Picker = panel.** Opening a run sets the submittal picker to that run's
  document. Choosing a document in the picker opens its latest run, or closes
  the panel when it has none. The two can no longer show different documents.
- DB migration: **none** (the technical sentence is stored in the existing
  run-outcome JSON).

## Item 2 - CRS "Review notes" sheet (2f) and grouping (2e)

- **The contractor's column holds only comments.** These internal notes are no
  longer printed in COMPANY Comments as "AI Review":
  - requirements that need another document;
  - pages not yet readable;
  - values the page reader did not find;
  - cited standards that are not in the library.

  They are now a **"Review notes"** sheet, in the internal review copy only.
  The copy issued to the contractor has no such sheet. The CRS preview shows
  them in a collapsed "Review notes - internal" table.
- **Grouped, not listed.** Requirements that need another document form one
  note per standard with a count ("12 of this run's requirements from
  <standard> name their own evidence..."), not hundreds of rows.
- **The same rule is one comment.** When two standards carry identical
  requirement text, decided the same way against the same datasheet value and
  page, the CRS prints one row that cites every standard ("The same
  requirement is in: ..."). Rules that are merely similar are not merged.
- **Why the count moved.** Each run now says which standards came into or left
  scope since the previous run of the same submittal, for example "Since the
  previous run: 4 standards removed (...); 1 added (...)". The comparison is
  made from each run's stored applicability decision, under the caller's
  access (a standard they cannot read is not named).
- Kept on the CRS sheet: the one-row "not answered by any field read"
  (missing-information) summary. It is a question for the contractor, not an
  internal note.
- DB migration: **none**.

## Item 4 - datasheet self-checks (2c, kind B)

- **What the engineer gets.** Every review now checks the datasheet against
  ITSELF. This needs no standard, so a run with zero standards held still
  gives "Datasheet check" comments. Each comment cites the datasheet page and
  field and states the calculation, for example "Design pressure 18 barg
  (page 1) is not at least operating pressure 20 barg (page 1)."
- **The rules** are data (`backend/app/reference/datasheet_checks.json`), each
  with an id and plain-English text:
  - consistency: design pressure at least operating pressure (DS-C1); design
    temperature at least operating temperature (DS-C2); test pressure above
    design pressure (DS-C3); rated flow within the minimum and maximum flow
    (DS-C4, DS-C5);
  - mandatory fields per equipment type (vessel, centrifugal pump, pump):
    present (DS-M1), and not "TBA", "TBD", "later" or "by vendor" (DS-M2);
  - units: present (DS-U1), and of the field's kind (DS-U2);
  - a revision block (DS-R1).
- **Never guessed.**
  - Values are compared only on one scale: gauge against absolute, or units
    that do not normalise to one, are skipped.
  - When two different values sit under one field name, the check is skipped
    rather than picking one.
  - An absent mandatory field is qualified like every absence: while a page is
    unread, or read only by the page reader, it is an engineer's question and
    not the contractor's omission.
- **Where they go.**
  - Failures are findings of the run (`origin = 'datasheet_check'`) and count
    in the suggested code, by code only.
  - Passes add no row.
  - On the CRS each is its own "Datasheet check:" comment, including missing
    values, and they are not counted in the missing-information summary.
  - The findings table labels them "Datasheet check".
- **Not in this PR:** document number and revision consistency across pages.
  It needs per-page title-block reading, which comes with the extraction work.
- DB migration: **none**.

## Extraction filter audit (part 2)

See `docs/extraction-filter-audit.md` for the per-rule report.
- A label / unit / value row now reads as "value unit".
- Material, code and rating designations count as answers.
- The revision-block, title-block, heading and furniture guards are kept.
- Honesty audit entry 69.
- DB migration: **none**.

## 2a + 2b - table and formula rules in code, judged on the output field

- **What the engineer gets.** A range-table rule is now calculated instead of
  being sent to an engineer. Example: design pressure from the maximum
  operating pressure, "the greater of 1.1 x MOP and MOP + 170". The finding
  shows the calculation, for example "required design pressure at least
  3,300 kPa from operating pressure 3,000 kPa (table row: over 1,800 up to
  6,900 kPa); the datasheet says 3,200 kPa", and meets or does not meet.
- **The right field (2b).** The verdict judges the OUTPUT field (design
  pressure) and names the INPUT used (operating pressure).
  - Output absent: "design pressure not stated on the datasheet" (missing
    information).
  - Input absent: the required value cannot be calculated, so an engineer
    decides.
  - The input is never compared against the rule.
- **Pure arithmetic** (`backend/app/rule_eval.py`):
  - rows use max or min of linear terms over input ranges;
  - units convert through the unit table;
  - gauge against absolute is never compared;
  - a table that states no basis is read on the datasheet's gauge basis, and
    the rationale says so;
  - an input outside every row goes to an engineer;
  - an unparseable table gives no rule. The requirement stays with an engineer
    and says "the table on page N could not be read". For a garbled table, the
    page's ruled table is re-read by the table reader first.
- **Model-assisted parsing is optional**, behind `RULE_PARSE_MODEL_ENABLED`
  (default off; it also needs the Claude lane and stays within the USD caps).
  A model's parse is kept only when every number in it appears verbatim on the
  clause's page. The arithmetic is always Python.
- **Stored once, auditable:** `standard_requirements.rule_json` and
  `rule_source` (`code` or `model_parsed_verified`).
- Supported now: design pressure from operating pressure, and design
  temperature from operating temperature. Other rule families stay with an
  engineer until they are added to `rule_eval.KNOWN_RULES`.
- DB migration: **YES**. Two additive nullable columns on
  `standard_requirements`, added automatically at start-up. Back up the laptop
  DB before updating.

## Screen redesign PR A - readiness strip, summary, notes, grouped runs, Edit/Reject

See the PR description for the full list. In short: `GET /api/reviews/readiness/{id}`
(pages read, standards held/missing, "nothing changed since the last run"),
the four-total summary with kind A/B/C counts, on-screen Review notes, runs
grouped per document, and an Edit/Reject action on individual comments.
Also fixed a pre-existing mutation-id collision on `main` between
`chat_claude_first.py` and `rule_eval.py`.
- DB migration: **none** (`completed_at` and `engineer_comment` are additive
  nullable columns, added automatically at start-up).

## Screen redesign PR B - "Read unread pages" + comments grouped by topic

- **"Read unread pages"** (`POST /api/reviews/readiness/{submittal_document_id}
  /reread-pages`): re-runs `datasheets.extract_facts(replace=True)` on this ONE
  submittal, so a page the ledger says is unread gets another try (rule and
  geometry readers first; vision only where B7 says they still fail), then
  answers the same readiness numbers as the GET route (shared helper, so the
  two routes cannot drift into two answers to one question - CLAUDE.md rule 8).
- **Nothing is deleted.** `extract_facts(replace=True)` supersedes a stale
  fact rather than removing it (#179); this route writes no review finding
  and no compliance verdict - it reads fields, it does not compare them.
- **On the screen:** the readiness strip's "Read unread pages" button is
  shown only while pages are unread, and reports the API's own error rather
  than failing silently.
- **Comments grouped by topic.** The findings table is now split by the
  field a comment is about (the matched datasheet field name, or the
  equipment tag when there is none, or "Other") - ten findings on one field
  read as one group of ten, not ten unrelated rows. Unchanged when there is
  only one topic.
- **Testing.** Owner decision 2026-09-27 (minimum testing mode): no local
  test-suite run, no mutation run. A few tests only, for the new behaviour
  and the safety rules - permissions (a caller without access gets 404 from
  the re-read route, same as every review route), no data loss (a run's
  findings are unchanged by a re-read of the submittal they were about), and
  AI never sets pass/fail (re-reading writes no new finding and no
  compliance status). CI is the gate for this PR.
- DB migration: **none**.

## 2d-2 - public web standards check (kind D), behind `REVIEW_WEB_STANDARDS_ENABLED`

- **Off by default.** Even on, nothing is sent unless the market lane's own
  two egress flags are also on and a search tier is configured - the SAME
  lane the chat web question and the market page already use, with the same
  host allowlist, rate limit and audit. No new socket is opened; a small
  `market_transport.fetch_text` (raw page text, for quote verification) was
  added to the market lane's own existing gated transport, not a new one.
- **Never a company standard.** `web_standards.is_public_identifier` is an
  ALLOW-list (a known public standards body's own numbering) with a second,
  independent block-list (SAES/SAMSS/KOC-*) - an identifier that matches
  neither, or matches the allow-list but also carries a company marker, is
  never searched, never fetched, never logged with its own text. It reads
  "Company standard - upload required", same as any other missing reference.
- **Never an unverified quote.** A candidate is kept only when its quote can
  be found, word for word, on the page this module itself fetched - a
  search snippet alone is never enough.
- **Never a guessed verdict.** The quote is run through `rule_eval` only
  when the caller names which datasheet field it concerns; the generic
  missing-standard lookup this PR wires in never guesses one, so its items
  are always "engineer to confirm", never a pass/fail invented from prose.
- **Never compared across editions.** A cited edition that does not match
  the web page's own date is "edition differs" and is never compared.
- **Never counted.** Stored as a pending, unconfirmed draft
  (`origin = 'web_standard_check'`, kind D) exactly like the AI engineering
  check (kind C) - never seen by `comparison.recommend_code`, shown on the
  CRS only after an engineer confirms it (same "AI Review Comments" column
  and confirm-moves-it-to-COMPANY-Comments rule, now shared by kind C and D).
- **On demand or automatic.** `POST /api/reviews/runs/{id}/web-check` runs it
  again; it also runs once at the end of a review job, after the AI
  engineering check, only with its flag on.
- **The Anthropic server-side web search tool** is checked for and, being
  genuinely unwired in this build, always falls back to the market lane
  honestly rather than claiming a capability that does not exist.
- **Testing.** Owner decision 2026-09-27 (minimum testing mode) continued:
  a few tests plus mutations for the new module specifically (privacy-
  critical), since this is a new outbound lane - `backend/tests/
  test_web_standards.py` (20 tests) and `scripts/mutations/web_standards.py`
  (M1112-M1117, all detected). No full suite run; CI is the gate.
- DB migration: **none** (the existing `origin` column is reused).
