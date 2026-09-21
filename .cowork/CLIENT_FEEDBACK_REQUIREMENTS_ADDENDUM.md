# Client Feedback Requirements Addendum

Status: **Requested requirements — not yet implemented or accepted as complete**

This addendum extends the existing AI Submittal Review plan. It does not replace
`NORTH-STAR.md`, `CURRENT_STATE_AND_BLOCKERS.md`, or the approved architecture.
The local model remains the primary path. Claude is optional and must remain
behind an explicit feature flag and budget guard.

## Decision update — standards must be discovered by the system

The owner has decided that the client should not have to provide a complete
standards list. The system must discover likely applicable standards itself
from the contract, FEED, datasheet, project specifications, equipment type,
service, materials, pressure/temperature, discipline and hazardous-area
information.

This does **not** mean comparing every document with every standard. It means:

1. extract standards explicitly named in the project documents;
2. infer candidate standards from an equipment/discipline applicability matrix;
3. verify the contractor's stated standards against those candidates;
4. identify missing, conflicting or questionable standards;
5. retrieve the exact clauses and evidence for the selected candidates;
6. let the local reasoning model explain the applicability decision; and
7. require engineer confirmation when applicability is inferred or uncertain.

The initial applicability matrix should cover, where relevant:

- pressure vessels and relief devices: ASME VIII, API 520/521/526/527;
- centrifugal pumps: API 610 / ISO 13709 and API 682;
- process piping: ASME B31.3 and ASME B16 standards;
- materials and sour service: ASTM and NACE MR0175 / ISO 15156;
- welding: ASME IX and ISO 3834;
- hazardous-area electrical equipment: IEC 60079 and applicable NFPA rules;
- functional safety and instrumentation: IEC 61508, IEC 61511 and ISA rules;
- HAZOP: IEC 61882;
- Saudi Aramco, KOC, project and contract requirements whenever applicable.

These are candidate families, not automatic requirements for every submission.
The system must store the reason each standard was selected or excluded. A
model suggestion without a source, applicability reason and engineer decision
must never become a final compliance requirement.

If a cited or independently identified standard is absent, report
`MISSING_LOCALLY`. Only an explicitly authorised online-lookup mode may
retrieve it; the retrieved copy must be hashed, permission-scoped, revisioned
and cited. Model knowledge alone is never an acceptable clause source.

## 1. Standards coverage

The system must review against every applicable requirement source, not only
Saudi Aramco SAES/SAMSS documents. Supported source families may include API,
ASME, ASTM, ISO, IEC, NFPA, NACE, KOC, project specifications, contract
articles, FEED/design-basis documents, and other standards explicitly cited by
the project.

Each source must retain: issuing body, standard number, title, revision,
effective date, document hash, source type, permission scope, and page/clause
citations. Standards remain logically separated by source family in the same
database; do not create a second retrieval database.

If a required standard is missing, the system must report `MISSING_LOCALLY`.
Optional online lookup is allowed only when the client authorizes it. Retrieved
documents must be stored, hashed, cited, and marked as externally obtained.
The system must never present model knowledge as a verified standard clause.

## 2. Engineering comments

Comments must use a controlled engineering-review style based on the agreed
international/project standard. The exact client standard or comment template
must be confirmed before calling this requirement complete.

Every comment must be understandable to a non-specialist stakeholder and must
contain, where applicable:

- what was checked;
- datasheet quote and page/section;
- requirement quote and exact clause/page;
- result and reasoning in plain language;
- action required from the contractor;
- limitation or missing evidence;
- review code and engineer-confirmation state.

The model may draft wording, but Python validates that quoted evidence exists.
An engineer confirms the final finding.

## 3. CRS formatting and page references

The CRS export must use the client's template and preserve these fields:

1. Submittal number
2. Page number / section of the reviewed document
3. System-generated reference number
4. Review code
5. Comment
6. Exact clause reference (SAES/SAMSS, other standard clause, or contract article)

Cells containing comments must wrap text, preserve readable line breaks, and
include page/section references in the visible output. Row height must expand or
use a safe maximum with an explicit continuation rule. The exported workbook
must be reopened and visually checked before release.

## 4. Claude benchmarking

The local model is primary for offline/confidential operation. Claude is an
optional benchmark and emergency fallback only, controlled by:

- explicit enablement flags;
- public-egress approval;
- per-run and total budget limits;
- no secrets in prompts, URLs, logs, CRS, or client output;
- identical frozen evidence packets, prompts, and acceptance tests for every
  model comparison.

Benchmark results must report accuracy, unsupported-claim rate, citation
accuracy, abstention quality, latency, memory, token/cost usage, and failure
cases. Claude must not silently approve a finding or hide local-model failure.

## 5. HAZOP risk review

Add a HAZOP review mode that produces structured, engineer-confirmed records:

- node and design intent;
- deviation;
- cause;
- consequence;
- existing safeguards;
- recommendation/action;
- severity, likelihood, and risk ranking;
- source evidence and page/clause references;
- owner, due date, and closure state.

HAZOP output is separate from ordinary datasheet compliance findings but may
reuse the same evidence and audit infrastructure. The AI proposes; a qualified
engineer accepts, edits, or rejects.

## 6. FEED and simulation mode

Add an explicit `FEED_REVIEW` / `SIMULATION` mode. It must be visibly labelled
as a design-evaluation scenario, not an approved final design.

The system should read FEED documents, design basis, P&IDs, equipment lists,
layouts, specifications, schedules, and referenced standards, then report:

- extracted design assumptions;
- missing deliverables;
- inconsistencies and conflicts;
- risks and required calculations;
- detailed-engineering actions and responsible discipline;
- evidence and confidence for every conclusion.

The system must not claim that a simulation or detailed-engineering result was
performed unless the relevant calculation/tool output exists and is cited.

## 7. Legal-assistant letters

Add a `LETTER_DRAFT` output for transmittals, clarification requests,
technical non-conformance notices, responses, and review-result letters.

Letters must be factual, source-cited, and clearly labelled **AI draft — human
and legal review required**. The system must not provide legal advice, invent a
contract obligation, or send a letter automatically.

## 8. Deliverables and schedule

Maintain a project deliverable register with:

- deliverable name and type;
- contractual/source reference;
- revision and status;
- required-by date;
- owner/responsible discipline;
- dependencies;
- submitted/approved dates;
- missing or overdue flag;
- source evidence.

Provide a schedule view for review runs, submissions, actions, HAZOP items,
FEED deliverables, and CRS release milestones. Dates must come from project
data or be labelled as assumptions.

## 9. Required end-to-end workflow

Upload contractor datasheet and project/FEED documents → classify documents and
context → extract text, tables, facts, and citations → identify applicable
standards independently of the contractor's stated list → retrieve evidence →
local model reasons over the frozen evidence packet → deterministic validation
checks quotes, units, pages, and clauses → engineer confirms findings → export
CRS, HAZOP actions, letters, deliverable register, and schedule views.

## 10. Acceptance gates before client demo

This addendum is complete only when tests prove:

- a non-Aramco standard is cited and appears in the CRS correctly;
- a missing required standard is reported without hallucinated content;
- every visible comment has valid source quotes and page/clause references;
- CRS text wraps and remains readable after reopening the workbook;
- local-model and Claude benchmark results use the same frozen packet;
- HAZOP findings contain the required fields and require engineer confirmation;
- FEED/simulation output is labelled as scenario/design evaluation;
- legal letters are drafts requiring human/legal approval;
- deliverables and schedule entries preserve source evidence and status;
- the complete workflow works on a previously unseen datasheet.

## Open decisions required from the client

Before implementation is called complete, obtain:

1. Which international comment/review standard or client template governs wording?
2. Which external standards and licensed sources may be used?
3. Is online lookup permitted, and who approves retrieved documents?
4. Which HAZOP risk matrix and severity/likelihood definitions apply?
5. What does “simulation” mean for this project: scenario assessment, process
   calculation, or connection to an external simulator?
6. Which letter types and contract/legal templates are required?
7. Which deliverables and schedule fields are mandatory?
