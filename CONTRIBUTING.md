# Contributing

Read `README.md` first — setup lives there and is not repeated here. This file
covers how work is done once the project runs.

## Setup, in one line

Follow **Getting started** in the README exactly as written. It was executed
from a clean clone into an empty directory, and every step that failed was
fixed in the repository rather than worked around in someone's head. If a step
does not work for you, that is a bug in the README and worth an issue.

### Turn on the pre-commit hook — a fresh clone does not run it

The secret-scanning hook lives in `.githooks/pre-commit` (gitleaks on staged
content, plus the path checks). Git does not version the setting that points
at it: `core.hooksPath` is local config, so **a fresh clone commits without
any scan until you run, once, from the repository root:**

```bash
git config core.hooksPath .githooks
```

Check it took with `git config --get core.hooksPath` (it must print
`.githooks`). The hook also needs `gitleaks` on `PATH` or at one of the
locations it searches; without it the hook blocks the commit rather than
passing it unscanned. The same setting enables `.githooks/post-checkout`,
which keeps the main working tree (the live checkout) on `main`; do branch
work in a worktree under `.claude/worktrees/`.

## Branches

```text
<type>/<issue-number>-<area>-<short-description>
```

Examples from the history: `feat/37-fts5-keyword-index`,
`chore/60-sec-001-upload-ceiling-and-reachability`, `docs/32-equation-caveat`.

Types: `feat`, `fix`, `chore`, `docs`, `perf`, `test`, `refactor`.

The convention held for 17 issues and 58 pull requests, then lapsed the moment
work went off-plan. That is recorded rather than tidied away, because a
convention that silently stops is worth knowing about.

## Commits

Conventional commits, with the subject saying what changed and why it matters:

```text
fix(search): the reranker was judging long chunks on a fragment of themselves
```

not

```text
fix search bug
```

The body is where the reasoning goes. A future reader with a `git blame` in
front of them is the audience.

### After a `git commit` that errored, check what it actually did

**`git add` can succeed while `git commit` fails on the same `.git/index.lock`,
and the error message does not say so.** Both report the same lock, so a failed
commit looks like nothing happened when the index has in fact been staged.

This has bitten once already. A `git add <paths> && git commit` chain hit a
stale lock; the `add` had gone through, the `commit` had not, and the retry
committed a much larger change set than intended — one commit ended up carrying
two unrelated changes under a message describing only one.

So after any commit that reported an error:

```bash
git show --stat HEAD     # what the last commit actually contains
git status --short       # what is still staged
```

Verify the file list matches what you meant to commit before doing anything
else. If a commit is wrong and **not yet pushed**, `git reset --soft HEAD~1`
followed by `git reset` puts everything back in the working tree with no work
lost, and the split can be redone.

A stale lock is safe to remove only after confirming no git process is running
(`tasklist | grep git` on Windows). Git's own message says as much, but it says
it about a crash, and the common case here is a crash.

### A specification may be committed as a strict xfail, never as a red test

Work is sometimes specified in tests before it is built, and committing that
specification is right - the tests are the clearest statement of what the
behaviour must be. Committing them RED is not.

A permanently red suite is how a team stops reading test output. Once "27
failures, that's the spec file" is normal, "28 failures, probably the spec
file" follows within a week, and the 28th is a real regression nobody looked
at.

Mark the module instead:

```python
pytestmark = pytest.mark.xfail(
    strict=True,
    reason="#90: <what is specified here and not yet implemented>",
)
```

`strict=True` is the important half. A strict xfail that PASSES is a failure,
so the suite goes red at the moment the work is finished - the tests announce
their own completion, and nobody has to remember to unmark them. The reason
must name the issue, so a reader meeting the marker can find out what is
missing.

`backend/tests/test_recommendation_gate.py` is the worked example.

## Pull requests

- One PR per branch, into `main`.
- The template requires a `Closes #NN` line. If nothing is closed, say so
  explicitly rather than deleting the line.
- **Merge commits, not squash.** The history is deliberate and a squash
  destroys it. Repository settings enforce merge-only; do not change that
  without a decision recorded in an ADR.
- CI must be green: backend tests, frontend tests and typecheck, secret
  scanning, and the client-data guard.

## Repository governance

This private GitHub Free repository cannot currently enforce protected `main`,
required reviews, or required checks. Treat direct pushes as prohibited by
process, use the pull-request template, and do not merge with a red or pending
check. CODEOWNERS and Dependabot are enabled now; branch protection should be
activated when the repository plan supports it. See ADR-0006 for the exact
activation checklist and the controls that are currently enforceable.

## Tests

```bash
# backend
.venv/Scripts/activate          # or source .venv/bin/activate
cd backend && python -m pytest -q

# frontend
cd frontend && npm run test && npx tsc -b
```

Both suites must pass before a PR. The backend suite needs the staged model
weights — `python scripts/fetch_models.py` — and stops immediately without
them rather than skipping silently.

## What this project asks of a change

These are not style preferences. They are the rules the project has repeatedly
found it needs, several of them after getting them wrong first.

**Measure before you tune.** A threshold that fixes one question also changes
what happens to every other passage in the corpus. Measure that population and
report it before changing a constant. `docs/limitations.md` records a case
where lowering a score floor admitted three wrong answers to recover one right
one.

**A number is not a measurement until you can say what it counts.** Name the
unit and the population, and hand-check one case. `docs/status-honesty-audit.md`
records nine occasions where this project produced a number that was correct
arithmetic over the wrong population — including one that overstated a
feature's headline value threefold.

**Nothing is dropped silently.** A page or chunk excluded from the index must
have a recorded reason a reader can look up. "It did not seem useful" is not a
reason; a rule name and its evidence is.

**A refusal beats a confident wrong answer.** For engineering specifications
this is not a preference. If a change makes the system more willing to answer,
say what it now answers that it previously refused, and check those cases by
hand.

**Report the number you measure, not the number you expect.** A change that
improves nothing is a finding. Say so plainly rather than presenting it as
progress.

## Architecture decisions

Anything that changes how the system works — not how it is written — gets an
ADR in `docs/adr/`. Six exist. Follow their shape: the decision, the context,
what was rejected and why, and the consequences including the bad ones.

## Where things live

| Path | Contents |
|---|---|
| `backend/app/` | FastAPI application, retrieval, chunking, OCR, answering |
| `frontend/src/` | React application — Documents, Chat, Ingestion, Dashboard |
| `eval/` | The evaluation harness and its recorded results |
| `docs/adr/` | Architecture decision records |
| `docs/limitations.md` | Client-facing register of what this system cannot do |
| `docs/status-honesty-audit.md` | Recorded instances of measurement error |
| `docs/backlog-issues.md` | Known gaps, each with evidence |
| `scripts/` | Model staging and maintenance |
