# ADR-0004 — GitHub free-tier governance gaps and compensating controls

- **Status:** Accepted
- **Date:** 2026-09-04
- **Decision:** Nothing paid. Gaps are documented, not purchased away.

## Context

- The repository is `abubakarshahid16/saudi-aramco-rag-chatbot`, **verified `PRIVATE` by API**.
- It is owned by a personal account on GitHub **free tier**.
- EXECUTION.md §9 requires protected branches, required status checks, and secret scanning. Probing showed these are unavailable:

```
GET  /repos/.../rulesets  -> HTTP 403  "Upgrade to GitHub Pro or make this repository public"
PATCH /repos/... secret_scanning -> HTTP 422  "Secret scanning is not available for this repository"
```

- Making the repository public would fix both and is **not an option** — it violates EXECUTION.md §6 and §18 outright.

## Gaps and compensating controls

| §9 requirement | Status | Compensating control |
|---|---|---|
| No direct pushes to `main` | ❌ Unenforceable | PR-only convention; branch-per-issue discipline |
| No force pushes to `main` | ❌ Unenforceable | Convention |
| Required status checks before merge | ❌ Unenforceable | CI runs on every PR; merge gated manually on a green run |
| Secret scanning | ❌ Unavailable (GHAS) | **gitleaks in CI *and* as a pre-commit hook** |

## Controls actually implemented

- **`.githooks/pre-commit`** — blocks secrets and client documents *before* they enter git history. This is **stronger than GHAS**, which only alerts after a push.
- **`secret-scan` workflow** — gitleaks 8.30.1 pinned by version **and** verified by SHA-256 checksum, rather than a wrapper action. `actions/checkout` pinned to full commit SHA. `permissions: contents: read`.
- **`no-client-data` CI job** — not required by the plan. Fails any PR tracking `.pdf`, `.onnx`, `.gguf`, `.safetensors`, `.sqlite`, `.db`, `.lance` or `.env` outside `tests/fixtures/synthetic/`. The highest-consequence leak here is a committed Aramco PDF, not an API key.
- **`.gitignore`** reproducing §9 verbatim plus platform additions.
- **CODEOWNERS** — retained, annotated as advisory-only on this tier.

## Verified by deliberate failure test

- Fake AWS key + RSA private key staged → `leaks found: 1`, commit rejected, `git log` unchanged.
- Client PDF staged at repo root → `BLOCKED: forbidden file type staged`, commit rejected.
- Synthetic fixture under `tests/fixtures/synthetic/` → correctly allowed.
- CI run `33796984643` → both jobs `success`.

## Consequences

- ⚠️ **These four gaps must appear in the client limitations register.**
- ⚠️ **They must not be described to the client as enforced.**
- If this work ever moves to an Aramco-owned GitHub organisation, all four become available and the compensating controls should be kept alongside, not replaced.
