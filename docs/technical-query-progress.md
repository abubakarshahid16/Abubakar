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
- Mailbox webhooks stay disabled (503) until push authentication and durable queueing exist; the unused notification-normalizer module was moved aside.
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
- Every state a response has ever been in, every decision, every evidence change and every send attempt stays in the database. The original email is preserved as received.
- Evidence that is conflicting or ambiguous also blocks approval and send until a reviewer resolves it.

## Attachment checks

- Each PDF attachment gets a static check for active content (scripts, launch actions, embedded files, rich media, form submission). It is NOT an antivirus scan and the screen says so. A flagged PDF keeps its original available, but its text is not pulled into a proposed question. A file that cannot be found is shown as "not checked". If an antivirus tool is added later, it should write its own status beside this one.

## Routing

- An administrator maps an exact sender address, or a company domain, to a contractor and department. A match fills only blank fields when an email arrives and is shown as "from a routing rule"; saving routing by hand overrides it. Public mail domains cannot be routed by domain, because they do not identify a company; an exact address on one can.
- The queue filters by status, contractor, department, responsible person, received date range and evidence state; the count beside the list uses the same filters except status.

## Retention and deletion

- The application deletes nothing: queries, messages, attachments, evidence, drafts, decisions and send records are kept. This follows the project rule that nobody deletes. Removing a record is a deliberate, backed-up, owner-approved database operation outside the application, not a button.

## Tests

- `backend/tests/test_technical_queries.py` includes one complete workflow test from email to resolution through the real route functions, with only search, the answer model and Gmail replaced.
- `backend/tests/test_attachment_safety.py` covers the static check.

## Not done (needs the owner or a real account)

- Real Gmail connect, import, polling, thread reply and token expiry or revocation; they need an authorized test account.
- Release gates on a live update: backup and rehearsal, and the owner's go.
