# Security controls pack

The controls behind the cybersecurity questionnaire, rows 31 to 50 (#806, Stage S of #805). There is one file per control. Each file says which question it answers, who acts, and what proves it is done.

| Control | Question(s) | File | Status |
|---|---|---|---|
| S1 Responsibility matrix | Q31 | [responsibilities.md](responsibilities.md) | Committed; owner to confirm the Anthropic and GitHub terms |
| S2 AI register | Q33, Q37, Q39 | [ai-register.md](ai-register.md) | Committed; CI-checked; owner to sign once on #806 |
| S3 Data classification | Q34, Q35 | [data-classification.md](data-classification.md) | Committed; the approved-list check is s1's code PR |
| S4 Least privilege for AI agents | Q38 | [least-privilege.md](least-privilege.md) | Committed; items 1, 2 and 5 are the owner's |
| S5 Logging and monitoring | Q40 | [logging.md](logging.md) | Committed; first weekly check by s2 |
| S6 Human approval for high-risk actions | Q41 | [approvals.md](approvals.md) | Committed |
| S7 Kill switch | Q42 | [kill-switch.md](kill-switch.md) | Committed; to be tested in the S10 drill |
| S8 Incident response | Q44 | [incident-response.md](incident-response.md) | Committed |
| S9 Roles, escalation and severity | Q45 | [severity-and-roles.md](severity-and-roles.md) | Committed; owner to name the KJO IT security contact |
| S10 Exercises | Q46, Q47 | [exercises.md](exercises.md) | Committed; first drill within 2 weeks |
| S11 Forensics and evidence | Q48 | [evidence.md](evidence.md) | Committed |
| S12 Threat levels | Q50 | [threat-levels.md](threat-levels.md) | Committed |

**Machine check:** `backend/tests/test_806_security_docs.py` (and `scripts/check_ai_register.py`) fails CI in two cases:
- a file above is missing;
- the AI register's switch table does not match the AI switches in `backend/app/config.py`, by name and by default.

A new AI switch, a removed one, or a changed default therefore cannot merge without updating the register.

**Hardening checks in CI (#521):** secrets by `secret-scan.yml` (gitleaks, history and working tree); uploads validated in `backend/app/upload.py` (PDF signature, workbook structure, zip-bomb limits); runtime dependencies by `dependency-audit.yml` (pip-audit on `backend/requirements.txt`, `npm audit --omit=dev`, high or critical fails the check).

These files describe controls. They never contain a key, a password, a document's text or a client's name.
