# EXECUTION ORDER - implement B24 and B23

Approved by Muhammad Usman, 2026-09-21, on the evidence in
`.cowork/B24-B23-PREFLIGHT.md`. For the session with a working shell.

## Read first

`.cowork/README-INDEX.md`, `NORTH-STAR.md` (**verify sha256
`3d0505be629a99631e8cbcc0681134c642b7a00ae962a5c9f5ebf9df43499619`**, 9 sections,
checklist at section 8 - STOP if it differs), `CURRENT_STATE_AND_BLOCKERS.md`,
`AI_SUBMITTAL_REVIEW_SYSTEM_AUDIT_AND_NORTH_STAR_V3.md`,
`CLIENT_FEEDBACK_REQUIREMENTS_ADDENDUM.md`, `B24-B23-PREFLIGHT.md`. Plus
`docs/status-honesty-audit.md`.

## Scope

B24 and B23 only. **Do not** rerun Phase 0.5, touch the frozen packet, start B19,
M-03, HAZOP, FEED, CRS expansion or Claude benchmarking. No deletes, no git reset, no
schema change, no push, no claim of engineering accuracy.

---

# B24 - CONDITION EVALUATION SAFETY GATE

## CRITICAL: scope by `requirement_type` first. This is not optional.

The preflight proved `condition` carries two different meanings:

| requirement_type | rows | with condition | what `condition` holds |
|---|---|---|---|
| `numeric_limit` | 1,659 | **87** (5.2%), zero noise | **a real condition** - this is B24's scope |
| `table_value` | 4,246 | 4,246 (100%), 37.7% digits-only | **a table row label** - NOT a condition |
| `statement` | 28,935 | 1,011 (3.5%) | mixed, out of scope for v1 |

**B24 reads `condition` ONLY for `numeric_limit`.** For every other type the field is
ignored entirely.

A gate that fired on `table_value` would abstain on 4,246 rows reading "Arsenic" and
"100" as conditions, burying the 87 that matter. That is B20's defect in mirror image.

**Required test:** a `table_value` row with `condition="Arsenic"` does **not** trigger
the gate and its behaviour is byte-identical to today.

## Placement

At the final comparison/review boundary, so every caller is protected, not one upstream
path. Same reasoning that put B20 in `claims._compatible`. Name the boundary you chose
and why in the report.

## The four condition shapes, v1

Exact, case-folded term matching only:

1. named material
2. named service or fluid
3. numeric threshold - route through `claims`, so the B20 dimension guard from `abd391b`
   applies
4. equipment or area class

**Semantic matching is forbidden for establishing a condition.** `applicability.py`
already states that a semantic hit is not evidence of applicability; the same rule holds
here. A condition is established by exact match or it is not established.

## Outcome table - decide this in code, not at review time

| State | Outcome |
|---|---|
| Condition established **and matches** the submittal | comparison may proceed |
| Condition **unknown** - no fact available to evaluate it | `NEEDS_ENGINEER_REVIEW` |
| Condition **mismatched, with an exact-matched fact proving it** | `NOT_APPLICABLE`, recording the fact that proves it |
| Condition **appears mismatched but the proving fact is absent, partial or inexact** | `NEEDS_ENGINEER_REVIEW` |

`NOT_APPLICABLE` requires positive evidence. Unknown never becomes `NOT_APPLICABLE` -
collapsing those two is the mirror of the B24 defect itself.

Never return `COMPLIANT` or `NON_COMPLIANT` from an unevaluated condition. Do not weaken
`MISSING_INFORMATION` or any existing safe status.

Every gated finding records **which condition was not established**, and preserves the
exact requirement and datasheet evidence.

## Two things to resolve while you are in here

**The dead `CONDITIONAL` status.** Declared, given an action string, counted in a tally,
mapped in two places, never assigned - so the tally is structurally always zero. Either
wire it to B24 or delete it. A status that cannot occur is worse than no status, because
a reader assumes conditional handling exists. State which you did and why.

**The 98-row remainder.** `numeric_limit` + `table_value` + `statement` = 34,840 against
a total of 34,938, and their conditions sum to 5,344 against 5,349. **Ninety-eight rows
and five conditions are unaccounted for.** Name the other `requirement_type` values and
confirm those five do not need the gate, or bring them into scope.

---

# B23 - EVIDENCE QUOTE VALIDATION

## Normalization - a CLOSED list, documented in the code

- curly quotes to straight
- en dash and em dash to hyphen
- non-breaking space to normal space
- collapse repeated whitespace
- strip leading and trailing whitespace

**Nothing else.** Digits, decimal points, units, operators, comparison words and every
other character must match exactly after that normalization.

## Required cases

| Input vs model output | Result |
|---|---|
| `1/16”` vs `1/16"` | **ACCEPT** - typography only |
| `1.6 mm` vs `1.6mm` | **ACCEPT** - whitespace only |
| `1.6 mm` vs `1.5 mm` | **REJECT** - digit changed |
| `at least` vs `approximately` | **REJECT** - meaning changed |
| `>=` vs `>` | **REJECT** - operator changed |

## Behaviour

`contractor_quote` must resolve to the contractor document and page.
`requirement_quote` must resolve to the standard document and page.

On failure: no `COMPLIANT`, no `NON_COMPLIANT`; mark `NEEDS_ENGINEER_REVIEW`; record the
validation failure; preserve the model output separately as unverified text. Never
silently trust a model-rewritten quote.

---

# HISTORICAL FINDINGS

B24 applies to **new evaluations only**. Do not retroactively modify, delete or
re-evaluate any of the 20,288 existing `review_findings` rows.

Record the commit hash and date at which gate behaviour becomes active, so a comparison
between a pre-gate and post-gate run has a stated reason for differing.

---

# TESTS - mutation-proven

1. Missing material condition cannot produce `NON_COMPLIANT`.
2. Missing service condition cannot produce `COMPLIANT`.
3. Missing equipment-type condition cannot produce a final verdict.
4. **A `table_value` row with `condition="Arsenic"` does not trigger the gate.**
5. Condition mismatch **with** a proving fact yields `NOT_APPLICABLE`.
6. Condition mismatch **without** a proving fact yields `NEEDS_ENGINEER_REVIEW`.
7. Requirements with **no** condition behave exactly as before.
8. Removing B24 makes tests 1 to 6 fail.
9. Contractor quotes accepted only when source-valid; all five B23 cases.
10. Removing B23 makes test 9 fail.
11. Existing valid comparisons still work, including the `abd391b` dimension cases.
12. Existing CRS fields and disposition behaviour unchanged for unconditional
    requirements.

**Do not rewrite a test to make a gate pass.** A mutation that detects zero tests is a
harness failure, not a pass.

Run `cd backend && python -m pytest -q` for the full suite and the targeted tests
separately. Run the committed mutation harness and report every mutation. Run
`git diff --check`.

---

# REPORT BEFORE COMMITTING. Do not commit or push until the owner has it.

- files changed
- exact baseline and final test counts, and every remaining failure
- every mutation result
- which boundary you placed B24 at, and why
- what you did with the dead `CONDITIONAL` status
- the 98-row remainder explained
- confirmation the frozen Phase 0.5 packet and the 20,288 historical findings are
  untouched

Update `CURRENT_STATE_AND_BLOCKERS.md` with a checkpoint row per step, continuing from
row 25, and `.cowork/B24-B23-PREFLIGHT.md` with the outcome.

## Open, not blocking

With only ~71 genuine prose conditions in the `numeric_limit` set, having a discipline
engineer read and structure them once would give engineer-confirmed conditions rather
than regex-derived ones, which NORTH-STAR section 6 requires for anything deciding truth.
That is a **later quality improvement feeding the same evaluator**, not a prerequisite.
Build the evaluator now.
