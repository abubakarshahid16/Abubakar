# S9. Roles, escalation and severity (Q45)

| Severity | Example | Report to | Within |
|---|---|---|---|
| S1 Critical | Confidential documents or keys leaked; an agent acting outside its access | The owner, then KJO IT security | 1 hour |
| S2 High | An unapproved document sent to an external AI; a key exposed in a log or chat | The owner, then KJO IT security | 4 hours |
| S3 Medium | An agent broke a rule without data leaving (for example, it touched `backend/.env`) | The owner | 1 day |
| S4 Low | A failed check or a near miss | #692 | The next report |

**Roles:**
- The **owner** is the incident lead.
- **KJO IT security** is the escalation contact. **The owner fills in the name and contact route here** (not in a public comment).
- **Legal and communications** are contacted through KJO IT for an S1 incident.
