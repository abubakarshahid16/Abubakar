# S6. Human approval for high-risk actions (Q41)

The owner approves **in writing on #692** before any of these:

- any change to the live database, or a re-extraction (a verified backup comes first; `live_guard.prepare_live_write`);
- sending any new document to an external AI (it must first be added to the approved list, S3);
- merging a change that switches an AI step off or widens AI access (the AI register, S2, shows this in the diff);
- deleting files or data;
- creating or widening any token or connection.

These approvals already happen in practice. This list makes them official.
