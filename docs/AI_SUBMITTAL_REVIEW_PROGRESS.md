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

---

# Phase 3A (Standards Library)

Clause hierarchy, atomic requirements, revision and effective-date management,
and the Standards Library screen. Applicability, conditions, exceptions,
numeric limits, units, operators, normalisation and the verification workflow
are **3B** and are deliberately absent.

## 27. What already existed, and was reused rather than rebuilt

**A COMPANY_STANDARD PDF already goes through the whole pipeline.** It is
chunked, it is in `chunks_fts`, and it is embedded in `chunk_vectors`. So:

**There is no second index.** `standard_requirements` is a LAYER POINTING INTO
THE EXISTING CHUNKS, via a new `chunk_id` column. A parallel exact-text or
vector store would duplicate retrieval and, worse, bypass the
`allowed_document_ids` masking that only the existing path enforces - the mask
is applied to the score vector *before* top-k precisely so the size of the
shrinkage cannot disclose how much matching material exists in documents the
caller cannot read. A second store would have none of that.
`test_no_second_index_was_created` asserts no such table appeared, and
`test_a_requirement_points_at_a_chunk_retrieval_can_also_see` asserts the
requirement's chunk id is one `chunks_fts` also carries.

**There is no second clause parser.** `chunker.looks_like_heading`,
`_validate_heading`, `plausible_heading_numbers` and `segment_document` already
decide what a clause heading is - strictly, and with a documented history of
why each rule exists ("330 Hudson Street" is not section 330). The result is
already stored on `chunks.section`. `standards.clause_number()` reads that
column and takes the number exactly as `chunker._heading_number` does.

**Nothing in chunker.py needed to change, and that is worth stating plainly.**
The prompt allowed extending those functions in place if they were insufficient
for standards. They were not insufficient. What they do not compute is the
HIERARCHY - parent clause and depth - and that is not a gap in the parser: a
chunker has no reason to know that 5.3.3's parent is 5.3. `parent_clause()` and
`clause_depth()` are new, they are pure string functions over an
already-validated heading, and they live in `standards.py` because that is
where the hierarchy is needed.

## 28. Clause hierarchy

`GET /api/standards/{id}/clauses` returns one row per distinct clause with its
number, parent, depth, title, page and **chunk id** - so every clause in the
library resolves to a passage a reader can open.

Ordered by page then chunk ordinal, which is the document's own order. Sorting
by clause number as a string would put 5.10 before 5.9; sorting it numerically
would impose an order the document may not have.

A chunk with no `section` yields nothing. **A clause is never inherited from
whatever clause preceded it** - an inherited number is a citation that resolves
to the wrong place, which is worse than one that says it does not know.
`test_a_clause_is_never_inherited_from_the_preceding_chunk` holds that line.

## 29. Atomic requirements

`standard_requirements` had never been written to. It is now filled by
`POST /api/standards/{id}/requirements/extract` (admin).

Every row carries clause, page, `requirement_text`, `source_text` (the verbatim
span), **`chunk_id`**, `extraction_method` and `confidence`.

### No requirement without a resolving citation

`create_requirement` REFUSES a row on three separate grounds, and each is a
different failure:

1. **the chunk does not exist** - the citation resolves to nothing;
2. **the chunk belongs to another document** - the citation opens something
   real and wrong, which is the worst of the three;
3. **the page is outside the pages the chunk spans** - the citation opens the
   right document at the wrong place.

The check is in code rather than in the schema because `chunk_id` was added by
`ALTER`, and **SQLite cannot add a column with a foreign key to an existing
table**. A freshly created database therefore has the constraint and a migrated
one does not; the code check holds on both. That asymmetry is stated in the
schema comment rather than left for someone to discover.

### A guess stays labelled a guess

Every extracted row is written `extraction_method='extracted'` with
`confirmed_by` NULL. Phase 3A never confirms anything.

`confidence` is **a heuristic and is labelled as one** in the schema, the
contract and the UI. It is not a probability and nothing treats it as one; its
only job is to decide whether a row is presented as a requirement or as one
awaiting verification (`VERIFICATION_THRESHOLD = 0.75`). The dominant term is
whether the clause could be identified at all.

### What is not a requirement

- **`should` is not recorded.** It is a recommendation, and recording it would
  manufacture non-compliance against advice. `M33` adds it back and the test
  fails.
- **`shall not` IS recorded**, categorised as a prohibition: violating it is a
  real finding.
- A sentence under five words is a table cell or a heading that happened to
  contain "shall".
- A chunk with `retrievable = 0` is not read at all: a requirement citing a
  passage no answer can reach would be a citation into a hole.

### Re-extraction

`extract_requirements` replaces the unconfirmed rows for that standard, so
running it twice does not double anything - and **never deletes a confirmed
row**, so once 3B lets an engineer confirm one, re-extraction cannot silently
discard their decision. `M34` removes that clause and the test fails.

## 30. Revision and effective-date management

The columns existed from Phase 1; the logic did not.

**A superseded standard is excluded from SELECTION and stays fully READABLE and
CITABLE.** Those are different questions and this is the one place the rule
lives (`selectable_standard_ids`). An engineer must still be able to open the
revision a submittal was reviewed against last year; what must not happen is a
new review quietly using it. The test asserts both halves, including that a
superseded standard's requirements still resolve.

`supersede()` is **audited** (`audit_events`, `resource_type='standard'`), and
refuses three things: superseding a document by itself, naming a superseding
document the caller cannot read (otherwise a caller learns a document exists by
pointing at it), and acting on a document with no classification row.

Revision history groups by `document_number` rather than by walking a
`superseded_by` chain: a chain breaks the moment one link is missing, and a
missing link is the normal state while a library is being populated.

## 31. The Standards Library screen

`frontend/src/views/StandardsView.tsx`, wired into the nav between Documents
and Analysis Hub.

List: standard number, title, revision, effective date, active/superseded,
discipline, requirement count, requirements awaiting verification.
Detail tabs: **Original Document, Requirements, Revision History, Processing
Details.** There is no Applicability tab - that is 3B, and an empty tab reads as
a broken feature rather than an unbuilt one. A test asserts the tab strip is
exactly those four.

What the screen refuses to say:

- A standard with nothing extracted says **"No requirements extracted yet"**,
  never "0 requirements", which reads as *this standard requires nothing*.
- A requirement whose clause could not be identified renders **"Clause not
  identified"**, never a guessed number.
- An extracted row is labelled **"Extracted, not confirmed"**.
- A row whose chunk has gone is labelled **"Citation no longer resolves"**
  rather than being silently dropped.
- Null renders as nothing.

## 32. Permissions and audit

Every read path takes `allowed_document_ids` **keyword-only with no default**
and filters **in the query**. Seven call sites are covered by a parametrised
test that each raises `TypeError` when the scope is omitted.

`list_standards` ANDs the role with the grants, so the library is always a
subset of what the caller already holds - **the role is a classification, not a
grant** (CLAUDE.md rule 5).

`extract_requirements` reads chunks under the caller's grants too: extraction
from a document the caller cannot read reads **zero chunks** and writes nothing.

Audited: `standard.requirements_extracted`, `standard.superseded`,
`standard.supersession_cleared`. Detail carries ids and counts only - never
requirement text, never a document title. The audit table is the one most
likely to be exported.

## 33. Explicitly NOT built, and the table was not half-extended

No `requirement_type`, `operator`, `value`, `unit`, `condition` or `exceptions`
columns were added. **Half a numeric limit is worse than none**: a row carrying
`value: 90` with no operator reads as a limit and is not one. 3B will `ALTER`
the table.

**`confirmed_by` and `confirmed_at` already exist from Phase 1, so 3B's
verification queue has its storage waiting.** `needs_verification` is already
computed and already surfaced in the API and the UI; 3B needs the write path,
not the schema.

Also not built: conditions, exceptions, applicability tags,
conflicting-standard handling, engineer corrections, datasheet extraction,
applicability selection, AI comparison, CRS export.

## 34. Mutations - 38/38, after one that was NOT detected

| # | Mutation | Runner |
|---|---|---|
| M27 | Write a requirement whose citation does not resolve | pytest |
| M28 | Stop lowering confidence for an unidentified clause | pytest |
| M29 | Keep selecting a superseded standard | pytest |
| M30 | Drop the scope filter from the library list | pytest |
| M31 | Drop the scope filter from the requirements read | pytest |
| M32 | Stop auditing the supersede action | pytest |
| M33 | Record recommendations (`should`) as requirements | pytest |
| M34 | Let re-extraction delete a confirmed requirement | pytest |
| M35 | Render "0 requirements" instead of "none extracted yet" | vitest |
| M36 | Guess a clause number when none was identified | vitest |
| M37 | Stop labelling an extracted requirement as unconfirmed | vitest |
| M38 | Show the supersede control to a non-admin | vitest |

### M38 was NOT DETECTED, and the test was vacuous

Reported loudly rather than quietly fixed.

The test did
`await waitFor(() => expect(queryByLabelText("Superseded by")).toBeNull())`.
`waitFor` succeeds on its FIRST tick, and on that tick the tab is still a
spinner - nothing is on screen to find. So it asserted that a control had not
rendered **yet**, not that it never would, and it passed with the permission
check deleted.

The fix is a positive assertion first: wait for the revision list to be on
screen, *then* assert the control is absent. That is the same lesson as the
phase 1 migration tests (instance 6 in the honesty audit) in a new costume -
**a check that runs before the thing it judges can exist will always pass.**

### M32 was rewritten before it counted

Its first version replaced the audit call with a call to a function that does
not exist, which fails the test with a `NameError` - the right verdict for the
wrong reason, and indistinguishable from a real detection. It now disables the
audit without raising, so the mutation reproduces the DEFECT: the action
happens and no record is written. This is the second time this exact mistake
has been made in this harness; it is recorded in the honesty audit.

## 35. Verification, measured

Backend, `python -m pytest -q` in `backend/`:

| | passed | skipped | deselected | xfailed | wall |
|---|---|---|---|---|---|
| Baseline | 1661 | 27 | 1 | 17 | 552.12s |
| **After 3A** | **1695** | 27 | 1 | 17 | 535.87s |
| Delta | **+34** | 0 | 0 | 0 | |

+34 is exactly `tests/test_standards_library.py`.

Frontend, measured the only way that works on this suite - **in isolation**:

| Measurement | Result |
|---|---|
| Files this phase touched or added, isolated | **70 passed, 0 failed** |
| The 4 known-bad files, isolated | **59 failed, 7 passed** - unchanged |
| New tests | **14** (`StandardsView.test.tsx`) |
| Full parallel run | 610 total (596 + 14), 62 failed |
| The 3 failures above the stable 59, isolated | **46 passed, 0 failed** - flaky |

The nav entry added to `Shell.tsx` and `routing.ts` did **not** change the
known-bad set: it is still exactly 59, the same four files, before and after.
That mattered enough to check on its own, because `glossary.test.ts` and
`Shell.test.tsx` assert UI terminology and a new nav label is exactly the kind
of change that would break them.

| Check | Result |
|---|---|
| Mutations | **38/38 detected** |
| `npm run build` | passes |
| `git diff --check` | clean |

## 36. Known limitations - 3A

1. **Requirement extraction is a regex over mandatory modals.** It finds
   sentences containing `shall`, `must`, `is/are required to`, `is/are to be`.
   It does not understand them. Everything it writes is labelled `extracted`
   and unconfirmed for exactly that reason.
2. **`requirement_text` and `source_text` are identical in this phase.** They
   are separate columns because 3B will normalise one and must not lose the
   other; today one is a copy of the other and the API says so.
3. **Clause detection is only as good as `chunks.section`.** A standard whose
   headings the chunker could not validate produces requirements with null
   clauses - correctly marked low-confidence, but a whole document of them
   means the chunker did not recognise that document's numbering. The count of
   awaiting-verification rows is the signal.
4. **No requirement is extracted from a table.** Chunk kind is not consulted,
   and a requirement stated only in a table cell is not found. Many
   specification limits live in tables, so this is a real gap and 3B's numeric
   limits work will meet it.
5. **Nothing consumes `selectable_standard_ids` yet.** It is written and tested
   here because the supersession rule belongs with the data; 3B is what asks.
6. **The extraction is synchronous.** A large standard blocks the request. It
   does not go through the background job mechanism, which master-plan
   section 26 asks for on long-running work.
7. **No referenced-standard detection**, which section 9 lists. It needs the
   cross-reference parsing that 3B's applicability work brings.
8. **The 59 pre-existing frontend failures are untouched**, per instruction.

---

# Phase 3B (structured requirements)

Table extraction, numeric limits and units, conditions and exceptions,
applicability tags, conflict reporting, the verification queue, and moving
extraction onto the existing background worker.

## 37. Table extraction, and what measuring it actually showed

This was built first because it is load-bearing, and because a requirement set
with the sentences and none of the tables looks complete while missing the
numbers an engineer checks against.

### The two prior-art claims were both correct

**`chunks.kind` is populated, not defaulting.** Verified before anything was
built on it - on the live database: 6,349 `prose`, **134 `table`**, 47 `toc`,
28 `index`, 17 `frontmatter`, 5 `references`. So no table is re-found in a PDF;
`WHERE kind = 'table'` says which chunks are tables and on which pages.

**`claims.py` does the unit work**, and no second unit table was written.
`normalise`, `Measurement`, `parse_value`, `parse_comparator`, `unit_dimension`
and `UnknownUnit` are used as they stand - including its deliberate refusal to
convert Fahrenheit.

### What could NOT be reused: the chunk text

Extraction flattens a table to one cell per line with the column structure
already destroyed. Real example, `civil-Design-and-Construction.pdf` page 59:

```
1252\n562\nof abutment\n0\n0\n0\n...\nStrength I\n1565\n758\n...\nSenvice 1\n...
```

Which number belongs to which column is not in that string, and the
OCR-damaged labels beside it ("Senvice", "Brioge") make a positional guess
worse than useless. So the chunk decides WHERE a table is and the stored PDF is
re-read for that page to recover WHAT SHAPE it has. That is not a second table
detector: nothing here decides whether a region is a table, and a page the
chunker never called a table is never opened.

### The measured parse rate, corrected twice

| Measurement | Result |
|---|---|
| Pages holding table chunks | 98 |
| `find_tables()` returns something | 33 (34%) |
| ...after minimum rows/columns | 29 (30%) |
| ...after the fragmentation gate | 25 |
| **...after the column-count gate** | **21 (21.4%)** |

**The first two numbers were wrong and are retracted.** "33 of 98" counted
shapes without reading them. Reading them showed things like

```
['DE', 'F', 'I', 'N', 'IT', 'I', 'O', 'N']      (51 columns)
['T', 'H', 'E', 'O', 'R', 'E']
```

which are the words DEFINITION and THEOREM cut into columns by the white space
between their letters. A scanned page has no ruling lines, so the detector
latches onto letter spacing and returns a grid of fragments. Accepting those
would have put "F" and "IT" into a requirement as a field name and a value.

Two gates were added, both chosen after reading the failures rather than before:
a cell-length ratio, and a **25-column ceiling** - no engineering table has
fifty columns, and both fragmentation cases had 46 and 51.

**What survives the gates is genuine.** From the live corpus:

```
['Pile Use Category', 'Southern Pine Creosote (pcf)', 'Douglas Fir Creosote (pcf)', ...]
['Foundation',        '12',                           '17', ...]
['Marine (Saltwater) N. of Delaware', '16',           '16', ...]
```

Row labels, column headers carrying their unit in parentheses, numeric cells.
That is the shape the extractor reads.

### SAES-A-105 IS NOT IN THIS REPOSITORY

The prompt asked for proof against Tables 1 to 5 of SAES-A-105. **That document
is not in the corpus** - `SELECT COUNT(*) ... WHERE filename LIKE '%SAES%'`
returns 0 - and nothing here was proven against it. No standard in this corpus
has machine-readable tables at all; the 21 that parse are from a civil
engineering text and a mathematics textbook.

So the parser is proven two ways, and neither is "we ran it on SAES-A-105":

1. **against real corpus tables** (the creosote retention table above), which
   is where the gates and the header-unit rule were derived from;
2. **against a PDF with real ruled geometry drawn in the test**, because the
   corpus contains no standard whose tables a parser can see, and a fixture
   that draws its own lines is the only way to test the accepting path
   end to end.

The 78.6% that cannot be parsed are reported as UNPARSED with a reason and drag
`parsed_fraction` down. That figure is the honest measure of how much of a
standard's tabular content this system actually read.

## 38. Numeric limits and units - deterministic, never the model

`requirements_3b.py` parses limits, conditions and exceptions with regular
expressions and hands every number to `claims.normalise`. **Nothing in this
phase calls Ollama** (master plan section 14): a limit that depends on a
language model is a limit nobody can reproduce.

### An unknown unit is None, never 0

Measured, and it matters more than it might look:

| Unit | Normalised |
|---|---|
| `mm` | 12 -> **12000.0 um** |
| `MPa`, `degC`, `bar`, `%` | converted |
| **`dB(A)`** | **None** |
| **`pcf`** | **None** |
| `F` | None - Fahrenheit is refused by design |

**The master plan's own worked case is in the None column.** `dB(A)` is not in
`claims.py`'s table, so a 90 dB(A) limit is extracted with
`raw_value='90'`, `raw_unit='dB(A)'` and `value=None`. That is the honesty rule
working exactly as specified: the value is still extracted, still cited, still
quotable, and simply cannot be compared across unit systems until someone adds
the unit deliberately. A 0 there would read as a limit of zero - a real and
very different requirement.

### Nothing is invented for text the parser did not understand

An obligation with no recognisable limit is recorded as `statement`, which is a
true description of it, rather than a `numeric_limit` carrying a null value - a
shape that reads as a limit nobody bothered to record.

## 39. Conditions and exceptions - the PSV case

The worked case, end to end:

> The noise level shall not exceed 90 dB(A), except for pressure relief valves,
> which shall not exceed 115 dB(A).

yields a general limit `<= 90 dB(A)` and

```json
[{"applies_to": "pressure relief valves", "operator": "<=", "raw_value": "115", "raw_unit": "dB(A)"}]
```

**An exception that is dropped turns a compliant PSV into a false finding**,
which is why M42 exists and why the exception carries its own limit rather than
just a note.

Conditions are parsed conservatively and stop at the comma: "For new equipment,
the noise level shall not exceed..." conditions on `new equipment`, not on
`new equipment, the noise level`. A wrong condition NARROWS a requirement and
silently excuses a real deviation - the opposite failure from a wrong limit,
and much harder to notice.

## 40. Conflicts - surfaced, never resolved

Two standards limiting the same field differently is reported as a conflict
with **both sides returned and neither marked the winner**. There is no
precedence rule and there must not be one: seniority between two company
standards is not something this system can know.

Two deliberate silences:
- the same limit in two standards is agreement, not conflict;
- **values that cannot be compared are not called a conflict.** When either
  side has a null normalised value - an unknown unit - the pair is skipped.
  Two numbers this system cannot compare are not evidence of disagreement, and
  claiming one would invent a finding.

## 41. Verification queue and engineer corrections

`confirm`, `edit`, `reject`. **A correction sets `extraction_method` to
'human'** - after it the row is a person's statement and nothing downstream may
present it as extracted. Confirming sets `confirmed_by`/`confirmed_at`, which
`needs_verification` already read from phase 1, so a confirmed row leaves the
queue whatever its confidence was.

**Reject deletes the row and keeps the audit.** An extraction that is wrong is
not evidence of anything, and leaving it flagged would put it in front of the
next reader to judge again. What survives is the record that somebody looked
and said no.

All three are audited. The queue is filtered in the query, which matters
because it takes a LIMIT.

## 42. Background extraction - one worker, lowest priority

Extraction was synchronous and would block a request on a large standard.
It now queues onto the **existing** `jobs` table with a new stage
(`extract_requirements`) - master plan section 25, "do not create a new table
if an existing table can be safely extended" - and is drained by the
**existing** `IngestionWorker`, only when no document needs work.

That is what section 24's "one ingestion/review worker" and its priority list,
which puts background standard reprocessing LAST, mean on a single worker.
`test_no_second_worker_was_added` asserts the module still constructs exactly
one thread.

The worker has no caller and therefore no scope, so it reads every document id
and passes it explicitly - the same decision `access.unrestricted_scope()`
makes, named at the point it is taken rather than defaulted into by omitting an
argument.

## 43. Mutations - 48/48, after one NOT detected and one refused

| # | Mutation | Detected by |
|---|---|---|
| M39 | Stop reading the unit out of a table header | real-table test |
| M40 | Coerce an unknown unit to 0 | unknown-unit test |
| M41 | Report an unparsed table as parsed | completeness test |
| M42 | Drop the exception clause | PSV test |
| M43 | Silently resolve a conflict | conflict test |
| M44 | Leave `extraction_method` as 'extracted' after a correction | queue test |
| M45 | Drop the scope filter from the verification queue | permission test |
| M46 | Make queuing extract synchronously | job test |
| M47 | Accept character fragmentation as a table | fragmentation test |
| M48 | Record "see 5.2" as the number 5.2 | cell-value test |

### M47 was NOT DETECTED, and the test was a unit test pretending to be one

`test_character_fragmentation_is_not_accepted_as_a_table` called
`tables._is_fragmented(...)` **directly**. That proves the predicate works and
nothing whatever about whether the pipeline uses it - M47 deleted the call site
in `parse_page_tables` and the test passed happily.

It now builds a PDF whose ruled cells contain single letters, runs it through
`parse_document_tables`, and asserts the result is UNPARSED - plus a genuine
table on the same path that IS accepted, so the gate is not simply refusing
everything.

This is a third distinct species of vacuous test in this project's record:
entry 6 tested a migration against a table that was never old, entry 11
asserted an absence before the screen had loaded, and this one tested a helper
instead of the behaviour that depends on it. Recorded in the honesty audit.

### M31's anchor became ambiguous, and the harness refused to guess

The new `verification_queue` opens with the same `_scope_clause` line as
`list_requirements`, so M31 matched twice and the harness reported ERROR rather
than mutating an arbitrary one. That is the safety property working for the
second time; the anchor was disambiguated by the SELECT that follows it.

## 44. A defect my own test found

`claims.parse_value` deliberately tolerates a leading prefix so that `<= 90`
and `max 90` yield 90 - correct for a sentence. Applied to a TABLE CELL it read
`see 5.2`, a cross-reference to clause 5.2, as **the number 5.2**, and would
have recorded it as a limit. `requirements_3b.cell_value` now requires a cell
to be a number in its entirety (a comparator symbol and a footnote marker are
allowed; words are not). M48 covers it.

## 45. A regression I introduced, caught by an existing test

The first full run after 3B came back **1 failed, 1727 passed**. The failure
was `test_no_internal_leaks.py::test_every_endpoint_declares_a_typed_success_
response`, and it was mine: three new routes were declared
`response_model=dict`.

That test is right to fail them. An `additionalProperties: true` response body
is a contract that promises nothing - a client generator has nothing to
generate from it, and the "typed result, never a thrown string" rule the API
client is built on stops at the first untyped route.

Fixed with two real models, `ExtractionJob` and `RequirementDecisionResult`,
rather than by relaxing the test. `response_model=dict` now appears zero times
in `main.py`.

Worth stating plainly because it is the counter-example to this phase's own
mutation work: **48 of 48 mutations passed while a real regression sat in the
same commit.** Mutation testing proves a test observes its feature; it says
nothing about features nobody wrote a mutation for. The suite caught this one,
which is what a suite is for.

## 46. Verification, measured

Backend, `python -m pytest -q` in `backend/`:

| | passed | skipped | deselected | xfailed |
|---|---|---|---|---|
| Baseline | 1695 | 27 | 1 | 17 |
| **After 3B** | **1728** | 27 | 1 | 17 |
| Delta | **+33** | 0 | 0 | 0 |

+33 is exactly `tests/test_standards_3b.py`.

| Check | Result |
|---|---|
| Mutations | **48/48 detected** |
| `npm run build` | passes |
| Frontend, touched files isolated | 67 passed, 0 failed |
| Frontend, the 4 known-bad files isolated | 59 failed - unchanged |
| CI lint gate | passes |
| `git diff --check` | clean |

**3B added no frontend code.** The Standards Library screen still shows the 3A
fields; the limits, exceptions, conflicts and queue are API-only. That is a
real gap and it is listed below rather than implied away.

## 47. Known limitations - 3B

1. **78.6% of this corpus's table chunks cannot be parsed**, because they are
   scanned pages with no ruling lines. Reported honestly as unparsed; it is
   not fixable without OCR-level table reconstruction, which is not in any
   phase yet.
2. **`dB(A)` and `pcf` do not normalise.** They are not in `claims.py`'s table.
   Adding them is a deliberate act - a unit table entry is a safety decision,
   which is why Fahrenheit is absent - and it was not taken unilaterally here.
   Until then, noise limits cannot be compared numerically across documents.
3. **No 3B UI.** Conflicts, the verification queue, limits and exceptions are
   reachable only through the API.
4. **The limit parser is regular expressions over English.** It handles the
   comparator phrasings listed in `_OPERATOR` and will miss others. Everything
   it writes is `extracted` and unconfirmed.
5. **Ranges are not parsed.** "between 10 and 20 mm" yields at most one bound.
   `claims._interval` exists and was not wired in; that is honest scope, not an
   oversight to discover later.
6. **A table value is recorded at confidence 0.5**, below the verification
   threshold, because a table cell carries no obligation word. Every extracted
   table value therefore lands in the queue for a human - deliberate, but it
   means a large table produces a large queue.
7. **Multi-row headers and merged cells are not handled.** The first row is
   taken as the header.
8. **Conflict detection compares only normalised values**, so the units that
   matter most for noise are exactly the ones it cannot compare (see 2).
9. **SAES-A-105 was never tested against**, because it is not in the
   repository. See section 37.

---

# Phase 4 (datasheet intelligence)

## 48. Step zero: the measurement, before any normalisation was written

The files were found outside the repository, in `~/Downloads`, and all three
are NATIVE TEXT (not scanned):

| File | Pages | What it is |
|---|---|---|
| `EF1975-DAS-M-03.pdf` | 7 | KOC centrifugal pump datasheet (recycle brine pumps) |
| `EF1975-DAS-I-06.pdf` | 5 | KOC pressure safety valve datasheet |
| `SAES-A-105.pdf` | 14 | Saudi Aramco standard |

**`SAES-A-105.pdf` exists after all.** Phase 3B reported it absent from the
corpus, which was true of the corpus and is still true - it has never been
ingested - but the file is on this machine. That correction is recorded in the
honesty audit.

### What `tables.py` recovers, and why the first number was a trap

| File | Pages with a parsed table | Rate |
|---|---|---|
| `EF1975-DAS-M-03.pdf` | 7 of 7 | **100%** |
| `EF1975-DAS-I-06.pdf` | 5 of 5 | **100%** |
| `SAES-A-105.pdf` | 3 of 14 | 21% |

**The I-06 figure is worthless, and reading the content is what showed it.**
Every one of those five "tables" is the two-row title block:

```
['KUWAIT OIL COMPANY', 'DATA SHEET FOR PRESSURE SAFETY VALVES (PSVs)', 'DOCUMENT NO. EF1975-DAS-I-06']
['PROJECT NO. EF/1975', '', 'Sheet 2 of 6', 'Rev. 1']
```

Not one PSV value is in it. Reporting "100% of pages parsed" for a datasheet
whose every value was missed is exactly honesty-audit entry 14 repeating, and
the only reason it did not happen is that the content was read before the rate
was believed.

M-03 is the opposite: the grid is real.

```
['VAPOR PRESSURE:', 'bar a (psia)', '0.42 (6.09)']
['SPECIFIC GRAVITY:', '0.974 @ 170 OF']
```

### The path taken, and why

**Both paths, chosen per page, neither a fallback for the other.**

I-06's data is in TEXT BLOCKS with a numbered label-value shape - master plan
section 10's "preserve text blocks and coordinates":

```
5 | Design/Operating pressure | 23.5 / 9 barg (Note - 3) | 46 | Bonnet / Yoke | ...
8 | Set pressure             | 340 psig (By Contractor, as per Code) | 49 | ...
```

So `datasheets.py` runs the grid path where a grid exists and
coordinate-ordered label-value pairing over text blocks where it does not.
**A form is not a table**, and forcing it through a table parser would have
produced nothing while reporting success. `tables.py` is imported, not
duplicated.

## 49. First code change: same-unit comparison, so phase 5 can evaluate its own flagship case

`claims.py` maps `"db": None` and that mapping is CORRECT - a decibel is a
logarithmic ratio with no dimension to convert through. But the master plan is
written around a 90 dB(A) limit with a 115 dB(A) relief-valve exception, and as
built neither was comparable to anything. Phase 5 could not have evaluated the
one requirement the plan is about.

`_compatible` now compares directly when **both sides carry the identical unit
spelling**, converting nothing:

| Comparison | Result |
|---|---|
| 95 dB(A) vs `<= 90 dB(A)` | **False** - breach detected |
| 85 dB(A) vs `<= 90 dB(A)` | **True** - compliant |
| 115 dB(A) vs `<= 90 dB(A)` | **False** - the PSV exception's own limit works |
| dB(A) vs pcf | **None** - undecidable, unchanged |
| dB(A) vs dB | **not the same unit** - A-weighting is part of the meaning |
| `normalise_strict("90","dB(A)")` | still raises `UnknownUnit` |
| `normalise_strict("90","F")` | still raises - Fahrenheit refused by design |
| 12 mm | still 12000 um |

The ScaleMismatch discipline is intact: what was relaxed is only the case where
there is no mismatch to speak of. Mutations M53 and M54 prove both directions.

## 50. The two schema decisions, made rather than inherited

**1. `submittal_facts.chunk_id` added** (PRAGMA + conditional ALTER), same
reasoning as 3A: a fact without a resolving chunk is an assertion.
`create_fact` refuses three ways - no chunk, a chunk of another document, a
page outside the chunk.

**2. `review_run_id` was NOT NULL, and is now NULLABLE. Facts are per
DOCUMENT and reused across runs.**

Phase 1 made a fact unable to exist outside a run, which forces a full
re-extraction of a datasheet every time a review starts. Master plan section 24
asks the opposite on a 16 GB machine: "reuse cached extraction and embeddings
for duplicate documents". A datasheet's facts are a property of the datasheet,
not of the review that happened to read it first.

This needed a TABLE REBUILD, because SQLite cannot drop a NOT NULL. It is safe
here and nowhere else: the table has never been written to in any build, which
the migration CHECKS rather than assumes - if a row exists the rebuild is
skipped and the old shape is kept. Data is never dropped to satisfy a schema
preference.

## 51. Extraction quality, measured on the real sheets - and it is limited

| | facts | blanks | pages | unparsed | fraction |
|---|---|---|---|---|---|
| `EF1975-DAS-I-06.pdf` | 37 | 25 | 5 | 1 | 0.80 |
| `EF1975-DAS-M-03.pdf` | 9 | 8 | 7 | 4 | 0.43 |

What it gets right is genuinely right:

```
Set pressure                  | 340 psig (By Contractor, as per Code) | BLANK "By Contractor"
Density at relieving temper.  | 23.55 Kg/m3                           | 23.55  Kg/m3
Compressibility factor        | 0.892                                 | 0.892
Max. allow. working pressure  | 23.5 barg By Contractor / Vendor      | BLANK
MANUFACTURER                  | *___                                  | BLANK "placeholder"
```

**RECALL IS POOR AND IS NOT DISGUISED.** The PSV sheet has roughly sixty
numbered rows and 37 facts were recovered; the pump sheet yielded 9 from seven
pages, with four pages reported unparsed. `parsed_fraction` carries that, and
`unparsed` names the pages and the reason. This is the "if extraction quality
is insufficient, report the affected pages and lower completeness" case, and it
is reported rather than smoothed over.

### Two defects found by running it on the real files

**1. Measurements invented from prose.** `"2nd Stage Desalter"` parsed as value
2 with unit `nd`; `"10-05-498 & 556-05-513"`, a P&ID reference, as the value 10.
Using the unit table as the discriminator then DROPPED `"9970 Kg/hr"`, a real
value whose compound unit is simply not in `claims`. The rule that works is
about what FOLLOWS: a measurement is the whole cell give or take a
parenthetical dual unit, and words after the number mean the cell was a
sentence that happened to start with a digit.

**2. 427 phantom blank fields out of 439.** The first end-to-end run produced
rows whose "label" was `0.01cP By Contractor` and whose value was empty - every
stray text block became a required field somebody had failed to fill in. Two
guards fixed it, and both are measured rather than theoretical:

- `is_field_label` - a label must contain real words, must not itself parse as
  a measurement, and must not be mostly digits;
- **an empty adjacent cell is not evidence of anything.** A fact is recorded
  only where the sheet says something: a value that parses, or a value the
  sheet EXPLICITLY marks as the contractor's ("By Contractor", "TBA", a drawn
  rule of underscores). An empty cell beside a label is a pairing artefact of a
  two-column form, and recording it manufactures findings against a vendor who
  was never asked.

After both: 37 real facts instead of 439 invented ones.

## 52. Mutations - 56/56, after one NOT detected

| # | Mutation |
|---|---|
| M49 | Stop reading the unit off a datasheet value |
| M50 | Treat a "By Contractor" field as a filled value |
| M51 | Report a page that yielded nothing as parsed |
| M52 | Stop detecting referenced standards |
| M53 | Refuse same-unit comparison again, re-blocking dB(A) |
| M54 | Compare across different units, breaking ScaleMismatch |
| M55 | Drop the scope filter from the facts read |
| M56 | Promote a value into a field label |

**M56 was NOT DETECTED**, and the reason is worth keeping. The prose test that
was supposed to cover it is actually defended by the FACT GATE, not by the
label guard: prose with no number and no blank marker is dropped either way. So
deleting `is_field_label` changed nothing that test could see.

What the label guard actually prevents is **two value cells side by side** -
the first becomes the "label", the second parses, and a row appears whose field
name is a number. A test for that case now exists. This is the same lesson as
entries 6, 11 and 13 in a fourth costume: **the test was not standing where
the feature could fail it** - it was standing where a different feature was
holding the line.

## 53. Verification, measured

All numbers below were taken from the same tree state, at commit
``02e0acb` (code) / `12d9455` (tests and harness)`.

| | passed | skipped | deselected | xfailed |
|---|---|---|---|---|
| Baseline | 1728 | 27 | 1 | 17 |
| **After Phase 4** | ****1749**** | 27 | 1 | 17 |

| Check | Result |
|---|---|
| Mutations | **56/56 detected** |
| `npm run build` | passes |
| Frontend known-bad set, isolated | 59 failed - unchanged (Phase 4 touched no frontend) |
| CI lint gate | passes |
| `git diff --check` | clean |

## 54. Known limitations - Phase 4

1. **Recall is low.** 37 facts from a ~60-row PSV sheet, 9 from a 7-page pump
   sheet. Precision is good; coverage is not. The completeness figure and the
   unparsed page list are the honest signal, and improving recall is the next
   real piece of work.
2. **No classification of document or equipment type.** Section 10 asks for it;
   it is not built. The role already exists on the document from Phase 2.
3. **Ranges are not parsed.** `-3 to 121OC` and `23.5 / 9 barg` yield nothing -
   the same gap 3B recorded, now hit on real data where ranges are common.
4. **No scanned-datasheet path.** All three files are native text, so the OCR
   route was never exercised. A scanned datasheet would fall to the text-block
   path with no text and be reported unparsed - honest, but not useful.
5. **Multi-page tables are not stitched.** Each page is read independently, so
   a table continuing across a page break yields two partial readings.
6. **`Kg/hr`, `Kg/m3`, `psig`, `barg`, `dB(A)` and `pcf` do not normalise.**
   Values and spellings are preserved; comparison across unit systems is not
   available for them. Same-unit comparison now works for all of them.
7. **The two real datasheets are NOT in the repository and no test depends on
   them** (CLAUDE.md rule 3). The test fixtures build their own PDFs; the
   measurements above were taken by hand against the real files and are
   recorded here rather than automated.
8. **`SAES-A-105.pdf` was measured but not ingested**, so the corpus still has
   no machine-readable engineering standard.


---

# Phase 5A (applicability selection)

Which standards apply to a submittal, why, and what is missing. Nothing about
whether the submittal complies - that is 5B, and keeping the two apart is what
stops a selection heuristic becoming a compliance verdict.

## 55. The real run, and it is the phase working correctly

Both real KOC datasheets, with `SAES-A-105` loaded as the only library
standard:

| | KOC pump (M-03) | KOC PSV (I-06) |
|---|---|---|
| Library size | 1 | 1 |
| Standards the sheet cites | 15 | 8 |
| **Selected** | 1 | 1 |
| **Missing references** | **15** | **8** |
| `reference_coverage` | **0.0** | **0.0** |
| `extraction_coverage` | 0.429 | 0.80 |
| **completeness** | **0.0** | **0.0** |

Missing on the pump sheet: `API 610`, `API 670`, `ISO 1940`, `ISO 9906`,
`ISO 10438`, `KOC-MP-008`, `ASTM A995`, `ASTM A276`, `EN 13463` and six more.
On the PSV sheet: `API RP 520 Pt-1`, `KOC-MP-027`, `NACE MR-0175`,
`ISO 15156`, `API RP 578`, `ASTM A216`, `ASTM A193`, `ASTM B633`.

**Every standard these datasheets cite is absent from the library, and the
system says so.** That is the correct answer, not a failure.

The single selected row is `SAES-A-105`, chosen by **discipline match** and
labelled as exactly that. It has nothing to do with a KOC pump - and
critically, **it does not mark any citation satisfied**. `reference_coverage`
stays 0.0 with it on the list. That is the whole phase in one line: something
was found, and finding it changed nothing about what is missing.

## 56. The guard this phase exists for

Master plan section 23: vector similarity "must never be the sole basis for
declaring compliance". Section 11 puts explicit references first and semantic
retrieval fifth. The specific way that goes wrong:

> A datasheet cites API 610. API 610 is not in the library. Retrieval finds a
> vaguely related pump document. It lands on the list as "applicable". The
> missing standard disappears, and a review that could not possibly have been
> performed reads as complete.

So the rule implemented is stronger than "prefer references":

**A SEMANTICALLY RETRIEVED STANDARD MAY NEVER SUBSTITUTE FOR AN EXPLICITLY
REFERENCED ONE THAT IS ABSENT.**

`_semantic_cannot_cover_a_missing_reference` is a function of its own, doing
nothing but returning the missing list unchanged and marking every semantic
row `satisfies_reference: False`, so removing it is a visible act rather than
an edited condition. Mutation M59 removes it and the test fails. The test
asserts the retrieved standard WAS selected before asserting the citation is
still missing, otherwise it would pass on a run where nothing was found at
all - species four.

## 57. Selection, in section 11's priority order

| Rule | `selection_method` | Confidence ceiling |
|---|---|---|
| 1. Named in the datasheet | `referenced` | 0.9 |
| 2. Equipment type | `equipment_type` | 0.7 |
| 3. Discipline | `discipline` | 0.5 |
| 4. Service / conditions | `service` | 0.5 |
| 5. Semantically retrieved | `semantic` | 0.4 |
| 6. Contract / project | `project` | 0.4 |
| An engineer's decision | `manual` | 0.9 |

**The method is recorded per row.** `record_selection` REFUSES a row with no
reason, an unknown method, or an exclusion with no exclusion reason.

**Confidence is never "high"** (CLAUDE.md rule 4). Each method has a ceiling
and the value is clamped to it. Even an explicit citation stops at 0.9.

When two rules pick the same standard the STRONGER reason wins. A null
attribute on either side is not a match - "neither has a discipline recorded"
is not evidence they belong together.

## 58. What else is recorded

- **Standards considered and EXCLUDED**, each with its `exclusion_reason`.
- **Missing references, by the identifier the datasheet used** - not a
  canonical form.
- **Completeness**, from `reference_coverage` and `extraction_coverage`,
  **multiplied, not averaged**: a review with every standard present but half
  the datasheet unread is half a review, and an average would let one good
  number hide the other. `None` when there is nothing to judge, never 0.

## 59. Permissions

Every read takes `allowed_document_ids` keyword-only with no default, and
access filters BEFORE ranking. `applicable_standards` filters twice - the
run's submittal must be readable AND each standard row is restricted to
standards the caller may read. **Reading a submittal does not grant the
standards it cites.** An override requires both documents readable and a
non-empty reason, and writes `review.applicability_override` to
`audit_events`.

## 60. Mutations - 63/63, after one that reached for a known shortcut

| # | Mutation |
|---|---|
| M57 | Stop matching standards the datasheet names |
| M58 | Silently drop a referenced standard the library lacks |
| M59 | **Let a semantic hit satisfy a missing reference** |
| M60 | Select superseded standards again |
| M61 | Stop recording standards considered and ruled out |
| M62 | Stop auditing an engineer override |
| M63 | Drop the confidence ceiling |

All seven detected on the first pass at the test level, and the 22 tests
passed first run - the first phase where that happened. **But M62's first
version reached for the `NameError` shortcut a THIRD time**: replacing the
audit call with a call to a nonexistent function, which fails for the wrong
reason. That is honesty-audit entries 10 and 12, now a third occurrence.
Corrected to disable the audit by returning early, with the reasoning written
at the mutation itself.

## 61. A production defect found by suite flakiness, and a number corrected

While verifying 5A against the full suite, three runs of one unchanged tree
gave three different results: two permission tests failed, then a clean run,
then `test_access_routes::test_two_concurrent_requests_never_share_scope`
failed alone. Different victims each run, no random-order plugin installed,
no hash-seed sensitivity (probed at seeds 0/1/2) - the signature of lock
contention, not ordering or data pollution.

**The cause: `submittal_review.ensure_schema()` - called by every read in that
module - held a conditional `DROP TABLE` / `CREATE TABLE` migrating
`submittal_facts`.** DDL on one SQLite connection blocks readers on other
connections. The concurrency test failing is what identified the mechanism.

**This was a production defect, not a test defect.** The same DDL would block
concurrent readers in the running application exactly as it did in the suite;
the first request after startup to trigger the rebuild could have stalled
whatever else was in flight.

**The fix:** the rebuild moved to `migrate_facts_to_per_document()`, called
once from `main.lifespan` beside the other startup schema calls. Two
source-assertion tests hold the shape (`test_the_upload_module_guards_the_
stored_path`'s idiom, because a timing race cannot be caught reliably by a
behavioural test):

- `test_ensure_schema_contains_no_ddl` - no `DROP TABLE`/`DROP INDEX` in
  `ensure_schema`'s body, AND the migration function still contains its DROP
  (so the test cannot pass by the migration being deleted too);
- `test_the_facts_migration_is_called_at_startup` - `main.lifespan`'s source
  actually calls it.

Two `ORDER BY created_at DESC` clauses with no tiebreaker were fixed alongside
this (`_now()` is second-granularity): `list_review_runs` and
`list_standard_requirements` now order `created_at DESC, id DESC`, matching
the pattern `review_status_for` already used.

**The retraction: "2 of 3 runs failed" was reported as an observed rate, and
it should not have been.** Whether those three runs had the machine to
themselves was never checked at the time. A later, unrelated `TaskStop` call
was found to leave its child process running past the stop - the kind of thing
that goes unnoticed exactly when nobody is looking for it - which raises the
live possibility that a similar overlap affected runs 1-3 undetected.
**If a second suite was alive during any of those three runs, the observed
rate is inflated, and inflated in the one direction that looks like the bug**:
DDL contention manufactures the same symptom the diagnosis was hunting for.

This does not weaken the diagnosis - the mechanism is real independent of what
else was running, and the concurrency test failing is consistent either way -
but **2-of-3 must be read as an uncontrolled observation, never as a measured
baseline**. Recorded as honesty-audit entry 18.

**Ten runs were then taken with the machine verified single-runner
throughout** (process count checked before starting and mid-run):
**10 of 10 clean - 1773 passed, 0 failed, every run**, wall times 7-9 minutes
each. Read against the corrected denominator rather than the original
arithmetic: ten-for-ten does not retroactively validate 2-of-3 as a rate, but
it is independent evidence that whatever the true failure rate is now, it is
low enough that ten single-runner runs did not observe it once.

## 62. Verification, measured

All numbers below were taken from the tree at `01f0545` plus the changes
described in sections 55-61.

| | passed | skipped | deselected | xfailed |
|---|---|---|---|---|
| Baseline (Phase 4) | 1749 | 27 | 1 | 17 |
| **After 5A, single run** | **1773** | 27 | 1 | 17 |
| **After the DDL fix, 10 consecutive runs** | **1773 every time** | 27 | 1 | 17 |

+24 from baseline is the 22 new applicability tests plus the 2 new source
assertions.

| Check | Result |
|---|---|
| Mutations | **63/63 detected**, re-verified after the DDL fix |
| `npm run build` | passes |
| Frontend known-bad set, isolated | 59 failed - unchanged (5A touched no frontend) |
| `python run.py` -> `GET /api/health` | 200 |
| `GET /openapi.json` | 200 |
| CI lint gate | passes |
| `git diff --check` | clean |

## 63. Known limitations - 5A

1. **Rule 5 is FTS5, not the dense index.** The dense path (`search.search`)
   exists and was not wired in; on a library of one standard it would add
   nothing measurable, and an unmeasured retrieval path is exactly what this
   phase warns against. 5B's call, once there is a library to retrieve from.
2. **The library is one document.** Every measurement above is against a
   library of size 1. Load the KOC standards and the numbers change
   completely - reporting 0.0 now is the point.
3. **No equipment-type mapping table.** Rule 2 matches on exact string
   equality; "centrifugal pump" does not match "pump".
4. **Referenced-standard matching is by identifier only.**
5. **No relevant-clause extraction.** Section 11 asks for it per standard;
   5A stores the standard and its reason, not clause-level relevance.
6. **Exclusion rows are written for the whole library on every run.** Needs a
   bound before it is realistic on a large library.
7. **No API routes.** 5A is engine and storage only.
8. **The concurrency test that surfaced the DDL bug was not itself modified.**
   `test_two_concurrent_requests_never_share_scope` already existed; it simply
   had never been exposed to a DROP TABLE in a read path before this phase's
   schema work.


---

# Phase 5B (the compliance comparison engine)

For each applicable requirement: does this submittal meet it, what is the
evidence on both sides, and what code does that add up to.

## 64. THE STANDARDS ARE NOT LOADED, so this was proven on fixtures

Checked before building anything: the live database has **zero** documents
with a `document_role`, **zero** standard requirements, **zero** submittal
facts, **zero** review runs and **zero** findings. The KOC datasheets and
`SAES-A-105.pdf` are still only in `~/Downloads`, never ingested.

So 5B was built and proven against **constructed fixtures**, and the numbers
below are fixture numbers. **No real-corpus run of the comparison engine has
happened.** When the standards are loaded, the first real run is the one that
matters, and phase 4's measured 0.43 extraction recall on the pump sheet
predicts what it will say: Manual Review Required, gated on completeness.

## 65. Section 14 is the shape of the engine

**Python decides; the model describes.**

| Deterministic, in code | The model, and only this |
|---|---|
| numeric comparison | interpreting technical wording |
| unit conversion | matching a field label to a requirement |
| required-field presence | reading a condition in prose |
| threshold evaluation | drafting the contractor-facing comment |
| review-code policy | explaining its reasoning |
| citation existence | |

**When they disagree, the deterministic result wins and the disagreement is
recorded.** `_reconcile` is the one place that happens, written as its own
function so deleting it is a visible act. Mutation M69 makes the model's
opinion win and the test fails.

Nothing in this module calls Ollama. A verdict that depends on a language
model is a verdict nobody can reproduce, and the point of a comparison engine
is that 95 against a 90 limit comes out the same way every time.

## 66. The three refusals

**1. An absence is never a failure.** A blank "By Contractor" field is
`MISSING_INFORMATION`. Phase 4 detects those blanks correctly and this engine's
job is not to undo that - manufacturing a finding against a vendor who was
never asked is the worst output this product could produce. `MISSING_INFORMATION`
is deliberately absent from `BLOCKING`, so it steers the code through
completeness rather than masquerading as a breach. Mutation M66 turns a blank
into `NON_COMPLIANT` and the test fails.

**2. No finding without both citations.** The contractor's page and the
standard's clause must each resolve to a real chunk of the right document, on a
page that chunk spans. Anything failing that is downgraded to
`NEEDS_ENGINEER_REVIEW` with the reason recorded in `unresolved_evidence` -
never dropped, never guessed into a status. A citation that opens the WRONG
document is treated as failure too: a reader who follows it sees something real
and believes it.

**3. An exception wins over its general limit.** A standard capping equipment
at 90 dB(A) with an exception allowing relief valves 115 dB(A) does not make a
108 dB(A) PSV non-compliant. The test asserts the same value IS a breach under
the general limit first, so it is standing where the exception can fail it -
without that it would pass on an engine that called everything compliant.
Matching is conservative: an unknown subject gets the general limit, because
an exception applied too eagerly EXCUSES a real breach, which is the more
dangerous direction.

## 67. A real defect the end-to-end test found

`datasheets.measure_value("95 dB(A)")` returned unit **`dB`**, not `dB(A)` -
the unit regex excluded parentheses. The comparison engine then did exactly the
right thing and REFUSED to compare `dB` against a `dB(A)` limit, because
`claims.same_unit` correctly holds that A-weighting is part of what the number
means (asserted in phase 4's own tests).

The effect: **the flagship case of the entire product was silently unevaluable
because of a character class.** Every noise comparison would have come back
`NEEDS_ENGINEER_REVIEW` with a unit-mismatch rationale, which is honest and
useless.

Fixed in `datasheets.py`: a unit may contain parentheses when it starts with a
letter. `0.42 (6.09)` is unaffected - the unit group must begin with a letter,
so a bare parenthetical is still a dual-unit remainder, not a unit.

This is the second time a phase 5 test has found a phase 4 extraction defect
(the first was prose parsed as measurements). The comparison engine is a good
test of the extractor precisely because it is the first thing to actually use
the values.

## 68. Completeness gates the review code

A review that examined nine fields and returns "Approved with Comments" is
making a claim about the two hundred and forty nobody looked at. **That is the
most dangerous output this product can produce**, because the code and the CRS
both imply coverage.

So `recommend_code` checks completeness FIRST and overrides everything:

| Condition | Recommended code |
|---|---|
| completeness below threshold | **Manual Review Required** |
| any requirement unevaluable | Manual Review Required |
| any requirement not met | Rejected / Revise and Resubmit |
| only missing information | Approved with Comments |
| everything met | Approved |

`COMPLETENESS_THRESHOLD = 0.6`, deliberately above phase 4's measured 0.43 on
the real pump datasheet: **that review would be gated, and it should be.**

Completeness is **the weakest link, not the average** - a review with every
standard present but a tenth of the sheet read is a tenth of a review, and an
average would let the good number carry the bad one (mutation M72).

It is **always reported with its denominator**: "the review examined 9 of
approximately 250 fields". `fields_estimated` is labelled an ESTIMATE, because
nobody has counted the real total and pretending to would be worse than saying
approximately.

## 69. Review codes, and who decides

Codes are **configurable** (section 15) - `recommend_code` takes a `codes`
tuple and the policy is fixed while the labels are not. Defaults: Approved,
Approved with Comments, Rejected / Revise and Resubmit, Manual Review Required.

Stored per run: the AI-recommended code and its reason, the final engineer
code, the override reason, the reviewer and the timestamp. **The AI recommends;
the engineer decides.** A final code that DIFFERS from the recommendation
requires a reason - an override with none is indistinguishable from a mistake
six months later - and one that agrees does not. Every decision writes
`review.code_recorded` to `audit_events`.

Confidence is never "high" (rule 4). The vocabulary stops at `medium`: a
deterministic comparison is the strongest thing here and is still only as good
as the extraction that fed it.

## 70. Mutations - 72/72

| # | Mutation |
|---|---|
| M64 | Stop comparing numbers, so a breach is never caught |
| M65 | **Drop the exception, failing a compliant PSV** |
| M66 | **Turn a blank By-Contractor field into NON_COMPLIANT** |
| M67 | Store a finding whose citations do not resolve |
| M68 | Guess a comparison when the units cannot be compared |
| M69 | **Let the model overrule the deterministic result** |
| M70 | **Approve a review that examined a fraction of the fields** |
| M71 | Allow a code override with no reason |
| M72 | Let completeness average instead of taking the weakest link |

All nine detected on the first run, and 35 of the 36 tests passed first time -
the one failure was the `dB(A)` extraction defect above, which is the test
doing its job.

## 71. Verification, measured

All numbers from the same tree state, at ``93359d2` (code and tests; docs follow)`.

| | passed | skipped | deselected | xfailed |
|---|---|---|---|---|
| Baseline (5A) | 1773 | 27 | 1 | 17 |
| **After 5B** | ****1809**** | 27 | 1 | 17 |

| Check | Result |
|---|---|
| Mutations | **72/72 detected** |
| `npm run build` | passes |
| Frontend known-bad set, isolated | 59 failed - unchanged (5B touched no frontend) |
| `python run.py` -> `GET /api/health` | 200 |
| `GET /openapi.json` | 200 |
| CI lint gate | passes |
| `git diff --check` | clean |

## 72. Known limitations - 5B

1. **NO REAL-CORPUS RUN.** The standards are not loaded. Everything above is
   fixtures. This is the single most important caveat in the phase.
2. **Field matching is exact-normalised only.** `_match_fact` matches a
   requirement's `field` against a fact's normalised `field_name` and nothing
   else. Section 14 assigns label interpretation to the model and **that half
   is not built** - an unmatched requirement becomes `MISSING_INFORMATION`,
   which is honest but will be the dominant status on a real sheet.
3. **The model is never actually called.** `model_opinion` is a parameter this
   engine accepts and reconciles; no code path generates one. The contractor
   comment is the deterministic rationale. Drafting comments and reading
   conditions in prose - the model's half of section 14 - is not wired.
4. **`CONDITIONAL` and `NOT_APPLICABLE` are never produced.** They exist in the
   vocabulary and in `_required_action`, but no rule assigns them. A
   conditional requirement currently lands in `NEEDS_ENGINEER_REVIEW`.
5. **`fields_estimated` is 35 slots per page**, a rough constant, not a count
   of the sheet. It is labelled an estimate everywhere it surfaces.
6. **Severity is always `major`.** Nothing computes it, so the blocking rule
   uses status alone.
7. **No API routes.** 5B is engine and storage only; phase 6 exposes it.
8. **Section 13's formal gap types** (missing certificate, unconfirmed test,
   contradictory values within the submittal) are not detected as distinct
   categories.


---

# Document roles: a watched-folder convention and a bulk assignment

Not a phase. A contained fix between 5B and 6, because phase 5A's applicability
selection and 5B's comparison engine both filter on `document_role`, and **the
column was NULL on every document in the corpus**.

## 73. THE PREMISE OF THE TASK WAS WRONG, AND THAT IS THE FINDING

The work was requested as "fix the 4 existing untagged documents". Measured
before building anything:

| | count |
|---|---|
| documents in the corpus | **280** |
| with a `document_role` | **0** |
| ingested by the watcher | 281 events, 272 files currently in `watch-inbox/` |
| NOT standards (CVs, proposals, a research paper, a test fixture, the confidential register) | **8** |

So it was not 4, it was all 280 - and the 8 include `Engineering Deliverables.pdf`,
the client's confidential register. A blanket backfill would have made that
document a COMPANY_STANDARD, which is to say **a candidate standard for future
submittal reviews**. Reported before acting rather than after, and the backfill
was deliberately NOT run: the standards get tagged by being moved into
`watch-inbox/standards/`, which is a person's decision per file rather than a
filename rule applied by this system to 280 documents at once.

## 74. The subfolder convention

```
watch-inbox/standards/   -> COMPANY_STANDARD
watch-inbox/submittals/  -> CONTRACTOR_SUBMITTAL
watch-inbox/contracts/   -> CONTRACT_DOCUMENT
watch-inbox/supporting/  -> SUPPORTING_DOCUMENT
watch-inbox/            -> no role, unchanged, still tagged by hand
```

Created on every scan, not once at startup: the folder belongs to the client
and these four directories are the entire user interface of the feature. A
share that is remounted or restored loses them, and a convention nobody can see
is a convention nobody uses.

**THE FOLDER DECIDES. THE FILENAME NEVER DOES.** This corpus holds 272 files
named `SAES-*`, so a filename rule would be about 97% right on today's folder,
which is exactly what makes it dangerous. A contractor's reply named
`SAES-A-105-vendor-response.pdf` is a SUBMITTAL, and tagging it
COMPANY_STANDARD makes a vendor's own document the standard its submittal is
reviewed against - the system then finds it perfectly compliant with itself,
cites real pages, and is completely wrong.

The regression guard is written to fail that specific change: it drops a file
named `SAES-A-105.pdf` into the folder ROOT and asserts it comes out with **no
role**. Mutation M73 adds the filename rule and the test goes red.

One level only. `standards/archive/superseded/` would otherwise hand
COMPANY_STANDARD to documents filed precisely because they are NOT current.

## 75. THE CASE THAT MAKES IT USABLE: duplicates carry the role

Every one of the 272 standards was ingested from the folder root before the
convention existed. Moving them into `standards/` produces **272 duplicates and
zero ingests** - so a role applied only at ingest time would have tagged
exactly none of them, silently, while reporting clean scans. The documented way
to tag the library would have done nothing at all.

So a duplicate landing in a role folder applies the role to the document it
duplicates - **only when that document has no role yet**. The folder is a
convenience, not an authority: a correction a person makes in the UI must not
be re-stamped by a file that happens to still be sitting in a folder.

## 76. Keyed by relative path, not by filename

Once subfolders exist, `SAES-A-105.pdf` can be both a standard and a
contractor's copy of it. The watcher's stability and already-handled maps were
keyed by bare filename, which would make the second file collide with the first
- found already-handled and skipped without ever being looked at. Keys are now
`standards/SAES-A-105.pdf`; a root file's key is still just its name, so
nothing about the previous behaviour moved.

## 77. The bulk endpoint, and the two things it refuses

`POST /api/documents/bulk/role`, admin capability plus scope, **asked per
document rather than once for the request**. A bulk endpoint is the classic
place for an authorisation check to become a formality; here the loop IS the
asking. M79 removes the per-document scope check and M78 removes the admin
gate, and both are caught.

**It is not the PUT.** `PUT /classification` replaces the whole record, so
sending a role through it would clear the title, revision, project and subjects
on every document in the selection - metadata somebody typed, destroyed by an
action that said it was setting a role. `classification.set_role` writes one
column and nothing else.

**Failures are named, not counted.** "37 updated" for a request naming 40 tells
the caller something went wrong and makes it impossible to find out what. Every
id that was not written is returned with a reason, and the status is 207 rather
than 200 - so neither a client that reads only the body nor one that reads only
the status can mistake a partial write for a whole one. Unknown and
out-of-scope ids get the SAME `not_found` answer, because a distinct
"forbidden" would let a caller probe forty ids per request for which documents
exist.

`updated` and `unchanged` are separate: re-applying a role a document already
holds is not a change, and counting it as one inflates every confirmation on
screen. That distinction needed a real fix - SQLite's `rowcount` counts a row it
rewrote with the same value, so the first version reported forty changes having
made none (M81).

## 78. Mutations - 83/83

| # | Mutation |
|---|---|
| M73 | **Guess the role from the filename instead of the subfolder** |
| M74 | Ingest from a role folder without applying the role |
| M75 | **Skip the role on a duplicate, so a loaded library can never be tagged** |
| M76 | Let a folder overwrite a role a person set |
| M77 | Key watched files by bare filename again |
| M78 | **Drop the admin gate from the bulk route** |
| M79 | **Stop re-asking scope inside the bulk loop** |
| M80 | Report bulk failures as a silent count instead of by id |
| M81 | Let `set_role` report a change when the value is identical |
| M82 | Show the bulk selection to a non-admin |
| M83 | Report a partial bulk write as an unqualified success |

**Two were NOT DETECTED on the first run and both were real:**

  * **M73** was a broken MUTATION, not a vacuous test - it patched a line a
    file in the folder root never reaches, so it changed nothing for the only
    case the test is about. Moved above the guard; detected.
  * **M82** was a genuinely vacuous test. `DocumentsView` renders `DocumentCard`
    from two places, and the fixture put both documents in the same group, so
    the other render path never ran and an "expect not.toBeInTheDocument"
    passed against a branch that did not exist on screen. Recorded as
    honesty-audit entry 20, with the rule it produces: **an assertion that
    something is ABSENT must also prove the code path ran.**

## 79. Verification, measured

| | passed | skipped | deselected | xfailed |
|---|---|---|---|---|
| Baseline (5B) | 1809 | 27 | 1 | 17 |
| **After this fix** | ****1833**** | 27 | 1 | 17 |

| Check | Result |
|---|---|
| Mutations | **83/83 detected** |
| New frontend tests | 4 passed (`DocumentsView.bulkRole.test.tsx`) |
| `tsc --noEmit` | clean |
| `npm run build` | passes |
| Frontend suite | **59 failed / 555 passed** - the known-bad 59 exactly, and 551 + 4 new |
| Frontend runs | TWO. The first gave 62 failed / 552 passed; the three extra all passed in isolation and did not recur. **One run is an uncontrolled observation, so both are stated rather than the convenient one** - the same correction phase 5A's 2-of-3 rate needed. |

## 80. Known limitations

1. **NO DOCUMENT HAS A ROLE YET.** The feature is built and proven; the corpus
   is still 280 documents with `document_role` NULL. Tagging happens when the
   standards are moved into `watch-inbox/standards/`, and that has not been
   done in this change.
2. **Only four of the five roles have a folder.** `CRS_TEMPLATE` is in the
   vocabulary and settable through the bulk endpoint, but has no subfolder -
   nobody drops CRS templates by the hundred.
3. **An unrecognised subfolder is not walked at all**, so a PDF in
   `watch-inbox/archive/` is never ingested and no event is recorded for it.
   That is unchanged from before this feature (subfolders were never scanned),
   but it is now a place a person might reasonably put a file.
4. **The bulk UI has no select-all.** Selection is per row, so tagging 272
   standards through the UI is not practical - which is the point of the
   subfolder route.
5. **Nothing reconciles a role with the folder a document came from.** Once
   set, a role is independent of the file's location; moving a file out of
   `standards/` does not clear it.

---

# Phase 6 — Findings become visible and actionable

Date: 2026-09-19 · Branch: `feat/phase-1-ui-reaches-backend` · Python 3.12.10

The engine had been writing 1,580 findings per run into a table nobody could
open. Phase 6 is the screens that reach them, the Dashboard entry point that
starts a review, and the engineer's signature that closes one. Five commits:
`ebccf16` (the Review page), `1c18790` (orphaned runs, and the product naming),
`9715c3d` (the placeholder it replaced), `f78d6da` (the visual record) and
`e9ee336` (the Dashboard entry point and the final code).

## 81. The Review page, and the honesty rules that shaped it

The run list answers "what has been reviewed and what did it conclude"; a run
answers "which standards were compared and why each is on the list"; a finding
answers "what does the clause say, what did the contractor submit, and where
can I read both". Every count carries its denominator, the recommended code is
printed in the recommendation's own words including the NOMINAL-estimate note,
and `MISSING_INFORMATION` is neither coloured nor worded as a failure.

**1,578 of 1,580 findings are "no evidence submitted".** They are collapsed
behind their own count rather than hidden, because 2 findings in a list of
1,580 is a different fact from 2 findings.

## 82. The Dashboard entry point (CLAUDE.md rule 10)

`ReviewDashboardPanel` holds the entire block the rule names - four cards, one
`Upload Datasheet and Run AI Review` button, one compact Recent Reviews table -
in ONE component, so a fifth tile cannot be added to Dashboard without editing
the rule first. Rule 10 was itself updated for this workflow before any tile
was added.

Measured on the real corpus:

| card | value | its denominator |
|---|---|---|
| Contractor submittals | 2 | 0 of 2 awaiting review |
| Active standards | 272 | 21 of 21 cited standards are not in the library |
| Reviews in progress | 8 | 0 running · 8 awaiting an engineer's code |
| Needs attention | 9 | 8 not enough was read to recommend a code · 1 the run failed |

The Needs Attention tile lists WHY. A tile reading "9" is a number a reader can
only trust; the breakdown is what makes it checkable.

Upload itself stays on Documents, where upload progress lives. A second
uploader on Dashboard would either hide the ingestion wait or duplicate the
screen that reports it.

## 83. The engineer's final code (master plan section 15)

The AI recommends; the engineer decides; **both are stored and both are
shown**. The recommendation stays where `_store_run_outcome` wrote it and the
decision goes in columns of its own - `engineer_final_code`, `override_reason`,
`decided_by`, `decided_at` - because "which reviews are waiting for an
engineer" is a question the dashboard asks in SQL and cannot ask of a JSON
blob.

A reason is REQUIRED when the two differ and optional when they agree, which is
the difference between overriding a judgement and confirming one. And a run
carrying a decision is not re-run underneath its signature: `replace=True` is
how every fix reaches the corpus, but doing it to a signed run would leave the
code attached to findings it was never made about. A new review is a new row,
so nothing is blocked except overwriting history.

## 84. THE DEFECT NINE GREEN TESTS COULD NOT SEE

`POST /api/reviews/runs/{id}/code` carried `Depends(admin.current_admin)` for
the audit actor alone. **That dependency is a gate, not a lookup:** it raises
the admin surface's deliberately silent 404 for any non-admin. So the only
caller who could record a final code was an admin, and every engineer got
"not found" about a run the same screen had just listed.

Nine unit tests were green over it. They could not see it twice over:

1. every one called `comparison.record_engineer_code` directly and **never
   traversed the route**, where the dependency lives;
2. `conftest` pins `AUTH_MODE=disabled`, under which `current_admin` waves an
   **anonymous** caller straight through - so even a route-level test that
   skipped the login would have passed.

Found by signing in to the running app as an ordinary non-admin engineer and
pressing the button. Fixed with `_actor_from_scope`, which resolves the name
without deciding anything about permission - the route's own scope had already
done that - and three route-level tests that log in with a real token. Mutation
M221 puts the gate back and is DETECTED.

**Recorded as honesty-audit entry 41, and as row 8 of "the verification that
verified nothing".** Its lesson became standing rule 15: *a test that never
crosses the boundary cannot see a guard that lives on it.* Calling the function
is not exercising the route - dependencies, authentication and the mode the
suite pins are all outside the function and all decide whether a real caller
gets through. Where a feature has a user who presses a button, at least one
test must arrive the way that user does.

## 85. Three more defects, each found by running it rather than reading it

1. **`GET /api/reviews/runs` loaded 14,000 findings to produce six numbers.**
   Nine runs by 1,580 rows, counted in Python, before the page rendered.
   Replaced with SQL aggregates: 0.65s.
2. **`reviews.dashboard()` had no `ShapeCheck`**, so a body of the wrong shape
   arrived as `ok` and `.toLocaleString()` threw inside the first card - taking
   the WHOLE Dashboard down over one panel. That is precisely the white screen
   `ShapeCheck` exists to prevent, and 21 Dashboard tests said so the moment
   the panel was wired in.
3. **A stale `running` run locked its submittal out of the product forever.**
   `run_c9b16f71c398` sat at `running` with no process behind it, and
   `POST /api/reviews/run` refuses to start a second review while one is
   going. It was marked failed with a reason, **not deleted** - somebody
   started it and a crashed run is history - and startup now sweeps any run
   still `running`, which is safe for the same reason the extraction sweep is:
   this process has just begun, so it owns none of them.

## 86. Two fixtures that were wrong, not two constraints

`decided_by` and `confirmed_by` are foreign keys to `users(id)`. Two tests in
`test_comparison.py` passed an email and a bare initial as `reviewer`, and the
schema refused the write. **The fixture was fixed, not the schema** - a test
that dodges a foreign key is testing a table shape production does not have.

## 87. Mutations - 13 new, all detected

| phase | ids | what they delete |
|---|---|---|
| 17 | M208-M210 | the orphaned-run sweep: delete instead of fail, sweep every status, never call it at startup |
| 18 | M211-M215, M221 | the final code: override with no reason, overwrite the recommendation, accept any string, re-run a decided run, block every re-run, gate the engineer on being an admin |
| 19 | M216-M220 | the four cards: unscoped counts, every completed run awaiting a decision, a needs-attention number with no breakdown, a running review counted as done, an unbounded Recent Reviews table |

The full harness is **217/217** at the close of phase 6.

## 88. Verification, measured

| | result |
|---|---|
| Backend suite | **2252 passed**, 0 failed, 27 skipped, 17 xfailed, 529s |
| Mutation harness | **217/217 detected**, 0 not detected, 0 harness error |
| `tsc -b` | clean |
| `npm run build` | passes |
| Frontend suite | 598 passed; **58 failed = the known-bad set exactly**, measured at HEAD and again with the work, identical |
| New backend tests | 31 (`test_review_code.py` 12, `test_review_dashboard.py` 10, `test_orphaned_review_runs.py` 9) |
| New frontend tests | 45 across `src/components/review` |

The known-bad set is 58 rather than the long-standing 59 because
`glossary.test.ts` went green: the ban on the word "submittal" contradicted the
product's own navigation, which now reads "AI Submittal Review". The test was
updated to allow it and **keeps every other banned term, the old client name
above all**. It was not deleted.

## 89. Screenshots, against the real corpus

Fourteen images in `docs/screenshots/phase-6/`, captured signed in as an
ordinary non-admin engineer - which is how section 84's defect surfaced. They
show client document content (requirement sentences from the SAES standards,
one submitted value with its field name and equipment tag) and none of
`Engineering Deliverables.pdf`, which rule 3 keeps out of the repository
entirely.

## 90. Known limitations - 6

1. **The model tier is still OFF** and 272 standards stay unqueued. Nothing in
   this phase changed either.
2. **The Dashboard still carries its pre-existing blocks** - "What this system
   can do right now", the EPC delivery overview, the readiness headline.
   Rule 10 names what the REVIEW block may contain; it has not been applied
   backwards to the tiles that were already there.
3. **58 frontend tests fail and are not this phase's.** Four files asserting a
   nav button named `/Chat/` that now reads "Document Q&A". Measured unchanged
   before and after, and deliberately not touched: renaming assertions across
   54 tests could mask a real regression.
4. **Two demo decisions were written to the live corpus and then cleared.**
   Recording a code end-to-end needs a signed-in engineer, so a throwaway
   account was created and deleted; `ON DELETE SET NULL` left two runs signed
   by nobody. Those four columns were cleared on both runs - the decisions
   were the verification's, not an engineer's - and the AI recommendations
   were never touched: 10 intact, 0 decisions remaining.
5. **No CRS export yet.** That is phase 7.
