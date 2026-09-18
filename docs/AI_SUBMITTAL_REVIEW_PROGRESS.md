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


---

# Phase 2 (continued): the remaining product gaps

Sections 11-19 recorded Phase 2's backend. This records the gaps that were
still open after it: Excel upload and preview, and the frontend that makes any
of it reachable.

## 20. XLSX upload: accepted, proven, stored, never indexed

**XLSX only.** Not `.xls` (not OOXML at all), not `.xlsm` (macros), not `.csv`.

### The signature check goes past the magic bytes

`PK\x03\x04` proves "a zip" and nothing more - `.docx`, `.pptx` and `.jar` open
with the same four bytes. The gate is therefore two-stage:

1. the first block must open as a PDF **or** a zip, otherwise it is refused
   exactly as before;
2. a zip is then opened and must contain **`xl/workbook.xml`**, which is the
   part a renamed `.docx` cannot fake.

### A decompression bomb is refused, not expanded

The upload ceiling bounds the bytes *on the wire* and is no protection at all
against a 40 KB file that expands to gigabytes. `validate_xlsx` reads the
**declared** sizes from the zip central directory - decompressing nothing - and
refuses a workbook claiming more than 256 MB total or more than 5,000 entries.
A real CRS template is a few hundred kilobytes.

`workbook.py` applies the second half of that bound while actually reading:
every part is read with a ceiling, and the preview stops at 25 sheets, 500 rows
and 60 columns, **reporting truncation rather than applying it silently**.

### The stored suffix is derived from the validated type

`upload.py` hardcoded `f"{sha256}.pdf"`. It is now
`f"{sha256}{_SUFFIX_FOR_KIND[kind]}"`, and the suffix comes from the **bytes**,
never from what the caller named the file: a workbook uploaded as `.pdf` is
stored as `.xlsx`, and a PDF uploaded as `.xlsx` is stored as `.pdf`.

This sits directly under the M15 immutability guard, so **M19** exists to prove
the two still work together - it puts the hardcoded `.pdf` back and the
immutability test fails.

### The PDF path is unchanged, and that is proven rather than asserted

`backend/tests/test_upload.py` was **not modified** and passes. Two of its
tests did fail mid-change, and both were fixed in the CODE rather than in the
test:

- `stream_to_temp` had grown a third return value, breaking a test that
  unpacks two. The kind is now detected by `detect_kind()` reading four bytes
  back off the written file, and the signature is untouched.
- `test_non_pdf_is_rejected_and_leaves_nothing_behind` uploads
  `b"PK\x03\x04zip"` and expects `not_pdf`. A file that opens with the zip
  magic and then fails to be a zip at all is now reported as `not_pdf`, not
  `not_xlsx`: four bytes of coincidence is not a declaration of intent, and
  calling it a bad *workbook* claims to know more about it than we do. A
  readable zip that is not a workbook - a real `.docx` - does get `not_xlsx`,
  where the intent is clear and the precise message is the useful one.

### THE DECISION: a workbook is stored and NEVER indexed

Stated explicitly because the alternative is to arrive at the same place by
accident.

A CRS template is **a form to be filled, not corpus content**. Extracting it
would put spreadsheet scaffolding - blank cells, header rows, the word
"Remarks" - into the retrieval pool, where it can be returned as the answer to
an engineering question: a citation to a document that asserts nothing.

So an xlsx is written with a new **terminal** status, `stored_not_indexed`, and
**no extract job**, and `ingest` returns `job_id = None` because a job id is a
promise that work is happening and none is. It is never extracted, OCR'd,
chunked, embedded or made retrievable.

The load-bearing detail is that the state is TERMINAL.
`IngestionWorker._next_document` selects every status outside
`TERMINAL_STATES | {PARTIALLY_SEARCHABLE}`, so a non-terminal state here would
have the worker pick the workbook up on every poll forever - exactly what the
`no_searchable_content` omission once did. `test_the_ingestion_worker_never_
selects_a_workbook` asserts that against the worker's own query rather than
against the constant.

Letting it queue and fail in `extract` would have reached the same place, landed
it in `failed`, and told an operator to go and fix something that is working as
intended.

A workbook still gets a filename-only classification suggestion, so it appears
in the needs-classification queue like anything else. Stored and not indexed is
not the same as invisible.

## 21. The frontend now reaches the Phase 2 backend

Everything here was wired to routes that already existed.

| Surface | File | Notes |
|---|---|---|
| Metadata editing + role assignment | `classification/MetadataEditor.tsx` | All 12 fields. Blank means CLEARED, so a PUT replaces the record. |
| Filters | `classification/DocumentFilters.tsx` | Role, discipline, equipment type, project. |
| PDF + XLSX preview | `DocumentPreview.tsx` | One route for previewed and downloaded bytes. |
| Technical details | `DocumentTechnicalDetails.tsx` | Metadata and processing information. |
| Citation to page | `PageImageViewer.tsx` | New `initialPage`. |
| Wiring | `views/DocumentsView.tsx`, `DocumentCard.tsx` | Preview and Details actions, filter bar. |

### The filters are applied by the SERVER

Every selection is passed to `GET /api/documents` and nothing is filtered in
the browser. The route puts them through `classification.restrict`, which
intersects with the caller's grants and returns a **narrower `AccessScope`**.
Filtering the returned array instead would mean the server had already sent
rows the caller was not meant to see, and the filter would be decoration over a
leak.

Note the screen now carries **two filters with different reach**, and each says
which it is: the metadata filters go to the server, while the older type filter
never leaves the browser and only hides rows already fetched.

### Citation to page

`PageImageViewer` always opened at page 1. Following a citation to page 214 of a
specification landed the reader on the cover sheet - **a citation that does not
open its own page is not a citation, it is a filename.** It now takes
`initialPage`, clamped to 1 so a malformed citation cannot render page 0, and
follows a later citation while already open.

### Nothing is fetched by a bare URL

Preview, download and page images all go through `request()`/`downloadReport`/
`useAuthedImage`, which put the token in the **Authorization header and never on
a URL**. A URL reaches browser history, proxy logs and Referer headers. This is
the fourth surface in this codebase to need that fix; it was built that way from
the start.

### The workbook is read on the SERVER

`backend/app/workbook.py`, Python standard library only. The obvious
alternative - SheetJS in the browser - was rejected: the npm `xlsx` package is
no longer published there by its authors, so `npm install xlsx` fetches a stale
release with published prototype-pollution advisories, and it would mean a
third-party parser running over a contractor-supplied file inside the reader's
browser. **No new frontend dependency was added.**

### Null renders as nothing

`DocumentTechnicalDetails.Field` returns `null` for an unset value - never
"Unknown", never 0, never a dash that reads like a recorded value. All eleven
metadata fields are null on every one of the 19 documents in the live corpus.
**M26** puts "Unknown" back and the test fails.

## 22. Frontend test numbers, and a correction to the 63

**The suite is flaky under parallel load, and the earlier "63 known
pre-existing" was an artifact of that.** Measured properly:

| Measurement | Result |
|---|---|
| Baseline at `9f75ba5`, everything stashed | **575 total, 60 failed, 515 passed** |
| After this work, one full run | **596 total, 63 failed, 533 passed** |
| After this work, another full run | 596 total, **59** failed, 537 passed |
| The 4 consistently failing files, run alone | **59 failed**, every run |
| The 7 files this work touched or added, run alone | **64 passed, 0 failed** |

The STABLE pre-existing failure set is **59**, in four files:
`ChatView.test.tsx` (54), `ChatView.comparisonScope.test.tsx` (3),
`Shell.test.tsx` (1), `glossary.test.ts` (1). Those assert UI terminology
against the navigation relabel in `f0c70a2`.

Everything above 59 varies between runs. The baseline run failed
`IngestionView.watch.test.tsx`; a later run failed
`AnalysisModeScreen.citation`, `AnalysisModeScreen.typeFilter` and
`LoginView` instead. **All of those pass when run in isolation** (46 passed),
so they are load-sensitive, not broken - and the baseline exhibits the same
behaviour.

**Delta from this work: +21 tests, all passing, and no new failure.** That was
established by running every touched and added file in isolation, not by
comparing two summary lines - comparing summary lines is what produced the
wrong 63 in the first place.

The figure "63 known pre-existing" as stated in section 17 is therefore
**retracted**: it was one flaky run's total, quoted as though it were a stable
property. Recorded in `docs/status-honesty-audit.md`.

## 23. Mutations

`python scripts/mutation_check.py` - **26/26 detected**. The harness now runs
**vitest as well as pytest**, because a backend-only harness would have left
every screen unproven while reporting a perfect score.

| # | Mutation | Runner |
|---|---|---|
| M16 | Accept any zip as a workbook | pytest |
| M17 | Remove the decompression-bomb ceiling | pytest |
| M18 | Queue a workbook for indexing like a PDF | pytest |
| M19 | Hardcode the stored suffix back to `.pdf` | pytest |
| M20 | Accept macro-enabled workbooks | pytest |
| M21 | Open the page viewer at page 1, ignoring the citation | vitest |
| M22 | Stop clearing blank metadata fields | vitest |
| M23 | Send the human role label instead of the contract value | vitest |
| M24 | Show the metadata form to a non-admin | vitest |
| M25 | Render a workbook's empty cells instead of populated ones | vitest |
| M26 | Render "Unknown" for a field that was never recorded | vitest |

### Three defects the harness found in this round

1. **The harness could not read vitest's output.** On a Windows console at
   cp1252 the decode of vitest's box-drawing characters raised, the harness
   treated the exception as a non-zero exit, and reported **6/6 DETECTED
   without a single test having been consulted**. Fixed with explicit UTF-8
   decoding and an ASCII-flattened summary. A harness that cannot read its
   runner reports a perfect score by accident - the precise failure it exists
   to catch, committed in the file that catches it.
2. **M13's anchor became ambiguous.** The new `document_workbook` route opens
   with the same two lines as `document_original`, so the anchor matched twice
   and the harness **refused to run it** rather than guessing. That refusal is
   the safety property working; the anchor was disambiguated by the line that
   follows.
3. **M13's replacement called a function that does not exist.** It would have
   failed the test with a `NameError` - the right verdict for the wrong reason.
   It now performs a real unscoped read, so the mutation reproduces the DEFECT
   (serving a document the caller holds no grant for) rather than merely
   breaking the route.

## 24. Known limitations after this round

1. **`.xls` and `.csv` are still refused**, by decision. `.xlsm` is refused on
   its macro part specifically.
2. **A workbook is never searchable.** Asking a question about a CRS template
   returns nothing from it. That is the decision in section 20, not a defect.
3. **The workbook preview is bounded** at 25 sheets / 500 rows / 60 columns and
   says when it truncated. Cell formatting, merged cells, formulas as written,
   charts and images are not shown; a formula cell shows its last computed
   value.
4. **Citation-to-page is wired in the page viewer, not re-verified on every
   surface.** `PageImageViewer` now opens at a cited page and the Documents
   screen uses it. The master-plan requirement that *every* citation in Chat,
   Analysis, Submittal Review and Reports does so was not audited surface by
   surface, and is not claimed.
5. **The 59 pre-existing frontend failures are untouched**, per instruction.
6. **The frontend suite is flaky under parallel load** (section 22). Any future
   claim about its totals should quote an isolated run, or say which run it is.
7. **`equipment_tags` is editable but still not filterable.**
8. **The role vocabulary is still enforced at the API boundary only.**

## 25. Verification for this round, measured

Backend, `python -m pytest -q` in `backend/` on the project venv:

| | passed | skipped | deselected | xfailed | wall |
|---|---|---|---|---|---|
| Baseline (before this round) | 1642 | 27 | 1 | 17 | 457.55s |
| **After** | **1661** | 27 | 1 | 17 | 645.39s |
| Delta | **+19** | 0 | 0 | 0 | |

+19 is exactly `tests/test_xlsx_upload.py`. **No pre-existing backend test
changed status, and `tests/test_upload.py` was not modified.**

| Check | Result |
|---|---|
| Full backend suite | 1661 passed, 0 regressions |
| `python scripts/mutation_check.py` | **26/26 detected** |
| `cd frontend && npm run build` (`tsc -b && vite build`) | passes |
| Frontend, files touched or added, isolated | **64 passed, 0 failed** |
| Frontend, the 4 known-bad files, isolated | 59 failed - unchanged, untouched |
| Frontend, full parallel run | 596 total; failures vary 59-63 by run (section 22) |
| `python run.py` -> `GET /api/health` | 200 |
| `GET /openapi.json` | 200 |
| `GET /api/documents/{id}/workbook` unauthenticated | **404** - scoped, no bytes |
| `GET /api/documents?document_role=BANANA` | **422** "unknown document role" |
| `GET /api/documents?document_role=...` unauthenticated | `[]` - empty scope, no leak |
| CI lint gate (`ruff --select E9,F63,F7,F82`) | passes |
| `git diff --check` | clean |

## 26. What did not work first time, recorded

1. **Two existing PDF upload tests broke mid-change, and the CODE was fixed
   rather than the tests.** `stream_to_temp` had grown a third return value;
   the kind is now detected separately and the signature is untouched. And a
   zip that fails to be a zip is reported `not_pdf`, not `not_xlsx`. See
   section 20.
2. **The mutation harness reported a false 6/6.** See section 23.
3. **A mutation's replacement called a function that does not exist**, so it
   would have failed for the wrong reason. See section 23.
4. **The "63 pre-existing frontend failures" figure was wrong**, including
   where this document stated it. See section 22, and the retraction in
   `docs/status-honesty-audit.md`.
5. **SheetJS was written into the frontend and then removed** in favour of a
   standard-library reader on the server, once its npm distribution turned out
   to be stale and carrying advisories. No new frontend dependency was added.
