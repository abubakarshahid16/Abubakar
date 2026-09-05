# Status honesty audit

Every status, count and boolean the API exposes, what it is computed from, and
what it must never be taken to mean.

**Why this document exists.** Ten separate times a status field has claimed
something the system was not doing:

| # | The claim | The reality |
|---|---|---|
| 1 | `jobs.state = 'running'` written at upload, from step 1 | No worker existed. Nothing was running. |
| 2 | "11/11 terminal" reported to the client | Measured during a run corrupted by a second concurrent writer |
| 3 | `stalled: false` with six documents waiting | Computed from heartbeat freshness, which only proves the loop is spinning |
| 4 | `failed` on a fully embedded document | The chunk short-circuit did not advance the state, so a guard tripped |
| 5 | `ready` with nothing searchable | A document whose every chunk was excluded still reported ready |
| 10 | Three green tests over code that was broken | Each had fixtures that could not produce the condition the test claimed to check. A vacuous test does not fail; it passes, which is worse |
| 9 | README: "Disk — ~2 GB" | 768 MB inside the clone, measured. Nobody had ever measured it; the figure was written from intuition and read as a specification |
| 8 | OCR raised coverage by **+12.5%** on NORSOK | It raised it by **+4.2%**. The "before" figure dropped every recognised CHUNK, which also drops pages that chunk merely spans — three pages were charged to OCR that OCR never read |
| 7 | A passing ordering test over a document that had `failed` | The test asserted the statuses it OBSERVED at every OCR invocation and never asserted where the document FINISHED. `partially_searchable -> chunking` was an illegal transition; the raise was swallowed by the broad handler in `process()`; every scanned document on a fresh machine landed at `failed`, green suite and all |
| 6 | "Quoted verbatim from the document" over OCR text | `AnswerCard.tsx:277` rendered the label unconditionally. 92 recognised chunks were retrievable, so a passage OCR had guessed off a page image could be cited as the document's own words, beside "quoted directly, no AI rewriting" |

The pattern is always the same: **a field derived from something adjacent to
the truth rather than from the truth itself.** Every entry below states what
it is derived from, so the next instance is easy to spot.

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

The lesson is a rule, now standing rule 11: **a provenance field that no
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

### The rule this produces

**Before trusting a check, confirm it fails when it should.** Plant the defect
it exists to catch and watch it go red. Two of the first five passed for weeks;
none failed loudly; two were found only by accident. Of the nine instances now
recorded, exactly one — the eighth — was caught by a check rather than by luck.

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
| `last_error` | `{code, message, document_id, stage, at}` | **Response-safe only.** Full tracebacks go to `backend/data/logs/nabaa.log` |

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
7. **A test must be shown to FAIL against the unfixed code, or it is not
   evidence.** A test that has never been watched failing is an assertion that
   the fixtures reach the code, and that assertion is usually untested.
8. **A number is not a measurement until you can say what it counts.** Before
   quoting a figure, name the unit and the population, and check one case by
   hand. An internally consistent wrong number passes every automated check
   there is.
9. **Observing a step is not observing an outcome.** A test that asserts
   intermediate state must also assert terminal state. Watching the right
   thing happen says nothing about whether it worked.
10. **A documented hazard is not a guard.** If a trap is worth writing down, the
   check belongs in the path of the tool that can fall into it.
11. **A provenance field that no assertion reads is decoration.** Storing,
   typing and requiring it are not the safeguard. Where provenance decides
   what a claim may say, a test must assert the ABSENCE of the stronger claim
   — presence-only assertions pass while both claims are on screen.
