# Issue map — stable ID to GitHub number

Required by EXECUTION.md section 11 step 6. Contains no confidential data.

Repository: `abubakarshahid16/saudi-aramco-rag-chatbot` (private)

## Epics

| Stable ID | GitHub | Title | Milestone |
|---|---|---|---|
| EPIC-01 | [#1](../../issues/1) | Private local platform and repository governance | M0 |
| EPIC-02 | [#2](../../issues/2) | Resumable high-throughput document ingestion | M1 |
| EPIC-03 | [#3](../../issues/3) | Accurate hybrid retrieval and grounded answers | M1 |
| EPIC-04 | [#4](../../issues/4) | Polished chat and operations dashboard | M2 |
| EPIC-05 | [#5](../../issues/5) | Evaluation, security, and enterprise readiness | M3 |

## M0 — Repository & Architecture Ready

| Stable ID | GitHub | Title | Depends on |
|---|---|---|---|
| GOV-001 | [#6](../../issues/6) | Configure private repository governance and compensating controls | — |
| ARC-001 | [#7](../../issues/7) | Record architecture, corrected privacy boundary, and non-goals | #6 |
| CON-001 | [#8](../../issues/8) | Define API, status, citation, error, and streaming contracts | #7 |
| DEV-001 | [#9](../../issues/9) | Scaffold reproducible Python and React workspaces with CI | #7 |

## M1–M3

Not yet created. Issues are created as their milestone is approached, so that the
scope cuts recorded in ADR-0003 are reflected rather than the original backlog.

## Milestones

| Milestone | GitHub | Cutoff (AST, client) | Cutoff (PKT, local) |
|---|---|---|---|
| M0 — Repository & Architecture Ready | [#1](../../milestone/1) | 2026-09-04 09:00 | 11:00 |
| M1 — Local RAG Vertical Slice | [#2](../../milestone/2) | 2026-09-04 11:30 | 13:30 |
| M2 — 3PM Prototype | [#3](../../milestone/3) | 2026-09-04 15:00 | **17:00** |
| M3 — 7PM Client Handoff | [#4](../../milestone/4) | 2026-09-04 19:00 | 21:00 |
| M4 — Full Corpus Pilot | [#5](../../milestone/5) | gated on client sizing | — |
| M5 — Enterprise Release Candidate | [#6](../../milestone/6) | gated on security review | — |

> **Timezone note.** The client deadline is Arabia Standard Time (UTC+3).
> The development machine runs Pakistan Standard Time (UTC+5), two hours ahead.
> The 3:00 PM AST cut is **5:00 PM on the local clock**. Always state which zone.
