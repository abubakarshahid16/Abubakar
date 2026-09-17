# Code review — full codebase, September 2026

A review of every module, the frontend, the test suites and the documentation,
against this project's own recorded failure modes (`../status-honesty-audit.md`)
and the review rules in `.claude/commands/review.md`.

**Method.** Nine parallel static reviews, one per area. Every finding names a
file and line, the concrete failure it produces, and the smallest fix. Reviewers
were instructed that "no findings" is a valid result and that padding a list is
itself a defect. Nothing was executed against the running system; where a
question could only be settled at runtime, the report says so. Two reviewers ran
read-only checks (`tsc`, four `pytest` files, SQLite FTS5 probes in a container)
and recorded exactly what they observed.

**Scope reviewed.** ~22,800 lines of backend Python, ~14,000 lines of frontend
TypeScript, 47 HTTP routes, 23 of 76 backend test files, the frontend test
suite, the README, six ADRs and fifteen design documents.

## Result

| Area | Critical | High | Medium | Low | Report |
|---|---|---|---|---|---|
| Access control and auth | – | 3 | 5 | 2 | [access-auth.md](access-auth.md) |
| Every route's scope usage | – | 3 | 4 | 4 | [routes-scope.md](routes-scope.md) |
| Egress and market boundary | – | 5 | 6 | 4 | [egress-market.md](egress-market.md) |
| Backend test vacuity | 2 | 4 | 4 | 3 | [tests-backend.md](tests-backend.md) |
| Honesty of the answer path | 3 | 6 | 3 | 2 | [honesty-output.md](honesty-output.md) |
| Ingestion pipeline | 1 | 8 | 9 | 4 | [ingestion.md](ingestion.md) |
| Retrieval and chat | 1 | 3 | 8 | 3 | [retrieval-chat.md](retrieval-chat.md) |
| Frontend | 2 | 2 | 3 | 2 | [frontend.md](frontend.md) |
| Documentation conformance | – | 6 | 16 | 3 | [docs-conformance.md](docs-conformance.md) |
| **Total** | **9** | **40** | **58** | **27** | 134 findings |

36 of the 47 routes were verified correct and are listed as such. The citation
gate, the "high confidence is unreachable" invariant, FTS5 escaping against 25
hostile inputs, and the fact that the access scope reaches both SQL `WHERE`
clauses before any `LIMIT`, were each traced and found to hold.

**Audit entry 15 — the `/api/metrics` scope defect — is genuinely fixed.** It is
not re-reported. Its *shape* recurs elsewhere and those instances are P1 below.

## The dominant pattern

The honesty audit says every past defect was **a field derived from something
adjacent to the truth rather than from the truth itself**. That still holds. This
review found a second, narrower pattern that accounts for a third of the
findings:

> **A defect fixed in one of its two homes.**

`egress_state()` was corrected to read the flags; `market.NOTICE` was not, so the
product still tells the client "this machine is offline" with egress on. The
README's "four views" was corrected; `Shell.tsx`'s own docstring was not. The
verbatim-label defect (audit #6) was fixed in `AnswerCard.tsx`; the report PDF
and two analysis components still assert it unconditionally. The disk figure's
heading was re-measured to 773 MB; the rows beneath it still sum to 768.

When fixing anything below, the question to ask is not "is it fixed" but **"where
else does this claim live?"**

## Priority order

Severity alone is the wrong sort order — a critical bug in uncommitted code
blocks a commit, while a critical bug in a shipped PDF misleads a client. These
are ordered by what to do first.

### P0 — blocks the current commit

The working tree holds uncommitted frontend work with two critical defects and
39 red tests. **Do not commit as it stands.**

| # | Defect | Where |
|---|---|---|
| 1 | Confirming a document's type sends only `doc_type`, so the backend upserts discipline, doc_class and every subject to NULL and deletes the `document_subjects` rows — a routine admin click silently destroys the register's classification, and the card reports success | `DocumentsView.tsx:208` |
| 2 | An unvalidated `vocabulary` body throws on `types.length` and takes down the default view. **This — not a missing coverage mock — is what fails 24 Dashboard tests**: `mockApi` routes `/classification/coverage` but not `/classification/vocabulary` | `DocumentsView.tsx:298`, `TypeFilter.tsx:94` |
| 3 | 15 of 29 `DocumentsView` tests also red; three assert against text the component splits across elements, so this diff's frontend tests were never run | `DocumentsView.test.tsx` |

### P1 — the privacy claim, and access control

The product's headline promise is that documents never leave the machine. One
finding contradicts it directly.

| # | Defect | Where |
|---|---|---|
| 4 | **The answer path POSTs prompts containing retrieved passages to `settings.ollama_url`, an unvalidated `.env` string** — no allowlist, no loopback check, no flag, no audit row. The socket-containment test covers four hand-listed market files and does not see this, the largest outbound lane in the system. README:14 and ADR-0002 promise the opposite and have no enforcement point | `answer.py:404`, `analysis.py:667`, `metrics.py:271`, `config.py:106` |
| 5 | Under the shipped default `AUTH_MODE=disabled` every caller is `unrestricted`, so `corpus_wide = scope.unrestricted or scope.is_admin` means "everybody": host telemetry, `current_document` and `last_error` — the fields removed from `/api/health` for privacy — are unauthenticated again | `main.py:193`, `metrics.py:439,484` |
| 6 | The self-deactivation guard is keyed on `actor`, which is `None` for the anonymous caller that same default admits: an unauthenticated `DELETE /api/admin/users/<admin>` deactivates every administrator. No test can see it — `test_admin.py` pins `demo_required` | `admin.py:442,219` |
| 7 | The whole `/api/admin/*` gate reads `roles.name`, not `roles.kind='capability'`. A row named `admin` with `kind='discipline'` is a full administrator to every admin route and an ordinary engineer to `AccessScope.is_admin`; `create_user` attaches it by name with no kind check | `admin.py:193,372` |
| 8 | `check_host` parses the host by string splitting, so `https://evil.test?@api.openalex.org/…` is approved as allowlisted and requested against `evil.test`, carrying the phrase and the Bearer key | `market_providers.py:282` |
| 9 | `/api/watch/status` resolves an `AccessScope` and uses it only for `folder_name`; `recent_events()` has no scope predicate, so ten real document filenames plus grant lists in `detail` go to a caller for whom `/api/documents` returns `[]` | `watch_api.py:233,304` |
| 10 | `term_occurrences`/`indexed_count` take no scope, so the answerability verdict and the user-visible "does not appear anywhere in the indexed documents" are a presence oracle over documents the caller has no grant on | `keyword.py:289`, `lexical.py:192-251` |
| 11 | `example_questions()` is unscoped: typing "hi" returns filenames and clause headings of unreadable documents, embedded in the answer and persisted to the transcript | `intent.py:212` via `answer.py:457` |
| 12 | Three dashboard ingestion aggregates (`needs_ocr_pages`, `recognised_pages`, `equation_pages`) are summed with no `WHERE`, shipped beside `"corpus_wide": false` | `metrics.py:378-381,408-410` |
| 13 | The login rate limiter's refusal writes an unauthenticated `audit_events` row, and its key is the caller's own email — a fresh email per request meets no bucket and reaches a 64 MiB Argon2 verify | `auth.py:280-287` |
| 14 | `_secret()` will sign and verify with a zero-length key | `auth.py` |

#### P1 verification (17 September 2026)

The following register was re-checked against the current tree after the
checkpoint commit. “Fixed” means the cited defect is absent in code and a
regression test exercises the boundary; “partially fixed” means the original
finding is fixed but a related claim remains elsewhere in the codebase.

| Finding | Current verdict | Evidence |
|---|---|---|
| 5 | **Fixed** | `/api/metrics` keeps corpus-wide read aggregates separate from host telemetry; host and worker identity fields require the explicit `admin` capability, including when `AUTH_MODE=disabled`. `test_disabled_auth_does_not_turn_unrestricted_reads_into_host_access` proves the old gate fails. |
| 8 | **Fixed** | `check_host()` parses URL authority with `urlsplit`, rejects credentials and non-HTTP(S) URLs, and validates the actual hostname. `test_host_allowlist_uses_url_authority_not_string_splitting` covers the historical `?@` bypass. |
| 9 | **Fixed** | `recent_events()` requires an `AccessScope` and filters `watch_events` by document grant (or the explicit admin/unrestricted policy). Watch-folder scope tests cover zero-grant and admin cases. |
| 10 | **Fixed** | `term_occurrences()` and `indexed_count()` require a scoped document set; lexical coverage passes that set through. `test_keyword.py` contains the unreadable-document oracle regression. |
| 11 | **Fixed** | `example_questions()` requires and applies the caller's document set; `test_intent.py` covers empty and restricted scopes. |
| 12 | **Fixed** | OCR and equation aggregates in `metrics.warnings()` use the same document predicate as the other dashboard counts. `test_metrics.py` and the host-telemetry suite verify grant-specific counts. |
| 13 | **Fixed** | The limiter has per-host work reservations and records a rate-limit audit event once per filled window instead of on every refusal. Auth limiter tests cover both bounds. |
| 14 | **Fixed** | Token issue refuses a signing key shorter than `MIN_SECRET_BYTES`, and token verification returns `None` for a weak key even when auth is disabled. `test_auth.py` covers both paths. |

The original static entries above remain as historical findings; this table is
the authoritative current status and prevents an old “open” row being mistaken
for a present defect.

### P2 — claims the client can read that are not true

| # | Defect | Where |
|---|---|---|
| 15 | The frozen report PDF renders "Quoted verbatim from the document" on every extract answer with no `text_source` branch, while the same file adds an OCR caveat to the same passage. This is audit #6 re-shipped in the artefact a client files. ADR-0006 forbids it; `runbook.md:78` tells the reader to report exactly this | `reports.py:354` |
| 16 | Two more unconditional verbatim labels on the analysis screen — and they *cannot* branch, because `claims.Claim` drops `text_source` before rendering. The enumerated-provenance guard only sweeps components with an `AnswerPassage`-typed prop, a boundary it never states | `ClaimTable.tsx:160`, `GapAnalysisCard.tsx:357`, `claims.py:215` |
| 17 | `AnalysisRecommendation` does not declare `recommendation_refusal`, so the reason is dropped at the wire and the screen prints its own guess — "Nothing was produced that carried a citation" — which is false for the window-overflow and model-declined cases | `schemas.py:841` |
| 18 | "This machine is offline" is a hardcoded literal in five places, so the product asserts it with both egress flags on. ADR-0002 forbids exactly this claim | `MarketPanel.tsx:96`, `market.py:54`, `analysis.py:46`, `schemas.py:869`, `AnalysisModeScreen.tsx:1543` |
| 19 | The previewed payload is not what leaves: the approval dialog shows five fields, the bytes are a URL built from `phrase` plus `&mailto=<operator email>` and `per-page`/`srlimit` that were never previewed, while the approved `country` and `freshness_days` are sent by no provider. No test compares payload to URL | `market_providers.py:480` |
| 20 | `tiers_attempted` and the `market.outbound_query` audit row are written on loop entry, so no-transport, rate-limited and refused-host cases record queries that never left | `market_providers.py` |
| 21 | `jobs.state='running'` is still written at upload and still counted, so eight queued documents report eight running jobs against a single-document worker — audit #1, unfixed at the surface that reports it | `upload.py:136`, `metrics.py:159` |
| 22 | A confidence check that could not be computed renders as "— clear", and a test locks that in. A missing check must not read as a passing one | `synthesis.py`, `test_synthesis.py:485` |
| 23 | The baseline document's own second row counts as "the project documents spoke", so a facet only the baseline addresses reads **Met** over a real gap; and `addition → met` prints "Positive matching evidence was found" where the value is absent | `claims.py`, `GapAnalysisCard.tsx` |
| 24 | "Awaiting a type" is printed over `needs_classification` (documents awaiting *confirmation*) directly above the real no-type count under the identical label — two numbers ten apart, one name | `DocumentsView.tsx:319`, `DashboardView.tsx:531` |
| 25 | The OCR backlog warning is computed from a subtraction that can never reach zero, so "N pages not read yet" can never clear once a page is recognised-but-blank | `metrics.py` |
| 26 | A page whose recognition crashed is recorded as "recognition has not run", retried forever, and its error discarded — the `ocr_failed` exclusion rule is dead code | `ocr.py`, `chunker.py` |
| 27 | Chunk-scope exclusions hardcode `clause_headings = 0`, so a whole clause lost to the quality gate raises no alert | `chunker.py` |

### P3 — functional defects

| # | Defect | Where |
|---|---|---|
| 28 | `DESIGNATOR`'s value group cannot span a dot, so `clause 5.3.2` becomes the *required* phrase `"clause 5"`, which no chunk can match (`.` is a tokenchar) — measured: zero rows against a chunk containing "clause 5.3.2". The same regex makes a heading `Table 3.9` declare `table 3` for a question about table 3.4 | `keyword.py:71-77` |
| 29 | One broad `except` turns any exception — a locked DB, one bad page image — into terminal `failed`, and **nothing can resume it**: `_next_document` excludes terminal states, no reprocess route exists, and re-upload dedups to the same dead row | `ingest.py:418` |
| 30 | `check_transition` guards 1 of 9 status writers, though the audit describes the state machine as enforced by it. Three dead edges are listed in the report's derived transition table | `ingest.py` |
| 31 | The identifier boost adds RRF units to rerank scores — two different scales — with a comment claiming it protects the result | `search.py` |
| 32 | Every `sqlite3.OperationalError` in the keyword path is reported to the user as "nothing matched" | `keyword.py` |
| 33 | The double synthesis: `recommendation()` re-synthesises its own summary, so it can refuse beside a summary panel full of citations. Mitigated in the frontend by sequencing; the backend cause stands | `analysis.py:1012` |

### P4 — tests that do not hold what they claim

| # | Defect | Where |
|---|---|---|
| 34 | The assertion the test was rewritten to add is **dead**: `hasattr(seed, "upsert_user")` is False (the function is `seed_user`), so no admin holder is created, `holder is None`, and the `scope_for_user` check never runs. Probed directly; the file reports 20 passed | `test_seed_access.py:180` |
| 35 | "Never says compliant/approved" asserts four literals absent from a stub string the test wrote itself. The real guard has **no** end-to-end test — delete it and the suite stays green | `test_analysis_routes.py:274`, guard at `synthesis.py:602-605` |
| 36 | The counter test reimplements the production increment verbatim, so the figure is tested against the test's own copy | `test_audit_findings.py:115` |
| 37 | Deny-by-default is asserted against a re-typed copy of `scope_for_user`'s SQL | `test_access_schema.py` |
| 38 | `test_the_admin_capability_is_not_a_discipline` creates roles after `init_db`, so `admin` carries `kind='discipline'` and the test stays green if `roles.kind` were dropped entirely | `test_admin.py:554` |
| 39 | 5 of 17 parametrised market-leak cases run zero assertions, including the bare `doc13.pdf` case | market leak test |
| 40 | "Reaches no documents" is checked against a database with no documents | `test_auth.py:209` |

### P5 — documentation that no longer describes the system

| # | Defect | Where |
|---|---|---|
| 41 | ADR-0006 says "Proposed — no code written" over a shipped feature | `docs/adr/ADR-0006` |
| 42 | LanceDB is in the README stack table and in no import — vectors are SQLite BLOBs plus a memmapped numpy matrix | `README.md` |
| 43 | `benchmarks.md` declares four metrics "Not yet measured" that its own file measures | `benchmarks.md:117-131` |
| 44 | Test counts are stale again: measured statically, backend `def test_` = **1,151** in 72 files, frontend `it(`/`test(` = **515** in 43 files. The README claims 1,174 and "496 across 42 files", both from older commits | `README.md` |
| 45 | `main.py:873` "No network call exists in this build. Both routes…" — there are four routes, and a flag-gated transport exists | `main.py:873` |
| 46 | `main.py:874` "Both routes are scoped" and `main.py:1413` "A NON-ADMIN GETS 404" are false of the code beside them; `schemas.py:164` still calls it "the scoped /api/metrics" | various |
| 47 | 16 further medium documentation defects, itemised with verdicts in the report | [docs-conformance.md](docs-conformance.md) |

## Architecture

There was no architecture document. One was written from the code — not from the
README — and is at [`../architecture.md`](../architecture.md). It records the
seven lanes, the data model, the three request flows with their enforcement
points named, the trust boundaries, and **which invariants have no single owner**
(7 and 8). It ends with the commands a future reader should run to check whether
it is still true.

## How to use this register

- Fix in P-order, not severity order.
- For each fix, ask **where else this claim lives** — a third of these findings
  are one half of a two-home defect.
- When a fix corrects something this project previously stated as true, add the
  retraction to `../status-honesty-audit.md`. That file is at 24 entries; several
  findings here belong in it.
- Do not mark a finding fixed without a test that fails when the fix is removed.
  Six of the findings above are tests that pass while their guarantee is absent.

## Boundary of this review

Stated plainly, because an unstated boundary is itself a defect here:

- **Not executed.** No reviewer ran the application, called the API, or ran the
  full backend suite. Items marked "needs runtime confirmation" in the reports
  are unproven either way.
- **Backend tests: 23 of 76 files read** (11 in full, 12 in sections), plus a
  mechanical AST pass over all 76. `test_watch_folder.py` and `test_reports.py`
  are the significant unopened files.
- The device's Python is 3.10 and the project needs 3.12, so every test file
  importing `app.main` failed collection during the review.
- `chunker.py` (1,634 lines) and `synthesis.py` (1,425) were reviewed against the
  invariants, not line by line.
- No performance, load, concurrency or scale testing was in scope.
