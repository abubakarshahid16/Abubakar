# AI Contractor Document Submittal Review: master plan

Approved specification, recorded 2026-09-18. This is the authoritative scope
document. Phase reports are reviewed against this file, not against chat
history.

## Amendments to the original specification

Two corrections are folded into the sections below. They are recorded here so
the change is visible rather than silent.

1. **Dashboard (section 20).** The original eight-card proposal is withdrawn.
   The approved design is four cards, one primary button, one compact table and
   one conditional banner. `CLAUDE.md` rule 10 was updated to match in commit
   `732ce42`.
2. **Vector store (sections 10, 11, 23).** The specification says LanceDB. The
   code does not use LanceDB for retrieval: dense vectors are `BLOB` rows in the
   SQLite `chunk_vectors` table, memory-mapped into one numpy matrix by
   `vectorcache.py`, searched by brute-force cosine in `search.dense_search`.
   `lancedb` appears only in `config.py`. Read every "LanceDB" requirement below
   as "the existing dense-vector store". Do not introduce LanceDB.

---

## 1. Mandatory read-first process

Before editing: read `AGENTS.md` (absent in this repo), `CLAUDE.md`, README,
setup and architecture docs. Run `git status` and preserve user changes. Inspect
frontend and backend structure. Trace the real execution flow for PDF upload,
ingestion, extraction, OCR, chunking, SQLite persistence, FTS5 retrieval,
dense retrieval, Ollama generation, citation creation, authentication,
role-based access, document permissions, analysis modes, report generation,
deliverables/WBS, guided review and watched-folder ingestion. Read source line
by line before modifying. Inspect current tests and migrations. Run the test
suite and record the baseline. Do not assume a feature works because a route or
file exists; trace the runtime path. Reuse existing architecture and services.

Prohibited: deleting or resetting the repository, destructive git commands,
discarding uncommitted work, reinstalling the stack, rewriting working modules
unnecessarily, duplicate document/user/permission/retrieval systems, pushing
without being asked, sending document content to any external API, replacing
the local-first architecture, stopping after the audit without a real blocker.

## 2. Primary product objective

A contractor uploads an equipment datasheet. AI reads and classifies it,
searches the complete standards library, selects all applicable standards,
reviews the datasheet requirement by requirement, produces cited findings,
recommends an overall review code, and generates a completed CRS Excel
workbook.

Client workflow: Upload datasheet, Run AI Review, Inspect findings, Download
completed CRS.

The engineer reviews or edits the AI result before issuing it. The engineer must
not select every clause or create findings one by one. "All standards" means
search the complete library and apply every relevant standard, not compare every
datasheet against every unrelated standard.

## 3. Supplied reference files

`EF1975-DAS-M-03.pdf`, `EF1975-DAS-I-06.pdf`,
`216400C-2003-SP-0810-0003_00 (1).pdf`, `SAES-A-105.pdf`,
`CRS - Form of Agreement_2028 (1).xlsx`.

Datasheets are representative contractor-submittal formats. SAES-A-105 is the
first example standard; production must support many SAES, SAMSS, contract,
project and company standards. The CRS workbook is the required output template.

Do not hard-code filenames, equipment types, values, clauses or findings from
these samples. They are integration fixtures. The live demonstration may use an
unseen datasheet in the same, a modified, or a different format.

As of 2026-09-18 none of these files are present in the repository or `data/`.

## 4. Preserve existing functionality

Keep and integrate with: FastAPI backend, React/TypeScript frontend, SQLite,
FTS5, the existing dense-vector store, local Ollama, OCR fallback, keyword and
vector retrieval, page-level citations, authentication, role-based document
access, document permissions, document history, chat, quote analysis, focused
analysis, comprehensive analysis, gap analysis, recommendations, market
intelligence, evidence reports, deliverables/WBS, watched-folder ingestion and
current administration features. The new workflow extends the product; it
removes nothing.

## 5. Final navigation

1. Dashboard
2. AI Submittal Review
3. Documents
4. Standards Library
5. Analysis Hub
6. Document Q&A
7. CRS & Reports
8. Deliverables
9. System: Ingestion, Administration, System Health

Renames: `Review flow` to `AI Submittal Review`, `Chat` to `Document Q&A`,
`Analysis` to `Analysis Hub`, `Reports` to `CRS & Reports`. Move Ingestion and
Administration under System if routing supports clean grouping. Preserve
responsive and mobile sidebar behavior. Do not break routes without redirects or
updated links.

Status: the four renames landed in commit `f0c70a2`. Standards Library, System
grouping and System Health are not yet built and are deliberately absent from
`NAV`, because the shell's own rule is that navigation never implies capability
that does not exist.

## 6. Document roles and storage

Extend existing document records. Do not create a disconnected document system.

Roles: `CONTRACTOR_SUBMITTAL`, `COMPANY_STANDARD`, `CONTRACT_DOCUMENT`,
`SUPPORTING_DOCUMENT`, `CRS_TEMPLATE`.

Store standards and submittals separately at the logical/database level while
reusing current file storage and permissions. Metadata, adapted to the existing
schema: document number, title, revision, effective/issue date, project,
contractor/vendor, discipline, equipment type, equipment tags, service,
transmittal number, document role, processing status, review status,
superseded/active status.

AI may predict metadata; authorized users must be able to correct it. Migrations
must be safe and must not destroy or invalidate existing records.

## 7. Documents page

Filters/tabs: All, Contractor Submittals, Company Standards, Contract Documents,
Supporting Documents, CRS Templates.

Columns/cards: document name, document role, document number, equipment type,
discipline, revision, pages, processing status, review status, Preview action,
Start Review action where applicable.

Move chunks, passages, excluded pages, embeddings and internal processing logs
into an expandable `Processing Details` drawer. Preserve delete safeguards and
permissions.

## 8. In-app document preview

PDF: embedded viewer, page thumbnails, page navigation, search, zoom, rotate,
download original, metadata, OCR/extraction status, direct opening of cited
pages, highlighting of cited text or table regions where coordinates exist.

Every citation in Chat, Analysis, Submittal Review and Reports must open the
exact document and page.

Excel/CRS: read-only workbook preview, sheet switching, populated-cell preview,
download original `.xlsx`.

Never convert the only copy of an uploaded file. Preserve original bytes.

## 9. Standards Library

Dedicated library using existing storage and permissions. Each standard shows:
standard number, title, revision, effective date, active/superseded/expired
status, discipline, applicable equipment types, number of extracted
requirements, requirements awaiting verification, referenced standards missing
from the library.

Detail page tabs: Original Document, Requirements, Applicability, Revision
History, Processing Details.

Preprocessing on upload: extract text and layout; OCR only pages that need it;
detect clause hierarchy; create atomic requirement records; extract mandatory
wording, applicability conditions, numeric limits and units, exceptions,
required forms/certificates/supporting documents, referenced standards; add
discipline and equipment applicability; index exact clause text in FTS5; create
clause-level embeddings; preserve document, page, clause and source text for
every requirement; mark low-confidence extractions for verification.

Requirement shape:

```json
{
  "standard": "SAES-A-105",
  "revision": "2021",
  "clause": "5.3.3",
  "page": 9,
  "requirement_type": "numeric_limit",
  "field": "noise_at_1_meter",
  "operator": "<=",
  "value": 90,
  "unit": "dB(A)",
  "condition": "new equipment",
  "exceptions": [
    {
      "equipment_type": "pressure_relief_valve",
      "operator": "<=",
      "value": 115,
      "unit": "dB(A)"
    }
  ],
  "source_text": "...",
  "confidence": 0.98
}
```

Process each standard once and reuse the structured requirements. The model must
not reread an entire standard for every submittal.

## 10. Format-independent datasheet ingestion

No parser tied to one sample layout. Per datasheet: extract embedded PDF text
first; preserve text blocks and coordinates; extract tables, rows, labels,
values, units; OCR only pages without usable embedded text; fall back for
scanned or difficult tables; classify document and equipment type; extract
metadata; normalize field names and units; identify referenced standards;
identify blank `By Contractor/Vendor` or required fields.

Store every fact with original text, normalized field, normalized value, unit,
page, section, table/row or coordinate, and confidence.

```json
{
  "field": "design_pressure",
  "value": 3.5,
  "unit": "bar_g",
  "original_text": "Internal Design Pressure: 3.5 bar (ga)",
  "page": 4,
  "section": "Process Data",
  "confidence": 0.98
}
```

Support native-text PDFs, scanned PDFs, multi-page table datasheets, the same
template with changed values, different table layouts, and pump, PSV, vessel and
future equipment types. If extraction quality is insufficient, report the
affected pages and lower review completeness. Never invent values from
unreadable content.

## 11. Automatic applicable-standard selection

Search all accessible active standards and select applicable ones, in priority
order: standards explicitly referenced in the datasheet; standards mapped to the
detected equipment type; discipline matches; service and operating-condition
matches; semantically relevant standards via vector retrieval; relevant
contract/project requirements.

Hybrid retrieval: FTS5 for exact standard numbers, clauses and phrases; the
dense store for semantic matching; metadata filtering before vector retrieval;
existing role-based access filters before all search and retrieval.

For each selected standard store and display selection reason, selection method,
confidence and relevant clauses. Also display referenced standards missing from
the library, standards considered but excluded, and the exclusion reason. A
missing referenced standard reduces review completeness and is never silently
ignored.

Selection is automatic. Engineers may add or remove a standard afterward with an
audit reason.

## 12. AI compliance-review engine

A dedicated engine, not one giant RAG prompt. Per applicable requirement:
retrieve contractor evidence; retrieve the exact requirement; determine
applicability; account for conditions and exceptions; normalize units and
values; compare objective values in deterministic code; use the local model for
technical wording and descriptive requirements; assign a result; generate a
contractor-facing comment; validate both citations; store the finding.

Statuses: `COMPLIANT`, `NON_COMPLIANT`, `MISSING_INFORMATION`, `CONDITIONAL`,
`NOT_APPLICABLE`, `NEEDS_ENGINEER_REVIEW`.

Every finding carries: contractor document id/name, contractor page/section,
contractor evidence, standard/contract source, exact clause, standard page,
requirement source text, status, severity, AI comment, confidence, AI rationale,
engineer decision, audit timestamps.

Missing information is not automatically non-compliance. Do not claim a
requirement failed when the evidence only shows information is absent.

Do not create a finding unless the contractor citation resolves, the standard
citation resolves, the clause supports the comment, and applicability is
established or clearly marked conditional. Unsupported findings are blocked or
downgraded to `NEEDS_ENGINEER_REVIEW`.

## 13. Formal compliance gaps

Produced automatically by AI Submittal Review: mandatory value missing;
contractor value conflicts with a standard; required certificate missing;
required test not confirmed; referenced standard unavailable; required form
missing; mandatory technical field blank; requirement only conditionally
demonstrated; contradictory values within the submittal.

These may enter the CRS after validation. Keep them separate from exploratory
gaps produced by the general Analysis Hub.

## 14. Deterministic validation

Python, not the model, performs: numeric comparison, unit conversion,
date/revision comparison, required-field presence, exact identifiers, threshold
evaluation, review-code policy, citation existence checks. Use strict structured
output validated by Pydantic or the project's existing schema system.

The model performs: technical wording, document classification, field-label
interpretation, conditions and exceptions, descriptive comparison, comment
drafting, explanation.

## 15. Review-code engine

Review codes are configurable; the client may use different names or numbers.
Defaults: Approved (no unresolved significant findings); Approved with Comments
(only non-blocking findings); Rejected / Revise and Resubmit (at least one
blocking technical conflict, unsafe value, or materially incomplete submission);
Manual Review Required (unreadable evidence, missing critical standards or
insufficient confidence).

Store AI-recommended code, final engineer code, override reason, reviewer and
timestamp. The AI performs the review and recommends the code; the engineer's
final action is governance, not the initial review.

## 16. AI Submittal Review UI

Three client-facing stages, replacing the current simple guided review.

**Stage 1, Upload.** Upload or select contractor datasheet, show document
preview, show detected metadata, allow corrections.

**Stage 2, AI Review.** One primary action: `Run AI Review`. Show real
processing stages: reading document, identifying equipment, selecting applicable
standards, reviewing requirements, validating citations, recommending review
code, generating CRS. Do not require the user to type a question or select
clauses.

**Stage 3, Results and CRS.** Show recommended overall code, review
completeness, applicable standards, missing standards, compliant requirement
count, compliance gaps, non-compliant findings, conditional findings,
needs-review findings, CRS readiness. Provide a side-by-side finding view:
contractor page/evidence, standard page/clause, comparison, proposed CRS
comment.

Engineer actions: Accept, Edit, Reject AI finding, Mark not applicable, Change
severity, Add manual finding, Override review code with reason. Persist progress
so reviews resume.

## 17. CRS workbook generation

Use the supplied workbook as a template. Do not rebuild it as a visually
unrelated workbook. The exporter must: copy the master template; preserve
sheets, formatting, merged cells, widths, borders, branding and print settings;
fill transmittal and document metadata; populate one row per accepted finding;
include document name, exact contractor page/section, a clear contractor-facing
comment, the exact clause, and reviewer/comment author; leave Contractor
Response and Final Resolution blank; add the AI-recommended overall code; store
the workbook as a review artifact; provide in-app preview and `.xlsx` download.

If the template cannot take a new clause-reference column without changing the
official layout, append the reference inside `COMPANY Comments`:
`Reference: SAES-A-105, Clause 5.3.1, Page 9.`

CRS field mapping must be configurable so another official template is supported
without rewriting the review engine.

CRS states: AI Draft, Engineer Reviewed, Issued to Contractor, Contractor
Responded, Closed, Superseded.

## 18. Analysis Hub

Preserve all modes, organized as Quote, Focused Analysis, Comprehensive
Analysis, Gap Analysis, Recommendations, Market Intelligence.

**Quote:** exact document wording with clickable page citation, minimal or no
generation. **Focused:** one narrow engineering question against a selected
scope. **Comprehensive:** complete cited synthesis across selected documents,
run as a background job. **General Gap Analysis:** exploratory gaps (missing
sections, cross-document inconsistencies, revision differences, unclear
responsibilities, possible missing deliverables). These are advisory and must
not automatically enter the CRS; provide `Send to Review as Draft Finding`, and
the compliance engine then validates applicability, evidence and clause support
before it becomes a formal finding. **Recommendations:** keep document facts and
AI recommendations visually and structurally separate; only
requirement-supported actions may enter the CRS by default.

**Market Intelligence:** preserve the existing controlled public-information
lane. Private documents and standards stay local. Only a generic sanitized query
may leave the machine. Never send private passages, project names, equipment
tags, contract numbers, proprietary values or contractor comments. Market
findings must cite public sources, be labelled public/advisory, must not affect
the formal review code, must not enter the CRS automatically, and may appear in
a separate Market Intelligence report.

## 19. Document Q&A

Keep the existing cited chat. Add scope controls: current submittal, applicable
standards, current review, selected documents, all accessible documents.

Suggested questions: why was this standard selected; which contractor fields are
missing; which clause supports finding 3; what prevents approval; explain the
PSV exception; show all conflicting values.

Every citation opens the source preview at the exact page. Chat may create a
draft finding but cannot silently approve reviews, change the final review code
or alter an issued CRS.

## 20. Dashboard

**Approved design. This supersedes the original eight-card proposal.**

Four essential cards only:

1. **Contractor Submittals**, total and awaiting review
2. **Active Standards**, available and missing/referenced
3. **Reviews in Progress**, processing or awaiting engineer decision
4. **Needs Attention**, rejected, blocked, failed or low-confidence reviews

Plus:

- One prominent `Upload Datasheet and Run AI Review` button
- One compact Recent Reviews table: document, equipment, findings, recommended
  code, status, Open action
- One small system warning banner, shown only when there is a real issue such as
  low memory, failed OCR or missing standards

Relocations:

- Detailed Standards Readiness goes to the **Standards Library** page
- Recent Intelligence Work goes to the **Analysis Hub**
- RAM, model, OCR, embeddings, latency and ingestion detail go to **System
  Health**

`CLAUDE.md` rule 10 was updated to match: "Dashboard stays minimal" now means a
focused operational dashboard with no unnecessary tiles, not a dashboard that
excludes the primary workflow.

## 21. CRS & Reports

**Formal review outputs:** CRS Excel, AI Review Evidence PDF, review audit
history, previous/superseded review revisions.

**Analysis outputs:** Focused Analysis, Comprehensive Analysis, Gap Analysis,
Recommendations, Market Intelligence.

Extend the existing Evidence Report with: review identification, contractor
document, applicable standards, missing standards, review completeness,
recommended review code, findings summary, detailed findings, contractor
evidence, exact standard clauses, AI confidence, engineer decisions, audit
history. Keep draft watermarks until frozen or issued.

## 22. Ingestion screen and job management

Extend the existing ingestion queue. Do not build a second worker system.

Standards stages: extracting pages, detecting clauses, extracting requirements,
extracting exceptions, creating embeddings, awaiting verification, ready.

Submittal stages: extracting pages, OCR, extracting tables, classifying
equipment, normalizing facts, detecting standards, ready for review.

Filters: Standards, Contractor Submittals, OCR Required, Failed, Awaiting
Classification, Awaiting Verification, Ready. Prioritize active AI review jobs
over background analysis.

## 23. Database and vector-search decision

Keep the local architecture: SQLite for records and workflow, FTS5 for exact
standard/clause/phrase search, the existing dense-vector store for semantic
retrieval, Ollama for local AI, Python for deterministic validation. Do not
migrate to PostgreSQL or pgvector for this demo.

Separate logical retrieval scopes: standards, contractor submittals, contract
documents, supporting documents. Apply user permissions and document-scope
filters before keyword or vector retrieval. Vector similarity finds candidates
and must never be the sole basis for declaring compliance or non-compliance.

## 24. Hardware constraints

Target: 16 GB RAM, Intel Core i7 12th generation, 10 cores, Windows, local
Ollama, model approximately `qwen3.5:4b`.

Resource-aware execution: one heavy job at a time; one ingestion/review worker;
maximum two OCR pages in parallel; small embedding batches; vectors on disk; OCR
only pages that need it; never run OCR, embedding and generation simultaneously
under low memory; allow the worker to unload or pause the model during heavy OCR
or embedding; reuse cached extraction and embeddings for duplicate documents;
preprocess standards before the demo; use focused requirement batches rather
than a whole datasheet plus all standards in one prompt; strict JSON output with
schema validation; expose low-memory warnings in System Health; do not add a
larger model as a mandatory dependency before benchmarking.

Job priority: active AI Submittal Review, CRS generation, Quote/Focused
requests, Comprehensive Analysis, General Gap Analysis, Market Intelligence,
background standard reprocessing.

## 25. Proposed backend components

Adapt names to repository conventions and reuse existing services.

```
standard_requirement_extractor   datasheet_classifier
datasheet_fact_extractor         standard_applicability_engine
compliance_review_engine         unit_normalizer
citation_validator               review_code_engine
crs_template_mapper              crs_exporter
document_preview_service         analysis_job_manager
resource_scheduler
```

Likely new or extended records:

```
standard_versions        standard_requirements    submittals
submittal_facts          review_runs              review_applicable_standards
review_findings          finding_decisions        crs_templates
generated_review_artifacts                        analysis_jobs
```

Do not create a new table if an existing table can be safely extended.

## 26. API requirements

Follow existing conventions. Add or extend routes equivalent to:

```
POST   /api/standards
GET    /api/standards
GET    /api/standards/{id}
GET    /api/standards/{id}/requirements
PATCH  /api/standards/{id}/requirements/{requirement_id}

POST   /api/submittals
GET    /api/submittals/{id}
PATCH  /api/submittals/{id}/metadata

POST   /api/reviews
GET    /api/reviews/{id}
POST   /api/reviews/{id}/run
GET    /api/reviews/{id}/status
GET    /api/reviews/{id}/applicable-standards
PATCH  /api/reviews/{id}/applicable-standards
GET    /api/reviews/{id}/findings
PATCH  /api/reviews/{id}/findings/{finding_id}
PATCH  /api/reviews/{id}/overall-code

POST   /api/reviews/{id}/export/crs
GET    /api/reviews/{id}/export/crs
GET    /api/documents/{id}/preview
GET    /api/documents/{id}/pages/{page}
```

Do not duplicate routes that already provide the same capability. Long-running
work uses the existing background job mechanism and exposes progress without
blocking the HTTP request.

## 27. Security requirements

Preserve deny-by-default. Every standard, submittal, review, finding and report
respects document permissions. Retrieval is filtered before ranking. Users
cannot reference unauthorized document ids. Preview and export endpoints check
access. Generated CRS and report files inherit the review's permission scope.
Ollama endpoints remain local-only. Private content never enters
market-intelligence web queries. Engineer decisions and overrides are auditable.
Original uploaded files remain immutable.

## 28. Implementation order

Maintain a runnable application throughout.

| Phase | Scope |
|---|---|
| 1 | Foundation: document roles, metadata, safe migrations, review/finding entities, permission tests |
| 2 | Document experience: filters, PDF/Excel preview, citation-to-page navigation, technical-details drawer |
| 3 | Standards Library: UI, clause extraction, atomic requirements, conditions/exceptions, revision handling, exact and vector indexes |
| 4 | Datasheet intelligence: classification, table extraction, fact and unit normalization, blank-field detection, referenced-standard detection |
| 5 | AI review engine: applicability selection, requirement comparison, deterministic validation, citation verification, findings, review-code recommendation |
| 6 | AI Submittal Review UI: upload, progress, results, side-by-side evidence, Accept/Edit/Reject, resume |
| 7 | CRS and reporting: template mapping, Excel generation, preview/download, evidence-report extension, revision/audit history |
| 8 | Navigation and dashboard: final sidebar, four-card dashboard, System Health relocation |
| 9 | Analysis integration: preserve every mode, separate exploratory from compliance gaps, preserve market isolation, draft-finding promotion |
| 10 | Performance and demo hardening: resource scheduling, memory checks, caching, failure recovery, integration tests, benchmarking on the 16 GB machine |

## 29. Testing requirements

Unit, integration and end-to-end. Required cases: native-text pump datasheet;
PSV datasheet; vessel datasheet; same layout with changed values; different
layout; scanned datasheet; blank required contractor field; numeric conflict;
unit conversion; conditional requirement; equipment-specific exception; missing
referenced standard; superseded standard; low OCR confidence; unauthorized
document access; citation opens exact page; accepted finding enters CRS;
rejected AI finding does not enter CRS; review-code calculation; CRS template
formatting preservation; restart and resume of an incomplete review; low-memory
job scheduling; market-intelligence query sanitization.

Do not hard-code expected findings around the sample filenames. Tests must prove
the generic workflow. Per `CLAUDE.md` rule 6, every test must fail when its
feature is deleted; prove it by mutation.

## 30. Definition of done

An unseen contractor datasheet can be uploaded and the application
automatically: opens and previews it; identifies document/equipment type;
extracts technical fields and referenced standards; searches all accessible
active standards; selects applicable standards; reports missing referenced
standards; reviews applicable requirements; handles conditions and exceptions;
produces findings with two-sided citations; separates missing information from
non-compliance; recommends the overall review code; generates a completed CRS
workbook; allows engineer Accept/Edit/Reject; preserves an audit trail; runs
locally within 16 GB; and preserves Chat, Analysis Hub, Market Intelligence,
Reports, Deliverables and existing permissions.

## 31. Working behavior

Per phase: inspect the existing implementation; make the smallest coherent
changes; add or update tests; run targeted tests; run the broader regression
suite when practical; verify frontend build and type checking; verify backend
startup; verify database migration; report what changed and any real limitation;
continue unless blocked.

Do not claim something works because files or routes were added. Test the real
execution path. If a requirement conflicts with the existing architecture,
preserve working behavior and explain the safest adaptation. Ask only when a
missing decision would materially change the implementation; otherwise make the
safest reasonable decision and continue.
