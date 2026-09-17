# KJO EPC requirements scorecard

Status is evidence-based: DONE means the feature is usable in the UI and has
automated coverage; PARTIAL means infrastructure or a screen is still missing;
BLOCKED means it requires a client-approved input.

| # | Client area | Status |
|---:|---|---|
| 1 | AI engineering/submittal review | PARTIAL — browser workflow still needs a clean authenticated end-to-end pass |
| 2 | Standardized pre-configured templates | BLOCKED — client templates |
| 3 | EPC timeline and deliverable tracking | DONE |
| 4 | Automated reminders | PARTIAL — delivery provider and live email not verified |
| 5 | Escalation matrix | PARTIAL — delivery provider and live email not verified |
| 6 | WBS hierarchy | DONE |
| 7 | Document and deliverable management | DONE |
| 8 | AI search and question answering | DONE |
| 9 | AI gap and risk identification | PARTIAL — automatic risk notification not live-verified |
| 10 | Management dashboard and reports | PARTIAL — dashboard is present; report generation not live-verified in this pass |
| 11 | Baseline-rule selection | PARTIAL — backend is present; review-screen auto-selection needs authenticated browser verification |
| 12 | Named comparison workflows | PARTIAL — selector is present; comparison execution not live-verified in this pass |
| 13 | Expected/missing deliverable intelligence | DONE |
| 14 | Structured EPC search | DONE |
| 15 | Typed risk register | PARTIAL — UI exists; create/filter flow not live-verified in this pass |
| 16 | Review traceability | PARTIAL — backend chain verified; authenticated UI action still needs verification |
| 17 | Stakeholder roles and approval workflow | PARTIAL — backend/UI wiring exists; approval flow not live-verified in this pass |

The scorecard is intentionally not inflated. This pass verified the four
structured-search kinds in the browser and verified the complete traceability
chain directly through the backend. It did not mark a requirement DONE when
the final authenticated browser workflow or an actual notification/report
delivery was not observed. Client templates remain blocked on client input.
