# KJO EPC requirements scorecard

Status is evidence-based: DONE means the feature is usable in the UI and has
automated coverage; PARTIAL means infrastructure or a screen is still missing;
BLOCKED means it requires a client-approved input.

| # | Client area | Status |
|---:|---|---|
| 1 | AI engineering/submittal review | DONE — authenticated browser review produced cited findings with severity, owner, and due date |
| 2 | Standardized pre-configured templates | BLOCKED — client templates |
| 3 | EPC timeline and deliverable tracking | DONE |
| 4 | Automated reminders | PARTIAL — delivery provider and live email not verified |
| 5 | Escalation matrix | PARTIAL — delivery provider and live email not verified |
| 6 | WBS hierarchy | DONE |
| 7 | Document and deliverable management | DONE |
| 8 | AI search and question answering | DONE |
| 9 | AI gap and risk identification | PARTIAL — risk register works, but automatic-risk provenance and notification are not live-verified |
| 10 | Management dashboard and reports | PARTIAL — report records are present, but a fresh download/open was not confirmed |
| 11 | Baseline-rule selection | DONE — auto-selected badge and manual override were both observed in the review screen |
| 12 | Named comparison workflows | DONE — Baseline vs submittal was selected and returned cited review results |
| 13 | Expected/missing deliverable intelligence | DONE |
| 14 | Structured EPC search | DONE |
| 15 | Typed risk register | DONE — manual creation and all four type filters were observed in the browser |
| 16 | Review traceability | DONE — full chain rendered: Finding, Document, Baseline, Citation, Deliverable, Owner, Action |
| 17 | Stakeholder roles and approval workflow | DONE — owner, reviewer, approver, and informed assignments were saved and displayed |

Live verification on 2026-09-17, authenticated as `testadmin`, confirmed the
review, baseline, comparison, risk-register, traceability, and stakeholder
workflows. SMTP is disabled in this environment (`SMTP_ENABLED` is not set),
so reminder, escalation, and automatic-risk email delivery remain genuinely
unverifiable rather than being marked complete. A fresh report download/open
was also not confirmed. Client templates remain blocked on client input.
