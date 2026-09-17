# ADR-0016: Automatic risk detection from workflow state

Risk records are created from existing tracked state: overdue deliverables,
aged open findings, overdue WBS parents, and unresolved requirement evidence.
Each condition is idempotent while open, links to its triggering record, and
uses the audited notification path. Manual risk entry remains supported.
