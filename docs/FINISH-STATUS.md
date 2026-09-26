# Finish-mode status (B6B → B11)

Running record, updated at every stage boundary. **Aggregate numbers only** –
no client text, questions, standard names or pages (CLAUDE.md rules 1 and 3).
The frozen B6 benchmark (72 answerable + 8 unanswerable, AI-authored, NOT
engineer-approved) lives outside git and is used for RELATIVE comparison only.

Categories are never merged: code complete / tested in CI / tested on real
documents / engineer-validated / owner-laptop pending.

## Owner gates still pending (cannot be run in the cloud session)

| Stage | Gate |
|---|---|
| B4 (merged #243) | owner laptop: backup, re-extract datasheets, one live review (nozzle facts present, no revision-block names) |
| B5 (merged #245) | owner laptop: `scripts/b5_on_copy.py` all PASS, then one live review; no approved equipment taxonomy yet |
| B6 (merged #247) | latency on the target laptop |

## B6B – retrieval improvements (branch `feat/b6b-e1-heading-embeddings`)

Frozen baseline: recall@1 0.583, recall@5 0.875, MRR 0.706; reworded
recall@1 0.417 / recall@5 0.778; own-words recall@5 0.972; 9/72 misses; cloud
p95 ≈ 2.45 s.

| Exp | Change | overall r@1 / r@5 / MRR | reworded r@5 | own-words r@5 | p95 | misses | Kept |
|---|---|---|---|---|---|---|---|
| E1 | clause heading in the semantic embedding input (stored text, citations, boundaries unchanged; body never cut for the heading) | 0.597 / **0.917** / 0.725 | **0.861** | 0.972 | 2.47 s | 6 (3 fixed, 0 broken) | yes |

| E2 | E1 + ancestor headings (outermost first) in the embedding input | 0.611 / 0.861 / 0.721 | 0.750 | 0.972 | 2.34 s | 10 (4 broken vs E1) | **no** – long ancestor chains dilute short chunks |
| E3 | E1 + running-header lines stripped when contiguous with the page-edge block (up to 2× the scan window) | 0.653 / 0.875 / 0.745 | 0.778 | 0.972 | 2.35 s | 9 (3 broken vs E1) | **no** – regresses reworded recall@5 |
| E4 | E1 + numbered-paragraph clause anchors in every document | 0.681 / 0.875 / 0.767 | 0.778 | 0.972 | 2.38 s | 9 (3 broken vs E1) | **no** – re-chunks well-structured standards finer |
| **E4b** | E1 + numbered-paragraph anchors only in a document with fewer detected headings than half its prose pages; a top-of-page clause number is never stripped as a running header | **0.653 / 0.903 / 0.755** | **0.833** | 0.972 | **2.44 s** | **7** (2 fixed, 0 broken vs frozen) | **yes** |
| E5 | query expansion / multi-query | – | – | – | – | – | **not run** – needs the local LLM (Ollama), not available in the cloud session; a hand-written synonym list would be corpus tuning. Pending on the owner laptop. |

Control: a full re-ingest with E1 alone reproduces E1 exactly (0.597 / 0.917 / 0.725), so E3/E4 effects are real.
E4b fixes the one standard with broken clause tracking: 25 chunks / 2 clause labels → 73 chunks / 64 labels (citation clause correctness); the other 8 standards chunk exactly as before.

**B6B final (E1 + E4b) vs frozen B6:** recall@1 0.583 → **0.653**, recall@5 0.875 → **0.903**, MRR 0.706 → **0.755**; reworded recall@1 0.417 → **0.500**, recall@5 0.778 → **0.833**; own-words recall@5 0.972 → 0.972 (recall@1 0.750 → 0.806); p95 2.45 s → 2.44 s. Misses 9 → 7, none newly broken.

Remaining 7 misses by root cause: identical boilerplate across standards (1, own words) – needs document scoping (B6C); long multi-clause chunk (1); benchmark label incomplete (1 – the top hit is a correct answer on another page); ambiguous question (1); vocabulary / rewording (2 – query expansion, E5); missing parent-heading context (1 – ancestry, E2, measured harmful).

Tests: `test_b6b_e1_heading_embedding.py` (4), `test_b6b_e4_numbered_paragraphs.py` (5); mutations M797–M803, 7/7.

**B6B merged: PR #248, merge commit `0cef6cd`.** CI green (8/8).

## B6C – question understanding (branch `feat/b6c-question-understanding`)

`app/understanding.py`: a deterministic, structured step between follow-up
resolution and retrieval. Retrieval input only – it never produces an answer
and never reads a prior answer's text (only which document / clause the
previous turn's evidence came from).

| Behaviour | How | Test |
|---|---|---|
| Document named by its designation scopes the search | designation read from the caller's own filenames, separator-insensitive | yes |
| Scope only narrows | named / referenced documents intersected with the permitted set | yes (M805, M807) |
| A name matching several documents | search those, choose none, report | yes (M806) |
| "this standard / that document" | the previous answer's document, else the conversation's; nothing to refer to → reported, not guessed | yes |
| "this requirement / the next / previous clause" | from the previous evidence's clause number; appended to the retrieval query | yes (M808) |
| Same text in several documents | search dedup now records which kept chunk a dropped copy repeats; the answer's source is reported as ambiguous | yes (M809, M811) |
| Fallback | anything not understood leaves the question exactly as typed | yes |

Measured: frozen B6 retrieval unchanged (0.653 / 0.903 / 0.755, same misses,
p95 2.45 s). Real boilerplate questions (2): named standard → answered from
it at the right page 2/2; unscoped → flagged ambiguous 1/2 (the other's top
passage is differently worded, a legitimate clause of another standard).
Tests `test_b6c_understanding.py` (18); mutations M804–M811 8/8.

**B6C merged: PR #249, merge commit `f00f560`.** CI green (8/8).

## B7 – vision only where text/geometry reading failed (branch `feat/b7-vision-routing`)

Before B7 the vision reader (Claude only, behind `GEOMETRY_READER_ENABLED`)
was asked about EVERY page. Now `extract_facts` runs:

1. a **plan pass** – rule + geometry readers, no vision, in a transaction that
   is rolled back – to learn which pages record no fact;
2. **routing** (`datasheets.vision_route`, deterministic): a page is sent only
   if it recorded no fact, has a text layer to prove readings against (an
   image-only page belongs to the OCR tier), and the per-document budget
   (`VISION_MAX_PAGES_PER_DOCUMENT`, default 10) is not spent; the model is
   called OUTSIDE any write transaction;
3. the **real pass** writes rule, geometry and vision facts in one
   transaction, with the unchanged B4 proof and precedence rules (a vision
   reading is kept only when the text layer proves it; a rule or geometry fact
   always wins).

Every page's routing reason is in the result (`vision_routing`) and, for
unread pages, in the page ledger. With the flag off extraction is one pass,
exactly as before.

Measured on the 3 real datasheets (model stubbed – nothing left the machine):
23 pages → **6** routed to vision (−74% model calls); 17 already read by the
text/geometry readers. Whether vision recovers information on those 6 pages
needs the Claude lane (owner key + egress flags): **PENDING OWNER VALIDATION**.

Tests `test_b7_vision_routing.py` (10); four B4 vision tests now force routing
(they test proof/precedence, kept as defence in depth); mutations M812–M817
6/6; B4 phase 64 30/30 after re-anchoring M649/M650/M652.

**B7 merged: PR #250, merge commit `80695c3`.** CI green (8/8). Real vision recovery: PENDING OWNER VALIDATION (needs the Claude lane).

## B8 – answer-level safety gate (branch `feat/b8-answerability-gate`)

Every answer (extract, generated, refused; direct API and chat) carries
`answerability`: a verdict decided by structure the code can check – **never
the reranker score** – with the passages it rests on, never "high"
confidence. Order: insufficient_evidence → requires_engineer_review
(compliance judgements: chat never decides) → conflicting_evidence (two
documents, same unit, different values – including search's dropped
near-copies, which used to make a real disagreement vanish) →
ambiguous_evidence (B6C) → requires_another_document (the matching clause
only defers to a standard not held, states no value itself, and the question
did not name it) → supported.

Optional model judge (`ANSWER_JUDGE_ENABLED`, off by default; local Ollama or
Claude via the approved transport and USD caps): runs only on `supported`;
may downgrade or point to a lower passage, never upgrade a refusal; a "yes" is
accepted only with a quote verified verbatim in the passage it names; any
other output is rejected and the structural verdict stands.

Also fixed: the HTTP response model silently dropped B6C `understanding` /
`scope_ambiguity` and would have dropped `answerability` – now declared in
`schemas.AnswerResult` and `contracts/types.ts`.

Measured on the frozen real set (AI-labelled; relative only), structural gate:

| | verdicts |
|---|---|
| unanswerable (8) | 7 insufficient_evidence, **1 supported** |
| answerable, right top passage (47) | 43 supported, 2 insufficient, 1 requires_another_document (a yes/no clause – known imprecision), 1 conflicting (two standards give different distances – coarse check) |
| answerable, wrong top passage (25) | 22 supported, 3 insufficient |

The structural gate cannot tell that a topically-right passage does not answer
– that is the model judge's job, and it needs a model: **PENDING OWNER
VALIDATION** (turn on `ANSWER_JUDGE_ENABLED` with the local model; re-run the
frozen set; target: the 1 negative and the wrong-top answers downgraded or
relocated). Tests `test_b8_answerability.py` (21); mutations M818–M828 11/11.

**B8 merged: PR #251, merge commit `57d9d05`.** CI green (8/8). Model judge: PENDING OWNER VALIDATION.

## B9 – chat over the pipeline (branch `feat/b9-chat-over-pipeline`)

Chat stays an interface over B6/B6C/B7/B8 – no separate answering path. What
already held and was checked, not rebuilt: follow-ups resolve from earlier USER
questions only (SQL `role = 'user'`); the previous answer contributes only
which document and clause its evidence came from, never its text; every
answer is persisted with its passages and replayed through the same card.

Added:

| Item | What |
|---|---|
| Verdict visible | the B8 verdict renders above the answer (conflicting / ambiguous / another document / engineer review), with the evidence's page and clause; the passages stay visible |
| Refusal wording | a refusal now says **"I cannot determine this from the available evidence"** – also when the gate calls an extract insufficient |
| Scope visible | the B6C scope ("Searched: …"), clause, and same-text-in-several-documents notice are shown, never silent |
| Replay | verdict, scope and ambiguity survive reopening a conversation (they were stored but not read back into the card) |
| **Permission gap fixed** | reopening a conversation checked ownership but not grants: an answer citing a document whose grant was revoked afterwards was returned in full. `chat.get_messages` now takes the caller's scope (required) and withholds such a turn whole. Honesty audit entry 59 |
| Follow-up after revocation | a follow-up no longer carries the scope or clause of a previous answer whose document is no longer readable |

Tests: `test_b9_reopen_permissions.py` (4), one added to
`test_b6c_understanding.py`, `answerVerdict.test.tsx` (8). Mutations
M829–M843: backend 8/8, vitest 7/7.

**B9 merged: PR #252, merge commit `b31061c`.** CI green (8/8).

## B10 – submittal review workflow (branch `feat/b10-submittal-review`)

Surveyed the chain (run → applicability → comparison → findings → code → CRS →
engineer decision) against the B10 list before changing anything. Already
true, verified in code: "not evaluated / missing" is never compliant
(COMPLIANT is set in one place, from a numeric verdict; migrations leave the
column NULL); `recommend_code` never approves with nothing evaluated, with
unresolved or out-of-scope requirements, or with a cited standard missing; a
model recheck can only move a finding to NEEDS_ENGINEER_REVIEW; each finding
stores contractor evidence, requirement, standard/page/clause, rationale,
status and engineer state.

Fixed:

| Gap | Fix |
|---|---|
| Approval could be recorded in anyone's name (`approved_by` from the body) | approver = authenticated caller; anonymous → 401 |
| A finding could be created already accepted | creation is always `pending`, no disposition |
| CRS printed the AI's code with no word that no engineer had decided it | "AI recommendation – NOT yet decided by an engineer" or "Decided by the reviewing engineer", in the workbook and the preview |
| Code-decision audit swallowed its own failure | written in the decision's transaction; a failed audit rolls the decision back |
| Pair rejection (an engineer act) not audited | `review.pair_rejected` audit row, same transaction, once per pair |
| Machine-written findings had no history | `created_by_review` event: no actor, pending |
| Two completeness formulas disagreed (and one reported 1.0 with pages unknown) | one formula: the gate's; the selection delegates |

Honesty audit entries 60, 61. Tests: `test_b10_engineer_decisions.py` (10),
3 in `test_comparison.py`, 1 vitest. Mutations M844–M852 9/9 (M313/M315
retired with the code they mutated). Local backend suite 3816 passed, 4
local-only OCR failures (models absent here; green in CI).

Not changed (recorded as limitations): datasheet classification is not
re-run by the review route (it runs at ingestion); "Approved with Comments"
is still the code when only MISSING_INFORMATION findings remain (they stay
MISSING_INFORMATION, never compliant); a real-document review through the
live route is an owner-laptop gate.

**B10 merged: PR #253, merge commit `7a8f620`.** CI green (8/8). Real-document review through the live route: PENDING OWNER VALIDATION.

## B11 – reliable background jobs (branch `feat/b11-reliable-jobs`)

Surveyed first (checklist item → evidence). Already present: atomic claim
(one conditional `UPDATE … RETURNING`), retries with doubling backoff then
POISONED with the last error kept, failure state, stale-claim recovery for
ingestion and a startup sweep for extraction jobs.

| Item | Before | Now |
|---|---|---|
| Idempotency | check-then-insert in two steps – two concurrent requests queued two jobs; same race for "one running review per submittal" | both decided under `BEGIN IMMEDIATE` (`job_queue.immediate`); proven with a pause injected between check and insert |
| Cancellation | absent | `POST /api/jobs/{id}/cancel` (admin who can read the document): queued/retrying → `cancelled`, one conditional UPDATE; a running job is refused (409 with its state), never reported cancelled; a cancelled job is never claimed |
| Bounded concurrency | one thread by construction only | `job_max_running` (default 1) enforced inside the claim; a dead worker's stale claim does not count |
| Version provenance | none on jobs | `created_by`, `code_version` (extractor source hash), `config_version` recorded at enqueue |
| Audit | enqueue only | `job.queued`, `job.cancelled`, `job.poisoned`, `job.done` in `audit_events`, inside the transition's transaction |
| Permissions / progress | no job API | `GET /api/jobs`, `GET /api/jobs/{id}`: only jobs on documents the caller may read; a hidden job is the same 404 as a missing one; filters only narrow; `pages_*` null when not counted |

Tests `test_b11_jobs.py` (10); mutations M853–M864 12/12.

Not done (recorded as limitations, not claimed): a review run and the
model-assisted datasheet read / recheck still execute inside the request – no
queue, no progress, no cancel for them; moving them onto the queue changes the
review API from synchronous to polled and is left for a follow-up.
`/api/progress/{id}` (Q&A stage names, in memory) stays unauthenticated. The
review-run startup sweep still fails every `running` run, which is correct
only for the documented single server process.

**B11 merged: PR #254, merge commit `9ff9f3a`.** CI green (8/8) after one fix: a
duplicate `JobState` type in `contracts/types.ts` broke `tsc -b` and stopped the
dev server rendering (so the accessibility job never saw the app connect) –
reproduced locally with Playwright, fixed by renaming the new types, re-run green.

## Final acceptance (the 16-item list), 2026-09-26

Cloud container: 4 vCPU, 15 GB RAM, no GPU, no Ollama, no OCR models. Real
documents: the owner's 9 standards and 3 datasheets, in a scratch database
outside git; only aggregate numbers are recorded here.

| # | Item | Result |
|---|---|---|
| 1 | Backend suite | local 3825 passed, 30 skipped, 18 xfailed; 4 OCR tests fail locally only (OCR models absent here) – green in CI on every merge |
| 2 | Frontend suite | local 727 of 729; the 2 failures are local-only (fail identically on main; pass in CI) – green in CI |
| 3 | TypeScript / lint / build | `tsc -b` clean; `vite build` succeeds; oxlint 0 errors, 75 warnings (pre-existing) |
| 4 | Accessibility (axe serious/critical) | green in CI on #251–#254 |
| 5 | Secret scan (gitleaks) | green in CI on #251–#254 |
| 6 | Client-data privacy guard | green in CI on #251–#254; local diff scan 0 hits before every commit |
| 7 | All mutation groups | MUTATION_RESULT |
| 8 | Frozen B6 retrieval benchmark (fresh re-ingest, current code) | r@1 / r@5 / MRR 0.653 / 0.903 / 0.755 (frozen 0.583 / 0.875 / 0.706); reworded r@5 0.833 (0.778); own-words r@5 0.972 (0.972); 7 misses (9); p50 / p95 2.17 / 2.37 s. Identical to B6B – no regression. AI-authored set: relative only |
| 9 | Answerability benchmark (structural gate) | unanswerable 7 of 8 refused, 1 supported; right-top 43 supported / 2 insufficient / 1 another-document / 1 conflicting; wrong-top 22 supported / 3 insufficient – unchanged from B8. Model judge: PENDING OWNER VALIDATION |
| 10 | One end-to-end submittal review | all 3 datasheets through `POST /api/reviews/run`: 12 of 12 documents ingested; 9 extraction jobs through the queue (1355 requirements); facts read 177 / 64 / 174. **None of the 50 standards the three datasheets cite is among the 9 held**, so each review correctly returned Manual Review Required with 25 / 10 / 15 MISSING_LOCALLY and 0 findings. To exercise findings, the 9 held standards were added by engineer override (an exercise, not an applicability decision): 1355 findings per datasheet – 134 NEEDS_ENGINEER_REVIEW, 1221 NOT_IN_DOCUMENT_SCOPE, 0 COMPLIANT, 0 NON_COMPLIANT (no datasheet value pairs with these standards' requirements – issue #193); every finding pending approval with a `created_by_review` history row |
| 11 | CRS | generated for every run (.xlsx HTTP 200, preview rows 25 / 10 / 15 missing-reference rows; 27 / 13 / 17 after override); prints "AI recommendation – NOT yet decided by an engineer" until the engineer records the code, then "Decided by the reviewing engineer"; one `review.code_recorded` audit row per decision |
| 12 | Citations checked | all 1355 standard citations (one run) against the cited page: 1308 verbatim, 26 same words re-ordered (table rows), 21 the same table value whose degree glyph the two extractors read differently (checked by eye). 0 wrong pages. Contractor citations: none to check (no pairings) |
| 13 | Permission isolation | a user granted one datasheet sees 1 document, 1 job; another document's job and another submittal's runs are 404 (same as missing) |
| 14 | Restart / job recovery | a claimed extraction abandoned by a "dead" worker was reclaimed by the startup sweep, re-run to done, 0 duplicate active jobs; a review left running is marked failed at startup (1 of 1) |
| 15 | Latency / RAM (this container) | ingest 8–32 s per standard, 4–11 s per datasheet (real e5 + reranker models); standards extraction 9 in 9.0 s; review route 0.1–14.2 s; comparison over 1355 requirements 8.5–8.8 s; retrieval p95 2.37 s; review-process peak RSS 188 MB (no local LLM loaded) |
| 16 | What cannot be verified here | listed below |

### Still pending – owner laptop / engineer (cannot be verified in the cloud)

| Stage | Gate |
|---|---|
| B4 | live re-extract of the datasheets and one live review on the laptop |
| B5 | `scripts/b5_on_copy.py` all PASS on the laptop, then one live review; an owner-approved equipment taxonomy |
| B6 / B6B | retrieval latency on the target laptop; E5 (query expansion) needs Ollama |
| B7 | real vision recovery through the Claude lane (key + both egress flags) |
| B8 | model judge (`ANSWER_JUDGE_ENABLED` with the local model) on the frozen set – target: the 1 negative and the 22 wrong-top answers |
| B9 | the chat screens in the browser on the laptop; the generated (Tier 2) answers need Ollama |
| B10 | a review against standards the datasheets actually cite (the full library) – the only way findings get COMPLIANT / NON_COMPLIANT verdicts on real documents; engineer review of those findings |
| B11 | a real process kill during extraction on the laptop |
| All | every benchmark and gold set here is AI-authored; nothing is engineer-validated |
| OCR | OCR paths on real scanned pages (the OCR models are not in this container) |

### Known limitations (stated, not fixed)

1. On the real datasheets, no contractor value pairs with a requirement of the
   9 standards available (issue #193): the real-document reviews produced
   engineer-review and out-of-scope findings only. Compliance verdicts on real
   documents are unproven here.
2. There is no HTTP route for the engineer's applicability override
   (`applicability.override` exists and is audited, but no screen or API can
   call it) - an engineer cannot add or remove a standard from a run.
3. A review run and the model-assisted datasheet read / recheck run inside the
   request: no queue, progress or cancellation for them (B11 covers ingestion
   and standards extraction).
4. The structural answer gate cannot tell that a topically-right passage does
   not answer: 22 of 25 wrong-top answers and 1 of 8 unanswerable questions
   are still "supported" until the model judge is validated.
5. Retrieval: 7 of 72 benchmark questions miss the top 5.
6. "Approved with Comments" is the code when only MISSING_INFORMATION findings
   remain (they stay MISSING_INFORMATION, never compliant).
7. Audit failures are no longer swallowed for review decisions and job
   transitions; the admin and standards audit helpers still swallow them
   (their documented policy).
8. `/api/progress/{id}` (in-memory Q&A stage names) is unauthenticated; the
   review-run startup sweep assumes the documented single server process.
9. Repository history: commits `85e10b4`, `b2683c1` and `76e3db0` were
   rewritten off their branches but remain reachable on GitHub by SHA; only
   the owner can ask GitHub Support to purge them.
