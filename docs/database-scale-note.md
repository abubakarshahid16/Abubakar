# Database and vector-service scale note

The current product uses local SQLite plus FTS5 and a local memory-mapped
dense-vector cache. That is appropriate for a private prototype and a single
operator, but it is not the target architecture for one million pages and five
or more concurrent users.

## Recommended direction

Use PostgreSQL as the system of record and start with `pgvector` for embeddings.
It keeps document, review, deliverable, risk, stakeholder, audit, and citation
transactions in one access-controlled database while allowing vector search in
the same scope query. A dedicated vector service should be considered only if
measured corpus size, recall, or query throughput exceeds the operating window
of a tuned PostgreSQL deployment; it adds a second consistency and tenancy
boundary.

## Migration approach

1. Freeze the current SQLite schema and export documents, pages, chunks,
   citations, workflow records, and audit events with stable UUIDs.
2. Create versioned PostgreSQL migrations matching the existing tables and add
   tenant/project scope columns and indexes before loading data.
3. Bulk-load metadata, then rebuild FTS and vector indexes from the canonical
   chunk rows. Validate row counts, document hashes, page citations, and
   retrieval gold questions before cutover.
4. Run dual-read comparisons in staging. Keep SQLite read-only as a rollback
   snapshot until answer, access-scope, and report parity are demonstrated.
5. Cut over behind a configuration flag, then remove local mutable state only
   after backup/restore and failure-recovery tests pass.

## Operational requirements

Use connection pooling, encrypted backups, point-in-time recovery, per-project
authorization filters, background ingestion workers, and object storage for
original PDFs/page images. Keep embeddings versioned so a model change can be
reindexed without invalidating citations.

## Rough effort

Schema/export and a staging parity harness are a medium project (roughly
2–4 weeks for one engineer familiar with the codebase). Production hardening,
load testing, backups, observability, and cutover add roughly 2–4 more weeks.
These are planning estimates, not a commitment; page mix, OCR volume, and
concurrency measurements should refine them.

No migration is performed by this note.
