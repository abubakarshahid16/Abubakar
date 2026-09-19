# After the retrieval audit: secure, unblock, then find the one cause

Read `docs/STANDARDS_RETRIEVAL_AUDIT.md` first. It FAILED, and the two
numbers that matter are: 252 of 272 standards have zero
standard_requirements, and 640 extracted pages have no retrievable chunk.

Do the steps in this order. Each step has a stop condition. Do not start the
next one until the current one is committed and its stop condition is
reported with the exact command and output.

DO NOT open, read, extract, run, or search for EF1975-DAS-M-03 or any
document mentioning "Recycle Brine". It is a held-out test document. If any
file, audit, or note you encounter describes its contents, skip that section
and say that you skipped it. This applies to every step below.

## Step 0. Push. Nothing else first.

    git log origin/feat/phase-1-ui-reaches-backend..HEAD --oneline | wc -l
    git push origin feat/phase-1-ui-reaches-backend

Report the count before and after. 73 commits exist on one disk. Stop
condition: the count after is 0.

## Step 1. Restart the backend

Two committed fixes (b782f96, 0a7ec06) are not in the running process.
Restart it and confirm with one live request that "how many standards are
there?" answers from the database.

## Step 2. The truncated flag

The screen reads a `truncated` flag that is never persisted with the answer,
so an answer cut off at its length limit can display as complete. You called
it a one-line fix. Make it, with a test that feeds a cut-off answer through
the persisted payload and asserts the screen marks it. One mutation.

## Step 3. Merge cowork/demo-polish and verify it

Head is f979ef4. Read `.cowork/HANDOFF-demo-polish.md` on that branch. It
contains three frontend edits that have NEVER been typechecked or tested,
because npm cannot run from where they were written. Merge, then:

    cd frontend && npx tsc --noEmit && npx vitest run

Write the test ReviewRunsView has never had: selecting a run renders the
findings section BEFORE the runs list in the DOM, and a run whose
recommended_reason already contains "NOMINAL ESTIMATE" renders that sentence
once on its card, not twice. Stop condition: tsc clean, suite green, new
test present and one mutation of it detected.

## Step 4. The "may not" gap, on a real clause

`_MANDATORY_HERE` in `backend/app/requirements_3b.py` lists shall, must,
is/are required to, is/are to be. It does not list "may not". The audit read
SAES-A-105 p9 and found: "Pressure relief valves, which may not exceed 115dB
(A)". That requirement is invisible today.

Ignore the earlier note in `.cowork/PROMPT-standards-retrieval-audit.md`
that said this sentence reads "shall not exceed" and told you not to fix it.
That note was wrong and is retracted in the same file.

Before changing the regex: count "may not" sentences across all 272
standards from the extracted pages, and report the number with a sample of
ten. Then add "may not" and "must not" to the mandatory verb pattern, re-run
extraction on SAES-A-105 ONLY, and report the requirement row for the PSV
limit: clause, page, source_text, limit value, unit, comparator. Mutation:
remove "may not" from the pattern and confirm the new test fails.

## Step 5. Why do 252 standards have zero requirements? INVESTIGATE ONLY.

This is the most important question in the project and it is one question.
Do not fix anything in this step.

For the 20 standards that HAVE requirements and the 252 that do not, find
what separates them. Check, and report each with a count and denominator:

- Was requirement extraction ever RUN on the 252? (job rows, timestamps)
- If run: did it produce zero candidates, or candidates that all failed a
  gate? Which gate, by count?
- Are the 20 different in ingestion date, file size, page count,
  classification, OCR vs text layer, or extraction version?
- Pick three of the 252 by hand, different families (SAES, SAMSS, other),
  run extraction on each in isolation, and show the first ten candidate
  sentences and what happened to each.

Stop condition: one sentence that states the cause, with the evidence that
supports it, or an honest statement that there is more than one cause, with
the split. Write it to `docs/ZERO_REQUIREMENTS_CAUSE.md` and STOP. Do not
proceed to fix it in this session. The fix is a separate decision after the
cause is read.

## Not in this prompt, on purpose

Clause identity on chunks, table row records, contents-page suppression,
and the applicability engine are all real and all wait. Every one of them
changes shape depending on the answer to Step 5.

## Reporting rules, as always

Every count states its denominator. No claim without the command and its
output. A mutation that collects zero tests is a harness error, not a
detection. If a step cannot be completed, say which and why, and stop.
