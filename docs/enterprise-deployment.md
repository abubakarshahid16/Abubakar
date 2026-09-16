# Enterprise deployment hardening track

This document is the release gate for production deployment. The current
application is a single-host, loopback-bound prototype; the controls below
describe the target deployment and the evidence required before claiming it is
enterprise-ready.

## Target architecture

- Keep the FastAPI service and SQLite corpus on an isolated application host.
- Put the browser behind an approved reverse proxy or private ingress with TLS.
- Keep document text, embeddings, OCR, and answer traffic inside the approved
  network boundary; no public egress is enabled by default.
- Integrate SSO through the organisation's chosen OIDC/SAML gateway. Map groups
  to application roles and retain local admin recovery for break-glass use.
- Store signing keys and any future provider keys in the organisation's secret
  manager, never in `.env`, source control, or browser storage.

## Recovery and availability

- Back up the SQLite database and its WAL safely while the service is stopped
  or via a tested consistent snapshot procedure.
- Back up the corpus files and vector store together with the database; restore
  them as one versioned snapshot.
- Record backup age, checksum, and restore result. A backup that has never been
  restored is not a recovery plan.
- For high availability, replace the single-host SQLite design with a reviewed
  shared database and object store. Do not place two writers on one SQLite file.

## Required drills before production

1. Clean air-gapped install from the documented release artifact.
2. Restore a snapshot into an empty host and verify document counts, citations,
   authentication, and report downloads.
3. Rotate the signing key and confirm planned session invalidation behavior.
4. Simulate host loss and record measured recovery time and data loss window.
5. Run load and soak tests with OCR, ingestion, and answering concurrent.
6. Verify monitoring alerts for stalled ingestion, low disk, model failures,
   authentication failures, and backup age.

## Current status

Implemented today: loopback binding, offline model staging, authentication and
RBAC, token revocation, bounded upload/OCR resources, secret scanning, and
documented backup/restore primitives.

Not implemented or not validated: SSO, enterprise key management, packaged
installer, automated disaster recovery, high availability, real monitoring,
load/soak evidence, and a production restore drill. These remain explicit
gates, not implied capabilities.
