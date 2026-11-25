# Technical Query Implementation Progress

This file is an implementation record for the isolated technical-query worktree.
It contains no client message text, document numbers, names or credentials.

## Completed

- Query, message, attachment, draft, evidence, decision, send and event tables.
- Idempotent provider-message import and provider-thread follow-up matching.
- Owner/admin query visibility and source-document permission checks.
- Attachment upload through the existing guarded document ingestion path.
- Exact-quote validation for manually attached evidence.
- Permission-scoped evidence preparation using existing search.
- Lifecycle guards for draft, approval, rejection, closure and send preparation.
- Dependency-free Word response renderer.
- Technical Queries frontend queue and detail view.
- Provider-neutral Graph/Gmail notification boundary.
- Synthetic smoke checks, backend lint and frontend type-check.

## Remaining independent implementation

- Provider fetch worker and reconciliation cursor; adapter activation requires an approved mailbox and credentials.
- Draft citation-to-evidence binding and conflict/supersession classification.
- Rich frontend edit, approve, response preview and resolution actions.
- Provider-backed send worker; activation remains disabled until explicitly approved.
- Full automated suite once local model artifacts are staged.

## Safety state

- Worktree only: `workspaces/technical-query`.
- No live database or live service changed.
- No secret or credential inspected.
- No external mailbox connected.
- No external message sent.

## Review and approval controls (26 Nov 2026 practice-app pass)

- A person confirms the question the draft answers; drafting runs the shared answer checks on that confirmed text only.
- The `technical_query_reviewer` capability is separate from `admin`. It is required to confirm a question, change evidence, approve or decline a draft, close a query and send. An administrator grants or revokes it for someone else (never for themselves); each change is in the admin audit log. `scripts/seed_access.py --role technical_query_reviewer` also assigns it.
- Evidence taken from any contractor attachment is not searched. Rows saved before that rule are moved once to `needs_review`; approval and send are refused until a reviewer keeps or rejects each one. A reviewer's decision is not undone by a later sweep.
- The contractor-facing Word file lists only verified evidence.
- Not done: real Gmail connect, import and send; attachment malware scanning; retention and deletion policy; contractor and department routing rules; full release gates and backup rehearsal.
