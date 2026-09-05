# Contributing

Read `README.md` first — setup lives there and is not repeated here. This file
covers how work is done once the project runs.

## Setup, in one line

Follow **Getting started** in the README exactly as written. It was executed
from a clean clone into an empty directory, and every step that failed was
fixed in the repository rather than worked around in someone's head. If a step
does not work for you, that is a bug in the README and worth an issue.

## Branches

```
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

```
fix(search): the reranker was judging long chunks on a fragment of themselves
```

not

```
fix search bug
```

The body is where the reasoning goes. A future reader with a `git blame` in
front of them is the audience.

## Pull requests

- One PR per branch, into `main`.
- The template requires a `Closes #NN` line. If nothing is closed, say so
  explicitly rather than deleting the line.
- **Merge commits, not squash.** The history is deliberate and a squash
  destroys it. Repository settings enforce merge-only; do not change that
  without a decision recorded in an ADR.
- CI must be green: backend tests, frontend tests and typecheck, secret
  scanning, and the client-data guard.

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
