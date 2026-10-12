# Load test - several engineers at once

`scripts/load_test.py` answers one question: **what happens to response times,
and does anything break, when several people use the system at the same time?**

> **Every number on this page is from a SYNTHETIC corpus on a SANDBOX machine,
> not the owner's PC.** They show how the system behaves as load rises. They
> are not production numbers, and they do not go in `docs/benchmarks.md`, whose
> rule is "measured on the target hardware only". Run the script on the
> owner's PC to get those.

## How to run it

From the repository root, with Python 3.12 and the models staged
(`python scripts/fetch_models.py`):

```
python scripts/load_test.py
python scripts/load_test.py --docs 20 --levels 1,2,5,10,20 --requests-per-level 200 --seed 7 --out C:\temp\load.json
python scripts/load_test.py --workloads answer,chat --levels 1,5 --requests-per-level 50
```

| Option | Default | Meaning |
|---|---|---|
| `--docs` | 20 | synthetic standards to generate (4 pages each, `--pages`) |
| `--sheets` | 3 | synthetic submittal datasheets |
| `--levels` | 1,2,5,10,20 | how many people at once |
| `--requests-per-level` | 100 | requests sent at each level, per workload |
| `--workloads` | all five | `documents,answer,crs,chat,mixed` |
| `--out` | `results.json` in the temp dir | where the results JSON goes. Keep it OUT of the repo. |
| `--seed` | 7 | makes the corpus and the mixed workload repeatable |
| `--warmup` | 3 | untimed requests per workload before timing |
| `--keep` | off | keep the temp directory (database, server log) afterwards |

It needs no Ollama, no login and no network. It never opens the live
database: it builds its own in a new temporary directory.

## What it does

1. **Builds a synthetic corpus** in a temp directory: standards-like PDFs with
   numbered clauses and requirement sentences carrying numbers and units
   ("The design pressure of the vessel shall be not less than 6900 kPa"), plus
   datasheets written like a contractor's submittal. Each is uploaded and fully
   ingested - extracted, chunked, keyword-indexed and embedded - by the same
   `IngestionWorker` the server uses. A completed review run with 12 findings
   is inserted directly into the database (the shape `test_crs_endpoint.py`
   uses) so the CRS preview has real rows to build.
2. **Starts the real server** in a separate process on `127.0.0.1` (uvicorn,
   as `run.py` does), pointed at that temp directory, with
   `AUTH_MODE=disabled` and every other setting at the code default -
   `backend/.env` is not read (the test suite's `env_isolation` is applied).
3. **Checks the routes do real work** before timing (untimed): every one of
   the 12 test questions is asked once and the number that came back with a
   passage is recorded, so the test cannot quietly measure a search that
   abstains on everything.
4. **Warms up** - the first answer loads the embedder and reranker models.
   That one-off cost is excluded from every timed number.
5. **Runs each workload at each level.** "Concurrency 10" means 10 simulated
   engineers, each sending its next request the moment the previous one
   returns (a closed loop - the worst case: real people pause to read).
6. **Scans the server's log** for tracebacks and for SQLite's
   `database is locked` / `schema has changed`, because a 500 response body is
   deliberately generic and would hide the cause.

Why a real server in its own process rather than `TestClient` threads: it is
what engineers actually hit - one uvicorn event loop feeding FastAPI's shared
thread pool - and the load generator does not share the server's Python
interpreter lock. It does share the machine's CPU cores (stated below).

### The workloads

| Workload | Route | What it exercises |
|---|---|---|
| documents | `GET /api/documents?limit=50` | the library list; SQLite reads |
| answer | `GET /api/answer?tier=extract` | keyword (FTS5) + vector search + cross-encoder rerank; the verbatim tier, no answer model |
| crs | `GET /api/reviews/runs/{id}/crs/preview` | building a Comment Resolution Sheet from 12 findings; SQLite reads |
| chat | `POST /api/conversations/{id}/ask`, `tier=extract` | the chat: the same search as `answer`, PLUS it **writes** both turns to SQLite |
| mixed | 40% documents, 35% answer, 10% crs, 15% chat | a realistic blend; each route's own numbers inside the mix are recorded too |

The chat workload spreads its requests over 20 conversations (one per
simulated engineer at the highest level).

### What counts as an error

Any response that is not 2xx, and any client-side exception. Errors are
counted by type: `http_500`, `exception:BrokenPipeError`, `sqlite_locked`,
and so on. Latency percentiles are over **successful** requests only, so a
fast failure cannot make the system look quicker.

## Results - 2026-09-29

**Synthetic corpus, sandbox machine, not the owner's PC.**

| Field | Value |
|---|---|
| Machine | Linux sandbox, Intel Xeon @ 2.80 GHz, **2 vCPU**, 7.8 GiB RAM, no GPU |
| Python | 3.12.3 |
| Load generator | on the same machine, sharing the 2 vCPU with the server |
| Corpus | 20 standards x 4 pages + 3 datasheets = 23 documents, 183 chunks, all 183 embedded, all 23 `ready` |
| Response check | answer: **12 of 12** questions came back with a passage (`extract`); CRS preview: 12 rows |
| Command | `python3.12 scripts/load_test.py --docs 20 --levels 1,2,5,10,20 --requests-per-level 200 --seed 7` |
| Wall time | 11 min 24 s for the whole run, corpus build included (ingest 10.3 s, warm-up 4.8 s) |

The command was run twice. The table is the second run; the first run is
compared below it.

### Each workload on its own

| Workload | Concurrency | Requests | Errors | req/s | p50 ms | p95 ms | max ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| documents | 1 | 200 | 0 | 406.7 | 2.3 | 3.6 | 7.6 |
| documents | 2 | 200 | 0 | 369.3 | 5.1 | 9.2 | 12.1 |
| documents | 5 | 200 | 0 | 254.4 | 17.2 | 39.8 | 57.7 |
| documents | 10 | 200 | 0 | 249.6 | 36.2 | 75.0 | 97.8 |
| documents | 20 | 200 | 0 | 181.3 | 100.3 | 220.6 | 310.2 |
| answer | 1 | 200 | 0 | 3.9 | 252.3 | 438.0 | 566.2 |
| answer | 2 | 200 | 0 | 3.7 | 522.9 | 990.4 | 1,170.1 |
| answer | 5 | 200 | 0 | 4.0 | 1,175.8 | 2,220.3 | 2,563.5 |
| answer | 10 | 200 | 0 | 4.1 | 2,313.9 | 4,418.3 | 4,848.6 |
| answer | 20 | 200 | 0 | 4.2 | 4,407.4 | 8,408.0 | 9,970.2 |
| crs | 1 | 200 | 0 | 300.9 | 3.0 | 5.0 | 14.5 |
| crs | 2 | 200 | 0 | 237.8 | 7.8 | 13.8 | 25.4 |
| crs | 5 | 200 | 0 | 184.4 | 24.8 | 45.4 | 60.9 |
| crs | 10 | 200 | 0 | 176.7 | 55.1 | 97.1 | 115.3 |
| crs | 20 | 200 | 0 | 179.8 | 92.9 | 208.1 | 277.6 |
| chat | 1 | 200 | 0 | 3.7 | 261.4 | 475.8 | 617.8 |
| chat | 2 | 200 | 0 | 3.4 | 567.9 | 1,044.0 | 1,179.4 |
| chat | 5 | 200 | 0 | 3.7 | 1,278.5 | 2,294.6 | 2,613.0 |
| chat | 10 | 200 | 0 | 3.9 | 2,514.8 | 4,460.9 | 5,333.0 |
| chat | 20 | 200 | **4** (http_500 2, BrokenPipeError 1, ConnectionResetError 1) | 3.9 | 5,021.6 | 8,202.1 | 10,410.2 |
| mixed | 1 | 200 | 0 | 6.7 | 175.8 | 362.7 | 564.2 |
| mixed | 2 | 200 | 0 | 6.8 | 101.0 | 746.6 | 1,096.7 |
| mixed | 5 | 200 | 0 | 9.6 | 21.2 | 1,663.7 | 2,508.8 |
| mixed | 10 | 200 | 0 | 7.1 | 1,650.7 | 3,480.1 | 5,268.8 |
| mixed | 20 | 200 | 0 | 7.7 | 736.1 | 7,247.7 | 9,423.5 |

### Each route inside the mixed workload

The mixed row's p50 blends a 2 ms route with a 250 ms one, so it jumps around
and means little. What each route experienced inside the mix (p50 / p95 ms,
n = how many of the 200 requests were that route):

| Route | C=1 | C=5 | C=10 | C=20 |
|---|---|---|---|---|
| documents | 2.3 / 5.4 (n=69) | 11.3 / 29.2 (n=94) | 23.5 / 154.5 (n=66) | 135.5 / 454.0 (n=83) |
| answer | 253.0 / 458.8 (n=77) | 1,259.5 / 2,284.3 (n=55) | 2,297.6 / 4,000.1 (n=74) | 4,468.2 / 8,180.5 (n=68) |
| crs | 3.3 / 6.8 (n=21) | 16.6 / 44.0 (n=30) | 51.4 / 112.4 (n=21) | 195.1 / 458.0 (n=19) |
| chat | 252.3 / 492.1 (n=33) | 1,320.9 / 2,291.4 (n=21) | 2,503.2 / 3,716.4 (n=39) | 5,266.7 / 8,210.0 (n=30) |

### Repeatability - run 1 against run 2

Same command, same seed, fresh corpus each time.

| Workload | C | p50 run 1 / 2 | p95 run 1 / 2 | req/s run 1 / 2 | errors run 1 / 2 |
|---|---:|---|---|---|---|
| documents | 1 | 2.5 / 2.3 | 3.5 / 3.6 | 385.9 / 406.7 | 0 / 0 |
| documents | 20 | 91.7 / 100.3 | 273.1 / 220.6 | 168.2 / 181.3 | 0 / 0 |
| answer | 1 | 262.7 / 252.3 | 459.6 / 438.0 | 3.8 / 3.9 | 0 / 0 |
| answer | 20 | 4,609.2 / 4,407.4 | 8,419.0 / 8,408.0 | 4.1 / 4.2 | 0 / 0 |
| chat | 1 | 274.5 / 261.4 | 515.3 / 475.8 | 3.5 / 3.7 | 0 / 0 |
| chat | 20 | 5,437.3 / 5,021.6 | 8,357.3 / 8,202.1 | 3.8 / 3.9 | **14 / 4** |

Run 1 also had 2 errors in `mixed` at concurrency 20 (1 `http_500`, 1
`BrokenPipeError`), all from the same cause as below. Latency and throughput
agree within about 10% between runs; the error count does not repeat
exactly, which is what a race looks like.

## Finding: two questions at once in the same chat conversation can fail with a 500

**Measured.** Chat workload, concurrency 20: 2 x HTTP 500 in run 2, 7 x HTTP
500 in run 1, plus 1 in run 1's mixed workload. No other workload and no
lower level produced an error. The server log holds one traceback per 500,
all the same exception (run 2: 2 tracebacks; run 1: 8):

```
  File "backend/app/main.py", line 2615, in ask
    return chat_mod.ask(
  File "backend/app/chat.py", line 722, in ask          (run 1: 4 here, 4 at line 870)
    user_message = _insert_message(
  File "backend/app/chat.py", line 539, in _insert_message
    conn.execute(
  File "backend/app/db.py", line 844, in execute
    return super().execute(sql, parameters)
sqlite3.IntegrityError: UNIQUE constraint failed: messages.conversation_id, messages.ordinal
```

**Not "database is locked".** Zero `database is locked` and zero
`schema has changed` in either run's server log.

**When it happens.** Only when two requests for the SAME conversation are
being answered at the same time. With 20 simulated engineers spread over 20
conversations, request *i* and request *i+20* land in the same conversation
and can overlap; at 10 and below they practically never did. In real use this
is one engineer sending a second question in the same chat before the first
has come back, or the same conversation open in two browser tabs.

**Likely cause - read from the code, not proven by a separate test.**
`_insert_message` (`backend/app/chat.py` lines 525-560) reads
`SELECT COALESCE(MAX(ordinal), 0) + 1` and then INSERTs that ordinal, inside
`with conn:`. Python's `sqlite3` in its default mode does not open a
transaction for a SELECT, only before the INSERT, so two threads (each with
its own connection) can both read the same MAX and both try to insert it. The
second one waits for the first to commit (busy timeout) and then hits the
unique index.

**What the user sees and what is left behind.** The failed request gets a 500.
At line 722 the user's question was not stored. At line 870 (4 of run 1's 8)
the question WAS stored and the answer insert failed - the conversation is
left with a question that has no answer turn, and the retrieval work for it
was thrown away.

**The broken-pipe / connection-reset errors are a side effect, not a second
problem.** They appear only in the levels that had 500s and in roughly the
same number (run 2: 2 x 500, 2 connection errors; run 1 chat: 7 and 7). After
an unhandled exception the server closes that keep-alive connection, and the
load generator's next request on it fails before reaching the server. A
browser would reconnect and retry. This one-to-one pairing is an inference
from the counts, not traced packet by packet.

**Not fixed here** - this change only measures. Application code is
untouched.

## What the numbers show

- **The search is CPU-bound and does not get faster with more people -
  answers queue.** `answer` and `chat` throughput stayed flat at about
  **4 answers per second** from 1 to 20 concurrent users on 2 vCPU.
  Latency grows in step with the queue: p50 ~250 ms alone, ~1.2 s at 5,
  ~2.3 s at 10, ~4.4 s at 20 - roughly (people waiting) / (4 per second).
  The work is the embedder and the cross-encoder reranker running on the CPU;
  more simultaneous requests just share the same cores.
- **It degrades smoothly.** No timeouts, no collapse in throughput and no
  memory errors at 20 concurrent users. Everything except the same-conversation
  race above completed.
- **Plain reads stay fast on their own, and slow down beside answers.**
  The document list and CRS preview answer in 2-3 ms alone and ~100 ms at 20
  concurrent users. In the mixed workload, the document list's p95 rises to
  454 ms at 20 because it shares the CPU (and the Python interpreter lock)
  with answers being reranked.
- **SQLite was not the bottleneck here.** WAL lets many readers run beside
  one writer. The chat workload writes two rows per question and was only
  slightly slower than `answer` (about 4% at 1 user, 14% at 20); no
  `database is locked` appeared. The writes in this test are small and short.

## What the numbers do NOT show

- **Not the owner's PC.** 2 vCPU here against 12 logical cores on the owner's
  laptop (`docs/benchmarks.md`). Answer throughput should rise with cores,
  but by how much is not measured - the laptop's cores are mixed performance
  and efficiency cores, and the reranker's own thread count is capped. Run the
  script there.
- **Not the client's library.** 23 small documents, 183 chunks. A one-off
  smaller run (4 documents, 28 chunks) answered in ~107 ms alone against
  ~250 ms here, so answer time grows with corpus size. The owner's library is
  far larger.
- **Not Tier 2.** Only the verbatim `extract` tier was tested. A generated
  answer from the local model takes about 50 s (the note on
  `auth_token_seconds` in `backend/app/config.py`) and
  would dominate everything above; several people asking for generated
  answers at once is not measured.
- **Not heavy writes.** No uploads, ingestion, OCR or review runs happened
  during the timed phases. SQLite allows one writer at a time; a long write
  transaction (ingesting a large document, a review run writing hundreds of
  findings) running beside these reads is where `database is locked` would
  be most likely, and this test does not create that.
- **Not login.** Auth was disabled (`AUTH_MODE=disabled`), as in the test
  suite. The owner runs `demo_required`; token checking adds a little per
  request and is not measured.
- **Worst case, not typical.** Each simulated engineer fires the next request
  instantly. Real engineers read the answer first, so 20 real people load the
  system far less than 20 simulated ones.
- **Client and server shared the 2 vCPU.** The load generator's own CPU use
  is included in the server's contention.

## Tests

`backend/tests/test_load_test_script.py` holds the script's pure parts:
percentile maths, error classification (including SQLite's messages inside a
500), aggregation (latency over successes only), argument parsing, the mixed
workload's shares and the server-log scan. 23 tests, under a second, no
corpus. Each was proven by mutating the script and watching a test fail
(20 mutations, all caught).
