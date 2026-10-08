# ADR-0016: Automatic risk detection from workflow state

Risk records are created from existing tracked state: overdue deliverables,
aged open findings, overdue WBS parents, and unresolved requirement evidence.
Each condition is idempotent while open, links to its triggering record, and
uses the audited notification path. Manual risk entry remains supported.

## Amendment 2026-10-08 (W7 P0, #478 #608): where detection runs

Detection does NOT run inside `GET /api/risks`, or inside any GET. It runs from
`risks.run_detection`: a background thread every `RISK_DETECTION_INTERVAL_SECONDS`
(default 900, 0 = off) and `POST /api/risks/detect` (admin only). It is
single-flight, reads the existing open risks once and diffs, inserts the new
risks in one transaction, and sends ONE digest email per run, rate-limited by
`RISK_DIGEST_MIN_INTERVAL_SECONDS`. The same job creates the due reminder
events (`deliverables.generate_reminders`); `GET /api/management/reminders`
only reads them.
