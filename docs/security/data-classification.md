# S3. Data classification (Q34, Q35)

| Class | Examples | External AI? |
|---|---|---|
| Public | Public copies of international standards, product brochures | Allowed |
| Internal | Code, synthetic test files, plans | Allowed, without document text |
| Confidential | KJO submittals, company standards (SAES), CRSs, review results | **Only** through `reader_transport.py`, and **only** for documents the owner approved in writing (the list is kept in the AI register, S2) |
| Restricted | Passwords, API keys, `backend/.env`, personal data | **Never** |

- The code already blocks every other outbound path for document content (CLAUDE.md, standing rule 1). Only four modules may open a socket, each behind a gate.
- **Still to add (s1, small code PR):** the Claude lane refuses a document whose id is not on the owner's approved list, with a test.
- **Done when:** this list is committed, and the approved-list check is merged with its test.
