# S6. Human approval for high-risk actions (Q41)

The owner approves **in writing on #692** before any of these:

- any change to the live database, or a re-extraction (a verified backup comes first; `live_guard.prepare_live_write`);
- sending any new document to an external AI, except chat requests where the user explicitly chooses Claude and selects the exact files for that request (owner decision in #692; non-chat workflows still require the approved list, S3);
- merging a change that switches an AI step off or widens AI access (the AI register, S2, shows this in the diff);
- deleting files or data;
- creating or widening any token or connection.

These approvals already happen in practice. This list makes them official.

## Who merges

From #805 rule 5, as amended by planner orders 44, 46 and 48 on #692 (order 44 approved by the owner in writing, 17 Oct 2026). Changing this table needs the owner's written approval on #692.

| Merger | Merges |
|---|---|
| s2 | Review-path and danger-zone (CLAUDE.md rule 6) PRs |
| s1 | Frontend, docs, security and privacy PRs |
| cloud | cloud-2's PRs that are off the review path and not danger-zone |

Nobody merges their own PR. Every merge passes the full gate first (main plus the PR: mutation anchors, quality ratchet, tests, Windows, secret scan; the PR's head unmoved) and is reported on #692.

