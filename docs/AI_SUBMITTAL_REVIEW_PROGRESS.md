# AI Submittal Review — Phase 1 (Foundation) and Phase 2 (Document experience)

Phase 1 is sections 1–10. **Phase 2 begins at section 11.**

# Phase 1 (Foundation)

**Status: foundation only.** Schema, vocabularies and scoped read paths. There
is no extraction engine, no applicability engine, no comparison engine, no
Standards Library UI and no CRS export. A table existing in this phase is not a
claim that anything fills it.

Date: 2026-09-18 · Branch: `feat/phase-1-ui-reaches-backend` · Python 3.12.10

---

## 1. Test counts, measured

Both runs are `python -m pytest -q` in `backend/`, on the project venv.

| | passed | skipped | deselected | xfailed | wall |
|---|---|---|---|---|---|
| **Baseline** (before any edit) | **1556** | 27 | 1 | 17 | 455.54s |
| **After Phase 1** | **1611** | 27 | 1 | 17 | 464.25s |
| Delta | **+55** | 0 | 0 | 0 | |

The +55 is exactly the new file `tests/test_submittal_review_foundation.py`
(55 tests, of which 24 are parametrised cases over the two vocabularies).
**No pre-existing test changed status.** The 27 skips are the pre-existing
parked `test_relevance_floor` / `test_typo_tolerance` set and are unrelated to
this work.

## 2. Mutation proof (CLAUDE.md rule 6)

Every test here was proven non-vacuous by deleting its feature and confirming
the test fails. The harness backs up each file, applies one mutation, runs the
selected tests, and restores in a `finally` block.

| # | Mutation applied | Result |
|---|---|---|
| M1 | Delete the scope filter from `list_review_runs` | 2 failed ✅ |
| M2 | Delete the scope filter from `list_submittal_facts` | 2 failed ✅ |
| M3 | Make an empty grant set mean *everything* (the `deliverables.py` defect) | 1 failed ✅ |
| M4 | Drop the standards-side filter in `list_applicable_standards` | 1 failed ✅ |
| M5 | Give the read paths a **default** scope | 1 failed ✅ |
| M6 | Remove the `document_classification` column migration | 1 failed ✅ |
| M7 | Remove the `review_findings` ALTER block | 1 failed ✅ |
| M8 | Widen `DocumentRole` to a free string | 6 failed ✅ |
| M9 | Widen `ComplianceStatus` to a free string | 7 failed ✅ |
| M10 | Give `review_findings.standard_document_id` a CASCADE foreign key | 1 failed ✅ |

**10/10 detected — but only after a correction that is the point of the rule.**

On the first run **M6 and M7 still passed**: the two migration tests were
**vacuous**. The fixture calls `db.init_db()`, which builds the table from
today's `SCHEMA` — already containing the new columns — so the `ALTER` path
never executed and the tests passed with the migration deleted. They were
rewritten to construct the table from an explicit pre-migration DDL
(`_LEGACY_CLASSIFICATION_DDL`, `_LEGACY_FINDINGS_DDL`) and to assert the old
shape first (`assert "document_role" not in before`) so the test fails loudly
if it ever stops testing a migration. This is the project's documented
recurring defect, reproduced and caught; it belongs in
`docs/status-honesty-audit.md`.

## 3. Files changed

| File | Change |
|---|---|
| `backend/app/db.py` | 11 nullable columns on `document_classification` in `SCHEMA`; matching conditional `ALTER` block in `_migrate` using this file's `r["name"]` idiom |
| `backend/app/review.py` | 10 columns on `review_findings` in the CREATE and in the existing ALTER dict (`row[1]` idiom); new `idx_review_findings_run` |
| `backend/app/schemas.py` | `DocumentRole` and `ComplianceStatus` Literals; 11 new fields on `DocumentClassification` |
| `backend/app/classification.py` | `of_document` decodes `equipment_tags` from JSON; `import json` |
| `backend/app/main.py` | import `submittal_review`; `ensure_schema()` at startup beside the other four |
| `backend/app/submittal_review.py` | **new** — 4 tables, 6 scoped read paths |
| `backend/tests/test_submittal_review_foundation.py` | **new** — 55 tests |

## 4. Schema changes

**`document_classification`** — 11 columns, all nullable, all plain `TEXT`:
`document_role`, `document_number`, `revision`, `effective_date`, `project`,
`contractor_vendor`, `equipment_type`, `equipment_tags` (JSON array as TEXT),
`service`, `transmittal_number`, `superseded_by`.

**`review_findings`** — 10 columns beside (never replacing) `status` and
`disposition`: `review_run_id`, `compliance_status`, `contractor_page`,
`contractor_section`, `contractor_evidence_text`, `standard_document_id`,
`standard_clause`, `standard_page`, `requirement_source_text`, `ai_rationale`.

**Four new tables** (`submittal_review.py`, module-local `ensure_schema()`):
`standard_requirements`, `review_runs`, `submittal_facts`, and the normalised
`review_applicable_standards`.

Decisions worth naming:

- **No CHECK constraints.** This schema carries exactly one (`roles.kind`).
  SQLite cannot `ALTER ADD` a CHECK, so a second would force a table rebuild at
  the next column migration. The 5 roles and 6 statuses are enforced in
  Pydantic and appear in the OpenAPI contract as enums.
- **`review_applicable_standards` is a relation, not a JSON column**, because
  it is joined, permission-filtered and audited. A ruled-out standard stays as
  a row with its `exclusion_reason`: "we looked at this and decided it did not
  apply" is the answer an engineer actually asks for.
- **Two `standard_document_id` columns behave differently, on purpose.** On
  `standard_requirements` it is a CASCADE foreign key — a requirement is owned
  by the standard it came from. On `review_findings` it has **no foreign key**
  at all (the `report_documents` precedent): deleting a standard must not erase
  the record that it was cited.
- **`compliance_status` is a second vocabulary, not a reuse.** Six values that
  do not collapse to a boolean: `MISSING_INFORMATION` is not `NON_COMPLIANT`,
  and `NEEDS_ENGINEER_REVIEW` is the machine declining to answer, stored as a
  result rather than rounded to a guess. NULL is distinct from all six and is
  what every pre-existing row holds.

## 5. Migration behaviour, measured

Run first against a **copy of the live database, all three WAL files**
(`.sqlite`, `-wal`, `-shm`), then against the live one.

On the copy, run twice:

- 40 pre-existing tables, **row counts identical across both passes** —
  19 documents, 6580 chunks, 2921 pages, 19 classifications, 3 users, 40 grants.
- `pass1 == pass2` for tables, row counts **and column lists** — idempotent.
- 4 new tables created, all 21 new columns present, guided-review `status` /
  `disposition` / `approval_status` still present.

On the **live** database, via `python run.py`:

| | before | after |
|---|---|---|
| documents | 19 | **19** |
| chunks | 6580 | **6580** |
| pages | 2921 | **2921** |
| document_classification | 19 | **19** |
| users / grants | 3 / 40 | **3 / 40** |
| tables | 41 | **45** (+4) |

No row was lost. Nothing was back-filled: every new column is NULL on every
existing row, which reads as *not recorded* and never as a default role or a 0.

## 6. Permission model

Every read path in `submittal_review.py` takes `allowed_document_ids`
**keyword-only with no default** — `search.py`'s contract, not
`deliverables.py`'s. Forgetting it raises `TypeError` (tested, 6 call sites).

`_scope_clause` is shaped after `metrics._where` and filters **in the query**,
never in Python afterwards. Two deliberate differences from the modules nearby:

- There is **no `None` meaning corpus-wide.** Every table here is keyed to a
  submittal, so "no restriction" is not a state a caller may express. An
  admin's breadth arrives as a wide id set through the same parameter.
- There is **no `document_id IS NULL OR ...` branch.** That is
  `deliverables.list_items:150`, which makes NULL-document rows world-readable.
  A review run always has a submittal, so NULL must never mean visible to
  everyone; the columns are `NOT NULL` and an empty grant set resolves to
  `WHERE 1 = 0`.

`list_applicable_standards` filters **twice** — the run's submittal must be
readable *and* each standard row is restricted to standards the caller may
read — because they are two different documents. Reading a submittal does not
grant every standard it was compared against. Both directions are an
intersection, never a union (rule 5).

`get_review_run` returns `None` for both "does not exist" and "not yours",
following `api_utils.require_document`: a 403 would confirm the row exists.

## 7. API and contract changes

- **No new routes.** Phase 1 adds no HTTP surface.
- `GET /api/documents/{id}/classification` now returns the 11 new fields.
  `DocumentClassification.document_role` appears in `/openapi.json` as
  `{"enum": ["CONTRACTOR_SUBMITTAL", "COMPANY_STANDARD", "CONTRACT_DOCUMENT",
  "SUPPORTING_DOCUMENT", "CRS_TEMPLATE"]}` plus null. Verified in the served
  document, not inferred from the source.
- `equipment_tags` is a `list[str]` at the boundary and JSON TEXT in the
  column; a malformed value reads as `[]` rather than raising.
- `ClassificationUpdate` is **unchanged** — the new fields are readable but not
  yet writable through the API. See limitations.

## 8. Verification performed

| Check | Result |
|---|---|
| Migration on a copy of the live DB (3 WAL files), run twice | ✅ no row lost, idempotent |
| Full backend suite | ✅ 1611 passed (baseline 1556), 0 regressions |
| New targeted tests | ✅ 55 passed |
| Mutation proof | ✅ 10/10 detected (2 after correcting vacuous tests) |
| `cd frontend && npm run build` (`tsc -b && vite build`) | ✅ 80 modules, no type errors |
| `python run.py` → `GET /api/health` | ✅ 200, `{"ok":true,...}` |
| `GET /openapi.json` | ✅ 200, 67 paths |
| App starts against the **existing** DB, no rows lost | ✅ 19 documents, counts unchanged |
| `git diff --check` | ✅ clean |

## 9. Known limitations — what Phase 1 does NOT do

1. **Nothing writes these tables yet.** There are no create/update functions and
   no routes; the four tables are empty by construction. The read paths are
   tested against rows inserted directly by the tests.
2. **The new classification fields are read-only through the API.**
   `ClassificationUpdate` was deliberately not extended — an admin cannot set
   `document_role` from the UI yet. Until Phase 2 the only way a value arrives
   is a direct write.
3. **The Pydantic vocabulary is a boundary check, not a database constraint.**
   A direct SQL insert can still write `document_role = 'BANANA'`. That is the
   accepted cost of having no CHECK constraint; any future non-API writer must
   validate for itself.
4. **`superseded_by` is not validated as an existing document id** (no FK, by
   design). A dangling value is possible and is rendered as recorded, not
   resolved.
5. **No UI.** Nothing on screen reads or shows any of this.
6. **`review_findings` is empty in the live database** (0 rows), so the
   "existing findings still work" guarantee is proven by tests against a
   constructed legacy table, not by production rows.
7. **The two PRAGMA idioms still disagree** — `db.py` reads `r["name"]`,
   `review.py` reads `row[1]`. Each new block matches its own file; unifying
   them was deliberately left out of this phase.
8. **Not verified:** that the whole workflow produces a correct review. No
   extraction, comparison or export exists to verify.

## 10. Recommended Phase 2 scope

`docs/AI_SUBMITTAL_REVIEW_MASTER_PLAN.md` §28 is the authority here, and it
defines **Phase 2 as "Document experience: filters, PDF/Excel preview,
citation-to-page navigation, technical-details drawer."** The Standards Library
is **Phase 3**. This recommendation follows the plan.

**One thing must be carried into Phase 2 from this phase, and it is the
blocker:** the 11 new fields are readable but **not writable** —
`ClassificationUpdate` was deliberately not extended. A document therefore
cannot be marked `COMPANY_STANDARD` or `CONTRACTOR_SUBMITTAL` through the UI at
all. Phase 2's headline feature is *filters*, and a filter over a column no
admin can set will filter every document into the same empty bucket. So:

1. **Extend `ClassificationUpdate`** with the 11 fields, validating
   `document_role` against `DocumentRole` and `equipment_tags` as `list[str]`,
   and write them in `classification.confirm`. This is small, it closes the
   phase-1 gap, and every later phase depends on it.
2. **Document filters** by `document_role`, `discipline`, `equipment_type` and
   `project`. The filter must go through `classification.restrict`, which
   returns a **narrower `AccessScope`** — intersection, never union (rule 5) —
   rather than a new id set assembled at the route.
3. **PDF / Excel preview and citation-to-page navigation.** Note the open
   defect this lands on: `docs/design-access-holes.md` hole 1 — `client.ts:622,634`
   hand image URLs to `<img src>`, which cannot send the bearer token. Under
   `AUTH_MODE=demo_required` this is the path preview will use, so it needs
   `useAuthedImage` (or `request()`) rather than a raw URL.
4. **Technical-details drawer** showing the new metadata, with **null rendered
   as nothing** — never 0, never "Unknown" — since every field is null on all
   19 existing documents today.
5. **Tests**, mutation-proven: an invalid `document_role` is refused at the
   route; a filter narrows and never widens a scope; a user without a grant
   sees no filtered result; preview refuses a document the caller cannot read.

Explicitly **not** Phase 2: clause extraction, the applicability engine, the
comparison engine, CRS export (Phases 3, 5 and 7).

---

**Is Phase 1 safe to accept?** The schema, the migration and the permission
filter are verified by measurement and by mutation, on a copy and then on the
live database, with no row lost and no regression in 1611 tests. What it is
*not* is useful on its own: nothing writes these tables and nothing shows them.
Accept it as foundation, not as a feature.

---

# Phase 2 (Document experience)

Master-plan section 28 defines Phase 2 as "Document experience: filters,
PDF/Excel preview, citation-to-page navigation, technical-details drawer."
This section records what was built, what was **not**, and why.

## 11. The mutation harness is now a committed script

**It did not exist in the repository.** The ten Phase 1 mutations were run from
a file in a session scratchpad, which proves a claim once and cannot be re-run
by a reviewer - while section 14 of the handoff tells a reviewer to do exactly
that.

It is now `scripts/mutation_check.py`, carrying all fifteen mutations (ten from
Phase 1, five new).

```bash
python scripts/mutation_check.py              # all 15
python scripts/mutation_check.py --phase 2    # one phase
python scripts/mutation_check.py --list       # ids and descriptions
python scripts/mutation_check.py --only M11   # a subset
```

It backs each file up, applies one exact-anchor replacement, runs the selected
tests, and restores in a `finally` block, so an exception or a Ctrl-C cannot
leave the tree patched. Two properties worth naming:

- **An anchor matching anything other than exactly once is an ERROR, not a
  pass.** A mutation that silently stops applying reports "tests passed", which
  is indistinguishable from a vacuous test. That is how a harness lies.
- **It prefers `.venv`** over `sys.executable`: a 3.10 on PATH would fail every
  mutation for the wrong reason and read as a perfect score.

Exit code 0 means every mutation was detected.

## 12. Master-plan metadata mapping, resolved

Section 6 lists fifteen metadata items. Eleven were mapped in Phase 1. The four
that were not are resolved here, explicitly.

| Master-plan item | Resolution | Why |
|---|---|---|
| **title** | **New nullable column** `document_classification.title` | `documents.filename` is the name of the file and is authoritative for identity; a title is *descriptive* metadata about the same document. It belongs with the other descriptive fields, not on the core table whose columns decide lifecycle. Null means none recorded, and the UI falls back to the filename rather than inventing one. |
| **review status** | **DERIVED, never stored.** `submittal_review.review_status_for()` reads the latest `review_runs` row | A `review_status` column would be a second home for a fact `review_runs` already owns, and the two would disagree the first time a run was retried - CLAUDE.md rule 8 broken at design time. A test asserts the column does **not** exist on either table. |
| **processing status** | Already `documents.status` | The existing state machine (`states.py`) is the single source of truth for where a document is. A second status column is the same defect as above. |
| **active / superseded** | Already `superseded_by IS NULL` | Phase 1. Active is the absence of a supersession, not a separate flag that could disagree with one. |

`ReviewStatus` is `not_reviewed | pending | running | completed | failed`.
`not_reviewed` is a **real answer, not a null**: "has this been reviewed" has a
definite answer for every document, and it is "no". The other four mirror
`review_runs.status` exactly, so the two cannot drift into two vocabularies.

One subtlety the API preserves: a document the caller may **not** read is absent
from the result entirely, which is not the same as `not_reviewed`. A missing key
means "not yours to know".

## 13. What was implemented

| # | Item | Status |
|---|---|---|
| 1 | Extend `ClassificationUpdate` with the metadata fields | Done - all 12 fields, `document_role` validated as `DocumentRole` |
| 2 | Authorized users can assign `document_role` | Done - through the existing admin-gated `PUT .../classification` |
| 3 | document-role / discipline / equipment-type / project filters | Done - backend, on `GET /api/documents` |
| 4 | Filters narrow by intersection, never union | Done - routed through `classification.restrict`; mutation-proven |
| 5 | PDF and Excel preview | **Backend only** - `GET /api/documents/{id}/original`. No UI. See limitations. |
| 6 | Citation-to-page navigation | **Pre-existing, not extended.** See limitations. |
| 7 | Fix authenticated image preview URLs | Done - but the images were already fixed; the real bug was the **uploader**. |
| 8 | Technical document details and processing information | **Backend only** - fields added to `GET /api/documents`. No drawer. |
| 9 | Preserve original uploaded files | Done - guard plus a mutation-proven test |

### Item 7 was not the bug the architecture document describes

`docs/architecture.md` section 6 hole 1 says `<img src>` bypasses the bearer
header. **That is stale.** `useAuthedImage` exists, and both
`PageImageViewer.tsx:149` and `EvidencePanel.tsx:282` render from an object URL
rather than an API URL.

The transport that genuinely sent **no `Authorization` header** was
`Uploader.tsx` - `xhr.open("POST", "/api/documents")` with no header, against a
route that calls `_require_identity_to_write(scope)`. Under
`AUTH_MODE=demo_required` every upload was a 401 that the screen reported as
"Cannot reach the backend": a working server described as unreachable.

The fix adds `api.authorize(setHeader)` - a **setter**, not a `getToken()`. The
token keeps exactly one destination, an `Authorization` header, because a
returned value is one any caller could log, put in a URL or store, and the whole
reason it lives in memory only is that it must not be.

## 14. Files changed (Phase 2)

| File | Change |
|---|---|
| `scripts/mutation_check.py` | **new** - the committed harness, 15 mutations |
| `backend/app/db.py` | `title` column plus its migration entry |
| `backend/app/schemas.py` | `ReviewStatus`; `title`; 12 fields on `ClassificationUpdate`; 8 on `Document` |
| `backend/app/classification.py` | `METADATA_FIELDS`; `confirm()` writes metadata and tags; `ScopeFilter` gains roles/equipment_types/projects; three new WHERE clauses |
| `backend/app/submittal_review.py` | `review_status_for()` |
| `backend/app/main.py` | four filters on `GET /api/documents`; metadata and review status on the listing; `GET /api/documents/{id}/original`; `_MEDIA_TYPES` |
| `backend/app/upload.py` | the never-rewrite guard |
| `frontend/src/api/client.ts` | `authorize()` |
| `frontend/src/components/Uploader.tsx` | attaches the bearer header |
| `backend/tests/test_document_metadata_filters.py` | **new** - 20 tests |
| `backend/tests/test_document_original_file.py` | **new** - 11 tests |
| `frontend/src/components/Uploader.auth.test.tsx` | **new** - 3 tests |

## 15. Two defects found in my own work

Both were caught by the mutation harness, which is the argument for committing
it rather than the argument for trusting a report.

1. **`review_status_for` returned `not_reviewed` for every reviewed document.**
   The first version used
   `(doc, created_at, id) IN (SELECT doc, MAX(created_at), MAX(id) ...)`. Those
   two maxima are taken **independently**, so the tuple can describe a row that
   does not exist. Caught by a test, not by review.

2. **The immutability test was vacuous.** It re-implemented upload.py's
   `if final_path.exists()` branch inside the test, so it could never observe a
   change to upload.py. M15 reported NOT DETECTED. It now calls the real
   `upload.ingest()` against an orphaned stored file. The `-k` expression was
   wrong as well and selected a different test - two independent ways the same
   check was worthless.

## 16. Known limitations - Phase 2

1. **No Documents-page UI.** Filters, preview and the technical-details drawer
   are backend only. The API supports them; nothing renders them. Per CLAUDE.md
   the frontend belongs to Cowork, and this is the largest remaining gap.
2. **Excel cannot be uploaded at all.** `upload.py` enforces PDF magic bytes and
   stores `{sha256}.pdf`. `GET .../original` serves the correct workbook media
   type *if* an `.xlsx` is ever stored, and that is tested - but no route
   accepts one, so Excel preview is **unreachable in practice**. CRS templates
   are `.xlsx`, so this blocks the `CRS_TEMPLATE` role from being useful.
   Accepting non-PDF uploads touches the ingestion state machine and was out of
   scope for this phase.
3. **Citation-to-page was not extended.** The page-image route and
   `X-Answer-Located` already existed and already work from Chat. The
   master-plan requirement that *every* citation in Analysis, Submittal Review
   and Reports opens the exact page was **not** verified surface by surface, and
   is not claimed.
4. **`equipment_tags` is writable but not filterable.** It is a JSON array in one
   column; filtering it needs a join table or `json_each`, and neither was in
   scope.
5. **The role vocabulary is enforced at the API boundary only.** A direct SQL
   write or a direct `classification.confirm()` call can still store a bad role.
6. **`superseded_by` is still unvalidated** - no foreign key, by design, so a
   dangling id remains possible.
7. **The frontend test suite was already failing before this work.** See below.

## 17. The frontend suite is red, and it was red before Phase 2

`npx vitest run` reports **63 failed / 512 passed (575)** across 7 files:
`ChatView.test.tsx` (54), `ChatView.comparisonScope.test.tsx` (3),
`Shell.test.tsx` (1), `glossary.test.ts` (1) and others.

**This is not a Phase 2 regression, and that was verified rather than assumed:**
with the two frontend changes stashed, `ChatView.test.tsx` still fails 54/54,
and `glossary` and `Shell` still fail, at `9f75ba5`. The failures are consistent
with the navigation relabel in `f0c70a2` - those suites assert UI terminology.

This contradicts section 7 of the handoff, which stated that only
`npm run build` was outstanding. The build passes; **the suite was never run on
Windows after the relabel.** Recorded in `docs/status-honesty-audit.md`.

Fixing them is not Phase 2 work - the labels are a product decision and the
tests encode the old vocabulary - but nothing further should be called green
until they are addressed.

## 18. Phase 2 mutation proof

`python scripts/mutation_check.py` - **15/15 detected**, the ten Phase 1
mutations re-run from the committed harness plus five new ones.

| # | Mutation applied | Result |
|---|---|---|
| M11 | Make the metadata filter **union** with the caller's scope instead of intersecting | 3 failed |
| M12 | Let an unknown `document_role` through the update boundary | 4 failed |
| M13 | Drop the scope check from the original-file download | 2 failed |
| M14 | Make a filter that matched nothing fall back to the whole corpus | 3 failed |
| M15 | Let an upload overwrite an existing stored original | 2 failed |

M15 is the one that earned the harness its place: it reported NOT DETECTED on
the first run and exposed a test that could not observe the code it claimed to
test. See section 15.


## 19. Phase 2 verification, measured

Backend, `python -m pytest -q` in `backend/` on the project venv:

| | passed | skipped | deselected | xfailed | wall |
|---|---|---|---|---|---|
| Phase 1 baseline | 1611 | 27 | 1 | 17 | 583.76s |
| **After Phase 2** | **1642** | 27 | 1 | 17 | 637.21s |
| Delta | **+31** | 0 | 0 | 0 | |

+31 is exactly the two new backend files: 20 in
`test_document_metadata_filters.py` and 11 in `test_document_original_file.py`.
**No pre-existing backend test changed status.**

| Check | Result |
|---|---|
| Full backend suite | 1642 passed, 0 regressions |
| Mutation harness, all 15 | 15/15 detected |
| `cd frontend && npm run build` (`tsc -b && vite build`) | passes, 80 modules, no type errors |
| New frontend tests (`Uploader.auth.test.tsx`) | 3 passed; mutation-proven by deleting the `authorize(...)` line |
| Full frontend suite | **63 failed / 512 passed - pre-existing, see section 17** |
| `python run.py` then `GET /api/health` | 200, `{"ok":true,...}` |
| `GET /openapi.json` | 200 |
| `GET /api/documents/{id}/original` with no token | **404** - empty scope, no bytes served, and not a 403 |
| `git diff --check` | clean |

The unauthenticated 404 on the new route is the one worth reading twice: under
`AUTH_MODE=demo_required` an unidentified caller resolves to an empty scope,
`require_document` finds nothing, and the answer says nothing about whether the
document exists.

