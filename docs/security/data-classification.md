# S3. Data classification (Q34, Q35)

| Class | Examples | External AI? |
|---|---|---|
| Public | Public copies of international standards, product brochures | Allowed |
| Internal | Code, synthetic test files, plans | Allowed, without document text |
| Confidential | KJO submittals, company standards (SAES), CRSs, review results | **Only** through `reader_transport.py`. In chat, the user's explicit Claude choice plus explicit document selection is consent for only those selected files on that request; every non-chat Claude workflow still requires the owner-approved list (S2). |
| Restricted | Passwords, API keys, `backend/.env`, personal data | **Never** |

- The code already blocks every other outbound path for document content (CLAUDE.md, standing rule 1). Only four modules may open a socket, each behind a gate.
- **Enforced:** every Claude call declares its document scope. Chat consent is request-scoped and cannot be reused by another workflow; prior document-bearing history is filtered to the current selection. Other Claude workflows remain on the owner-approved list. Unknown document ids and undeclared content are refused.
- **Done when:** the request-scoped chat consent, unchanged egress/spending gates, and the owner-list checks for other workflows pass their tests.
- **A browser credential is now stored on the user's disk (owner order 164.2, PR #1242).** The sign-in is an `HttpOnly`, `SameSite=Strict` session cookie (`rag_session`, 8 hours): the page cannot read it, but the browser keeps it across a restart, so on a shared workstation the user must sign out. Sign-out ends that token on the server (`revoked_sessions`), so a copy of it is refused. It is a Restricted item: never in a log, URL or error body (tested).
