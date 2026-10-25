---
name: release-train
description: How a night's fixes become a release on this project: one feature per PR, who reviews, what is proven on the Mac, and how a release branch merges. Use when planning, reviewing, or merging more than one PR in a session.
---

# The release train

Read this instead of re-deriving it. The planner's orders on #692 are the source of truth; if this file and an order differ, the order wins and this file is fixed.

## Roles (one agent each; "cloud" is a different agent from "cloud-2")
- **s1** builds the release branch (`s1/release-quality-<n>`) from main plus the approved PRs, in the order they were approved, and re-merges a PR whose head changed.
- **s2** proves the release on the Mac (the local model, a diagnostic copy of the live database, never the live one) and **merges**. Nobody merges their own PR.
- **cloud, cloud-2, cloud-3** build one PR per feature and review each other's: danger-zone files are reviewed by two sessions within 15 minutes of a new head.
- The planner gives orders and never merges.

## A PR
1. One feature = one PR, branch from the release branch it will ride (or main). `Refs #692` only: never write close / fix / resolve before #692 or #805.
2. General fixes only (order 143): no code naming a datasheet, field label, tag or a standard's part list; units and physics may be code; word lists are a last resort with a reason per word.
3. Tests that fail without the fix (check once by hand). Mutation entries `M<PR>-NN` and audit entry `A-<PR>` only in the danger zone (rule 6). Big screen changes sit behind an OFF switch.
4. A fresh-eyes review by an agent that did not write it, before "PR ready".
5. Validate before every push: the changed test files, `scripts/check_mutation_anchors.py`, `scripts/check_lint_baseline.py check` (ruff 0.16.6), `scripts/check_system_map.py`, `scripts/gen_contract_types.py --check`, frontend `tsc -p tsconfig.app.json --noEmit` and vitest on the touched folders. Never the full suite locally (order 129).
6. Post on #692 only when a PR is claimed, ready, merged or blocked, or a review result is in. Never post "no change". Never post a token.

## Reviews (order 147)
Request changes only for correctness, a safety fence, order 143 or a missing test. Everything else is "optional, not blocking". GitHub refuses a formal approval on a PR from the same account, so an approval is a PR comment naming the head sha.

## The proof (orders 148, 157)
M-03, 216400C and I-06 run on the release head with the local model: fewer lines than main, 0 empty comments, 0 time-outs, I-06 no worse. A sheet with a time-out is re-run. Counts are checked read-only from the stored runs (order 155). When it passes, 1a merges, then 1b straight after.

## Merge
Merge commits, not squash. A release PR shows only its own changes once the one under it is merged. After each merge s2 confirms the plan issues closed (order 151) and the worktrees of merged PRs are removed.
