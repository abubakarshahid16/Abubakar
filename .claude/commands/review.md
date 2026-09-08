---
description: Review uncommitted or staged changes against this project's own recorded failure modes
---

# Code review — RAG Intelligence System

Review the changes in this repository and report findings. You are not a linter
and not a style checker: this project has a written record of 24 occasions when
something in it claimed what was not so, and your job is to catch the 25th
before it is committed.

## What to review

Default to the uncommitted working tree plus staged changes:

```
git status --porcelain
git diff HEAD
```

If `$ARGUMENTS` names a commit, a range, a branch or a path, review that
instead. If the diff is empty, say so and stop — do not review the whole
repository unasked.

Read the FULL text of every file the diff touches, not only the changed lines.
Nine of the recorded defects were invisible in the diff and obvious in the
file: a label rendered unconditionally, a scope resolved and discarded, a test
that asserted what it observed rather than where the run ended.

## The one pattern that produced every past defect

> **A field derived from something adjacent to the truth rather than from the
> truth itself.**

`stalled` derived from heartbeat freshness, which only proves a loop is
spinning. `ready` derived from a document existing, not from anything being
searchable. "Quoted verbatim" derived from a passage existing, not from its
provenance. For every claim the change makes — in code, in a label, in a
comment, in a docstring, in a test name — ask: **is this computed from the
thing it names, or from something that usually travels with it?**

Report every instance. This is the highest-value finding class in this
codebase.

## Rule 1 — honesty invariants

These are product invariants, not preferences. A violation is a defect at the
same severity as a crash.

- **No claim without resolving evidence.** A document-backed claim renders only
  when its citation resolves to a real page. A sentence the model produced that
  cannot be cited is dropped, never shown.
- **Null renders as nothing.** Never as `0`, never as an empty chip, never as a
  dash that reads like a measurement. `in_register: null` means no register is
  loaded; rendering `0` claims the register says none exist.
- **Unmeasured says unmeasured.** A value never measured must say so rather than
  display a zero or a plausible default.
- **Confidence is never "high".** Nothing here is calibrated. Confidence is
  derived from named checks that fired, and the checks are shown.
- **A count must state its boundary.** "12 documents" with no boundary reads as
  total. Say whose documents, or do not give the number. Two recorded defects
  came from a count that was arithmetically right inside a boundary the code
  chose for itself and never stated.
- **Silence is not compliance.** "The document does not mention it" must never
  render as met, compliant, or satisfied. In a comparison, "not addressed in B"
  is not a gap.
- **A guess renders as a guess** until a human confirms it. A suggested
  classification is not a classification.
- **Samples are labelled samples.** Market rows are illustrative unless a
  governed provider is enabled, and must never be describable as live.
- **No percentage without a stated denominator.**
- **A comment recording a false reason is a defect, not a nitpick.** Entry 15 in
  the audit spread through seven comments in five files and made a relocated
  leak read as hardening. Verify that every comment and docstring the change
  adds or leaves behind is still true of the code beside it.

## Rule 2 — the anti-vacuous-test check

The recorded defect: three green tests over broken code, each with fixtures that
could not produce the condition the test claimed to check. **A vacuous test does
not fail; it passes, which is worse than having no test.**

For every test the change adds or modifies, answer explicitly:

1. **Would it fail if the feature were deleted?** If you cannot say yes with a
   reason, report it. Name the mutation that should break it.
2. **Does it mock the thing under test?** A test that asserts against its own
   mock's shape proves the mock, not the product. This exact defect shipped 23
   tests that all passed while the panel rendered `undefined`.
3. **Can the fixture actually produce the condition?** A fixture that cannot
   reach the branch means the assertion never runs.
4. **Does it assert where the run ENDED, not merely what it observed on the
   way?** Entry 7: a test asserted the statuses it saw at every invocation and
   never asserted the final state, so every scanned document landed at `failed`
   with a green suite.
5. **Is there a positive control?** A test that only asserts absence passes when
   the renderer is broken and nothing renders at all.
6. **Does it depend on this machine?** Missing fixtures made eight tests pass
   only on the developer's box.

## Rule 3 — security and privacy

- **No secret in code, log, comment, test fixture, URL or error message.** Never
  a token in a URL. `.env` is never staged; check the diff for it explicitly.
- **Egress is one file.** Only the market transport module may open a socket.
  Any new outbound call anywhere else is a finding, however harmless it looks.
- **Only the typed phrase may leave.** No filename, no page reference, no
  passage text, nothing derived from a document may enter an outbound payload.
  If the change touches the market path, check the payload builder AND the
  preview, and confirm the previewed payload is byte-identical to the sent one.
- **Classification may only narrow.** A classification filter intersects with
  the caller's access scope; it may never union, widen, or bypass it.
  Classification says what a document is about; grants say who may read it.
  They are different tables and only the second decides anything.
- **A scope resolved must be a scope used.** Entry 15: the route took an
  `AccessScope` dependency and never passed it on. Every request resolved it and
  discarded it. For each route the change touches, trace the scope from the
  signature into the query. Filtering after the query, in Python, is a finding
  even when it currently returns the right rows.
- **404, not 403,** where a 403 would confirm a document exists.
- **Unauthenticated routes say the minimum.** Nothing that fingerprints the
  machine, names a document, or carries free text from an error.
- **A control that fails open is not a control.** Entry 24: the pre-commit hook
  exited 0 when its scanner was missing. Any guard the change adds must fail
  closed, and its absence must be loud.

## Rule 4 — ordinary engineering review

Also review as a senior engineer would: correctness, edge cases, error
handling, concurrency and races, resource leaks, N+1 queries and other
avoidable cost at scale, dead code, and readability. Two specific hazards in
this codebase:

- **Scale.** It is tested on tens of documents and intended for thousands.
  Flag anything whose cost is per-document in a loop, or that fetches one
  record at a time where one query would do.
- **The model is small and CPU-bound.** Flag anything that asks it for two
  syntheses on one screen, or that widens context without saying what it costs.

## How to report

Order findings **most severe first**. For each one give:

- **file:line**
- **What is wrong** — one sentence, stated as a defect, not a suggestion.
- **The failure it produces** — concrete inputs or state, and the wrong output,
  wrong claim, or crash that results. If you cannot name the failure, you have
  a style opinion; drop it.
- **Which rule** — honesty, vacuous test, security, or engineering.
- **The fix** — the smallest change that removes it.

Then, separately and briefly:

- **Verified clean:** the things you checked that were fine, so I know the
  review's boundary. Say what you did NOT review.
- **Confidence:** what you could not check without running the code, and what
  running it would settle.

Rules for your own report:

- **Do not pad.** An empty finding list is a valid and welcome result. Say
  "no findings" rather than inventing three minor ones.
- **Do not soften.** If a change should not be committed, say that.
- **Never claim to have run something you did not run.** If you did not execute
  the tests, say the review is static. Reporting an unverified pass would itself
  be entry 25.
- **Quote the code you are describing.** A finding without the line it refers to
  cannot be checked.

## Optional: prove the tests

If I ask for a deep review, or you find a test you suspect is vacuous, verify
rather than guess:

```
# frontend
cd frontend && npx vitest run <the test file>
# backend
python -m pytest <the test file> -q
```

Then delete or break the feature the test covers, re-run, and confirm the test
goes red. Restore the code afterwards and report what you did. A test proven to
fail on mutation is worth more than ten reviewed by reading.
