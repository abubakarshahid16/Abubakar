# ADR-0006: Repository governance and compensating controls

## Decision

Use pull requests, CODEOWNERS, required local verification, and GitHub Actions
as the repository's governance controls. Enable protected `main` with required
reviews and checks as soon as the repository plan supports branch protection.

## Context

This private repository is on GitHub Free, where branch protection and required
status checks are not enforceable. A green workflow can therefore be bypassed
by a direct push today. That is a platform limitation, not a claim that the
controls are active.

## Compensating controls in force now

- `.github/CODEOWNERS` declares ownership of the full tree and high-risk paths.
- `.github/pull_request_template.md` requires an issue link and verification
  evidence.
- `tests.yml` runs backend, frontend, typecheck, and production-build checks on
  every push and pull request.
- `secret-scan.yml` runs secret scanning and the client-data guard.
- Dependabot checks Python, npm, and GitHub Actions dependencies monthly.
- `CONTRIBUTING.md` requires merge commits, green checks, and local suites.

## Activation checklist

When branch protection becomes available, configure `main` to require one
CODEOWNER approval, all checks named `backend (pytest)`, `frontend (vitest +
tsc)`, `gitleaks`, and `no-client-data guard`, dismiss stale approvals, and
reject force pushes and branch deletion. Record the activation date here.

## Consequences

The repository has useful review and automated checks now, but until activation
they remain process controls rather than a technical barrier against a direct
push. This distinction is intentionally documented so release claims stay
honest.
