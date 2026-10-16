# S3. Data classification (Q34, Q35)

| Class | Examples | External AI? |
|---|---|---|
| Public | Public copies of international standards, product brochures | Allowed |
| Internal | Code, synthetic test files, plans | Allowed, without document text |
| Confidential | KJO submittals, company standards (SAES), CRSs, review results | **Only** through `reader_transport.py`. For chat collection summaries, the user's explicit Claude choice plus explicit document selection is consent for only those selected files on that request; every other Claude workflow still requires the owner-approved list (S2). |
| Restricted | Passwords, API keys, `backend/.env`, personal data | **Never** |

- The code already blocks every other outbound path for document content (CLAUDE.md, standing rule 1). Only four modules may open a socket, each behind a gate.
- **Enforced:** every Claude call declares its document scope. Collection-summary consent is request-scoped and cannot be reused by another workflow; other Claude workflows remain on the owner-approved list. Unknown document ids and undeclared content are refused.
- **Done when:** the request-scoped summary consent, unchanged egress/spending gates, and the owner-list checks for other workflows pass their tests.

