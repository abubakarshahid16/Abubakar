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

## M1–M3 (clock-deadline scheme)

Not yet created. Issues are created as their milestone is approached, so that the
scope cuts recorded in ADR-0003 are reflected rather than the original backlog.

## TWO MILESTONE SCHEMES SHARE THE NUMBERS M2, M3 AND M4

Read this before filing anything against a milestone number.

This file's milestones (below) are **clock deadlines** — M2 is the 3PM prototype
cut. `RAG-INTELLIGENCE-POC-EXECUTION.md` §12 defines a **different** set under the
same numbers, named for what they contain: M2 is the authorization boundary.
They are not the same milestone and they do not contain the same work.

Both now exist on GitHub, because the plan's were never created and the work
below belongs to them:

| Number | Title on GitHub | Scheme |
|---|---|---|
| 3 | `M2 - Full UI` (closed) | clock deadline, this file |
| 4 | `M3 - Polish & handoff` | clock deadline, this file |
| 5 | `M4 - Full Corpus Pilot` | clock deadline, this file |
| 7 | `M2 — Authorization boundary` | plan §12 |
| 8 | `M3 — Smart analysis` | plan §12 |
| 9 | `M4 — Market and reporting` | plan §12 |

The plan's titles use an **em dash**, this file's a hyphen. That is the only
thing distinguishing them at a glance, which is not enough — **name the scheme
whenever you cite a milestone number.** Consolidating the two is open work; it
was not done tonight because renaming a closed milestone rewrites the history
of issues already filed against it.

## Plan §12 milestones — issues filed

Stable IDs continue this file's scheme (`SEC-`, `UI-`, `ANA-`, `REP-`).
Bugs carry no stable ID; the plan's §12 `ISSUE-0NN` IDs name the parent feature
issue each of these extends.

| Stable ID | GitHub | Title | Milestone | Parent |
|---|---|---|---|---|
| SEC-002 | [#64](../../issues/64) | Add the four engineering disciplines and admin as a capability | M2 — Authorization boundary | ISSUE-004 |
| UI-002 | [#65](../../issues/65) | Build the admin screen so a client can grant access without a terminal | M2 — Authorization boundary | ISSUE-013 |
| ANA-002 | [#66](../../issues/66) | Detect compliance assertions a cited span does not make | M3 — Smart analysis | ISSUE-009 |
| — | [#67](../../issues/67) | bug: a stray punctuation fragment is reported as a removed sentence | M3 — Smart analysis | ISSUE-009 |
| — | [#68](../../issues/68) | bug: the recommendation panel asserted an egress state it never read | M4 — Market and reporting | ISSUE-011 |
| REP-002 | [#69](../../issues/69) | Audit every [S#] marker against the evidence frozen in the report | M4 — Market and reporting | ISSUE-012 |

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
