# EPC platform implementation issue plan

This is the delivery plan for turning the existing local RAG application into
the EPC engineering-submittal platform. It is deliberately staged so every
feature is testable and reviewable before it reaches `main`.

## Product boundary

The current RAG system remains the evidence engine: ingestion, access control,
keyword/vector retrieval, reranking, citations, evidence viewing, Q&A, gap
analysis, reports, administration, dashboard, and the isolated market lane are
preserved. The new work adds a controlled EPC workflow layer above it.

The client contract, project specifications, employer information requirements,
approved templates, applicable codes, and project procedures are the acceptance
authority. Standards guide the workflow but never replace project-specific
requirements or engineering approval.

## Milestones

### M0 Governance and source register

**Issue:** Define the project source hierarchy and review vocabulary.

Deliverables:

- source-of-truth register for contract, requirements, standards, templates,
  and procedures;
- review roles: author, reviewer, approver, owner, stakeholder, escalation
  contact;
- comment categories and severity levels;
- status and approval terminology;
- escalation levels, triggers, retention, and audit rules;
- client-approved submittal review template.

Acceptance: a real client review example can be mapped to the vocabulary with
no invented acceptance rule.

### M1 Submittal and revision register

**Issue:** Add controlled submittal packages and immutable revision history.

Deliverables:

- package, document, discipline, document type, revision, and WBS links;
- applicable requirements and standards;
- reviewer, approver, owner, planned dates, and current state;
- revision-to-revision comparison metadata;
- access-controlled audit history.

Acceptance: a reviewer can open one package and see the exact revision,
requirements, owners, review state, and source documents.

### M2 AI engineering submittal review

**Issue:** Review a submitted document against nominated requirements.

Deliverables:

- requirement extraction and evidence retrieval;
- missing-information, inconsistency, deviation, and technical-query findings;
- finding severity/category and confidence/uncertainty;
- exact document/page citations;
- clear engineering prose: Finding, Evidence, Why it matters, Required action;
- explicit human-review disclaimer; no automatic engineering acceptance.

Acceptance: every finding is traceable to a source page or is marked
insufficient evidence. A real completed client review produces comparable
findings and no unsupported compliance claim.

### M3 Human review, response, and approval workflow

**Issue:** Convert AI findings into assignable engineering review comments.

Deliverables:

- assign owner/reviewer/approver;
- required action and response fields;
- open, in-progress, awaiting-response, resolved, deferred, rejected;
- approval history and reviewer identity;
- comment response and closure evidence;
- exportable review register/PDF.

Acceptance: an engineer can assign, respond to, approve, reject, defer, and
close a finding while preserving the original AI evidence and audit history.

### M4 WBS and deliverable tracking

**Issue:** Link EPC work structure to information and reviews.

Deliverables:

- WBS hierarchy and work packages;
- activities, deliverables, dependencies, dates, and status;
- links from WBS to documents, reviews, risks, actions, and stakeholders;
- deliverable register views for upcoming, due, overdue, delayed, completed,
  and at-risk work.

Acceptance: selecting a WBS element shows what is due, who owns it, what
documents/reviews are linked, and what is at risk.

### M5 Reminder and escalation engine

**Issue:** Automate follow-up and escalation without changing evidence.

Deliverables:

- configurable reminder rules;
- reminders for upcoming, due, overdue, pending response, and pending approval;
- escalation matrix with levels, contacts, triggers, and response windows;
- escalation history and acknowledgement;
- local job/audit record for every generated notification.

Acceptance: a controlled test deliverable triggers the configured reminder and
escalation path, and repeated runs do not duplicate notifications.

### M6 Management dashboard and reporting

**Issue:** Give management a traceable project-control view.

Deliverables:

- open findings by severity/category/discipline;
- deliverable and review status;
- overdue actions, risks, approvals, and escalations;
- daily/weekly summary with drill-down;
- PDF/export reports linked to source records and evidence.

Acceptance: dashboard totals reconcile with registers and every metric drills
down to an underlying record; no metric is inferred from missing data.

### M7 Pilot, security, and client acceptance

**Issue:** Validate the complete workflow on one real project package.

Deliverables:

- real client review example and approved template;
- role/access test;
- revision and response test;
- citation and evidence audit;
- reminder/escalation test;
- performance and failure-path test;
- client sign-off record.

Acceptance: the client confirms that the review is clearer than the current
manual process, findings are traceable, and the report/workflow terminology is
acceptable.

## Standards alignment

- ISO 9001: controlled documented information, objective evidence, corrective
  action, and auditability.
- ISO 10006: project quality planning, responsibility, measurement, analysis,
  and improvement.
- ISO 21502: project planning, control, risk, issue, change, information, and
  governance.
- ISO 21511: WBS and work-package structure.
- ISO 19650-1/-2 where BIM/information management applies: controlled
  information containers, delivery, review, approval, and revision exchange.

## Branch and merge policy

1. Create one feature branch per milestone or tightly coupled issue group.
2. Keep the standards/issue plan and implementation commits separate.
3. Add focused backend/frontend tests with every issue.
4. Run backend tests, frontend tests, type-check, production build, security
   checks, and the real retrieval/evidence regression suite.
5. Review the diff for feature removal, privacy leaks, and unsupported claims.
6. Push the feature branch and open a pull request with the milestone and test
   evidence.
7. Merge into `main` only after the relevant gate passes. Never force-push or
   overwrite unrelated work.

## Current state

The standards milestone document is already published on the feature branch.
The EPC workflow implementation is not complete and must not yet be described
as complete or merged into `main`.
