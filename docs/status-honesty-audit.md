# Status honesty audit

Every status, count and boolean the API exposes, what it is computed from, and
what it must never be taken to mean.

**Why this document exists.** Five separate times a status field has claimed
something the system was not doing:

| # | The claim | The reality |
|---|---|---|
| 1 | `jobs.state = 'running'` written at upload, from step 1 | No worker existed. Nothing was running. |
| 2 | "11/11 terminal" reported to the client | Measured during a run corrupted by a second concurrent writer |
| 3 | `stalled: false` with six documents waiting | Computed from heartbeat freshness, which only proves the loop is spinning |
| 4 | `failed` on a fully embedded document | The chunk short-circuit did not advance the state, so a guard tripped |
| 5 | `ready` with nothing searchable | A document whose every chunk was excluded still reported ready |

The pattern is always the same: **a field derived from something adjacent to
the truth rather than from the truth itself.** Every entry below states what
it is derived from, so the next instance is easy to spot.

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

### The rule this produces

**Before trusting a check, confirm it fails when it should.** Plant the defect
it exists to catch and watch it go red. Two of the five above passed for weeks;
none of the five failed loudly; two were found only by accident.

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
