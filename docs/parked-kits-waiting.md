# Parked kits that wait for the owner's examples (#1482, #1483)

Scoping on the library copy of 2026-11-01 (documents + standard_requirements, read only).
Rule 4: no requirement is invented. A kit item cites the held clause that REQUIRES it, or says it is a DRAFT.

| Kind | Issue | Held standard that requires its content | Kit |
|---|---|---|---|
| Drawing | #1484 | SAES-A-202 (794 stored requirements; title block, revision block, scale, tags, drawing numbers) | Built, DRAFT: `reference/kind_kits/drawing.json`, 7 held items, 7 DRAFT items, behind `PARKED_KITS_DRAFT_ENABLED` (off) |
| Transmittal | #1482 | None. The only hits for "transmittal" are SAES-X-400 and SAES-X-700 (a QA checklist attached to the cover letter or transmittal sheet of a cathodic-protection or well-casing design package), and SAES-L-105, SAES-W-011, SAES-W-013 and SAES-M-100 (a passing word). No held clause says what a transmittal must contain. | Not built |
| Contract | #1483 | None. The held contract schedule files are contract forms with 0 stored requirements; no held standard requires content of a contract or schedule. | Not built |

## What a real transmittal kit needs

- 3 to 5 real transmittals from the owner (the sheet a contractor sends with a submittal), with the engineer's note of what is checked on each.
- The owner's transmittal procedure or the project's document-control procedure (document number format, revision and status codes, due dates), as a held document.
- From those: the list of fields every transmittal must carry (document number, revision, status code, date, list of documents), the codes allowed, and how the list is compared with what was received.

## What a real contract kit needs

- 3 to 5 real contracts or schedules (for example one schedule and its attachments in full) with the engineer's note of what is checked.
- The list of required clauses per schedule, from the owner's contract-review checklist (not from the schedule itself, which says what the contractor does, not what a contract must contain).
- The KJO standards the contract is compared with, already held, and the deliverables register for "deliverables against transmittals".

Until then the router still names these kinds (`document_kinds`), the kind chooses the rule set (#1474), and nothing else runs on them.
