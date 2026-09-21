# NORTH-STAR.md — governing product policy

Owner: Muhammad Usman

Status: **PENDING OWNER APPROVAL**

Applies to: Codex, Claude/Cowork, Claude Code, developers, testers and reviewers

Full design authority: `AI_SUBMITTAL_REVIEW_SYSTEM_AUDIT_AND_NORTH_STAR_V3.md`, after its exact approved version is pinned
Volatile facts: `CURRENT_STATE_AND_BLOCKERS.md`

This file contains stable rules. Git state, database counts, model availability, test
results and active bugs do not belong here. No client release is permitted while this
file or the approved V3 remains unsigned, or while a mandatory acceptance gate is open.

## 1. Product mission

Build an offline-first engineering document-review system that can:

1. receive contractor submittals and their project context;
2. understand equipment, service, discipline and document purpose;
3. independently discover potentially applicable requirements;
4. compare the submittal with authorized company standards, contracts, FEED documents
   and project specifications;
5. explain every proposed finding with evidence from both sides;
6. create a traceable CRS in the client's template; and
7. leave the final engineering decision to an authorized human.

The system must generalize beyond the demonstration documents and beyond standards
explicitly named by a contractor.

## 2. Non-negotiable principles

### 2.1 Local, runtime-independent AI

- A **locally hosted model** is the primary reasoner. Normal production operation must
  not require internet access or transmit confidential content externally.
- No particular model family, quantization or serving runtime is permanent. Ollama,
  llama.cpp and other local runtimes are replaceable implementation choices.
- The production model/runtime/quantization combination is selected only by a measured,
  engineer-labelled evaluation on the target hardware.
- The current development machine has **16 GB total RAM**. Acceptance measures peak
  memory for the complete running system, including the operating system, backend,
  retrieval, embeddings, OCR, model weights, context and cache—not merely model-file
  size.
- Claude or another external model may be used only as an explicitly authorized
  benchmark or escalation lane. External success never closes an offline acceptance
  gate.

### 2.2 Evidence, abstention and human authority

- Every engineering claim must resolve to authorized source evidence.
- An ordinary compliance finding must preserve the contractor quote and location,
  requirement quote and location, reasoning, verdict, limitations and confirmation
  state.
- An omission finding uses a type-specific evidence contract instead of inventing a
  missing quote:
  - `MISSING_INFORMATION` preserves the governing requirement, the exact contractor
    pages/sections/fields searched and the applicability evidence showing the
    information was expected;
  - `COVERAGE_GAP` preserves the evidence that makes the omitted source applicable,
    the contractor's declared-source list or exact scope searched, and a requirement
    quote when the applicable source is locally available; and
  - `MISSING_LOCALLY` preserves the citation, contract/FEED obligation, normative
    reference or other evidence identifying the required source, plus the local
    availability search. It does not fabricate a requirement quote from an unavailable
    document.
- “Not retrieved” never means “not present.” “Not mentioned” never means “compliant.”
- Uncertainty produces an explicit safe outcome. In review workflows this is
  `NEEDS_ENGINEER_REVIEW`; in Q&A or analysis it is `INSUFFICIENT_EVIDENCE` or an
  equivalent visible limitation. Uncertainty can never produce automatic approval.
- The AI proposes. Deterministic validators check. An authorized engineer decides.

### 2.3 Retrieval, reasoning and deterministic validation

- Retrieval narrows the evidence. It does not decide compliance.
- The reasoning model reads the relevant submittal evidence and governing requirement
  evidence together and explains their relationship.
- Deterministic code validates quotations, document identity, revision, page, clause,
  table coordinates, units, conversions and arithmetic.
- Deterministic matching may pre-fill obvious checks or expose inconsistencies, but it
  is not the general reviewer and cannot bypass model reasoning and validation.

### 2.4 Independent applicability discovery

- Contractor-declared standards are claims to verify, not a complete applicability
  list.
- The system independently proposes applicable sources using contract and FEED scope,
  project specifications, equipment type, service, discipline, standard scope clauses,
  normative references and approved cross-company terminology mappings.
- Each candidate standard records why it was included or excluded and the evidence for
  that decision.
- A potentially applicable source omitted by the contractor becomes a `COVERAGE_GAP`
  requiring engineer confirmation.
- A required source unavailable locally becomes `MISSING_LOCALLY`. The system must not
  reconstruct authoritative requirements from model memory.

### 2.5 Untrusted documents and controlled learning

- Text in PDFs, spreadsheets, contracts, standards, FEED documents or internet sources
  is evidence, never an instruction to the system. It cannot alter prompts, tools,
  permissions, policies, thresholds or external-access settings.
- Engineer decisions may improve evaluation data, terminology mappings, applicability
  mappings, retrieval configuration and future training data.
- The system must never silently retrain itself, rewrite a source, change an approved
  mapping or promote AI-generated content into production policy.
- Learned changes require provenance, versioning, regression evaluation and authorized
  approval before activation.

### 2.6 Permissions and privacy

- Every input, intermediate artifact and output is permission-scoped.
- Extracted text, page images, tables, embeddings, chunks, prompts, logs, summaries,
  analyses, findings and reports inherit the source documents' access restrictions.
- API keys, tokens and credentials never appear in URLs, logs, prompts, reports,
  exports or client output.
- A multi-document output is visible only to a user authorized for **every** underlying
  source, unless an approved declassification workflow creates a separately governed
  artifact.
- Permission filtering occurs before retrieval and generation, never only after a
  result has been produced.

### 2.7 External access

Before any external call or online acquisition, all of the following are required:

- document-level egress approval;
- user and client authorization;
- confidentiality review and redaction where possible;
- legal right and licence to download, store, index and quote the source;
- verified provenance;
- conservative pre-call cost estimate and model-specific output-token cap; and
- enforcement of the approved per-step and total budget.

Market intelligence operates in a separate authorized online lane. Confidential
document content must never silently enter that lane.

## 3. Client requirements currently reported

These requirements were reported by Muhammad Usman after the 2026-09-20 demonstration.
They remain user-reported until the client confirms them in writing.

- Review contractor equipment datasheets from any company against applicable Saudi
  Aramco requirements available to the system.
- Do not rely only on standards named by the contractor; identify possible omissions.
- When a cited or independently identified standard is unavailable locally, the client
  expects the system to obtain it and compare. This remains subject to section 2.7 and
  V3 section 13.1, requires client authorization, and is otherwise reported as
  `MISSING_LOCALLY`.
- Explain why a finding exists, not only pass/fail.
- Support stakeholder-friendly Simple View and evidence-complete Engineering View.
- Answer questions about authorized datasheets, standards, contracts, FEED and project
  documents with citations and stated coverage.
- Summarize one document, selected documents or the authorized corpus with measured
  coverage.
- Support focused analysis, comprehensive analysis and gap analysis.
- Chat, Analysis, Reports and Review must return a cited result or a visible safe
  failure.
- Export a CRS using the client's supplied template and preserve its lifecycle.

Required CRS information includes:

1. Submittal number;
2. Contractor page/section;
3. Stable system-generated reference number;
4. Recommended review code;
5. Company comment;
6. Requirement source and exact locator—SAES/SAMSS clause, contract article, FEED
   section or project specification;
7. Source document and revision;
8. Contractor response;
9. Comment status; and
10. Final resolution.

Pending exact client confirmation: “Contractor will submit the documents as required
by the scope/FEED documents.” This must not be converted into a binding acceptance
criterion until the original wording and intended CRS representation are confirmed.

## 4. Review reproducibility and historical integrity

Every review run preserves or immutably references:

- hashes and revisions of all source documents;
- candidate, selected and excluded standards with reasons;
- applicability evidence;
- exact evidence text snapshots or content hashes, not only mutable row IDs;
- chunk, page, clause and table coordinates;
- versioned requirement records and extraction provenance;
- OCR, parser, embedding, retrieval and reranker versions;
- model name, model-file hash, quantization, runtime and context settings;
- system-prompt and task-prompt versions;
- deterministic calculations and validation outcomes;
- generated findings and review-code rationale; and
- every engineer confirmation, rejection, edit and final decision.

Re-extraction must not destroy historical evidence. Replacement uses versioning or
supersession, not destructive deletion that leaves findings orphaned.

## 5. Model and runtime selection policy

### 5.1 Frozen comparison

Candidate local models receive the same frozen evidence packets, prompts, tool access,
context limits and engineer-labelled expected outcomes. Tuning documents, regression
documents and blind acceptance documents remain separate.

### 5.2 Candidate range

Phase 0.5 proves one vertical reasoning path using one initially selected local
configuration on one frozen controlled packet. It does not select the production
winner. The multi-candidate comparison runs in V3 Phase 4, after the evidence substrate
from V3 Phase 2 exists and the owner has nominated the engineering labellers.

V3 Phase 4 may test multiple suitable model families and, where practical:

- 7B–9B models at several quality-preserving quantizations;
- 12B–14B models only if the complete system safely fits in the RAM of the deployment
  target being measured (16 GB on the development machine);
- specialized local extraction, embedding or reranking models; and
- multiple fully local runtimes behind the same internal inference interface.

This list is a test range, not a preselection. A larger model does not win automatically.

### 5.3 Selection measurements

The winning local configuration is chosen from measured results including:

- applicability recall and unsupported applicability proposals;
- missed critical findings;
- false compliant and false non-compliant findings;
- correct interpretation of conditions, exceptions, definitions and cross-references;
- table row/column/value integrity;
- quotation, page, clause and revision accuracy;
- correct abstention;
- repeatability across runs;
- peak total system RAM and failure under memory pressure;
- time to first result and complete review latency; and
- throughput with the approved number of users.

No model is declared production-ready because of reputation, parameter count, one good
example or performance through an external API.

## 6. Evaluation truth

- Discipline engineers label expected applicability and findings.
- A lead engineer adjudicates disagreements.
- A custodian holds a genuinely unseen blind split.
- A blind document becomes a regression document after its results are viewed; each
  acceptance run requires unseen documents.
- Documents previously inspected during development are regression documents, never
  described as blind acceptance evidence.
- AI may propose labels but cannot approve its own evaluation truth.
- Tests for reasoning quality use engineer-labelled outcomes; software tests alone do
  not establish engineering accuracy.

## 7. Release rule

- The approved V3 mandatory acceptance cut line is one client-release gate unless the
  client explicitly authorizes separate acceptance scopes in writing.
- Phase 0.5 and all other partial demonstrations are internal milestones.
- No release occurs because screens exist, tests pass, Claude succeeds or one CRS looks
  correct.
- Release requires the complete mandatory evidence package, measured on the approved
  local configuration and signed by the authorized owner and engineering reviewers.

## 8. Checklist before every decision

Stop if any answer is “no” or is unknown without an explicit verification task.

- Does it scale from clause 10 to clause 10,000 without a new hand-written rule?
- Is the model reasoning over evidence rather than relying on a pairing table?
- Is each claim supported by the correct document, active revision and exact locator?
- Are tables, conditions, exceptions, definitions and cross-references preserved?
- Was applicability independently assessed rather than copied from the contractor?
- Does “not retrieved” remain distinct from “not present”?
- Is the result shown only to users authorized for every source behind it?
- Does a multi-source artifact require access to all sources?
- Is document content treated as untrusted data?
- Is any external action authorized, licensed, funded and necessary?
- Can the complete review be reproduced after reprocessing?
- Does failure produce abstention rather than approval?
- Is engineering truth independently labelled and mutation-sensitive where applicable?
- Was the fact verified on the real machine, or clearly labelled reported/unknown?
- Does this work advance a client requirement inside the approved acceptance cut line?
- Is Git protected and is any database migration tested on a complete stopped copy,
  including WAL/SHM where applicable?

## 9. Owner approval record

Muhammad Usman alone records approval here.

- This file: not yet approved.
- Approved `NORTH-STAR.md` locator: `<Git commit and/or SHA-256>`
- Approved V3 locator: `<Git commit and/or SHA-256>`
- Approved on: `<date and timezone>`
- Approved by: `<name>`
- CRS scope/FEED wording: awaiting exact client confirmation.
- Release structure: awaiting owner decision.
