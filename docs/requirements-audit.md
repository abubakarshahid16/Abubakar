# KJO EPC requirements scorecard

Status is evidence-based: DONE means the feature is usable in the UI and has
automated coverage; PARTIAL means infrastructure or a screen is still missing;
BLOCKED means it requires a client-approved input.

| # | Client area | Status |
|---:|---|---|
| 1 | AI engineering/submittal review | PARTIAL |
| 2 | Standardized pre-configured templates | BLOCKED — client templates |
| 3 | EPC timeline and deliverable tracking | DONE |
| 4 | Automated reminders | PARTIAL |
| 5 | Escalation matrix | PARTIAL |
| 6 | WBS hierarchy | DONE |
| 7 | Document and deliverable management | DONE |
| 8 | AI search and question answering | DONE |
| 9 | AI gap and risk identification | DONE |
| 10 | Management dashboard and reports | DONE |
| 11 | Baseline-rule selection | DONE |
| 12 | Named comparison workflows | DONE |
| 13 | Expected/missing deliverable intelligence | DONE |
| 14 | Structured EPC search | DONE |
| 15 | Typed risk register | DONE |
| 16 | Review traceability | PARTIAL |
| 17 | Stakeholder roles and approval workflow | DONE |

The scorecard is intentionally not inflated: client templates and the remaining
reminder/escalation and review traceability workflow surfaces remain partial or
blocked. Automatic deliverable inference and typed risk detection are measured
and covered by regression tests.
