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

## 11. Conversational assistant

The system must include a conversational assistant over the authorized corpus. It is a
first-class deliverable, not a convenience feature.

### 11.1 What it must do

1. Answer any question over the standards library, project documents, contracts, FEED
   documents and contractor submittals the caller is permitted to read.
2. **Cite every answer.** Document, page, and clause where a clause exists. An answer
   with no citation is not an answer; it is a refusal that must say so.
3. Accept a document uploaded **inside the conversation**, ingest it, and answer
   questions about it in the same session.
4. Produce, on request: summaries, insights, comparisons across documents, and gap
   analysis in narrative form.
5. Offer suggestions and recommended actions, **explicitly labelled as suggestions**.
6. Hold context across a conversation, so a follow-up question does not require the
   user to restate the subject.
7. Respect permission scope absolutely. A document the caller may not read must not
   appear in an answer, a citation, a summary, or a spelling suggestion.

### 11.2 The advisory boundary. This is the most important rule in this section.

**Chat output is advisory. It never becomes a compliance verdict.**

- The assistant **never writes to `review_findings`**.
- A chat answer is never a `COMPLIANT` or `NON_COMPLIANT` determination.
- Only the review pipeline, with its deterministic gates and engineer confirmation,
  produces verdicts that can reach a CRS.
- When asked "does this comply?", the assistant may lay out the requirement, the
  contractor's value, the applicability evidence and its reasoning, and must then state
  that a formal determination requires a review run and engineer confirmation.

This boundary is what allows the assistant to be genuinely useful without carrying the
liability of a compliance decision. An advisory error is visible and cheap. A verdict
error is a commercial position sent to a contractor.

### 11.3 Quality bar

The assistant must reason, not retrieve and paraphrase. Specifically it must:

- decompose a multi-part question into its parts and answer each;
- compare values, clauses or requirements **across two or more documents**;
- identify what is **absent**, not only what is present, and name the gap;
- ask one clarifying question when the query is genuinely ambiguous, rather than
  guessing which of two readings was meant;
- state uncertainty explicitly, naming what evidence would resolve it;
- use a table where a table is clearer than prose;
- keep to the corpus. General engineering knowledge may frame an answer but may never
  substitute for a cited clause.

### 11.4 Model tiering

The assistant is provider-agnostic. Two tiers, one interface:

| Tier | Provider | Default | Condition |
|---|---|---|---|
| 1 | Local model (Ollama) | **enabled** | always available, fully offline |
| 2 | Claude API | **disabled** | requires the client's written authorization, egress approval, and the budget guard in NORTH-STAR |

Rules that apply to both tiers without exception:

- identical citation requirements;
- identical refusal behaviour;
- identical permission scoping;
- **every answer records its `provider` and `model_tag`**, so no stored answer is ever
  ambiguous about which engine produced it.

Enabling tier 2 must be a configuration change, never a code change. Per the owner
decision of 2026-09-22, the Claude provider is built into the pipeline from the start
and switched off, not retrofitted later.

### 11.5 What the assistant must never do

- Never answer a factual question about a standard from model memory. NORTH-STAR:
  *"never reconstruct requirements from model memory."*
- Never fabricate, paraphrase or reconstruct a clause. A quote is verbatim or it is not
  a quote.
- Never present a suggestion as a requirement.
- Never write to `review_findings`, `submittal_facts`, or any table the review pipeline
  owns.
- Never surface content, filenames or terms from a document outside the caller's
  permission scope.
- Never treat "not retrieved" as "not present". An empty retrieval is reported as such.

### 11.6 Acceptance gates for section 11

This section is complete only when tests prove:

1. every answer carries at least one citation, or is an explicit refusal naming what was
   searched and not found;
2. a question about a document outside the caller's scope returns nothing, and leaks no
   filename, term or fragment;
3. a document uploaded in the conversation is answerable in the same session, with page
   citations into that uploaded file;
4. a deliberately unanswerable question produces a refusal that names the missing
   evidence, not a plausible guess;
5. a "does this comply?" question returns reasoning plus an explicit statement that a
   formal determination requires a review run and engineer confirmation;
6. `provider` and `model_tag` are stored on every answer;
7. a cross-document comparison question returns a correct comparison with citations on
   both sides.

---

## 12. Datasheet understanding moves from rule-based parsing to model reading

### 12.1 The measured reason for this change

Rule-based extraction has been measured on the live database and does not work on real
engineering datasheets:

- **82.82%** of extracted statements (28,935 rows) carry NULL `field`, NULL `subject`
  and NULL `raw_value`. They are empty shells.
- The pump datasheet regression document yields **0 facts and 0 findings** on the live
  database.
- On the tuning document, a **multi-column material field produced no fact at all for one
  of its columns**, while the other columns of the same field extracted correctly.

*Document names, values and row counts for all three measurements are recorded in the
register, `CURRENT_STATE_AND_BLOCKERS.md` section 10.11. They are deliberately not
written here: this file is one of the ten `.cowork` files `.gitignore` re-allows by name,
so everything in it reaches GitHub, and client document identifiers do not belong there.*

The cause is structural, not a tuning problem. Engineering datasheets use multi-column
layouts, merged cells, scanned pages, and inconsistent field labels. A deterministic
parser cannot generalise across them, and every document-specific rule added to rescue
one layout is forbidden by V3's own exit criterion: *"arbitrary held-out layouts work
without document-specific code."*

### 12.2 The change

The model reads the datasheet page and returns structured facts. Deterministic code
validates what it returns.

Required properties:

1. Each extracted fact carries: field name, value, unit, page, and the **verbatim source
   text** it came from.
2. Each fact carries the **column or label that scopes it** where the layout is
   multi-column. A corrosion-allowance value without the material column it belongs to
   is refused, never stored unscoped. This is the B33 defect.
3. The **B23 verbatim validator applies to every extracted fact.** A fact whose source
   text does not appear byte for byte on the cited page is refused, not stored.
4. Unit and dimension parsing stays deterministic. The model reports the text; Python
   parses the quantity.
5. A page the model cannot read produces an explicit refusal with a reason, never a
   silent zero. The silent `pages_read: 0` branch is a defect in its own right.
6. No document-specific rules, no hand-written field vocabularies.

### 12.3 Cost, stated honestly

Model-reading every page of every document is expensive. Measured on the development
machine (Dell OptiPlex 7040, i7-6700, no GPU), one model call on a 577-token packet took
**105 seconds** with the 4B and **135 seconds** with the 9B.

This section therefore carries a hardware dependency that must be recorded with it: model
based extraction at corpus scale is not achievable on the current development hardware.
It is achievable on one document for a demonstration, and requires GPU hardware or an
authorized cloud lane for production volume.

Recording this is not a reason to defer the design. It is a reason to size the hardware
against the design rather than the reverse.

### 12.4 Acceptance gates for section 12

1. the pump datasheet regression document yields a non-zero, page-cited fact set on a
   previously unseen run;
2. the tuning document's multi-column material field produces a fact carrying the column
   label that scopes it;
3. no fact is stored whose scoping label could not be determined;
4. every stored fact passes the B23 verbatim validator against its cited page;
5. the empty-statement proportion, currently 82.82%, is re-measured and reported;
6. a held-out datasheet of a different layout extracts correctly with no
   document-specific code added;
7. a page that cannot be read produces a named refusal, and the run reports it.

---

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
