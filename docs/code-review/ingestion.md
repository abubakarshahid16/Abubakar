# Ingestion pipeline — review findings

Static review. **I ran nothing**: no pytest, no worker, no ingest. Every claim
below is read off the code quoted with it, on the working tree at
`$HOME/mnt/Rag_chatbot` (read-only). Where I could not settle something without
running it, it is in **Confidence / not reviewed** at the end rather than stated
as fact.

Boundary of the sweep: `backend/app/{upload,ingest,chunker,ocr,watcher,watch_api,db,metrics,states}.py`
in full; `extract.py` and `keyword.py` only where they write `documents.status`
or a count; `backend/tests/*` by name plus the eight test files bearing on the
guarantees below, read in full or in the relevant part; `scripts/` only by grep
for a WAL-unsafe copy. `main.py` only at the upload route and the `/api/metrics`
scope hand-off. The frontend was not reviewed.

---

## 1. CRITICAL — every exception becomes a permanent `failed`, and nothing in the system can resume it

`backend/app/ingest.py:418`

```python
        except Exception as exc:  # noqa: BLE001 - the record must capture anything
            self.last_error = errors.record_failure(
                exc, code=errors.INTERNAL, document_id=doc_id, stage="process"
            )
            ...
                    (states.FAILED, errors.INTERNAL, safe_message, doc_id),
```

**What is wrong.** One broad handler turns *any* raise — a transient
`database is locked`, one unrenderable page image, an ONNX allocation failure,
an `IllegalTransition` that is a programming error — into the terminal state
`failed`, and no code path anywhere in the repository ever moves a document out
of `failed`.

**The failure.** `_next_document` excludes terminal states by construction:

```python
        settled = tuple(states.TERMINAL_STATES | {states.PARTIALLY_SEARCHABLE})
```
`ingest.py:191` — and `TERMINAL_STATES = frozenset({READY, NO_SEARCHABLE_CONTENT, FAILED})`
(`states.py:41`). So the worker never selects a failed document again. There is
no reprocess route (`grep -n "reprocess\|retry\|requeue" backend/app/main.py backend/app/admin.py`
returns nothing of the kind), and the operator's obvious remedy — re-upload the
file — cannot work, because `upload.ingest` deduplicates on sha256 and hands
back the same dead row:

```python
    existing = find_by_hash(sha256)
    if existing is not None:
        temp_path.unlink(missing_ok=True)
        return existing, None, existing["id"]
```
`upload.py:114`. `main.py:242` then skips granting and returns
`duplicate_of`, so the user sees "already in the corpus", pointing at a
document that answers nothing.

Concretely: a 900-page specification is `partially_searchable` and answering
questions; SQLite blocks a writer past its 30 s `busy_timeout` during
`embed_pending`; the document is stamped `failed` with `error_code = internal`;
it stops being answerable; it is never picked up again; re-uploading it returns
"duplicate". `states.py:68` declares `FAILED: frozenset({QUEUED, EXTRACTING,
CHUNKING, FAILED})` and `docs/status-honesty-audit.md` says of `failed`: *"That
the document is unusable forever — it is resumable"*. **It is not resumable by
anything that exists.** That sentence, and standing rule 2, are claims about
code that is not there. No test covers it: the resume test is parametrised over
`[QUEUED, EXTRACTING, CHUNKING, INDEXING_KEYWORD]` only
(`backend/tests/test_worker_health.py:62`).

**Smallest fix.** Add `FAILED` to the second `_next_document` query with a
bounded retry count (`jobs.retries`, a column that already exists and is never
written), and stop treating every exception as terminal: classify
`sqlite3.OperationalError` / `IllegalTransition` as retryable and leave the
document in its current non-terminal state.

---

## 2. HIGH — `jobs.state = 'running'` is still written at upload, and the dashboard still counts it

`backend/app/upload.py:136`, `backend/app/metrics.py:159`

```python
            """INSERT INTO jobs
               (id, document_id, stage, state, started_at, updated_at)
               VALUES (?, ?, 'extract', 'running', ?, ?)""",
```

```python
        "running": by_state.get("running", 0),
```

**What is wrong.** This is audit entry #1 with a worker bolted on beside it, not
removed: the row asserts `running` at the moment of upload, before the worker
has selected the document, and `/api/metrics` publishes the count of those rows
as `jobs.running`.

**The failure.** Drop eight PDFs into the folder. Eight `jobs` rows say
`running`. The worker processes **one document at a time**
(`IngestionWorker` docstring, `ingest.py:76`), so `jobs.running: 8` is a number
the system cannot produce truthfully. The document rows are honest
(`status = 'queued'`); the job rows are not, and the dashboard reads the job
rows. Second arm, same field: `extract.py:216` writes

```python
            "UPDATE jobs SET stage = 'chunk', state = 'done', pages_done = ?, updated_at = ? WHERE id = ?",
```

so `state = 'done'` means *extraction* finished — chunking, indexing and
embedding are all still to come — while `jobs.by_state` on the dashboard reads
it as a finished job.

**Smallest fix.** Insert the job as `'queued'`; have the worker set `'running'`
when it takes the document and `'done'` only where `_finish_if_embedded` already
does. `metrics.jobs()["running"]` should then be capped by / derived from the
worker's `current_document`, which is the thing it names.

---

## 3. HIGH — `/api/watch/status` resolves a scope and uses it for one field only

`backend/app/watch_api.py:236`, `:304`, `:215`

```python
def watch_status(request: Request,
                 scope: access.AccessScope = Depends(access.current_scope)):
```
```python
        "folder_name": folder_name(folder) if may_see_host_paths else None,
        ...
        "recent": recent_events(),
```
```python
        for r in connect().execute(
            "SELECT filename, outcome, observed_at, detail FROM watch_events"
            " ORDER BY id DESC LIMIT ?",
            (limit,),
        )
```

**What is wrong.** `recent_events()` takes no scope and applies none: every
caller, including one granted nothing, receives the filename of every document
dropped into the folder, plus `detail` strings that carry the grant list
(`"; granted to Civil-Engineering, Mechanical"`, `watcher.py:590`) and upload
refusal reasons.

**The failure.** This is audit entry 15's exact shape — a scope resolved via
`Depends` and discarded — and the codebase already has the test that would catch
it, pointed at a different route:
`backend/tests/test_access_routes.py:226` asserts
`"someone-elses.pdf" not in body` for `/api/metrics`. Run the same assertion
against `/api/watch/status` with `_grant("nobody", [])` and it fails: an
engineer granted nothing learns that `MOD-4 Firewater Deluge P&ID rev C.pdf`
exists, when it arrived, whether it was refused, and which disciplines it went
to. `backend/tests/test_watch_folder.py:493` positively blesses this — *"The
engineer still gets a usable answer: enabled, interval, recent events"* — so the
disclosure is asserted, not merely unguarded.

**Smallest fix.** Pass the scope into `recent_events()` and filter
`watch_events` by `document_id IN (allowed)`; for rows with no document
(`failed`, unhashable) return the outcome and `detail` with the filename
withheld from non-admins, or restrict `recent` to administrators.

---

## 4. HIGH — three of the dashboard's ingestion aggregates ignore the caller's grants

`backend/app/metrics.py:378`, `:408`

```python
    row = conn.execute(
        """SELECT COALESCE(SUM(needs_ocr_pages), 0) AS flagged,
                  COALESCE(SUM(recognised_pages), 0) AS recognised
           FROM documents"""
    ).fetchone()
```
```python
    equations = conn.execute(
        "SELECT COALESCE(SUM(equation_pages), 0) FROM documents"
    ).fetchone()[0]
```

**What is wrong.** Every other query in `warnings()` appends `id_where` from
`_where(allowed, "id")`; these three have no `WHERE` at all, and the function's
own docstring says *"Both are scoped"* — true of the two document loops above
them, false of what follows, and nothing says so.

**The failure.** A user granted four documents (or zero) opens the Dashboard and
reads *"412 scanned page(s) have not been read yet"* and *"96 page(s) are
equation-heavy"* — counts over the whole corpus, inside a payload whose
`corpus_wide: false` tells the screen these are their numbers. Standing rule 7
and the review's *"a count must state its boundary"* both fail here, and the
`test_metrics_does_not_name_another_users_unsearchable_document` guard cannot
see it because these warnings interpolate no filename.

**Smallest fix.** `+ id_where` with `id_args` on both queries, as the two loops
above already do.

---

## 5. HIGH — the OCR backlog warning is computed from a subtraction that can never reach zero

`backend/app/metrics.py:384`

```python
    flagged, recognised = row["flagged"], row["recognised"]
    awaiting = max(flagged - recognised, 0)
    if awaiting:
        ...
                f"{awaiting} scanned page(s) have not been read yet. "
                f"Recognition has not run on them, so they are not searchable "
```

**What is wrong.** `awaiting` is derived from two counts of different
populations. `needs_ocr_pages` counts pages flagged for recognition;
`recognised_pages` counts only pages recognition produced *text* for —

```python
        # Only pages that actually produced text count as recognised. A blank
        # page is not a recognised page ...
        n = conn.execute(
            "SELECT COUNT(*) c FROM page_ocr WHERE document_id = ? AND char_count > 0",
```
`ocr.py:244`. A page that was read and found blank is in neither term.

**The failure.** The audit itself measured *"5 of 12 flagged pages return zero
boxes at both 150 and 300 dpi. Those pages are BLANK"*. On such a document
recognition runs to completion, `ocr.pending_pages()` returns `[]`, the document
reaches its terminal state — and the Dashboard states forever: *"5 scanned
page(s) have not been read yet. Recognition has not run on them."* Recognition
ran. This is audit entry 8's family exactly: correct arithmetic over the wrong
population. Two definitions of "awaiting recognition" exist in the tree and the
dashboard uses the one that is not the truth; the other is right beside it:

```python
           WHERE p.document_id = ? AND p.needs_ocr = 1 AND o.page_no IS NULL
```
`ocr.py:215`.

**Smallest fix.** Derive `awaiting` from that same `pages LEFT JOIN page_ocr`
predicate, scoped, and report blank-but-read pages as their own figure.

---

## 6. HIGH — a page whose recognition crashed is recorded as "recognition has not run", retried forever, and its error is discarded

`backend/app/ocr.py:229`, `backend/app/chunker.py:1465`, `:1527`

```python
    for (pno, text, mean_c, min_c, boxes, secs, viol, sample, err) in rows:
        if err is not None:
            continue
```
```python
    ocr_results = {
        r["page_no"]: {"box_count": r["box_count"], "char_count": r["char_count"],
                       "error": None}
```
```python
            elif rec["error"]:
                rule = "ocr_failed"
                reason = f"recognition failed on this page: {rec['error']}"
```

**What is wrong.** `recognise_batch` captures the per-page exception
(`f"{type(exc).__name__}: {exc}"`, `ocr.py:185`), `_commit_batch` throws it
away, `page_ocr` has no column for it (`db.py:69-94`), and `ocr_results` sets
`"error": None` unconditionally — so the `ocr_failed` branch is **dead code**
and the four-rule comment above it (*"so the exclusion ledger can tell 'not run
yet' from 'ran and the page is blank' from 'ran and failed'"*, `chunker.py:1462`)
is false of the code beside it.

**The failure.** A page whose render or recognition raises writes no `page_ocr`
row, so (a) `pending_pages` returns it on every subsequent round, forever —
recognition retries it every pass for the life of the document; (b) the
exclusion ledger states `ocr_not_run` — *"recognition has not run"* — about a
page recognition ran on and crashed on; (c) the reason is not stored anywhere
and `_commit_batch` does not log it either, so the one fact an operator needs is
lost at the point it is produced. Then, per finding 10, the churn guard
eventually fails the document with *"N scanned page(s) still unread and no round
is making progress"*, which names the symptom and never the render error.

**Smallest fix.** Add `error TEXT` to `page_ocr` (additive migration, as
`_migrate` already does elsewhere) and insert the failed page with
`char_count = 0` and the error text, so it is recorded once, excluded with the
true reason, and never retried.

---

## 7. HIGH — the state machine is enforced on one of nine writers

`backend/app/ingest.py:549` is the only call site of `check_transition` in the
application:

```
backend/app/ingest.py:549:        states.check_transition(cur, nxt)
```

Every other writer of `documents.status` is a raw `UPDATE`:

```
chunker.py:1357   -> indexing_keyword   (short-circuit)
chunker.py:1604   -> indexing_keyword
extract.py:133    -> extracting         (once per batch)
extract.py:159    -> failed
ingest.py:296     -> extracting         (unknown status; deliberately unchecked)
ingest.py:425     -> failed             (from ANY state, in the broad handler)
ingest.py:592     -> no_searchable_content
ingest.py:614     -> ready
keyword.py:150    -> partially_searchable
```

**What is wrong.** `docs/status-honesty-audit.md` states: *"Legal transitions
are declared in `app/states.py` and enforced by `check_transition`."* They are
declared there and enforced for exactly one edge family — the ones `_set_state`
happens to write. This is a comment recording a false reason, the class the
review calls a defect rather than a nitpick.

**The failure.** It is why audit entry 7 could only be found by running a clean
clone: the illegal `partially_searchable -> chunking` edge was written through
`_set_state` (so it *did* raise) and swallowed by finding 1's handler, while
every other stage could have written an illegal status silently and nothing
would have raised at all. The only test of the machine calls the pure function:

```python
    states.check_transition(states.CHUNKING, states.INDEXING_KEYWORD)
```
`backend/tests/test_quality_gate.py:100`. Delete `check_transition`'s call in
`_set_state` and the suite stays green.

**Smallest fix.** One `set_status(conn, doc_id, nxt, expect=...)` helper that
checks the transition and does the compare-and-set, used by all nine sites; the
unknown-status path passes an explicit `force=True` with its existing comment.

---

## 8. HIGH — the two-scan stability rule cannot see a paused copy, and the truncated document that results is reported `ready`

`backend/app/watcher.py:458`

```python
            fingerprint = (stat.st_size, stat.st_mtime_ns)
            previous = self._seen.get(path.name)
            self._seen[path.name] = fingerprint
            ...
            if previous != fingerprint:
                # Either new to us, or still changing. Both mean "not yet".
```

**What is wrong.** Stability is derived from size and mtime — adjacent to
"the copy has finished", not the thing itself. The module docstring claims the
rule *"buys the difference between a partial document and no document"*
(`watcher.py:17-23`), a guarantee two metadata samples cannot give.

**The failure.** `settings.watch_interval_seconds` defaults to a five-minute
scan. A 40 MB PDF copied over a VPN that stalls, or a copy whose writer flushes
in bursts, presents identical `(st_size, st_mtime_ns)` to two consecutive scans.
The file is then hashed over its partial bytes, `stream_to_temp` accepts it
because it only ever checks the leading `%PDF-`

```python
                if not block.startswith(PDF_MAGIC):
```
`upload.py:72` — no trailer, no `%%EOF`, no page-count sanity check — and
PyMuPDF opens most truncated PDFs with a reduced page count. Extraction,
chunking, indexing and embedding all succeed over the truncated content and the
document reaches **`ready`**: searchable, quotable, and missing its second half,
with nothing in any row saying so. When the copy completes, size and mtime
change, `_handled` no longer matches, the file is ingested again under a new
sha256, and the corpus now holds **two** documents — the truncated one still
`ready`, still answering, and never superseded.

**Smallest fix.** Require N consecutive identical fingerprints *and* an age
floor (`now - mtime > interval`), and validate the PDF trailer before accepting:
reject a file whose last 1 KB has no `%%EOF`, recording a `failed` watch event.

---

## 9. HIGH — a corrected file dropped under the same name can be skipped forever, with no event recorded

`backend/app/watcher.py:462`, docstring `:273`

```python
            if self._handled.get(path.name) == fingerprint:
                result["already_handled"].append(path.name)
                continue
```
> *"Because the recorded size/mtime is part of it, REPLACING the file with a
> corrected version makes it eligible again, which is what an operator would
> expect after fixing a bad drop."*

**What is wrong.** The claim is derived from `(size, mtime)`, not from content.
Any replacement that preserves both — `cp -p`, `robocopy /COPY:T`, `rsync
--times`, a restore from backup, an edit that happens to keep the byte length —
matches the recorded fingerprint and is skipped.

**The failure.** The operator is told rev B was corrupt, fixes it, drops rev C
over it with timestamps preserved, and the watcher writes **no `watch_events`
row at all** — it is counted under `already_handled`, which is not one of the
three recorded outcomes. The document that the folder was built to make
non-silent is silently absent, and the panel shows the original `failed` event
as the last word. `_duplicate_hashes` has the same shape one level down: a
content hash already announced is returned as `DUPLICATE` with **no event**
(`watcher.py:533-537`), so the second and later appearances of the same content
under new names leave no record.

**Smallest fix.** Key `_handled` on the content hash for files small enough to
re-hash cheaply, or add a third component to the fingerprint that a
timestamp-preserving copy changes (`st_ino`/`st_ctime_ns`); at minimum, record
an event when a `_handled` file's *name* reappears with a new inode.

---

## 10. MEDIUM — a blank OCR round is charged as churn, so an answerable document can be failed while recognition is progressing

`backend/app/ingest.py:387`, `backend/app/ocr.py:318`

```python
                        if result["ocr"].get("pages_with_text"):
                            self._set_state(doc_id, states.CHUNKING)
                            continue
                        if result["ocr"].get("pages_remaining"):
                            # This round found only blank pages. ...
                            continue
```
```python
    stats = conn.execute(
        """SELECT COUNT(*) n,
                  COALESCE(SUM(CASE WHEN char_count > 0 THEN 1 ELSE 0 END),0) with_text,
                  ...
           FROM page_ocr WHERE document_id = ?""",
```

**What is wrong.** The call site reads `pages_with_text` as "this round produced
text". It is computed over the document's **entire** `page_ocr` table, with no
round or batch predicate — while `pages_recognised` in the same dict *is*
per-round (`len(payload)`). Two counts in one return value with two different
boundaries, and the caller branches on the wrong one.

**The failure.** After any round that produces text, `pages_with_text` is
permanently non-zero, so the second branch at `:390` is dead and every
subsequent blank round takes the `CHUNKING` path: a whole-document re-chunk plus
a full keyword re-index for pages that contributed nothing. Worse, the churn
signature (`ingest.py:275-282`) contains `recognised_pages`, which
`_commit_batch` only increments for pages with `char_count > 0`, so a blank
round moves no field in it. Each blank cycle re-visits three already-seen
signatures, `churn_budget = len(states.ALL_STATES) + 2 = 10`, so roughly the
sixth consecutive blank round raises

```python
                        raise RuntimeError(_stuck_reason(conn, doc_id, row, status))
```
→ finding 1's handler → `failed`, on a document that was answerable and whose
recognition was consuming pages every round, with the recorded reason
*"recognition stalled ... no round is making progress"*, which is false.
`backend/tests/test_settle_guard.py:45` cannot see this: its stub writes
`recognised_pages = calls["n"]` on every round, i.e. the fixture supplies
progress in exactly the field the guard watches and can never produce a blank
round.

**Smallest fix.** Return a per-round `pages_with_text_this_round` from
`recognise_document` and branch on it; add `COUNT(*) FROM page_ocr` (all rows,
blank included) to the churn signature so consumed pages count as progress.

---

## 11. MEDIUM — the "we dropped a whole clause" alert cannot fire for the gate that does most of the dropping

`backend/app/chunker.py:1556`

```python
    for ordinal, c in enumerate(chunks):
        q = quality[id(c)]
        if c.kind in RETRIEVABLE_KINDS and not q["ok"]:
            exclusion_rows.append(
                (doc_id, "chunk", c.page_start, c.page_end,
                 chunk_id(...),
                 "content_quality_gate", ",".join(q["reasons"]),
                 c.text[:2000], len(c.text.strip()), now, 0)
            )
```

**What is wrong.** The last column is `clause_headings`, and on the chunk path
it is the literal `0`. The page path computes it
(`dropped_real_content(ptext, rule)`, `:1510`, `:1554`), which is what
`db.py:154` describes as *"a regression detector: the classifier gate should
keep this at zero"*.

**The failure.** The audit's own measurement says the 21 uncovered pages *"all
carried a chunk-scope `content_quality_gate` row"* — the quality gate is where
content actually disappears. A chunk that is the whole of Clause 8, rejected by
the gate, is written with `clause_headings = 0`, so `metrics.exclusions()`
sorts it to the bottom (`ORDER BY clause_heading_pages DESC`, `metrics.py:129`)
and the alert reads zero. A document can lose an entire clause with the alert
built to catch that saying nothing. The only test sums the page scope:
`"SELECT COALESCE(SUM(clause_headings), 0) FROM exclusions WHERE scope = 'page'"`
(`backend/tests/test_correctness_fixes.py:167`), so the hardcoded zero is
invisible to the suite.

**Smallest fix.** Call `dropped_real_content(c.text, "content_quality_gate")`
for the chunk rows too.

---

## 12. MEDIUM — a page whose only chunk was excluded is treated as a page that contributed one

`backend/app/chunker.py:1450`

```python
    pages_with_chunks: set[int] = set()
    for c in chunks:
        for pno in range(c.page_start, c.page_end + 1):
            pages_with_chunks.add(pno)
```
…then `if pno in pages_with_chunks: continue` (`:1514`) skips the page-scope
exclusion row.

**What is wrong.** `chunks` is every chunk, retrievable or not, and membership
is by page **span**. So a page is credited with contributing to search when the
only chunk covering it was excluded, and a page is credited when a neighbouring
chunk merely spans across it. This is audit entry 8's mechanism — a page charged
to a chunk range rather than to its own content — reappearing in the exclusion
ledger.

**The failure.** `/api/documents/{id}/excluded` cannot answer *"was page 22
dropped?"*: page 22 has no page-scope row, and the chunk-scope row that
"accounts" for it names a range (`page_start..page_end`) that may cover three
pages of which only one was really lost. The promise the ledger exists to keep
— *"Nothing is ever dropped silently"* (`:1438`) — holds only if a reader
expands ranges and re-derives coverage themselves.

**Smallest fix.** Build `pages_with_chunks` from `retrievable` rather than
`chunks`, and record a page-scope row (`rule = "all_chunks_on_this_page_excluded"`)
for a page with no retrievable chunk of its own.

---

## 13. MEDIUM — `ready` can be stamped on a document with an unembedded retrievable chunk

`backend/app/ingest.py:563` vs `:447` and `:604`

```python
        actual = conn.execute(
            """SELECT COUNT(*) FROM chunk_vectors v
               JOIN chunks c ON c.id = v.chunk_id
               WHERE v.document_id = ?""",
```
```python
               WHERE c.document_id = ? AND c.retrievable = 1 AND v.chunk_id IS NULL
```
```python
        if row["embedded_count"] >= row["chunk_count"]:
```

**What is wrong.** `embedded_count` counts vectors joined to **any** chunk;
`chunk_count` is the **retrievable** count (`chunker.py:1604`,
`(len(retrievable), len(chunks), ...)`); `embed_pending` correctly embeds only
retrievable chunks. Three populations, two of them compared with `>=`.

**The failure.** A re-chunk that leaves a chunk id unchanged but flips
`retrievable` to 0 (same text, same ordinal, a changed quality threshold) keeps
its vector — the orphan sweep only deletes vectors whose chunk id is *gone*
(`chunker.py:1584`) — so `embedded_count` can equal or exceed `chunk_count`
while one retrievable chunk still has no vector. The document is stamped
`ready` and `indexed_at`, and hybrid search silently never surfaces that chunk.
The comment at `:606` — *"so the terminal stamp can never be applied on the
strength of a count that changed underneath it"* — is true about concurrency and
says nothing about the population mismatch.

**Smallest fix.** Add `AND c.retrievable = 1` to `_recount_embedded`'s join and
to the recount inside the `ready` transaction, so both sides of the comparison
count the same thing.

---

## 14. MEDIUM — `indexed_at` is never set on `failed`, though it is documented as the field to trust for "did this finish"

`backend/app/ingest.py:425`, `backend/app/extract.py:159`

```python
                    "UPDATE documents SET status = ?, error_code = ?, error_message = ?"
                    " WHERE id = ?",
```

**What is wrong.** `docs/status-honesty-audit.md`: *"`indexed_at` is set **only**
on reaching a terminal state, and is the field to trust for 'did this finish',
not `status` alone."* `failed` is terminal (`states.py:41`) and neither failure
writer touches `indexed_at`; only `ready` and `no_searchable_content` stamp it.

**The failure.** A consumer following the documented rule — and `backlog()`
partly does, `ingest.py:124` — reads a failed document as unfinished forever.
The field cannot distinguish "still working" from "finished badly", which is
precisely the distinction it is documented to provide.

**Smallest fix.** Stamp `indexed_at` on the failure path too, or correct the
document to say `indexed_at` means "finished *successfully*" and add
`failed_at`.

---

## 15. MEDIUM — a fully scanned document is labelled answerable, with zero indexed chunks, for the whole recognition run

`backend/app/keyword.py:128`, `:149`

```python
    rows = conn.execute(
        """SELECT id, text, section, filename FROM chunks
           WHERE document_id = ? AND retrievable = 1 ORDER BY ordinal""", ...)
    ...
                conn.execute(
                    "UPDATE documents SET status = ? WHERE id = ? AND status = ?",
                    (advance_to, document_id, expect_status),
                )
```

**What is wrong.** The advance to `partially_searchable` is unconditional on
`len(rows)`. `PARTIALLY_SEARCHABLE` is in `ANSWERABLE_STATES` and the audit
defines it as *"Keyword search works; vectors still arriving"*.

**The failure.** A 900-page scanned PDF produces no chunks, is indexed with
`indexed: 0`, and is marked answerable — `states.label()` renders *"partially
searchable - 0/0 embedded"* — for the hours recognition takes. Nothing is
searchable in it. The state that exists for this case,
`INDEXING_KEYWORD -> NO_SEARCHABLE_CONTENT`, is declared legal at
`states.py:52` and **no code ever performs it**; the only writer of
`no_searchable_content` is `_finish_if_embedded`, reachable only from
`partially_searchable`.

**Smallest fix.** In the `indexing_keyword` branch, advance to
`partially_searchable` only when `indexed > 0`; where it is 0 and recognition is
pending, stay in a non-answerable state (a `recognising` status, or keep
`indexing_keyword`) so nothing is called answerable before it is.

---

## 16. MEDIUM — `chunks_excluded` subtracts a stored count from a row count and clamps the disagreement to zero

`backend/app/metrics.py:112`

```python
        "chunks_total": chunks_rows,
        "chunks_retrievable": docs["chunks_retrievable"],
        "chunks_excluded": max(0, chunks_rows - docs["chunks_retrievable"]),
```
where `chunks_rows = COUNT(*) FROM chunks` and
`chunks_retrievable = COALESCE(SUM(chunk_count), 0) FROM documents`
(`:83`, `:91`).

**What is wrong.** Two counts of the same population from two different sources
— live rows and a denormalised column — subtracted, with `max(0, …)`
guaranteeing that a disagreement in one direction is displayed as *"0 excluded"*
rather than reported. The `chunks_total` alias computed at `:84` from
`SUM(chunk_count_total)` is discarded, so the response's `chunks_total` and
`chunks_retrievable` do not even come from the same source.

**The failure.** Any drift between `documents.chunk_count` and the `chunks`
table — a partially applied migration, a hand-run script, a re-chunk
interrupted between statements — surfaces as a confident `chunks_excluded: 0`
on the dashboard, i.e. "nothing was dropped", which is the one claim the
exclusion ledger exists to make honestly.

**Smallest fix.** Count both from `chunks`
(`SUM(retrievable)` and `COUNT(*)`), drop the clamp, and if the stored column is
kept as a cross-check, report the disagreement instead of hiding it.

---

## 17. MEDIUM — a document that cannot finish is re-selected in a tight loop with no wait

`backend/app/ingest.py:212`

```python
        while not self._stop.is_set():
            self.last_beat = time.time()
            try:
                doc_id = self._next_document()
                if doc_id is None:
                    self.current_document = None
                    self._stop.wait(self.poll_seconds)
                    continue
                self.current_document = doc_id
                ...
                self.process(doc_id)
```
and `process` returning on `after == states.PARTIALLY_SEARCHABLE` (`:409`).

**What is wrong.** The poll wait is on the *empty-queue* path only. A document
that `process()` cannot advance — `embed_pending` finds no rows while
`embedded_count < chunk_count` (finding 13's mismatch, or a stale-high
`chunk_count`) — returns immediately and is selected again with no sleep.

**The failure.** The worker spins at 100% of a core on a CPU-bound machine that
also has to run the embedder and Ollama, indefinitely. The churn budget cannot
stop it: `seen`/`churn` are local to each `process()` call and reset on every
pass. `stalled` does eventually go true after `NO_PROGRESS_SECONDS`, so the
condition is *reported* — while the machine burns.

**Smallest fix.** `self._stop.wait(self.poll_seconds)` after any `process()`
that did not change the document's status, and persist the churn count on the
`jobs` row so a non-settling document is failed rather than re-entered forever.

---

## 18. MEDIUM — the audit script tells the operator to copy a WAL database and calls the copy faithful

`scripts/section_audit.py:1035`

```python
            "Copy the database to local disk and audit the copy -- this script never\n"
            "writes, so a copy is a faithful subject:\n"
            f"    cp '{db}' /tmp/rag_intelligence.sqlite\n"
```

**What is wrong.** The database is opened in WAL mode
(`db.py:12`, `db.py:564`), so committed data lives in `-wal` until a checkpoint.
`cp` of the `.sqlite` alone is a snapshot as of the last checkpoint, not as of
now, and SQLite opens it without complaint.

**The failure.** The operator hits the documented `disk I/O error` on a network
mount, follows this instruction, and audits a database that is silently missing
every commit since the last checkpoint — most likely the very document just
ingested, which is why they are running the audit. "A faithful subject" is a
guarantee the copy does not provide. (`docs/plan-conformance-audit.md:798`
already records "No backup step anywhere"; this is the one place the tree
actively recommends an unsafe one.)

**Smallest fix.** `cp` the `.sqlite`, `-wal` and `-shm` together, or use
`sqlite3 "$db" ".backup /tmp/copy.sqlite"`, or open the original with
`?immutable=1` only after a `wal_checkpoint(TRUNCATE)`.

---

## 19. LOW — `reachable` says what the last scan saw, not whether anything is still scanning

`backend/app/watch_api.py:290`, `backend/app/watcher.py:315`

```python
        "reachable": watcher_mod.last_reachable(),
```

**What is wrong.** `last_reachable` is the most recent observation and stays
`True` after the watcher thread is gone. `FolderWatcher.alive` exists
(`watcher.py:341`) and is exposed nowhere; `WatchStatus` has no liveness field.

**The failure.** If the thread dies — or `start_watcher()` returned *"the
watch-folder thread is already running"* about a thread that has since exited —
the panel shows `enabled: true`, `reachable: true`, `last_error: null`, and only
`last_scan_at` quietly ages. That is verbatim the failure the field's own
docstring says it prevents: *"the panel stays perfectly healthy while
`last_scan_at` quietly ages"*.

**Smallest fix.** Add `alive: bool` from `watcher.alive`, and/or a
`scan_overdue` boolean derived from `last_scan_at` against
`interval_seconds`.

---

## 20. LOW — a bare `assert` decides whether over-long chunks reach the index

`backend/app/chunker.py:1379`

```python
    assert not over, (
        f"{len(over)} chunk(s) exceed the {ceiling}-token ceiling "
```

Under `python -O` the check disappears and over-ceiling chunks are embedded
truncated (the audit's entry-5 failure mode, in the writer instead of the
reranker). When it does fire, finding 1's handler records the document as
`failed` with `error_code = internal` — a chunker bug reported to the operator
as an internal error against their document. Smallest fix: raise a named
exception, or split the chunk and record the split.

## 21. LOW — the chunk signature omits the settings that change chunking

`backend/app/chunker.py:1265` hashes `doc_sha + CHUNKER_VERSION + page texts`
only. Change `settings.chunk_max_tokens` without touching `CHUNKER_VERSION` and
every existing document short-circuits with `"reason": "unchanged since last
chunking"` — a statement about the input that is true and an implication about
the output that is false. The same early return reports
`"chunks_retrievable": doc["chunk_count"]` from the stored column rather than
counting rows. Smallest fix: hash the chunking settings into the signature.

## 22. LOW — smaller derivations that do not measure what they name

- `documents_completed` (`ingest.py:114`) counts documents that reached
  `failed` as completed: `_is_finished` returns `True` for `FAILED`
  (`:499`). The docstring says *"Distinct documents finished"*.
- `stalled` (`:171`) fires whenever one document takes longer than
  `NO_PROGRESS_SECONDS = 180` with `pending_count > 0` — true of any single
  1,400-page document. `stalled_reasons` names it, so it is a false positive
  rather than a false claim, but the boolean is what the UI shows.
- `pages_declared` (`metrics.py:82`) is `SUM(page_count)` with `NULL`
  coalesced to 0, so a corpus with documents not yet extracted publishes a
  "declared" total lower than the real one, beside `pages_extracted`, with
  nothing saying which documents are not counted yet.
- `SCHEMA`'s `CREATE TABLE documents` (`db.py:15`) has no `embedded_count` or
  `recognised_pages`; both exist only because `_migrate` adds them to the
  just-created table (`:596`, `:613`). The declared schema is not the schema.
- A 0-page or structurally broken PDF passes `stream_to_temp` (magic bytes
  only), extracts 0 pages, and `chunk_document` raises
  `ValueError(f"{doc_id} has no extracted pages")` → `failed` with
  `error_code = internal`. The audit reserves `internal` for *"genuine
  unexpected failure"*; this is a caller's file and deserves a client code.

---

## State-transition table, derived from the code

`ALL_STATES` = queued, extracting, chunking, indexing_keyword,
partially_searchable, ready, no_searchable_content, failed
(`states.py:29`). Terminal: ready, no_searchable_content, failed.
Answerable: partially_searchable, ready.

| From | Declared legal (`states.py:48`) | Actually performed, by whom | Checked? |
|---|---|---|---|
| *(row insert)* | — | `queued` — `upload.py:130` INSERT | n/a |
| `queued` | extracting, failed | `extracting` — `ingest._set_state:307`; `failed` — `ingest.py:425` handler, `extract.py:159` | only `_set_state` |
| `extracting` | extracting, chunking, failed | `extracting` (self, per batch) — `extract.py:133`; `chunking` — `extract.py:212`; `failed` — `extract.py:159`, `ingest.py:425` | no |
| `chunking` | indexing_keyword, failed | `indexing_keyword` — `chunker.py:1604` and `:1357` (short-circuit); `failed` — `ingest.py:425` | no |
| `indexing_keyword` | partially_searchable, **no_searchable_content**, failed | `partially_searchable` — `keyword.py:150` (CAS, unconditional on row count); `failed` — `ingest.py:425`. **no_searchable_content is never written from here** (finding 15) | CAS on status only |
| `partially_searchable` | partially_searchable, chunking, ready, no_searchable_content, failed | `chunking` — `ingest._set_state:388` (OCR round); `ready` / `no_searchable_content` — `ingest.py:614` / `:592` (CAS); `failed` — `ingest.py:425` | `_set_state` only |
| `ready` | chunking, failed | **nothing.** `_next_document` excludes `ready`, and no route re-chunks. The "re-ingest on a new revision" comment (`states.py:66`) describes an unimplemented path | — |
| `no_searchable_content` | chunking, extracting, failed | **nothing.** `process()` returns immediately (`ingest.py:302`) and `_next_document` excludes it | — |
| `failed` | queued, extracting, chunking, failed | **nothing** (finding 1). Re-upload dedups to the same row | — |
| *unknown status* | — (`LEGAL_TRANSITIONS.get` → empty) | `extracting` — `ingest.py:296`, raw and deliberately unchecked | no, by design |

Notes on reachability, from the code rather than from the table:

- **Every state can reach `failed`, from anywhere, without a legality check**,
  because `ingest.py:425` writes it in the broad handler on the current row
  whatever the current status is.
- **Three declared edges are dead**: `indexing_keyword -> no_searchable_content`,
  `ready -> chunking`, `no_searchable_content -> {chunking, extracting}`.
  Two of those are the ones the audit's status table cites as evidence that
  non-terminal and terminal states alike are recoverable.
- **`process()` has no default branch.** Every one of the eight states is
  matched, so a ninth added to `ALL_STATES` without a branch would spin the
  `while True` loop until the churn guard trips — and the budget itself is
  `len(states.ALL_STATES) + 2`, so it grows with the table.
- Crash points, in terms of what the row then says:
  *between extract and chunk* → `chunking`, resumable, and `chunk_document`
  re-runs from `pages` (correct);
  *mid-extract* → `extracting` with `jobs.last_completed_batch` as a contiguous
  high-water mark, resumable (correct);
  *mid-embed* → `partially_searchable` with `embedded_count` recomputed by
  `_recount_embedded`, resumable (correct);
  *mid-OCR* → `partially_searchable`, and pages committed per batch, so
  resumable — **except** for a page whose recognition raised, which is retried
  forever (finding 6).
  The one thing written before the work it claims is `jobs.state = 'running'`
  at upload (finding 2).

---

## Verified clean

Checked, and I found nothing wrong with them:

- **Stage atomicity.** The index write and the state advance are one
  transaction with a compare-and-set (`keyword.py:134-152`), and so are the
  `ready` / `no_searchable_content` stamps (`ingest.py:590-621`). Extraction and
  recognition both commit batches in order with a contiguous
  `last_completed_batch` (`extract.py:111`, `ocr.py:222`). Chunking's
  delete-and-reinsert of `chunks`, `chunks_fts`, `exclusions` and orphaned
  `chunk_vectors` is a single transaction (`chunker.py:1566-1605`).
- **The OCR ordering test now asserts the outcome.** `test_ocr.py:356-365`
  checks the final row and that a recognised chunk exists, not only the statuses
  observed at each invocation — audit entry 7's lesson is applied here.
- **`_recount_embedded` before gating on the stored count** (`ingest.py:399`,
  `:577`) correctly refuses to let a stale-high `embedded_count` block its own
  repair. Only the population it counts is wrong (finding 13).
- **`page_ocr` as a separate table** genuinely protects recognised text from
  `pages`' `INSERT OR REPLACE` (`db.py:61-94`, `extract.py:116`), and
  `chunk_document` resolves recognised over extracted in one place
  (`chunker.py:1319-1332`).
- **`chunk_provenance`** (`chunker.py:1279`) labels a chunk `recognised` if
  *any* spanned page was recognised and takes the minimum confidence — the
  weaker claim, tested at module level rather than reimplemented
  (`test_ocr.py:214-259`).
- **Migrations** are additive, individually guarded by `PRAGMA table_info`, and
  the two unconditional `UPDATE`s (`exclusions` rule rename, `roles.kind =
  'capability'`) are idempotent; indexes over migrated columns are created after
  the `ALTER`s, with the reason recorded. Order does not matter between them.
  Foreign keys are enabled per connection (`db.py:565`) so the `ON DELETE
  CASCADE`s are live, and `test_worker_health.py:185` asserts derived rows are
  actually removed.
- **Path handling in `watch_api.folder_name`** is careful and well tested:
  both separators, drive designators, UNC hosts, trailing separators, and the
  admin gate plus the value-shape protection kept separate
  (`test_watch_folder.py:838-955`).
- **The watcher never modifies the source folder**, catches per file *and* per
  scan, and records `ingested` / `duplicate` / `failed` with a `CHECK`-constrained
  vocabulary; `NO_HASH` is spelled out in `detail` on every row that carries it.
- **`errors.redact` / `record_failure`** keep tracebacks and paths out of
  responses, and `_unreadable_because` builds the folder message from the
  exception class rather than `str(exc)` — the `OSError.filename` leak is
  genuinely closed.
- **`metrics.system()`'s CPU handling** (first call `None`, sub-2s window
  `None`, window reported alongside) does what it claims, and
  `_scoped_worker` correctly strips `current_document` / `last_error` for a
  caller who may not read the document.
- No connection leak and no transaction left open in the reviewed modules: one
  thread-local connection (`db.py:557`), and every write uses `with conn:`.

## Not reviewed / could not settle without running the code

- `chunker.py:1-1264` — `classify_page`, `content_quality`, heading and table
  detection, `segment_document`, `build_chunks` — read by targeted grep and at
  the call sites only. Whether the *page classification* itself drops real
  content is out of this review's boundary; findings 11 and 12 are about whether
  a drop is **recorded**, not about whether it is correct.
- `extract.py` outside its status/count writes; `keyword.py` outside
  `index_document`; `access.py`, `admin.grant_on_upload`, `telemetry`,
  `rates`, `quality.assess` taken as given.
- The 76 test files were surveyed by name and test-name; eight were read in the
  part that bears on a guarantee above. I did **not** run pytest, and I did not
  mutate any code to prove a test goes red — so every claim about a test is a
  claim about what its fixtures and assertions can reach, not a measured
  failure.
- Reachability of finding 10 depends on `settings.ocr_batch_size` and how many
  blank scanned pages a real document has; I state the mechanism and the
  approximate round count from the constants, not from a run. Running
  `test_settle_guard.py` with a stub that adds `page_ocr` rows with
  `char_count = 0` would settle it in one test.
- Finding 8's timing depends on the filesystem: whether a stalled SMB copy can
  hold `st_size` and `st_mtime_ns` constant across two scans is a property of
  the client's share, not of this code. The code's exposure to it is what I am
  reporting.
