# EXECUTION ORDER - commit B24 and B23

Authorized by Muhammad Usman, 2026-09-21. For the session with a working shell on
`D:\project\Rag_chatbot`, laptop ABUBAKAR.

Scope: **commit only.** No new features. The code is already written and tested
(checkpoint rows 26, 27, 28). This order gets it safely into git.

## Read first

`.cowork\README-INDEX.md`, `NORTH-STAR.md` (**verify sha256
`3d0505be629a99631e8cbcc0681134c642b7a00ae962a5c9f5ebf9df43499619`**, 9 sections,
checklist at section 8 - **STOP if it differs**), `CURRENT_STATE_AND_BLOCKERS.md`
sections 11, 14 and the checkpoint log, `EXECUTE-B24-B23.md`, `B24-B23-PREFLIGHT.md`.

---

# PART 1 - Four checks BEFORE anything is staged

Answer all four in the report. **If any cannot be answered, stop and say so rather than
committing around it.**

## Check A - prove the `requirement_type` scoping test exists and bites

The preflight's central finding: `condition` means a real condition on `numeric_limit`
rows (87 of them) and a **table row label** on `table_value` rows (4,246, 37.7% of them
digits-only noise like "Arsenic" and "100").

A gate that fired on `table_value` would abstain on thousands of rows and bury the 87
that matter. That is B20's defect in mirror image.

- Name the test that proves a `table_value` row with `condition="Arsenic"` does **not**
  trigger the gate
- Show it fails when the `requirement_type` scoping is removed. **A scoping test that
  passes with the scoping deleted is vacuous** - that is B14, this project's named
  recurring defect

## Check B - explain any change to `test_abstention_gate4.py`

That file was **already committed** in `abd391b`. If the working tree's copy differs from
`HEAD`, say exactly how and why. A safety test changing during unrelated work needs a
stated reason.

    git diff HEAD -- backend/tests/test_abstention_gate4.py

## Check C - the dead `CONDITIONAL` status

Declared, given an action string, counted in a tally, mapped in two places, never
assigned - so the tally is structurally always zero. The B24 order required you either to
wire it or delete it. **State which, and why.** A status that cannot occur is worse than
no status, because a reader assumes conditional handling exists.

## Check D - the 98-row remainder

`numeric_limit` + `table_value` + `statement` = 34,840 against a total of 34,938, and
their conditions sum to 5,344 against 5,349. **Name the other `requirement_type` values**
and confirm those five conditions do not need the gate, or say they were brought into
scope.

---

# PART 2 - Verify before staging

    cd backend && python -m pytest -q --no-header -p no:cacheprovider

- Report the **exact** pass/fail/skip counts and compare them against the baseline in
  checkpoint row 28
- Every remaining failure named, with whether it pre-existed (B3, B4, B7, B8 are known)
- Run the targeted suites separately: `tests/test_condition_gate.py` (26),
  `tests/test_quote_validation.py` (41)
- Run the committed mutation harness. **Report every mutation result, including M267 to
  M273.** A mutation detected by zero tests is a harness failure, not a pass
- `git diff --check` for whitespace damage

**Do not rewrite a test to make anything pass.** Rule 16 of the honesty audit.

---

# PART 3 - Stage precisely. Name every path.

    git status --porcelain=v1 -b

Stage **only** the B24/B23 files: `backend/app/conditions.py`, `backend/app/quotes.py`,
the `comparison.py` change that calls them, and the two new test files.

**Leave uncommitted:** the CRS lane (`crs_export.py`, `crs_mapping.py`,
`test_crs_export.py`, `test_crs_mapping.py`, `contracts/types.ts`), and any `.cowork`
housekeeping deletions.

**Before committing, print `git diff --cached --stat` and confirm nothing unrelated was
swept in.** If `comparison.py` carries changes beyond the B24 wiring, **stop and report**
rather than sweeping an unrelated change into a safety commit.

---

# PART 4 - Commit. Local only. No push.

The message must state: the defect each gate closes, where the gate sits and why there,
that `requirement_type` scoping confines B24 to `numeric_limit`, the mutation results,
and that historical findings were not re-evaluated.

**Do not claim engineering accuracy.** These gates make the system abstain correctly.
They do not make it right.

---

# PART 5 - Record the activation point

**This is the step most likely to be skipped, and it matters.**

B24 changes behaviour for **new evaluations only**. The 20,288 existing `review_findings`
rows are untouched. So a run before this commit and a run after it will differ, and
somebody will eventually notice and assume a regression.

Record in `CURRENT_STATE_AND_BLOCKERS.md`:

- the **commit hash and date** at which gate behaviour becomes active
- one line stating that any difference between a pre-gate and post-gate run has this
  commit as its stated reason

Add checkpoint rows continuing from row 29. Update the B24/B23 entries in the bug
register and `B24-B23-PREFLIGHT.md` with the outcome.

---

# PROHIBITIONS

No push. No `git reset`, rebase, squash or force. No deletes. No schema change. No
retroactive modification of existing findings. Do not start B19, M-03, CRS work, the
ceiling test or anything else in this task.

# REPORT

Checks A to D answered, the exact test counts, every mutation result, the staged file
list, the commit hash, and confirmation the frozen Phase 0.5 packet and the 20,288
historical findings are untouched.

## Next, for context only. Do not start.

B19: `datasheets.extract_facts` at line 1178 has **no caller anywhere in
`backend/app`**. Until it is wired, any newly uploaded datasheet produces zero findings.
That is the next task and it is the one that decides whether the demo workflow works end
to end.
