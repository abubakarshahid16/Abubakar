# EPC platform standards and milestones

This plan governs the EPC workflow layer added to the existing local RAG
system. The client contract, project specifications, employer information
requirements, approved project templates, and applicable discipline codes are
the acceptance authority. ISO guidance structures the workflow; it does not
replace a project requirement or authorize an engineering acceptance decision.

## Standards framework

| Area | Reference | Product implication |
| --- | --- | --- |
| Quality records and corrective action | ISO 9001 | Preserve controlled review records, objective evidence, actions, responses, and audit history. |
| Quality management in projects | ISO 10006:2017 | Provide project quality planning, assigned responsibility, measurement, analysis, and improvement records. |
| Project governance and control | ISO 21502:2020 | Link planning, risk, issue, change, information, and decision records to project work. |
| Work breakdown structure | ISO 21511:2018 | Represent work packages, activities, deliverables, dependencies, and ownership as a traceable hierarchy. |
| Built-environment information management | ISO 19650-1/-2 where applicable | Treat submissions, revisions, reviews, approvals, and information exchanges as controlled information containers. |

## Source and decision hierarchy

1. Client contract and project specifications.
2. Employer/project information requirements and approved design basis.
3. Applicable discipline codes, standards, and regulatory requirements.
4. Approved project templates, BEP, QCP/ITP, and review procedures.
5. Internal workflow defaults.

The AI must show which source supplied every finding. It must label uncertainty
and cannot declare engineering acceptance, compliance, or approval on behalf of
an authorized engineer.

## Delivery milestones and acceptance gates

### M0 Governance baseline

Configure source hierarchy, review roles, approval terminology, comment
categories, severity levels, status values, escalation levels, retention, and
the project-specific standards register.

**Gate:** one approved review template and one source-of-truth register exist.

### M1 Submittal and revision control

Create a submittal record for each document package, including document type,
revision, discipline, WBS location, applicable requirements, reviewer,
approver, planned dates, and current status. Preserve immutable revision history.

**Gate:** a reviewer can open a package and see its requirements, documents,
revisions, ownership, and review state.

### M2 AI engineering review

Run retrieval against the submitted document and nominated requirements. Return
structured findings with requirement reference, cited document/page evidence,
finding, category, severity, confidence/uncertainty, and required action.

**Gate:** every finding resolves to evidence or is explicitly marked as
insufficient evidence; no unsupported acceptance claim is produced.

### M3 Human review and response workflow

Allow an authorized reviewer to assign, edit, accept, reject, defer, respond to,
and close comments. Keep reviewer identity, timestamps, response text, and
approval history.

**Gate:** a complete review can be exported with open, closed, deferred, and
unresolved findings clearly separated.

### M4 WBS and deliverable control

Link WBS elements to activities, deliverables, documents, reviews, risks,
actions, dependencies, and stakeholders.

**Gate:** selecting a WBS item shows what is due, who owns it, what evidence is
attached, and what is at risk.

### M5 Reminders and escalation

Configure reminder rules for upcoming, due, overdue, and waiting-for-response
items. Escalate by missed deadline, review delay, critical finding, dependency
delay, repeated overdue status, or no response. Retain escalation history.

**Gate:** a test deliverable produces the expected reminder and escalation path
without changing the underlying review evidence.

### M6 Management reporting

Provide dashboards and daily/weekly summaries for deliverables, review status,
open findings, risks, overdue actions, approvals, and escalations. Every metric
drills down to its underlying record and evidence.

**Gate:** report totals reconcile with the register and can be traced to source
records.

### M7 Pilot and acceptance

Validate the complete flow against one real completed client review, the client
template, required standards, comment taxonomy, approval terminology, and
revision/response workflow.

**Gate:** client sign-off on review clarity, evidence traceability, workflow
states, report format, and alert/escalation behavior.

## Preservation rule

The existing document ingestion, local search/vector retrieval, reranking,
conversation history, citations, evidence viewer, gap analysis, PDF reports,
admin access controls, dashboard, and isolated market lane remain in place.
The EPC workflow is added above these capabilities rather than replacing them.
