# Status honesty audit

Every status, count and boolean the API exposes, what it is computed from, and
what it must never be taken to mean.

**Why this document exists.** Twenty-nine separate times something in this
system has claimed what was not so - a status field, a count, a measurement,
twice a design document about the code it was written against, once a type that
could not describe its own API, once an evaluation harness measuring a different
layer than the one it was cited for, once the secret-scanning hook that the
privacy ADR depends on, and once the product's headline promise itself:

| # | The claim | The reality |
|---|---|---|
| 1 | `jobs.state = 'running'` written at upload, from step 1 | No worker existed. Nothing was running. |
| 2 | "11/11 terminal" reported to the client | Measured during a run corrupted by a second concurrent writer |
| 3 | `stalled: false` with six documents waiting | Computed from heartbeat freshness, which only proves the loop is spinning |
| 4 | `failed` on a fully embedded document | The chunk short-circuit did not advance the state, so a guard tripped |
| 5 | `ready` with nothing searchable | A document whose every chunk was excluded still reported ready |
| 11 | "50 call sites updated" and "no such string in the frontend" | Both counts were complete WITHIN a boundary the sweep chose for itself and never stated. Five more call sites were in `eval/`; the string was in the backend |
| 10 | Three green tests over code that was broken | Each had fixtures that could not produce the condition the test claimed to check. A vacuous test does not fail; it passes, which is worse |
| 9 | README: "Disk — ~2 GB" | 768 MB inside the clone, measured. Nobody had ever measured it; the figure was written from intuition and read as a specification |
| 8 | OCR raised coverage by **+12.5%** on NORSOK | It raised it by **+4.2%**. The "before" figure dropped every recognised CHUNK, which also drops pages that chunk merely spans — three pages were charged to OCR that OCR never read |
| 14 | `--tier generated`, documented at the top of the eval harness | The scorer could not read a generated answer: every field read `answer_passages`, which only the extract branch sets. Tier 2 rows scored zero passages and no pages, so the harness under-reported its own citation figure |
| 13 | The coverage design's six-value status enum, reviewed and approved | **None of the six was true of Q4**, the gold question the feature exists to measure. Reviewing a taxonomy against an example is not testing it against that example |
| 12 | The coverage design: the shortlist cut is "the one place candidates are dropped with no recorded reason" | `deduplicate()` and the pool builder drop silently too. A candidate lost to dedup is indistinguishable from one that never existed, so recording only the cut would have answered "was doc17 ever in the pool?" wrongly, with apparent evidence |
| 7 | A passing ordering test over a document that had `failed` | The test asserted the statuses it OBSERVED at every OCR invocation and never asserted where the document FINISHED. `partially_searchable -> chunking` was an illegal transition; the raise was swallowed by the broad handler in `process()`; every scanned document on a fresh machine landed at `failed`, green suite and all |
| 6 | "Quoted verbatim from the document" over OCR text | `AnswerCard.tsx:277` rendered the label unconditionally. 92 recognised chunks were retrievable, so a passage OCR had guessed off a page image could be cited as the document's own words, beside "quoted directly, no AI rewriting" |
| 15 | `current_document` and `last_error` were moved OFF `/api/health` "to the scoped `/api/metrics`" | **`/api/metrics` was not scoped.** It resolved an `AccessScope` via `Depends` and never passed it on. The fields moved from one unscoped route to another, and a comment recording a false reason is what made the move look like hardening |
| 16 | README: `npm run test` — **"279 tests"** | **496**, across 42 files. Understated by 217. Nobody re-measured it after the redesign and the auth work added whole test files |
| 17 | README: `python -m pytest -q` — **"887 tests, ~5 minutes"** | **1,174 passed / 3 skipped / 17 xfailed / 1 deselected** in **4m57s**, measured by CI at cd72bac. A local run of an earlier tree (5baf18e, four tests fewer) gave 1,170 in 5m44s with `--ignore` for the two parked test files. The count was understated by 287. The DURATION claim is retracted rather than replaced: three CI runs of the identical suite took 3m18s, 4m57s and 10m48s, and locally 5m44s idle against over 11 minutes contended. "~5 minutes" was not so much wrong as unsupportable - the spread is 3x on identical work, so the README now gives a range and says to check the count, not the clock. Both original figures were written once and never re-run |
| 18 | README stack table: the answer model runs at **`num_ctx`~1536** and **60-100 output tokens** | `backend/app/config.py` sets `num_ctx = 4096` and `max_output_tokens = 250`. The 1,536 figure is real but historical - it survives in `context_budget.py` as the value a past measurement was taken at, and the README kept quoting it as current configuration |
| 19 | README scope cuts: **"System view — four views"** | **Six** built views plus an Administration section, per `Shell.tsx`. Analysis and Reports were built after the line was written; a scope cut that stopped being a cut still read as one |
| 20 | README title and setup steps named **Nabaa**, and `git clone <repo-url> nabaa` | The product is the RAG Intelligence System. The `cd nabaa` was worse than a stale name: a reader following the README landed in a directory that the next command did not expect |
| 21 | `contracts/types.ts`: `Metrics.system?: SystemMetrics` | The type could not express the response the server sends. `/api/metrics` serialises `"system": null` for a non-admin, so every consumer typed against this contract was typed against a shape the backend never produces |
| 22 | `eval/score_analysis_gold.py`, run to confirm the analysis accuracy fixes | **It cannot confirm them.** It imports `app.keyword` and calls `search()` directly, so it measures the RAW retrieval layer, before the analysis-layer scoping, per-document cap and percentage recall. Its output still shows doc16 taking 18 of 24 slots and hiding its own p.18 answer - the defect a288653 fixed - because that layer really does still do that. A green run of it would have said nothing about the fix. `eval/verify_analysis_accuracy.py` was added to measure the layer that was actually changed |
| 23 | `test_recommendation_gate.py`: **"all 27 are expected to fail"** | **Eleven now pass.** The advisory-gate half of #90 was implemented; the docstring still described the whole module as unimplemented specification. `strict=True` is what caught it - the eleven went red on completion exactly as designed - but the prose had to be corrected by hand |
| 24 | `.githooks/pre-commit`, the compensating control ADR-0004 rests on | It failed OPEN two ways: a missing gitleaks printed a WARNING and exited 0, and before that an unguarded `$LOCALAPPDATA` under `set -u` aborted the hook entirely on any machine not exporting it. A control whose absence is invisible is not a control |
| 25 | README:14 and ADR-0002's Enforcement section: **"Client document content never leaves this machine"** | **The one rule had no enforcement point on the answer path's own socket.** `ollama_url` was an ordinary `.env` string (`config.py:106`) with a loopback DEFAULT and no validation, and four call sites - `answer.py:404`, `analysis.py:667`, `metrics.py:271,279` - each formatted their own URL from it and POSTed. The body carries `_build_prompt` / `synthesis.build_prompt` output, which is retrieved passage text verbatim, so `OLLAMA_URL=http://collector.example.net:11434` in `backend/.env` sent client document content to that host with no allowlist, no flag, no audit row and no log line. The four Enforcement controls do not touch it: the binding rule is INBOUND and the offline flags govern HuggingFace. Nothing had leaked - Ollama is on localhost in every deployment - but the promise rested on a default rather than a rule, and the socket-containment test could not see it: `test_market_no_document_leak.py:57` iterates a hand-written tuple of three market filenames, so the largest outbound lane in the system sat outside every guard. Now: `config.check_model_url` parses with `urllib` (never string splits - `market_providers._host_of`'s `?@` bypass is a test case), refuses a non-loopback host, embedded credentials and anything that is not a base URL, and runs TWICE - at startup, so a misconfigured machine does not boot, and again in `model_transport` immediately before every request, because `settings` can be reassigned after startup. A non-loopback host needs two explicit settings and writes an audit row. `test_socket_containment.py` asserts all of it over the WHOLE `app/` package by globbing, so the next module that opens a socket is red without anyone remembering to list it |
| 26 | `test_admin.py:554` `test_the_admin_capability_is_not_a_discipline`, and the `is_admin` shown on the admin screen | **The test never touched the column whose name it cites, and the gate it was supposed to guard read the wrong column.** `temp_storage` runs `db.init_db()` before `world` inserts its roles, so `init_db`'s corrective `UPDATE roles SET kind = 'capability' WHERE name = 'admin'` never saw them and the fixture's `admin` role carried the column default `'discipline'`. Every assertion in that test - and every one of the 44 others in the file, including `test_an_admin_reaches_every_route` - was satisfied by the NAME predicate alone, over a database in which admin was not a capability. Dropping `roles.kind` from the schema entirely would have left them all green. Meanwhile `admin.is_admin` really did read `roles.name`, so a row named `admin` with `kind = 'discipline'` was a full administrator to all seven `/api/admin/*` routes and an ordinary engineer to `AccessScope.is_admin` for the same request, and `list_users` reported `is_admin: true` for them. `main.py:185-192` had already NAMED this divergence as a hazard and closed it for `/api/metrics` only. Now: `is_admin`, `create_user`'s lookup and the listing all use `kind = 'capability' AND name = ?`; `make_role` takes a kind and writes it; and a new parametrised test walks the whole `ROUTES` table with every resource present, so a 404 can only come from the gate |
| 27 | `admin.py:442`, the self-deactivation guard: **"Without this the last admin can lock every user, including themselves, out of a system whose only other door is a terminal."** | **The guard did not hold under the shipped default, and the comment describes the outcome it permitted.** It read `if actor is not None and user_id == actor.get("id")` - keyed on WHO IS ASKING. Under `AUTH_MODE=disabled` (the default at `config.py:51`, asserted by `test_access_routes.py:311`) `current_admin` returns `None` for a caller presenting no identity, by design, so `DELETE /api/admin/users/<id>` with no Authorization header at all reached `deactivate_user` with `actor = None` and the `actor is not None` prefix skipped the refusal completely. Every account holding the admin capability could be deactivated by an unauthenticated local caller; switching to `demo_required` afterwards - the documented hardening step - then left `/api/admin/*` unreachable by anyone, with `seed_access.py` at a terminal as the only door. The same anonymous path also reached `POST /api/admin/users` and both grant routes, so document access could be widened or removed permanently, under a mode whose stated concession (`admin.py:206-213`) is argued only for READS. No test in `test_admin.py` could see any of it: `temp_storage` pins `demo_required`, under which the anonymous caller is 404'd before reaching the guard. Now: `_is_last_active_admin` asks whether an active administrator would REMAIN - a property of the corpus that mentions no caller and so cannot be skipped by having no identity - and the self-check is kept beside it |
| 28 | `watch_api.py:28`, the module docstring: **"Everything else in the payload is: whether the feature is on, how often it looks, when it last looked, and what it decided"** - and `recent_events`' own docstring, concluding that withholding `source_path` closed the leak | **"What it decided" was ten real client filenames, sent unscoped to every caller.** The route resolved an `AccessScope` and spent it on ONE field, `folder_name`; `recent_events()` took no scope and its query had no predicate. A caller with zero grants received the last ten watched-folder decisions in the same second `GET /api/documents` correctly returned `[]` for them - and `duplicate` additionally asserts that a document with that content is already in the corpus. Measured during the fix: the leaked `detail` string also carried the grant list (`granted to Mechanical, admin`). The docstring inspected the host PATH and pronounced the leak closed while the filename beside it was the leak - the same fixed-in-one-of-its-two-homes shape the review names as this codebase's dominant pattern. `test_watch_folder.py:549` and `:568` asserted the filenames were PRESENT; nothing asserted they were withheld. Now: `recent_events` takes the scope and filters on `document_id`, `WHERE 1 = 0` for an empty scope and no predicate for `unrestricted`, and rows whose `document_id` is NULL sit behind the capability gate |
| 29 | `coverage.py:26-33`: **"The gate runs exactly once, before any per-document reasoning, on the scope the request already had, and its verdict is final."** | **There was no scope.** `keyword.term_occurrences` and `keyword.indexed_count` took no `allowed_document_ids` parameter at all and counted over the whole `chunks_fts` table, so the lexical gate's verdict - and the user-visible refusal "none of the terms in this question appear in the indexed documents" - was decided partly by documents the caller has no grant on. A term present only in an unreadable document made the answer "it exists, just not for you" without saying so; a term absent everywhere made a claim about documents the caller cannot see. Either way a caller could test for a term's presence in the whole corpus, which is the disclosure `/api/health` was stripped for. The comment was precise about a property the code did not have - it named the right rule and then asserted compliance with it. The same unscoped counts also fed `acronyms.harvest`, so an unreadable document could supply the expansion that decided a caller's verdict, and the expansions are phrases lifted from that document's text. Now: both take `allowed_document_ids`, keyword-only with no default, and it is threaded through `lexical.assess`, `distinctive_terms`, `distinguishing_uncovered_terms`, `acronyms.harvest`/`equivalents`/`known_expansions`/`reverse_map` and `coverage`. An empty scope counts 0, which makes the gate ABSTAIN rather than claim absence |

| 30 | `/api/metrics` host/worker fields were gated with `scope.unrestricted`, which is intentionally true for anonymous document reads when `AUTH_MODE=disabled` | The route now separates corpus-wide aggregate counts from host telemetry. CPU/RAM/disk/model/worker identity is admitted only for the explicit `admin` capability; the default unrestricted read scope no longer fingerprints the machine. The regression test toggles the shipped default and asserts the host block is withheld. |
| 31 | `market_providers.check_host()` derived the authority by splitting strings, so a `?@` URL could pass the allowlist while targeting another host | Host validation now uses `urllib.parse.urlsplit`, rejects embedded credentials and non-HTTP(S) URLs, and compares the parsed hostname. A regression test reproduces the old bypass URL and requires refusal. |

The pattern is always the same: **a field derived from something adjacent to
the truth rather than from the truth itself.** Every entry below states what
it is derived from, so the next instance is easy to spot.

**Entry 15 is the only one where the hardening itself carried the lie.**

`/api/health` used to return `current_document` — a real document id the UI
joins against the document list to show a filename — along with free-text
`last_error` and `stalled_reasons`. That was correctly identified as a
privacy-boundary problem and correctly fixed: those fields were removed from the
one unauthenticated route.

**They were moved to `/api/metrics`, and the reason recorded for choosing that
destination was that `/api/metrics` is scoped. It was not.** The route took
`scope: AccessScope = Depends(access.current_scope)` and then called
`metrics_mod.snapshot(...)` without it. The parameter was resolved on every
request and discarded, so the corpus block was byte-identical for an
administrator, a four-document user and a user granted nothing — measured, all
three reporting 12 documents while `/api/documents` correctly returned 6, 4
and 0.

So the hardening **relocated the leak**. A document id that an unauthenticated
caller could previously read on `/api/health` became a document id that any
authenticated caller could read on `/api/metrics`, regardless of grants, and the
change was recorded as a security improvement.

The belief spread. **Seven comments in five files** described the endpoint as
"the scoped `/api/metrics`", including two inside
`test_health_never_exposes_a_traceback` — the test written to hold this exact
boundary. That test never called `/api/metrics` at all. It asserts what
`/api/health` does *not* say, which is real and still passes, and the word
"scoped" in it was an assumption it had no way to check.

This is the distinguishing feature: the earlier entries are fields derived from
something adjacent to the truth. This one is **a justification derived from
something adjacent to the truth** — a comment that made a real design decision
look safe, and was then cited by later work as though it were a verified
property. A count without a boundary reads as total; a comment without a test
reads as a guarantee.

**Entry 11 is the same shape twice, and both times the sweep was mine.**

When `search()` gained a required scope parameter I reported **"50 call sites
now pass `every_document_id()` explicitly"**. The number was exact and the
boundary was silent: I had swept `backend/`. Five more call sites lived in
`eval/`, and they surfaced only when the harness crashed with
`ask() missing 1 required keyword-only argument`. Had the parameter carried a
default, those five would have kept meaning "every document" and nothing would
have said so.

Hours later, asked to find copy claiming a shipped feature was missing, I
searched the frontend and reported the strings I found. **The false string was
in the backend**, in `metrics.warnings()` - the Dashboard renders whatever the
API sends, so the copy was never in the frontend at all.

Both reports were accurate inside their boundary and neither stated the
boundary. **A count without a boundary reads as total** - that is standing
rule 7 - and the fix in both cases was not a better search but naming the
territory first. The copy sweep now scans backend, frontend AND contracts, and
exempts comments rather than files, because a file-level exemption would have
re-admitted the very string it was written to catch.

**Entry 10 is a pattern rather than an accident, which is why it is recorded
as one.** Three tests in a single session were green over broken code, and all
three failed the same way: **the fixtures could not produce the condition the
test claimed to check.**

| Test | What its fixtures could not produce |
|---|---|
| `provenance.enumerated.test.tsx` | Only ever supplied passages that EXIST, so it could not see the verbatim label being claimed over a null passage — the exact defect it was written to prevent |
| `Shell.test.tsx` | Answered every endpoint with the health object, so `/documents` returned a non-array; the screen degraded to a spinner and the test asserted "Reading the queue" and called that success |
| `test_a_passage_too_far_below_the_primary_is_not_admitted` | Calls nothing. `_hit` is a pure factory, the `primary` candidate is never used, and the assertion compares a `separation` the test itself set to `0.89` against a constant |

The third is the purest form: a comparison between two literals, wearing a
test's name. It passed for years of commits because **a vacuous test does not
fail — it passes**, and a passing test is the thing nobody re-reads.

**It recurred within the hour, in the work that recorded it.** The
route-enforcement tests for the access scope uploaded two PDFs built from the
same template — identical bytes, therefore the same SHA-256, therefore
deduplicated by the upload path into ONE document. `visible` and `hidden` were
the same id, so every test using that fixture was asserting that a document
could not see itself. It passed. It was caught only by deliberately widening
the scope and finding that a test which should have failed did not.

The fixture now gives the two documents different text and asserts
`visible != hidden` with a comment saying why, so the vacuity cannot come back
silently. That assertion is the cheap form of the rule: **make the fixture
prove it can produce the condition, in the fixture.**

**Two of the three were found by something other than the test suite.** The
provenance one was found by reading the branch; the third by `ruff F841` on the
first lint run this codebase has ever had. The suite could not find them
because they were part of the suite.

The rule this implies is standing rule 7: **a test must be shown to fail
against the unfixed code, or it is not evidence.** Every fix in this session
that carries "proven by deliberate failure" in its commit message is that rule
being followed; these three are what it looks like when it is not. Writing the
test first is one way to get there, but not the only one — reverting the fix
and watching the test go red works just as well and is available afterwards.

**Entry 9 is the smallest here and the most ordinary, which is the point.**
The setup guide stated a disk requirement of "~2 GB". The measured figure is
**768 MB** in the clone — `.venv` 527 MB, weights 159 MB, `node_modules`
80 MB — plus ~3.4 GB for the Ollama model, which sits outside the repository
and was not mentioned at all. So the number was wrong in two directions at
once: 2.6× too high for what it covered, and silent about the largest thing a
reader actually has to find room for.

It is the same family as entry 8 — an unverified number stated with the
confidence of a measured one — and it survived for a simple reason: **nothing
depended on it.** No test reads a disk figure. No code path branches on it. A
reader with a modern disk would never notice being asked for 2 GB instead of
0.77, and a reader who *was* short of space would have been misled about the
one number that mattered. Wrong claims that nothing checks are the ones that
last longest, and a setup guide is made almost entirely of them.

Caught by measuring the finished clone rather than by anyone doubting it.

**Entry 8 is the first one that no check could have caught, and that is the
point of it.** Every other entry here is a check pointed at the wrong thing, or
a claim that stopped being true. Entry 8 is neither: it is **a number that
looks like the thing you need and is a different quantity wearing the same
units.**

Coverage "before OCR" was computed by removing every recognised chunk from the
index and re-counting covered pages. That sounds right, and it is arithmetically
flawless. It is also not coverage-before-OCR, because a chunk spans a page
RANGE. One NORSOK chunk covers pages 21–24:

| Page | Truth | What the wrong number assumed |
|---|---|---|
| 21 | already covered by another chunk | lost without OCR |
| 22 | **413 extracted characters of its own** | lost without OCR |
| 23 | genuinely blank — 0 extracted, 0 OCR boxes | lost without OCR |
| 24 | 0 extracted, 14 OCR characters | lost without OCR — **the only true one** |

Three of the four pages were charged to OCR that OCR did not read. The reported
gain was **+12.5%**; the real one is **+4.2%**. It would have overstated the
feature's value threefold **in the feature's own headline number** — the single
figure anyone would quote about this work.

**No automated check would have found it.** The number was internally
consistent: the same query, the same rows, the same arithmetic, reproducible to
the digit. A test asserting "coverage after ≥ coverage before" passes. A test
asserting the gain is positive passes. There is nothing wrong to detect unless
you already know what the number is supposed to count.

**What caught it was hand-checking the smallest document.** NORSOK is 24 pages
with 3 recognised — small enough to list every page and ask, of each one,
whether OCR really reached it. That is the whole reason it was chosen as the
first proof, and it paid for itself immediately. The lesson is standing rule 7:
a number is not a measurement until you can say what it counts, and the cheapest
way to find out is to check one case by hand.

**The same measurement produced a second instance of the same shape, hours
apart.** The "what is still missing" breakdown reported *21 pages uncovered
with no exclusion recorded* — which, if true, would have broken the standing
promise that nothing is dropped silently, and was minutes from being filed as
a defect against the pipeline. It was a defect in the query: it looked only at
`scope='page'` exclusions, and a page can also be uncovered because every
CHUNK on it was excluded. All 21 carried a chunk-scope `content_quality_gate`
row saying exactly why. Correct arithmetic over the wrong population, twice, in
one script. The count of silently-dropped pages is **zero**.

**Entry 7 is a DIFFERENT SHAPE from every other entry here, and that is why it
is worth its own paragraph.** Every earlier failed check could not see its
subject: a footer fixture that was itself a footer, a typecheck that ran over
zero files, a reranker judging a chunk on a fragment of itself, a TestClient
that never traverses the layer where the `Server:` header is written. The fix
in all of those was to point the check at the real thing.

Entry 7 saw its subject perfectly clearly and **asserted the wrong property
about it.** The test watched every OCR invocation, confirmed each one happened
while the document was answerable, and was completely correct about that. It
simply never asked whether the document survived. `process()` catches broadly
and records failure on the row, so the exception left no mark the test was
looking at — a green suite over a corpus where every scanned document had
failed.

The rule this implies is standing rule 7: **a test that asserts intermediate
state must also assert terminal state.** Steps are cheap to observe and are
what a test naturally reaches for; outcomes are what the user gets. Nothing in
this repository's working tree could have caught it either, because the
document that exercises the path was already ingested here. It took a clone
into an empty directory.

**Two smaller instances from the same clean-clone pass**, both the same family
— a claim that was true when written and quietly stopped being true:

- **`huggingface_hub` was an undeclared dependency.** `scripts/fetch_models.py`
  imports it directly; pip was getting it for free as a transitive of
  `tokenizers`. Nothing was broken, and nothing would be until a resolver
  chose differently — at which point model staging fails on a fresh clone,
  during setup, on a machine about to be air-gapped. **A dependency you did not
  declare is one you did not choose.**
- **README "Getting started" read "Not yet available — see `docs/` once
  `DEV-001` lands".** DEV-001 landed long ago. A placeholder that outlives its
  plan stops reading as a placeholder and starts reading as a fact, and a
  fresh clone had no instructions at all.

**Entry 6 is the sharpest instance, and it happened inside the feature built
to prevent it.** Provenance was stored (`page_ocr`), carried to `chunks`,
threaded through retrieval and passage expansion, and made a REQUIRED field in
`contracts/types.ts` so no caller could omit it — and the one screen where it
decides whether a sentence may be called the document's own words never read
it. Every layer was correct and the claim was still false.

The lesson is a rule, now standing rule 12: **a provenance field that no
assertion reads is decoration.** Storing it, typing it and requiring it are
not the safeguard; the safeguard is a test that fails when the label is wrong.
The test that now guards this asserts the ABSENCE of the verbatim label on
recognised text, not merely the presence of the OCR one — a presence-only
assertion passes happily while both labels sit on screen together. It was
proven by deliberate failure: forcing the old unconditional branch back makes
it fail.

---

## The verification that verified nothing

A second pattern, distinct from the one above and more dangerous, because the
first is a field that lies while the second is a **check that cannot see the
thing it judges**. Five instances, all in this build:

| # | The check | Why it could not see | How it was caught |
|---|---|---|---|
| 1 | `Server:` header removal, asserted with TestClient | uvicorn writes that header at the HTTP protocol layer, **after** the ASGI app. TestClient never traverses it, so the assertion passed against a server that still sent it. | Reading the real response over the wire |
| 2 | Footer stripper, asserted against a synthetic page | Every line of the fixture was templated per page, so the fixture's own body text **was itself a repeating footer**. The stripper removed it correctly and the test demanded it fail to. | The test failing for the opposite reason to the one expected |
| 3 | `tsc --noEmit -p tsconfig.json` | `tsconfig.json` is a solution file with `"files": []` and project references, so it type-checked **zero files**. Every "typecheck clean" report was vacuous. | Noticing exit 0 on a file with an unterminated string literal |
| 4 | "Stale numbers are dropped on refresh", with fake timers | The timers were installed **after** the component had created its interval with real ones. Advancing them fired nothing; the test passed while asserting nothing. | Reading the test back after writing it |
| 5 | The cross-encoder's own rerank window | `rerank_max_tokens` was 256 against a `chunk_max_tokens` of 480, so a 486-token passage was scored on its first 256 tokens. The answer sat at token 350. It returned **−10.95** — correct about what it was shown, wrong about the passage. | Measuring a hypothesis that turned out to be false, and looking further |

**Number 3 recurred, on 2026-09-05, in this repository, to the person who wrote
this list.** CI was fixed to run `tsc -b` and carries a comment saying exactly
why. That did not stop `npx tsc --noEmit` being typed by hand, repeatedly,
across a whole session, with "typecheck clean" reported from it each time. The
command loads `tsconfig.json`, which has `"files": []`, and checks nothing.

It surfaced only when eleven untracked frontend files needed checking and the
listing came back empty - `--listFiles` printed no file at all, which is what a
vacuous check looks like when you finally ask it what it covered. Run properly
the eleven were clean. **Every conclusion was right and none of the evidence
was worth anything.**

This is standing rule 11 - **a documented hazard is not a guard** - demonstrated
against its own author. The hazard was written down, the CI path was fixed, and
the hand-typed path stayed open. The guard that would have caught it is the one
now applied everywhere else in this document: **ask a check what it covered
before believing it passed.**

Number 5 is the one to remember: **the evaluation recorded a retrieval failure
that was really a truncation failure.** The system was not bad at retrieval. Its
judge had read half the evidence.

A seventh, of the same family but caused by tooling rather than by design: a shell
heredoc silently turned `\b` into the literal byte it names, 0x08, **three
separate times**. Each produced a regex that could never match, inside a rule
that looked fully implemented and had never fired once. A 0x08 is invisible in
an editor, in `sed` output and in a diff, and is syntactically valid inside a
string literal. `backend/tests/test_source_hygiene.py` now fails the build on
any stray control character.

It earned its place within the hour. Writing the paragraph above, the heredoc
ate the `\b` **in the sentence describing `\b` being eaten** - a sixth
instance, in the document about the pattern. The guard failed the build
immediately, naming the file, the line and the byte. That is the whole
argument for it: the previous three were found by accident, days apart, after
shipping.

### A sixth, and the worst of them: CI never ran the tests

Found while writing this section. `.github/workflows/` contained
`secret-scan.yml` and nothing else - gitleaks and the no-client-data guard. So
**"CI green" on roughly ten pull requests meant "no secrets leaked"** and
nothing whatever about the 407 backend and 89 frontend tests. A failing test
could be committed and merged, and was: the source-hygiene guard was red in the
commit that introduced it.

Model weights are gitignored, which is presumably why no test job existed -
without them most of the backend suite does not fail, it SKIPS, and a skipped
suite reports success. `scripts/fetch_models.py` stages them and exits
non-zero on a partial staging, and the CI job verifies the staging BEFORE
running the suite, so a half-armed run cannot pass as a clean one.

`.github/workflows/tests.yml` now runs pytest, vitest, `tsc -b` and the
production build on every push and pull request.

### A seventh: a written-down trap is not yet a guard

A reprocessing script omitted the `__main__` guard that Windows `spawn`
requires. The project had this hazard **documented** — PyMuPDF must run in
processes, and Windows re-imports `__main__` in each child — and the script
still fell into it, deleting book4's extracted pages before dying.

The lesson is not "remember the guard". It is that **a trap written down in a
document is not in the path of the tool that falls into it.** Knowledge in
prose protects nothing; only a check in the execution path does.

### An eighth, and the first one caught by a check rather than by luck

A heredoc ate a `\b` and wrote a literal 0x08 backspace byte into a source
file. This had happened seven times before and every previous instance was
found by accident. The eighth was caught by `test_source_hygiene.py`, which
named the file, the line and the byte.

Recorded because it is the first time this class of bug was stopped by a guard
instead of by noticing. That is the whole point of the rule below, observed
working.

### A ninth: a result file that certified a corpus it never inspected

`eval/run_eval.py` stamped `"corpus": data.get("corpus")` on every result — a
static string copied out of the **questions file**. It described what the
questions were written against and was written to the result regardless of what
was actually ingested. The 4,346 ms result claims `"3 documents: NORSOK,
book1, book2"` whether or not a fourth 1,400-page document was present.

The cost was concrete. A reported **superlinear latency growth, 1,915 ms at 3
documents to 4,346 ms at 4**, could not be checked against the record, because
no stored result could say which corpus it ran on. Every one of nine runs was
unattributable. It had to be re-measured from scratch — and **the growth did
not exist**: retrieval grew x1.04 for x1.79 the chunks, and the change was
machine state across a 40-minute gap.

Replaced with `observed_corpus()`, read from the database at run time —
document count, chunk count, retrievable count, excluded count, vector count
and a hash of the document ids — kept as `corpus_observed` **alongside** the
static `corpus_declared`, so a mismatch between what the questions assume and
what the run saw is visible rather than silently resolved in favour of the
claim. `machine_state()` records free RAM and whether the answer model is
resident, because that moves the headline number further than the corpus does.

`test_eval_provenance.py` reinstates the old field and confirms four of its
six tests go red against it.

### A twelfth: the design premise that was wrong about its own pipeline

The multi-document coverage design named the 16-slot shortlist cut as **"the
one place in this pipeline where candidates are dropped with no recorded
reason"**. It was not the one place. `deduplicate()` discarded near-identical
candidates and returned a shorter list saying nothing about it, and the pool
builder skipped chunks whose row had gone or had been marked non-retrievable,
also silently.

The cost would have been a false answer to the question the telemetry was built
to answer. **A candidate lost to dedup is indistinguishable from a candidate
that never existed**, so a document that contributed candidates and lost them
all to duplicate-merging would have read as a document that matched nothing —
and "was doc17 ever in the pool?" would have been answered wrongly with
apparent evidence. All five drop reasons are now recorded under one slug
vocabulary.

### A thirteenth: a taxonomy reviewed against its example, never tested against it

The same design specified a six-value status enum for per-document coverage. It
was reviewed carefully and it reads well. **None of its six values was true of
Q4** — the gold question the entire feature exists to measure.

doc17 was retrieved, so not `expected_not_retrieved`. Shortlisted, so not
`expected_not_shortlisted`. Scored **+2.104 against a -3.0 floor**, so not
`retrieved_not_credible`. Not in `supporting`, and not `answered`, and plainly
not `searched_no_match`. Had the enum shipped as designed, Q4 would have been
filed under whichever value was least wrong, and the coverage report would have
made a false statement about the one case it was built for.

This is the same family as the vacuous fixture: **a structure that cannot
produce the condition it claims to cover.** The fixture could not produce two
distinct documents; the enum could not express the outcome it was designed
around. Reviewing a taxonomy against an example is not testing it against that
example — the test is to take the real case and try to write its row.

Fixed by a seventh value, `credible_not_cited`, which names the fact in the
reader's terms rather than the mechanism: this document had a passage that
passed the credibility floor, and the answer did not use it.

### A fourteenth: the harness could not score the tier it documented

`eval/run_eval.py` documents `--tier generated` at the top of the file. Its
scorer could not read a generated answer at all.

Every scored field - the cited pages, the cited document, the cited clause, the
passage count, the returned text - read `answer_passages` or `passage`, and
**both are set only by the extract branch**. A Tier 2 answer sets `passages`
plus `cited`. So a generated answer scored zero passages, no pages, no
document, and empty text: `retrieval_correct` and `citation_correct` came out
false however well it had answered.

It surfaced the moment a question pinned itself to Tier 2. Question 17 answered
correctly - the right table, page 597, clause 15.3, values read off the row -
and the harness recorded `wrong page, wrong clause, pages []`. Fixing the
scorer moved the citation figure from 10/11 to **11/11**, which means the
harness had been under-reporting itself, in the safe direction, for as long as
anyone had been able to run it that way.

Nobody saw it because the harness had only ever been run at `--tier extract`.
That is the third instance of the same shape in this build: **the harness could
not see the defect because every question it asked avoided the condition.** The
P&ID false refusal needed an answer below rank 1; the token budget needed
evidence that was not prose; this needed a question asked at Tier 2.

The fix is one function, `evidence_of(result)`, used by every field that
previously read the extract shape directly, with tests for both tiers.

### The rule this produces

**Before trusting a check, confirm it fails when it should.** Plant the defect
it exists to catch and watch it go red. Two of the first five passed for weeks;
none failed loudly; two were found only by accident. Of the fourteen instances
now recorded, exactly one — the eighth — was caught by an automated check.

The twelfth and thirteenth were caught by reading a design against the code
while implementing it, and by taking the real case and trying to write its row.
That is diligence, not a check, and it does not scale — which is why the
thirteenth produced a standing rule rather than only a fix.

Corollary: **guard the guard.** Every check whose scope can silently shrink to
nothing needs a companion test asserting it still sees something — that the
scanner finds files, that the fixture list is non-empty, that the query matched
rows. `test_source_hygiene.py` does both: one test plants a backspace byte and
requires it to be caught, another asserts the scan covers more than forty files
so an empty sweep cannot pass as a clean one.

---

## Document status

Single source of truth: `documents.status`. Legal transitions are declared in
`app/states.py` and enforced by `check_transition`.

| Status | Set by | Means exactly | Does NOT mean |
|---|---|---|---|
| `queued` | upload | The row exists and the file is on disk | That anything is processing it |
| `extracting` | worker | Page extraction is in progress or interrupted part-way | That any page is searchable |
| `chunking` | `extract_document` on completion | Pages are extracted; chunking pending or interrupted | That chunks exist yet |
| `indexing_keyword` | `chunk_document` on completion **and on short-circuit** | Chunks exist; keyword index pending | That search works |
| `partially_searchable` | worker | Keyword search works; vectors still arriving | Ready. Never labelled ready |
| `ready` | worker, only when `embedded_count >= chunk_count` **and** `chunk_count > 0` | Keyword + vector search both complete | That every page was extractable — check `needs_ocr_pages` |
| `no_searchable_content` | worker, when `chunk_count == 0` after processing | Processing finished; nothing is searchable. `error_message` states which cause | Failure. Processing succeeded; the document is empty of usable text |
| `failed` | worker, on exception | Processing raised. `error_code` + safe `error_message` | That the document is unusable forever — it is resumable |

**Terminal:** `ready`, `no_searchable_content`, `failed`.
**Answerable:** `partially_searchable`, `ready`. Nothing else may serve a query.

`indexed_at` is set **only** on reaching a terminal state, and is the field to
trust for "did this finish", not `status` alone.

---

## Counts on the document record

| Field | Computed from | Trap it avoids |
|---|---|---|
| `page_count` | `fitz` page count, read once at extraction | `null` until the manifest is read — never assume 0 |
| `pages_done` | `COUNT(*) FROM pages` | Not a percentage; compare against `page_count` |
| `chunk_count` | `COUNT` of chunks with `retrievable = 1` | **Retrievable only.** What search can actually see |
| `chunk_count_total` | `COUNT` of all chunk rows | Includes front matter, contents, index and gate-rejected rows |
| `embedded_count` | `COUNT(*) FROM chunk_vectors` after each batch | Progress against `chunk_count`, not `chunk_count_total` |
| `needs_ocr_pages` | `SUM(pages.needs_ocr)` | **Detection only.** OCR is not implemented; these pages are not searchable |
| `equation_pages` | `SUM(pages.equation_heavy)` | Flags the worst pages, **not all** pages whose maths degraded. Not exhaustive |

`chunk_count` and `chunk_count_total` differ on nearly every real document.
Reporting only one of them is how "19% of pages vanished" stayed invisible.

---

## Worker health — `GET /api/health` → `ingestion`

| Field | Computed from | Notes |
|---|---|---|
| `alive` | thread `is_alive()` | Proves the thread exists, nothing more |
| `current_document` | document id being processed, `null` when idle | Idle is not the same as stuck |
| `seconds_since_heartbeat` | time since the loop last iterated | **Only proves the loop is spinning** |
| `seconds_since_progress` | time since a document last reached a *terminal* state | The honest progress signal |
| `documents_completed` | counter, incremented on a not-finished → finished transition | Resets when the process restarts |
| `pending_count` | count of documents in a non-terminal state, plus answerable ones with vectors outstanding | A backlog is visible without querying SQLite |
| `oldest_pending_age_seconds` | age of the oldest pending document's `uploaded_at` | Distinguishes a fresh queue from a stuck one |
| `stalled` | `not alive` **or** heartbeat > 120 s **or** (`pending_count > 0` **and** `seconds_since_progress` > 180 s) | Reflects whether work is *moving* |
| `stalled_reasons` | which of the above fired | Never just a bare boolean |
| `last_error` | `{code, message, document_id, stage, at}` | **Response-safe only.** Full tracebacks go to `backend/data/logs/rag-intelligence.log` |

An idle worker with an empty queue is **not** stalled. A worker alive and
ignoring a backlog **is**.

---

## Booleans on chunks and pages

| Field | Computed from | Trap |
|---|---|---|
| `chunks.retrievable` | `kind in {prose, table}` **and** the content-quality gate passes | Excluded rows are kept and readable at `?retrievable=false` |
| `chunks.quality_flags` | the gate's rejection reasons | `null` when retrievable |
| `pages.needs_ocr` | usable characters < 100 | Detection only |
| `pages.equation_heavy` | equation-token density ≥ 0.25 | Conservative; flags the worst, not all |

---

## Error codes

`internal` is reserved for genuine unexpected failure. A caller's mistake
returns `not_found`, `invalid_parameter`, `unknown_parameter` or
`confirm_required`; a rejected upload returns `not_pdf`, `encrypted_pdf`,
`too_large` or `duplicate`. Codes are declared in `app/errors.py` and a test
asserts no client error ever reports `internal`.

---

## Standing rules

1. A field must be derived from the thing it claims, not from something
   adjacent to it.
2. Any state that can be reached must be reachable *out of* — every
   non-terminal status is resumable by a running worker, tested without a
   restart.
3. No count is published alone when a second count changes its meaning
   (`chunk_count` always alongside `chunk_count_total`).
4. No rate is published from a near-zero denominator — `app/rates.py` returns
   `null` instead.
5. No API response carries a traceback, a path or a line number.
6. **A measurement records the state it ran against, read from that state.**
   Corpus counts and machine state come from the database and the OS at run
   time, never from a static declaration. A result that cannot say what it ran
   against is not a measurement.
7. **When you report a count of things found, state where you looked.** A
   count without a boundary reads as total. "50 call sites" and "no matches in
   the frontend" were both true and both incomplete, and neither said so.
8. **A test must be shown to FAIL against the unfixed code, or it is not
   evidence.** A test that has never been watched failing is an assertion that
   the fixtures reach the code, and that assertion is usually untested.
9. **A number is not a measurement until you can say what it counts.** Before
   quoting a figure, name the unit and the population, and check one case by
   hand. An internally consistent wrong number passes every automated check
   there is.
10. **Observing a step is not observing an outcome.** A test that asserts
   intermediate state must also assert terminal state. Watching the right
   thing happen says nothing about whether it worked.
11. **A documented hazard is not a guard.** If a trap is worth writing down, the
   check belongs in the path of the tool that can fall into it.
12. **A taxonomy is not tested until a real case has been written into it.**
   Reviewing an enum against an example proves only that it reads well. Take
   the case the feature exists for, try to fill in every field, and require
   that exactly one value is true. A structure that cannot express its own
   headline case will not fail loudly — it will file that case under whichever
   value is least wrong.
13. **A provenance field that no assertion reads is decoration.** Storing,
   typing and requiring it are not the safeguard. Where provenance decides
   what a claim may say, a test must assert the ABSENCE of the stronger claim
   — presence-only assertions pass while both claims are on screen.
14. **A check that can run against zero inputs must assert it ran against more
   than zero.** The rule the fixtures already carry, applied to tools. A type
   checker with no files, a scanner with no paths, a test filter that matched
   nothing — each exits 0 and reads as a pass. Before believing a tool's clean
   result, ask it what it covered (`--listFiles`, a count, a non-empty
   listing), and make the harness ask so a person does not have to.
