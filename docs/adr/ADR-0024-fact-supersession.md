# ADR-0024 — Re-extracted datasheet facts are superseded, never deleted

- **Status:** Accepted (owner authorisation, 2026-09-25: live re-extraction
  "preserving the historical findings")
- **Date:** 2026-09-24
- **Decision:** `datasheets.extract_facts(replace=True)` marks the document's
  current unconfirmed facts `superseded_at = <now>` and writes the new rows
  beside them. Nothing is deleted. Every reader of *current* facts filters
  `superseded_at IS NULL`; a finding resolves the fact it cited by id,
  unfiltered. The B40 refuse-unless-acknowledged guard on this path is
  retired because there is nothing left to refuse.

## The problem

`review_findings.fact_id` has no foreign key. Before this change a re-read of a
datasheet deleted its unconfirmed facts and wrote new rows with new ids, so
every finding that cited an old fact cited nothing. B40 (2026-09-22) made that
visible — count, record to `audit_events`, refuse unless the caller passed
`acknowledge_orphaned_findings=True` — but it could not make it safe: the
#179 extraction fixes cannot reach the live database without a re-read, and
the vessel datasheet's 12 findings (2 distinct findings × 6 review runs, all
`NEEDS_ENGINEER_REVIEW`) would have been orphaned. The project rule is
"re-extraction must not destroy historical evidence".

## The decision

| Place | Before | After |
|---|---|---|
| `submittal_facts` schema | — | additive nullable `superseded_at TEXT` (`submittal_review.ensure_schema`) |
| `datasheets.extract_facts(replace=True)` | `DELETE ... WHERE confirmed_by IS NULL` behind `orphan_guard.check_facts` | `UPDATE ... SET superseded_at` on current unconfirmed rows, in the same transaction as the new rows (B19) |
| Audit | `findings.orphaning.re_extract_facts` (refused / ok) | `facts.superseded.re_extract_facts`, detail `facts_superseded=N findings_citing=K`, same transaction; written only when N > 0 |
| `datasheets.list_facts` | all rows | current rows only |
| `submittal_review.list_submittal_facts` | all rows | current rows only |
| `submittal_review.ensure_facts_extracted` has-no-facts guard | any row | any *current* row |
| `comparison._document_is_tag_scoped` | all rows' tags | current rows' tags |
| `comparison.reject_pair_for_finding` fact lookup | by id | by id — unchanged, so a superseded fact still resolves |
| `acknowledge_orphaned_findings` on `extract_facts` | required to proceed past cited facts | removed (still exists for requirements: re-extract, re-chunk, delete, reject) |

A **confirmed** fact (`confirmed_by IS NOT NULL`) is never superseded: a
human's confirmation outlives a re-parse, as before.

## What this does not do

- It does not version **requirements** (`standard_requirements`). B38's guard
  stays; that redesign is still parked for the owner.
- It does not re-link an old finding to the new reading of the same cell. A
  superseded fact is history, not a current value; the finding says what was
  compared at the time.
- It does not repair the 16,168 requirement orphans B38 counted.
- The supersession timestamp is the only version marker; there is no
  `superseded_by` chain on facts because a re-read is whole-document, not
  row-for-row.

## Evidence

`backend/tests/test_b40_fact_orphan_guard.py` (rewritten): the cited fact
survives and stays cited; each of the four current-fact readers excludes
superseded rows; a confirmed fact stays current; the audit row carries both
counts; a first read records nothing; B19's cached-facts path is untouched.
Mutations M334–M336 (re-anchored) and M440–M444, phase 56 — 8/8 detected.
`scripts/reextract_on_copy.py` reports `current_facts_before`,
`unconfirmed_facts_superseded`, `review_findings_citing_superseded`,
`current_facts_after`, `rows_in_table_after`.

## Live-database consequence

Rows in `submittal_facts` only grow. For the three regression documents the
plan (`.cowork/issue179-live-reextraction-plan.md`) expects 103 current rows
to become 103 superseded + ~290 current. Row count is not a fact count any
more: **count current facts** (`superseded_at IS NULL`) when stating how many
facts a document has.
