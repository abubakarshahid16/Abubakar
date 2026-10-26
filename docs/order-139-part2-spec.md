# Order 139 part 2 - one comment per field, no empty comments, a real order

Architect's spec for the agent team (owner order 139 part 2, "fix all in
priority", items 4 and 5). Binding: CLAUDE.md rules 1, 4, 6, 8, 12, 13.
Branch `s1/139-crs-one-per-field`. The contract stubs named here are already
committed with this file; builders fill them in.

## 0. The problem, measured (M-03 run, diagnostic copy, counts only)

| What | Before |
|---|---|
| Internal CRS rows | 329 (missing_information 112, needs_engineer_review 200, ai_engineering_check 12, standard_not_cited 3, standard_not_applicable 2) |
| Rows for ONE missing field | up to 29 (then 15, 13, 12, 9, 9 ...); 112 missing rows cover 20 fields |
| Rows for ONE engineer-to-check field | up to 19 (then 7, 5); 158 questions have no field label |
| Severity | "minor" on 324, none on 5 - says nothing |
| Empty COMPANY Comments | 12, all unconfirmed `ai_engineering_check` |
| Issue copy | 0 rows (nothing confirmed yet) |

Cause: `crs_mapping._group_key` is one row per (status, requirement wording,
field). One blank field cited by 29 clauses is 29 rows. The screen groups
with a different rule (`sheetCards.buildCards`: origin, status, reason code,
comment template), so the screen and the file disagree about what one
comment is.

## a. Grouping key (decided)

A finding first takes a **bucket** (`crs_mapping.crs_bucket`), exactly the
branches `build_crs_rows` has today:

| Bucket | Findings | Grouped |
|---|---|---|
| `breach` | NON_COMPLIANT against a standard | today's key: one row per problem |
| `blank` | MISSING_INFORMATION paired with a field (`fact_id` or `contractor_page`) | **one row per datasheet field** |
| `not_found` | MISSING_INFORMATION with no field paired | **one row per datasheet field** |
| `question` | NEEDS_ENGINEER_REVIEW, not UNREAD_PAGES / PAGE_READER_ONLY | **one row per datasheet field** |
| `check` | datasheet self-check (kind B), not covered by a breach/blank row | today's key |
| `tick` | safety-tier COMPLIANT shown for a tick | one row per finding |
| `chat`, `ai`, `web` | engineer chat comment, AI check, web check | one row per finding |
| none | rejected, page notes, NOT_IN_DOCUMENT_SCOPE, NOT_APPLICABLE, plain COMPLIANT | not a row |

Rules:

1. **Field-grouped buckets** (`FIELD_GROUPED_BUCKETS`): the base key is
   `"field:" + field_comment_key(bucket, label)`, where `label` is
   `_fold(_field_label(f))` - the field exactly as the row prints it (the
   datasheet's printed label, else the matched phrase, else for a not-found
   value the clause's clean subject). The bucket is IN the key.
2. **Blank and not-found stay separate rows** even for the same field: their
   actions differ ("Contractor to complete the field 'X' (left blank)." vs "Clarification requested: please
   indicate where the datasheet states X, or confirm it is not stated.").
   Merging them would either ask the contractor for something the system
   only failed to find (honesty audit 50, #725 F7) or hide a real blank.
3. **No field label -> today's key** (`"req:"` + digest of today's
   `_group_key` parts, bucket included). The 158 label-less questions are
   NOT merged into one giant row.
4. **Breaches stay one row per problem.** Each NON_COMPLIANT names its own
   limit, its own value and its own deviation request; one row per clause is
   what the contractor answers. They are few (0 on the M-03 run).
5. **Engineer wording.** The screen now edits a whole row, and writes the
   same `engineer_comment` on every finding of it. So within one base group,
   findings split by folded `engineer_comment` (none = "") ONLY when the
   group holds two or more distinct values; each part then gets the suffix
   `":e" + comment_key("edit", folded text)[:12]`. A group whose findings all
   carry the same wording (or none) keeps its base key. This replaces
   today's "every edited finding is its own row" (which would re-split a
   29-finding row into 29 rows the moment an engineer edits it) and keeps
   its point: an engineer's wording is never merged with DIFFERENT words.
   A finding with no requirement text stays `"one:<id>"` (today's rule).
6. **The leader** (row text, byline, `finding_id`) is the same on every run:
   `_leader_order` gains tie-breakers after today's (confirmed first, page,
   tag, value): `_clause_key(standard_clause)`, folded
   `requirement_source_text`, then `id`.
7. `crs_groups(findings)` is THE grouping: list-level (filters rejected,
   applies the covered-check rule, splits by wording), returns the groups in
   sheet order (section f). `build_crs_rows` builds every finding row from
   it - no second grouping anywhere in the backend.

## b. One source for screen and file (decided)

The server computes; the screen never groups CRS findings by a rule of its own.

- `GET /api/reviews/runs/{id}/summary` (`backend/app/api/run_summary.py`,
  read by `useWorkspaceRun`, `CrsSheetView`, `compareRuns.loadCommentLines`)
  sends per finding row (`TierRow`, stubbed): `crs_group`, `crs_priority`,
  `crs_priority_label`, `crs_order`, `crs_action`; and on the summary
  `crs_grouping: true`. Computed in the `/summary` handler only (after
  `comparison.attach_crs_context` on the same findings `_crs_content` reads),
  never in `_tiers` - `/counts` (up to 200 runs) must not pay for it.
- The screen (`crs/crsRows.ts buildCrsRows`) groups every finding that has a
  `crs_group` by it (row key `crs:<crs_group>`), and orders comment rows by
  `crs_order`. `sheetCards.buildCards` is no longer used by `buildCrsRows`
  for grouping (it stays for the old card view, `views/ReviewSheetView.tsx`,
  which App does not route; do not change it).
- A finding with no `crs_group` on a summary with `crs_grouping: true` (a met
  value, not applicable, CONDITIONAL, a note, or a finding newer than the
  summary) is one row of its own (`one:<id>`, today's shape), after the
  grouped comment rows.
- **No server grouping** (`crs_grouping` false or absent - an older server -
  or the summary read failed): every finding is one row of its own
  (`one:<id>`) and the sheet says, once, in plain words:
  `"Shown one row per finding: the sheet's grouping could not be read from the server."`
  (constant `UNGROUPED_NOTE` in crsRows.ts). Never the old screen grouping -
  that would be a guess dressed as the file's grouping.
- On a refresh whose summary read fails after one succeeded for the same run,
  `useWorkspaceRun` keeps the last good summary (rows must not flip between
  grouped and ungrouped keys under the engineer's open decisions). Drafts
  stored under an old row key (the pre-139 card keys) are handled by the
  existing orphan-decision path (v2.1 round 2 F2); nothing new.
- **Parity proof**: `contracts/fixtures/crs_group_cases.json` (stubbed, 8
  invented cases). Backend `crs_groups` must produce `expected_rows`; the
  screen, given the same rows as summary fields, must show exactly that
  partition and order. Plus a server-side test that the summary's
  `crs_group` partition of a seeded run equals the internal CRS rows'
  `finding_ids` (the same function feeds both, proven end to end).

## c. The comment text of a grouped row (decided)

A row whose findings cite ONE distinct clause keeps today's text
(`engineer_comment_text`) byte for byte. A field-grouped row citing TWO or
more distinct clauses (distinct `(standard_document_id, standard_clause)`)
prints, lines joined with `"\n"` (Excel: one cell, wrapped; row height
already counts newlines):

```
<action line>
<said line>
Supporting clauses (<n>):
- <ref>: <words>
... at most MAX_CLAUSE_LINES = 10 lines ...
- and <k> more of these <n> (see Standard Reference).
```

- `<action line>`: `blank` -> `Contractor to complete the field '<Field>' (left blank).` (`Contractor to provide <Field>.` when the sheet gave a value, or when a tag of the row did);
  `not_found` -> `Clarification requested: please indicate where the datasheet states <Field>, or confirm it is not stated.`;
  `question` -> `Clarification requested on <Field>.` (`<Field>` = `_field_label`).
  This line is also `crs_groups()[i]["action"]` and the summary's
  `crs_action`.
- `<said line>`: the sentence `engineer_comment_text` already builds for the
  group (`Datasheet p.2, Corrosion allowance (P-101) is left blank.`, the
  per-tag variant, or `Not answered by any field read from the datasheet (...).`).
- One line per distinct `(standard_document_id, standard_clause)`, ordered by
  `_clause_key`, then reference text. `<ref>` = `_standard_reference(g)`.
  `<words>` = for blank/not_found `_requirement_words(g)` with the clause cut
  to `CLAUSE_LINE_CHARS = 160` (add a `limit` parameter); for question
  `_reason_words(g)` cut to 160 + "." . When one clause holds several
  requirements, the first one's words, then ` (+<m> more requirements of this clause)`.
- `<n>` = number of distinct clauses (the boundary); the last line appears
  only when `n > 10`, with `k = n - 10`. `Standard Reference` still lists
  every reference, `"; "`-joined.
- Engineer-worded rows print the engineer's words (today's rule); the
  machine text stays in `ai_comment` and the internal "AI wording" cell.
- Screen: the Required action cell shows the engineer's words if edited,
  else `crs_action` when sent, else the leader's `required_action` (today).
  Under it, "Supporting clauses (n)" and the first 10 clauses in the screen's
  own clause format (`clauseAndStandardOf`), then "and k more of these n" -
  the same cap and wording. n counts named clause groups (`clauseGroups`,
  excluding the no-clause group); the fixture pins it (`clause_count`).

## d. Permanent numbers and decisions when rows merge (decided)

- **Key of a field-grouped row**: `comment_key = field_comment_key(bucket,
  label)` = `comment_key("field group", bucket, label)`. Not the leader's
  `_subject_key`: the leader is whichever clause sorts first, so a re-run
  adding or dropping a clause would move the number; and the stored AI
  wording (`crs_wording`, keyed by row key) of one per-clause comment must
  never be printed beside a 29-clause row. Edit-split parts share the key;
  `crs_numbers.row_keys` already gives the second one `#2`, the confirmed
  part first. Every other row keeps today's key.
- Every finding row carries `member_keys`: sorted unique
  `finding_member_key(g)` (= today's `_subject_key`) of its findings. Never
  printed. `finding_comment_key(f)` returns the ROW key the finding lands on
  (the field key for field-grouped findings) - one home, used by rejections.
  `rejected_comment_keys` returns row keys AND member keys of rejected findings.
- **Old numbers** (`main._crs_content`, Builder B):
  1. present keys for `crs_numbers.open_elsewhere` = row keys UNION every
     row's `member_keys`. An Open, issued per-clause comment whose clause now
     sits inside a grouped row is NOT carried forward as a duplicate row.
  2. `lookup(member_keys)`: every ISSUED (issued = 1) and not WITHDRAWN
     member number is listed on the grouped row: `row["replaces_refs"]` and a
     last comment line, both copies:
     `Replaces earlier comments CRS-X-004, CRS-X-007 (now one comment per field).`
     The number an engineer confirmed is never silently dropped; it stays
     Open in its table, its replies stay with it, and the reviewer closes it
     as today. If its clause stops being raised, today's carry-forward prints it.
  3. Machine-draft member numbers (issued = 0) are not printed again and
     never reused (the table never frees a number). Not an engineer's - no
     confirmation is lost.
  4. **Decided only when all its findings are (#986)**: a grouped row is
     `engineer_confirmed` when crs_mapping's all-findings-confirmed says so,
     OR its own key holds an issued number (today), OR EVERY member key holds
     an issued, not withdrawn number (each clause was confirmed before). Some
     but not all -> still open; the "Replaces" line shows what was confirmed.
  5. Withdrawal: `_mint_crs_numbers` withdraws
     `rejected keys - row keys - present member keys`.
  6. Existing finished reviews: their grouped rows have new keys with no
     number until the next write on the run (a decision) or a re-run
     (`number_crs_rows`); until then they print as unnumbered rows (`Ref:
     RF-...`), today's shape for an unnumbered row. Stated, not hidden
     (owner question Q1).
- `crs_issue.group_of` / `apply_row_decisions` / the decide route: no change
  (a row's `finding_ids` are now the field group's).

## e. No empty COMPANY Comments (decided)

- Unconfirmed AI item: COMPANY Comments = `AI_UNCONFIRMED_COMMENT`
  ("AI suggestion awaiting an engineer's decision - its words are in AI
  Review Comments. Not issued to the contractor until an engineer confirms
  it."); web item: `WEB_UNCONFIRMED_COMMENT`. The draft stays ONLY in
  `ai_review_comment` (owner order 2d/2f kept: COMPANY Comments never holds
  the draft). New line in `build_crs_rows`:
  `"comment": text if confirmed else unconfirmed_comment,` (M1032 is
  re-anchored to it by the integrator).
- `build_crs_view` (Builder B), the hard guard, on the caller's comment text
  BEFORE the `Ref:` prefix:
  - internal copy: an empty comment prints `EMPTY_COMMENT_TEXT` = "No comment
    text was produced for this row. An engineer must write it before this
    row can be issued." and the row gets `comment_missing: True` (1b: a
    NUMBERED row prints `EMPTY_ISSUED_COMMENT_TEXT` instead - which comment,
    and what to do);
  - issue copy: such a row is never printed; the view carries
    `rows_withheld_no_text: <n>` (0 when none), never silent.
- Issue gate (`crs_issue.open_items`, Builder B): a row that would go on the
  issue copy (engineer_confirmed, not rejected, not a safety tick)
  with empty comment text is a blocker:
  `crs_issue.no_text_blocker(refs)` (1b: it names the comment number(s); a
  confirmed row that still holds a draft counts too, since its number may be
  issued; a waiting sentence is never text). So the export's
  drop above is a last guard, never the normal path.

## f. Priority and order (decided)

`priority` (int) on every row, from `row_priority(bucket or row kind, status)`
(a blank and a not-found share `row_kind` missing_information but not a
rank, so the rank is read from the bucket); `severity` stays on the row dict and the
preview JSON (back-compat) but is no longer printed.

| Rank | Word (internal / screen) | Issue copy word | Rows |
|---|---|---|---|
| 1 | Out of limit | Out of limit | breach; datasheet check NON_COMPLIANT |
| 2 | Missing value | Missing value | blank; datasheet check MISSING_INFORMATION; standard_not_cited |
| 3 | Engineer to check | Clarification | question; not_found; held datasheet check; AI and web items (any state); standard_not_applicable; safety tick |
| 4 | Engineer's comment | Engineer's comment | chat (the engineer's own; its importance is not known to the system) |
| 5 | Carried forward | Carried forward | carried-forward rows (`main`; their snapshot holds no kind to rank by) |

- Sort key of a finding row: `(priority, min datasheet page or 10**9,
  _clause_key(leader clause), folded field label, group key)` - total, so the
  order of two groups never depends on the rest of the list. Standards rows
  sort inside their rank with no page: `(priority, 10**9, (10**6,),
  folded identifier, comment_key)`. Carried forward: appended last by main
  (rank 5), in number order (today).
- Printed: the Severity column (#725 F7, ours, not one of the client's
  seven) becomes **"Priority"** (`crs_export.PRIORITY_COLUMN`, column I, both
  copies), printing `crs_mapping.priority_word(priority, copy)`; a row with
  no rank prints "". No new column: the client's seven do not move, and a
  rank column already existed in effect - it only said "minor".
- Same order on screen: comment rows by `crs_order` (server), then rows
  without a server group by page; `commentNo` 1..N in that order; Met rows
  last (today). The rank word is shown on each screen row as a short label
  (no new column; `CRS_COLUMNS` unchanged).
- Rule 4: never "high"/"low"/"critical" as a rank word; a rank is not a confidence.

## Must-keep fences

- `frontend/src/views/oldIssueGateFenced.test.ts`
- `frontend/src/components/review/workspace/numbers.agree.test.tsx`
- `frontend/src/components/review/crs/*.test.ts(x)` (crsRows, tiers.parity,
  CrsTable, issueGate, saveCrsDecisions, useCrsDecisions, issueContractorCopy)
- `frontend/src/components/review/workspace/compare/compareRuns.test.ts`,
  `workspace/WorkspaceSheet.test.tsx`, `workspace/contract.test.ts`
- `backend/tests/test_crs_mapping.py`, `test_crs_export.py`,
  `test_crs_endpoint.py`, `test_crs_permanent_numbers.py`,
  `test_779_crs_numbers_at_review_end.py`, `test_885_crs_issue_gate.py`,
  `test_986_crs_decide_every_row.py`, `test_review_ai_check.py` (M1032 "never
  in COMPANY Comments"), `test_crs_planted_defects.py` (every planted breach
  still its own row), `test_133_one_truth_tiers.py`, `test_95_run_summary.py`,
  `test_119_generated_contract_types.py`, `test_763_crs_ai_wording.py`,
  `test_95_ai_wording.py`
- `python scripts/gen_contract_types.py --check`;
  `python scripts/check_mutation_anchors.py`;
  `python scripts/mutation_check.py --changed`
- `crs_mapping._field_label` keeps its name and meaning
  (`.context/139/scripts/crs_measure.py` reads it).
- Expected-value changes in existing tests are allowed only where this order
  changes the sheet (grouping, order, "Severity" -> "Priority", AI
  placeholder); each such edit says `# order 139 part 2` beside it.

## File ownership (3 builders, no shared file)

| Builder | Owns (may edit) | Must not edit |
|---|---|---|
| **A - backend grouping** | `backend/app/crs_mapping.py`; `contracts/fixtures/crs_group_cases.json`; new `backend/tests/test_139_crs_one_per_field.py`, `backend/tests/test_139_crs_group_cases.py`; new `scripts/mutations/pr139_crs_mapping.py`; existing tests `test_crs_mapping.py`, `test_crs_planted_defects.py`, `test_b3_crs_unread_pages.py`, `test_754_required_vs_cited.py`, `test_r30_crs_reasoning.py`, `test_986_crs_decide_every_row.py`, `test_crs_review_notes.py`, `test_921c_reason_code_is_typed.py`, `test_805_checklist_meets.py`, `test_partial_standards.py`, `test_review_conditions.py`, `test_chat_pr5_actions.py`, `test_747_crs_to_answer_key.py` | everything else |
| **B - file, numbers, gate, route** | `backend/app/crs_export.py`, `crs_issue.py`, `crs_numbers.py` (only if needed), `main.py` (CRS section only: `number_crs_rows`, `_mint_crs_numbers`, `_prior_rejections`, `_crs_content`), `backend/app/api/run_summary.py`, `backend/app/schemas.py` (CrsPreviewRow, CrsPreview), `scripts/gen_contract_types.py`, `contracts/generated/*.ts` (regenerated only); new `backend/tests/test_139_crs_file_and_numbers.py`, `backend/tests/test_139_run_summary_groups.py`; new `scripts/mutations/pr139_crs_export.py`; existing tests `test_crs_export.py`, `test_crs_endpoint.py`, `test_crs_permanent_numbers.py`, `test_779_crs_numbers_at_review_end.py`, `test_885_crs_issue_gate.py`, `test_1066_issue_gate_reads_only_rejected.py`, `test_95_run_summary.py`, `test_133_one_truth_tiers.py`, `test_review_ai_check.py`, `test_f7_735_clean_crs.py`, `test_f7b_735_crs_transmittals.py`, `test_95_ai_wording.py`, `test_763_crs_ai_wording.py`, `test_audit_crs_fixes.py`, `test_b10_engineer_decisions.py`, `test_633_honest_exports.py`, `test_w3_633_absence_rest.py`, `test_b5_live.py`, `test_791_trace_store.py`, `test_884_coverage_shown.py`, `test_w1_crs_draft_and_upload_discipline.py`, `test_crs_submittal_delete_orphan_guard.py`, `test_119_generated_contract_types.py` | crs_mapping.py (request changes from A in your report) |
| **C - screen** | `frontend/src/components/review/crs/crsRows.ts` (+ `crsRows.test.ts`), new `crs/crsGroups.parity.test.ts`, `crs/CrsRow.tsx`, `crs/CrsTable.tsx` (+ tests), `components/review/CrsPreviewSheet.tsx` (+ its tests), `panels/BehindTheScenes.crs.test.tsx`, `workspace/useWorkspaceRun.ts` (+ test), `workspace/WorkspaceSheet.tsx` (+ test), `workspace/plainWords.ts` (if needed), `workspace/compare/compareRuns.ts` (the one `buildCrsRows` call; open PR #1174 touches compare - rebase, keep its change), `views/CrsSheetView.tsx` (the one call), `contracts/types.ts` | backend; `sheet/sheetCards.ts` (read only; not the screen's grouping any more); `views/ReviewSheetView.tsx` |

Rules: a builder whose change breaks a test outside its list does NOT edit
it - it lists the test, the failing assertion and the new expected value in
its report, and the integrator fixes it at merge. **No builder edits an
existing `scripts/mutations/*.py`**: each reports the anchors it broke
(`python scripts/check_mutation_anchors.py`), and the integrator re-anchors
(known: M1032 in `review_ai_check.py`; M987-01 if the `finding_ids` line
moves; M379 if the bucket tuple changes). The audit entry (rule 7) and
`docs/` edits are the integrator's.

Builder A starts from the stubs in crs_mapping.py; Builder B codes against
their names and shapes (monkeypatch `crs_groups` in its unit tests until A
lands); Builder C codes against the generated `RunSummaryTierRow` fields and
`ReviewRunTierSummary.crs_grouping`, and the fixture.

## Mutation entries (danger zone only: crs_mapping, crs_export, crs_numbers)

Placeholders: `M139-NN`, `phase=139`. **The integrator renames them to
`M<PR>-NN` / `phase=<PR>` once the PR exists** (rule 12), and renames the
files `scripts/mutations/pr<PR>_crs_one_per_field.py` (A's and B's entries
merged into it, or kept as `pr<PR>_crs_mapping.py` / `pr<PR>_crs_export.py`).
Registry layout: one module per file in `scripts/mutations/`, each defining
`MUTATIONS: tuple[Mutation, ...]` (`from ._base import APP, Mutation`;
precedent `pr987_decide_every_row.py`); the anchor must match exactly once;
`target` is the test file, `keyword` the test name; tags
`("honesty", "critical")`. Builder A uses 01-19, Builder B 21-39. Frontend
and main.py / crs_issue.py / run_summary.py are outside the danger zone:
ordinary tests, no entries (rule 6).

| Id | Module | Mutation | Killed by (file :: test) |
|---|---|---|---|
| M139-01 | crs_mapping | field branch of `crs_group_key` returns today's key | test_139_crs_one_per_field :: test_one_row_per_datasheet_field |
| M139-02 | crs_mapping | bucket left out of the field key (blank + not-found merge) | :: test_blank_and_not_found_stay_separate_rows |
| M139-03 | crs_mapping | an empty label is grouped as a field | :: test_rows_without_a_field_label_keep_one_per_requirement |
| M139-04 | crs_mapping | `BUCKET_BREACH` added to `FIELD_GROUPED_BUCKETS` | :: test_breaches_stay_one_row_per_problem |
| M139-05 | crs_mapping | the supporting-clause lines are not printed | :: test_grouped_comment_lists_supporting_clauses |
| M139-06 | crs_mapping | the cap or the "and k more of these n" line dropped | :: test_long_clause_list_says_how_many_more |
| M139-07 | crs_mapping | priority left out of the sort key (bucket order again) | :: test_rows_rank_out_of_limit_then_missing_then_engineer_to_check |
| M139-08 | crs_mapping | page left out of the sort key | :: test_within_a_rank_rows_go_by_page_then_clause |
| M139-09 | crs_mapping | unconfirmed AI/web comment back to "" | :: test_every_internal_row_has_company_comment_text |
| M139-10 | crs_mapping | field row keyed on the leader's `_subject_key` | :: test_field_row_number_key_survives_a_new_clause |
| M139-11 | crs_mapping | the wording split removed (different wordings merge) | :: test_different_engineer_wordings_split_same_wording_stays_one |
| M139-12 | crs_mapping | `member_keys` holds only the leader's key | :: test_a_field_row_carries_every_member_key |
| M139-13 | crs_mapping | not_found ranked 2 (asks the contractor) | :: test_not_found_ranks_with_engineer_to_check |
| M139-21 | crs_export | Priority column prints `severity` | test_139_crs_file_and_numbers :: test_priority_column_prints_the_rank_word |
| M139-22 | crs_export | issue copy prints the internal word for rank 3 | :: test_issue_copy_says_clarification_for_rank_three |
| M139-23 | crs_export | a row with no rank prints a guessed word | :: test_row_without_priority_prints_nothing |
| M139-24 | crs_export | the issue copy's empty-comment guard removed | :: test_issue_copy_never_carries_a_row_with_no_text |
| M139-25 | crs_export | the internal empty-comment text removed | :: test_internal_copy_names_a_row_with_no_text |
| M139-26 | crs_export | the view re-sorts rows (order not the caller's) | :: test_file_keeps_the_sheets_order |

## Test plan (beyond the mutation table; each must fail without its change)

Builder A (`backend/tests/test_139_crs_one_per_field.py`, invented data):
the tests in the table, plus `test_single_clause_row_text_is_unchanged`,
`test_grouped_row_names_every_finding` (finding_ids = all; #986),
`test_leader_is_the_same_whatever_the_input_order`,
`test_rejected_comment_keys_include_member_keys`,
`test_finding_comment_key_is_the_rows_key`. `test_139_crs_group_cases.py`
runs every fixture case through `crs_groups` AND `build_crs_rows` (rows'
`finding_ids` partition = groups' partition, same order).

Builder B: `test_139_crs_file_and_numbers.py` - the table's tests, plus
(`main._crs_content`, seeded DB) `test_an_issued_per_clause_number_is_not_carried_forward_twice`,
`test_grouped_row_lists_the_earlier_comments_it_replaces`,
`test_grouped_row_is_confirmed_only_when_every_member_was`,
`test_carried_forward_rows_rank_last`,
`test_rejected_field_row_number_is_withdrawn`,
`test_gate_blocks_a_confirmed_row_with_no_text` (crs_issue).
`test_139_run_summary_groups.py`: `test_summary_sends_group_rank_order_action`,
`test_summary_groups_equal_the_files_rows` (seeded run: partition of finding
ids by `crs_group` == internal CRS rows' `finding_ids`; `crs_order` order ==
row order), `test_counts_route_sends_no_groups`,
`test_priority_labels_match_crs_mapping_words` (the Literal == PRIORITY_WORDS 1-4).

Builder C: `crs/crsGroups.parity.test.ts` (every fixture case);
`crsRows.test.ts`: `groups by the server's crs_group, never its own`,
`orders comments by crs_order, then ungrouped by page`, `without server
grouping shows one row per finding and the note`, `a finding with no
crs_group is its own row`, `required action is the engineer's words, else
crs_action, else the finding's`, `the clause list caps at 10 and says how
many more of n`; `useWorkspaceRun.test.tsx`: `a failed summary refresh keeps
the last grouping`; CrsPreviewSheet: `prints the Priority column from
priority_label`. Must keep `numbers.agree.test.tsx` and
`oldIssueGateFenced.test.ts` green without edits.

## Before / after measurement (integrator)

On the diagnostic copy of the live DB (read only; never the live file):

```
backend/.venv/bin/python .context/139/scripts/crs_measure.py . --make-copy <live sqlite> before   # once, already done
backend/.venv/bin/python .context/139/scripts/crs_measure.py . <copy.sqlite> after
```

Counts only to stdout; field labels stay in `.context/139/` (never GitHub).
Pass when, on the after run: `internal.empty_company_comment == 0` and
`internal_file_empty_company_comment == 0`; no `(missing_information,
field)` has more than 2 rows (a blank row and a not-found row) and no
`(needs_engineer_review, field)` with a label more than 1 (no edits on the
copy); `by_priority` has no `(none)`; internal rows' priorities are
non-decreasing (add `order_ok` to the script locally); the 158 label-less
questions stay 158 rows (stated, not hidden: Q2); issue copy still 0 rows.
Report before -> after in the PR as counts only.

## Owner questions (not decided here)

- **Q1.** Existing finished reviews: grouped rows are unnumbered until the
  next decision or a re-run. Re-number them once with a script (a write,
  through `live_guard.prepare_live_write`), or leave it?
- **Q2.** The 158 questions with no field label stay one row per
  requirement. A later order could group them by standard and reason code.
- **Q3.** Chat comments rank 4 and carried-forward rank 5 because the system
  does not know their importance; does the owner want them elsewhere?
- **Q4.** The issue copy prints the rank word ("Out of limit", "Missing
  value", "Clarification") in the Priority column; the client has not seen
  that column renamed from "Severity".
