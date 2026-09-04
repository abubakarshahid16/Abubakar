## Closes

Closes #

<!-- REQUIRED. A PR with no issue is how the convention lapsed: it held for 17
     issues and 58 PRs, then stopped silently the moment work went off-plan.
     1 of the following 11 commits referenced an issue, and nothing in the
     repository said it should. This line is the same move as making
     text_source required rather than optional in contracts/types.ts - it
     removes the option to forget.

     No issue yet? Open one. If the change is genuinely too small for an issue,
     delete this section and say why in What changed. -->

## What changed

<!-- What a reviewer needs to know, not a restatement of the diff. -->

## The measurement

<!-- Nothing enters docs/benchmarks.md that was not measured on the target
     hardware, and the same standard applies here. If this PR claims something
     is faster, more accurate or more complete, give the number and the machine
     state it was measured in. If the choice was a guess rather than a
     measurement, SAY SO - a guess labelled as a guess is useful; a guess
     wearing a decimal point is not. -->

## Verification

- [ ] `cd backend && python -m pytest -q` passes
- [ ] `cd frontend && npx tsc -b && npm run test` passes
- [ ] Every fix ships with a test **confirmed to fail without it** — say how you confirmed
- [ ] Any claim that stopped being true is removed, not left standing
      (`OCR is not implemented`, `Not yet available`, and `a 15-second average`
      were all true when written)

## Not done

<!-- What this PR deliberately leaves out, and why. An honest gap is worth more
     than a silent one. -->
