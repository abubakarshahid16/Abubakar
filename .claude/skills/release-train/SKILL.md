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

## Speed rules (orders 215 and 216, permanent)
The pre-push guard (`.githooks/pre-push`, runs `scripts/pre_push_guard.py`) enforces R1 and warns on R2. Switch it on once per clone and worktree, at the start of every session: `git config core.hooksPath .githooks`.
- **R1. Check before you push.** Format only the lines you touched (never reformat a whole old file: `python scripts/quality_ratchet.py format-check --base origin/main` is the test; ruff 0.16.6 from `backend/.venv` or your session), then `check_lint_baseline.py check`, `check_mutation_anchors.py`, `check_system_map.py`, the tests of the modules you changed. A PR that fails CI on formatting, size or anchors is a miss: fix it within 10 minutes.
- **R2. Fresh with main before review.** Merge current main into your branch and push before asking for review, and again whenever main moves while the PR waits. Say "up to date with main at <sha>" in the review request.
- **R3. Next-job queue.** Your #1238 note has a "Next job: ..." line from the plan. When a job ends, start the next at once.
- **R4. Backup packer.** If fixes are labelled `state:approved` and s1 has not posted a pack within 15 minutes, s2 packs them (same bundle rules); s1 does the same for s2.
- **R5. Doorbell on any mention.** s1, s2, s3 wake on ANY `@s1`/`@s2`/`@s3` mention on #692 or their PRs.
- **R6. Builder teams for big fixes.** A fix expected to take over 90 minutes is built with the agent-team skill, one PR behind a switch; start in plan mode (post the plan, then build).
- **R7. Wake on news, sleep longer when waiting.** Cloud helpers check every 10 minutes only with an open PR in review or a job in progress, otherwise every 30. Every #1238 note ends with "Next wake: HH:MM PKT". A pause stops work, never the wake-ups; after any restart, rebook the chain and the hourly net first.
- **R8. Test only what changed.** Small fixes: the Rule C quick PF1 run only. The full real-sheet test runs once per bundle. Fixes that change reading, rules, prompts, model or the comment sheet always get the full test before release (orders 191.1 / 192.1).
