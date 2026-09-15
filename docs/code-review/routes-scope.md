# Route-by-route scope audit — `backend/app/main.py`, `backend/app/watch_api.py`

Subject: entry 15 of `docs/status-honesty-audit.md` — a route that resolves an
`AccessScope` and does not pass it into the data access, and the comments that
describe the route as scoped anyway.

**This review is static.** Nothing was executed: no server was started, no test
was run, no request was made. Every claim below is read off the source at the
line quoted.

Routes enumerated: **47** (46 declared on `app` in `main.py`, 1 on the router in
`watch_api.py`). Verdict counts: 11 FINDING, 36 OK, 0 needs-runtime-check as a
verdict (three separate items needing runtime confirmation are listed at the
end).

---

## 1. The complete route table

`scope dep` = takes `access.current_scope` (S) or `admin.current_admin` (A) or
neither (—).
`reaches query` = the caller's entitlement is in the SQL `WHERE` clause / the
id set handed to retrieval (yes), is resolved and never used (no), is applied in
Python after an unfiltered query (python), or the route reads no
caller-partitioned data (n/a).

| # | Method | Path | Line | Scope dep | Reaches query | `reject_unknown_params` | Verdict |
|---|--------|------|------|-----------|---------------|--------------------------|---------|
| 1 | GET | `/api/health` | 114 | — | n/a | n/a (no params accepted) | OK |
| 2 | GET | `/api/metrics` | 158 | S | partly — see F2, F3, F4 | yes | **FINDING** |
| 3 | POST | `/api/documents` | 207 | S | yes (`_require_identity_to_write`, `may_read(duplicate_of)`) | no | **FINDING** (F6 error shape) |
| 4 | GET | `/api/documents` | 261 | S | yes (`WHERE id IN (…)`) | yes | OK |
| 5 | DELETE | `/api/documents/{document_id}` | 309 | S | yes (`require_document(…, scope)`) | yes | OK |
| 6 | GET | `/api/documents/{document_id}` | 365 | S | yes | yes | OK |
| 7 | POST | `/api/documents/{document_id}/extract` | 381 | S | yes | no | OK (no query params declared) |
| 8 | POST | `/api/documents/{document_id}/chunk` | 391 | S | yes | **no, and it takes `force`** | **FINDING** (F7) |
| 9 | POST | `/api/documents/{document_id}/embed` | 406 | S | yes | no | OK |
| 10 | POST | `/api/documents/{document_id}/index-keyword` | 430 | S | yes | no | OK |
| 11 | GET | `/api/search` | 440 | S | yes (`keyword.search` SQL `IN`, dense mask before top-k) | yes | OK |
| 12 | GET | `/api/answer` | 498 | S | yes (threaded to both retrieval stages) | yes | OK |
| 13 | POST | `/api/auth/login` | 596 | — | n/a | no (body only) | OK |
| 14 | GET | `/api/auth/me` | 618 | S | yes (own identity only) | no | OK |
| 15 | GET | `/api/progress/{progress_id}` | 647 | — | n/a (in-memory, client-chosen id) | no | **FINDING** (F11, low) |
| 16 | POST | `/api/analysis/summary` | 700 | S | yes (`gather` → `narrow_to_named` intersection) | no (body only) | OK |
| 17 | POST | `/api/analysis/recommendations` | 716 | S | yes | no (body only) | OK |
| 18 | POST | `/api/analysis/gaps` | 730 | S | yes (+ baseline via `require_document`) | no (body only) | OK |
| 19 | GET | `/api/classification/vocabulary` | 787 | S | yes for the count; vocabulary deliberately unscoped and says so | yes | OK |
| 20 | GET | `/api/classification/coverage` | 807 | S | yes (`document_id IN (…)`) | yes | OK |
| 21 | GET | `/api/documents/{document_id}/classification` | 818 | S | yes | no | OK |
| 22 | PUT | `/api/documents/{document_id}/classification` | 842 | S + A | yes (both checks run) | no | OK |
| 23 | GET | `/api/market/findings` | 879 | S | **no — resolved and dropped** | no | **FINDING** (F8) |
| 24 | POST | `/api/market/preview-query` | 885 | S | **no — resolved and dropped** | no (body only) | **FINDING** (F8) |
| 25 | GET | `/api/market/preview` | 944 | S | yes (`_corpus_filenames(scope)` bounds the strip list) | **no, and it takes 3 params** | **FINDING** (F7) |
| 26 | POST | `/api/market/search` | 976 | S | yes (same scrub, re-run server-side) | no (body only) | OK |
| 27 | POST | `/api/reports` | 1035 | S | yes (`build_snapshot` refuses any cited doc outside scope) | no (body only) | OK |
| 28 | GET | `/api/reports` | 1054 | S | **python — unfiltered `SELECT * FROM reports`** | no | **FINDING** (F5) |
| 29 | GET | `/api/reports/{report_id}/verify` | 1059 | S | python, single row (`_require` → `_visible`), 404 not 403 | no | OK |
| 30 | GET | `/api/reports/{report_id}/download` | 1066 | S | python, single row, 404 not 403 | no | OK |
| 31 | POST | `/api/conversations` | 1094 | S | yes (identity required; `require_document`) | no (body only) | OK |
| 32 | GET | `/api/conversations` | 1110 | S | yes (`conversation_filter()` → `WHERE owner_user_id = ?`, page and `total`) | yes | OK |
| 33 | GET | `/api/conversations/{conversation_id}` | 1137 | S | yes (`owns_conversation`, 404 not 403) | yes | OK |
| 34 | DELETE | `/api/conversations/{conversation_id}` | 1149 | S | yes (ownership before confirm) | yes | OK |
| 35 | POST | `/api/conversations/{conversation_id}/ask` | 1184 | S | yes (ownership + `allowed_document_ids`) | no (body only) | OK |
| 36 | GET | `/api/documents/{document_id}/pages` | 1232 | S | yes | yes | OK |
| 37 | GET | `/api/documents/{document_id}/pages/{page_no}/image` | 1266 | S | yes (`require_document`; highlight join pins `chunk_id` to `document_id`) | yes | OK |
| 38 | GET | `/api/documents/{document_id}/chunks` | 1327 | S | yes | yes | OK |
| 39 | GET | `/api/documents/{document_id}/excluded` | 1366 | S | yes | yes | OK |
| 40 | GET | `/api/admin/users` | 1429 | A | n/a (not document data) | yes | OK, but see F9 |
| 41 | POST | `/api/admin/users` | 1442 | A | n/a | no (body only) | **FINDING** (F9) |
| 42 | DELETE | `/api/admin/users/{user_id}` | 1460 | A | n/a | no | OK, but see F9 |
| 43 | GET | `/api/admin/disciplines` | 1473 | A | n/a | yes | OK, but see F9 |
| 44 | GET | `/api/admin/grants` | 1487 | A | n/a | yes | OK, but see F9 |
| 45 | PUT | `/api/admin/grants` | 1500 | A | n/a | no (body only) | **FINDING** (F9) |
| 46 | DELETE | `/api/admin/grants` | 1509 | A | n/a | no (body only) | **FINDING** (F9) |
| 47 | GET | `/api/watch/status` | watch_api.py:233 | S | **no for the payload that names documents** | yes | **FINDING** (F1) |

Rows 40 and 42–44 are marked OK on their own conduct and appear again under F9,
which is about the comment above them and about the mode in which the gate is
vacuous.

---

## 2. Findings, most severe first

### F1 — HIGH: `/api/watch/status` resolves a scope and returns ten document filenames outside it

**`backend/app/watch_api.py:233`** (route), **`:304`** (`"recent": recent_events()`),
**`:198`–`:217`** (`recent_events`), **`:265`** (the one use the scope is put to).

**What is wrong.** The route takes `scope: access.AccessScope` and uses it for
exactly one field, `folder_name`; `recent_events()` takes no scope and its query
has no scope predicate, so the last ten watched-folder decisions — each carrying
a real document `filename` — are returned byte-identically to every caller.

```python
    may_see_host_paths = scope.unrestricted or scope.is_admin      # :265
        "folder_name": folder_name(folder) if may_see_host_paths else None,
        ...
        "recent": recent_events(),                                  # :304
```

```python
        for r in connect().execute(
            "SELECT filename, outcome, observed_at, detail FROM watch_events"
            " ORDER BY id DESC LIMIT ?",
            (limit,),
        )                                                           # :219-223
```

**The failure.** Under `AUTH_MODE=demo_required`, a caller with no token
(`empty_scope()`, zero allowed ids) or a Civil Engineering user with four grants
calls `GET /api/watch/status` and receives, in the same second that
`GET /api/documents` correctly returns `[]` or four rows, ten rows of
`{"filename": "…", "outcome": "ingested"|"duplicate"|"failed", "at": …,
"detail": …}` naming documents dropped into the client's inbox — including
`duplicate`, which additionally asserts that a document with that content is
already in the corpus. A correctly scoped route would restrict
`watch_events` to rows whose `document_id` is in `scope.allowed_document_ids`
and return `[]` to the ungranted caller. This is the same disclosure
`/api/health` was stripped for: "an unauthenticated caller learned that a
specific document existed and was being processed."

The comments beside it record a false reason. The module docstring (`:28`)
says "Everything else in the payload is: whether the feature is on, how often it
looks, when it last looked, and what it decided" — filenames are not named as
part of "what it decided"; `WatchEvent.filename`'s own description is "as it was
named in the folder"; and `recent_events`' docstring reasons only about
`source_path`, concluding that returning it "would move the leak rather than
close it - which is precisely how /api/health's disclosures ended up on
/api/metrics." The filename is the disclosure and the docstring inspects the
path instead. `backend/tests/test_watch_folder.py:549` and `:568` assert the
filenames are present; no test asserts they are withheld from a caller who may
not read the documents.

**Smallest fix.** Give `recent_events` the scope and put it in the query:
`... FROM watch_events WHERE document_id IN (…) ORDER BY id DESC LIMIT ?`, with
`WHERE 1 = 0` for an empty scope and no predicate for `scope.unrestricted`; rows
whose `document_id` is NULL (a `failed` drop that never became a document) are
still names of client files and belong behind `may_see_host_paths`.

---

### F2 — HIGH: `/api/metrics` gates host telemetry, `current_document` and `last_error` on a predicate that means "everybody" in the default mode

**`backend/app/main.py:193`**, **`backend/app/metrics.py:484`**,
**`backend/app/metrics.py:437`–`443`** (`_scoped_worker`),
**`backend/app/config.py:51`** (`auth_mode: str = "disabled"`).

**What is wrong.** `corpus_wide = scope.unrestricted or scope.is_admin` is used
as the admin gate for the machine's own specifications and for the worker's
document-identifying fields, but every caller is `unrestricted` under the
default `AUTH_MODE=disabled`, so in the shipped default configuration the gate
admits an unauthenticated caller.

```python
    corpus_wide = scope.unrestricted or scope.is_admin              # main.py:193
    return metrics_mod.snapshot(
        ingest_mod.get_worker().status(), allowed, corpus_wide, corpus_wide)
```

```python
        **({"system": system()} if host else {}),                   # metrics.py:484
```

```python
    if corpus_wide:
        return status                                               # metrics.py:439
```

**The failure.** With no token at all, in the default mode, `GET /api/metrics`
returns the `system` block — `cpu_logical_cores`, `cpu_physical_cores`,
`ram_total_bytes`, `ram_used_bytes`, `ram_free_bytes`, `process_rss_bytes`,
`disk_total_bytes`, `disk_free_bytes`, `data_dir_bytes` — the free-RAM figure
restated in the `low_memory_for_answer_model` prose, and the full worker status
including `current_document` (a real document id the UI joins to a filename) and
free-text `last_error`. Those last two are the exact fields removed from
`/api/health` because "an unauthenticated caller learned that a specific
document existed and was being processed"; they are reachable by that same
caller again. `metrics.snapshot`'s docstring states the opposite — "`host` gates
the machine's own specifications … on the ADMIN CAPABILITY" — and
`_scoped_worker`'s docstring says "A caller who may not read the document being
processed does not learn its id." `watch_api.py:16`–`24` already names this
exact hazard about this exact predicate ("under `AUTH_MODE=disabled` every
caller is `unrestricted`, so 'administrators only' means 'everybody' in the mode
the whole suite runs in") and adds a second protection for it; `/api/metrics`
has no second protection.

**Smallest fix.** Split the two questions the one predicate is answering: keep
`corpus_wide = scope.unrestricted or scope.is_admin` for aggregate counts, and
pass `host = scope.is_admin` (capability only, never `unrestricted`) for the
`system` block, the RAM prose and `_scoped_worker`'s `current_document` /
`last_error`.

---

### F3 — HIGH: `/api/metrics` returns three corpus-wide page counts while the payload says `corpus_wide: false`

**`backend/app/metrics.py:378`–`381`** and **`:408`–`410`**, reached from
`main.py:196`–`203`.

**What is wrong.** `warnings()` receives `allowed` and applies it to its two
document loops and to nothing else; the OCR and equation aggregates below them
query `documents` with no `WHERE`.

```python
    row = conn.execute(
        """SELECT COALESCE(SUM(needs_ocr_pages), 0) AS flagged,
                  COALESCE(SUM(recognised_pages), 0) AS recognised
           FROM documents"""
    ).fetchone()                                                    # :378-381
```

```python
    equations = conn.execute(
        "SELECT COALESCE(SUM(equation_pages), 0) FROM documents"
    ).fetchone()[0]                                                 # :408-410
```

**The failure.** A user granted nothing receives `corpus: {"documents": 0}` and,
in the same response, `"N scanned page(s) have not been read yet"`,
`"N page(s) were read by OCR and are searchable"` and `"N page(s) are
equation-heavy"`, where every N is summed over the entire corpus — measurements
about documents they cannot list, cannot search and cannot open. The four-grant
user gets the same three numbers as the administrator. And the response asserts
that these are *not* corpus-wide figures: `"corpus_wide": false` travels beside
them (`metrics.py:475`), and the field exists precisely so the screen can state
the boundary. `snapshot`'s docstring says "Everything the dashboard shows,
restricted to `allowed`"; `warnings`' docstring says "Both are scoped", which is
true of the two loops it is describing and false of the function's return value.
A correctly scoped route would sum `needs_ocr_pages`, `recognised_pages` and
`equation_pages` over the caller's own documents — 0 for the ungranted caller,
so the warning would not render at all.

**Smallest fix.** Apply the module's existing helper to all three:
`id_where, id_args = _where(allowed, "id")` is already computed at the top of
`warnings()`; append it to both queries and bind `id_args`.

---

### F4 — MEDIUM: the exact model names were moved to `/api/metrics` on the stated grounds that it is scoped; grant scoping cannot gate a machine fact

**`backend/app/metrics.py:485`** (`"models": models()`),
**`backend/app/main.py:126`**–`137`, **`backend/app/schemas.py:160`–`164`**.

**What is wrong.** `models()` is called unconditionally — it is not behind
`host`, and no grant can bound it — while the two places that justify moving the
answer model's identity off `/api/health` justify it by saying the destination
is scoped.

```python
        **({"system": system()} if host else {}),
        "models": models(),                                         # metrics.py:485
```

```python
    answer_model_present: bool = Field(
        description="whether an answer model is configured, NOT which one. The "
        "exact name and version is fingerprinting material and lives on the "
        "scoped /api/metrics."                                      # schemas.py:161-164
    )
```

**The failure.** `models()` returns `embed_model`, `reranker_model`,
`answer_model` (the configured name and tag), `answer_model_installed`,
`answer_model_loaded` and `ollama_error`. None of that is a document, so
`allowed` cannot remove any of it: a user granted nothing gets the same
fingerprint as an administrator, and in the default `AUTH_MODE=disabled` so does
a caller with no token — i.e. the material `/api/health` was stripped of is
reachable by the same anonymous caller on the route the docstring calls scoped.
`main.py:126`'s paragraph was corrected for the worker fields ("THAT SENTENCE
WAS FALSE WHEN IT WAS WRITTEN") but line 133–137 still offers grant scoping as
the protection for the model name, and `schemas.py:164` still says "the scoped
/api/metrics" with no correction beside it. This is entry 15's shape exactly:
the relocation is presented as hardening by a comment whose reason does not hold
of the code.

**Smallest fix.** Put the identifying fields of `models()` behind the same
capability-only flag F2 introduces (`answer_model`, `embed_model`,
`reranker_model`, `ollama_error`), leaving the `*_present` / `*_reachable` /
`*_loaded` booleans — which are what the dashboard branches on — for everyone;
then correct `schemas.py:164` and `main.py:133`–`137` to say what actually gates
the name.

---

### F5 — MEDIUM: `GET /api/reports` selects every report in the system and filters in Python

**`backend/app/reports.py:618`–`621`**, route at **`main.py:1054`**.

**What is wrong.** The scope reaches the decision but never the query: the route
reads the whole `reports` table with no predicate and no `LIMIT`, then drops the
rows the caller may not see in a list comprehension.

```python
def list_reports(scope: access.AccessScope) -> dict:
    rows = connect().execute("SELECT * FROM reports ORDER BY created_at DESC").fetchall()
    visible = [r for r in rows if _visible(r, scope)]
    owned = _owned_by(rows, scope)
```

**The failure.** Today the rows returned are correct. The defect is that
correctness is not enforced anywhere a future edit must pass: this is the shape
the project's own review rule names ("Filtering after the query, in Python, is a
finding even when it currently returns the right rows"), and `main.py:266`–`272`
and `chat.list_conversations` both refuse it on principle for exactly the reason
that applies here — the day someone adds `limit`/`offset` to `/api/reports`
(every other list route has them), the page is filled from the unfiltered set
and another owner's reports occupy slots or leak. It is also N+1 at scale:
`_visible` runs one query per report row and `_row_to_record` another, so
listing is 2N + 1 queries over the whole table for a caller who owns one report.

**Smallest fix.** Filter owner in SQL — `WHERE owner_user_id = ?` (plus the
`AUTH_DISABLED` no-predicate case) — before the `_visible` document check, and
give the route `limit`/`offset` with `reject_unknown_params` while the query is
being changed.

---

### F6 — MEDIUM: the upload 400 path returns an unredacted `detail` field the declared error model does not have

**`backend/app/main.py:230`–`235`**, `ApiError` at **`schemas.py:29`–`36`**,
`UploadError` detail built at **`upload.py:73`–`76`**.

**What is wrong.** Every other error in the API goes through
`errors.safe_error()`, which redacts; this one hand-builds a body from the
exception's own fields and adds a `detail` key that `ApiError` — the model the
route declares for 400 via `schemas.ERRORS_400` — does not declare.

```python
    except upload_mod.UploadError as e:
        return JSONResponse(
            status_code=400,
            content={"code": e.code, "message": e.message, "detail": e.detail},
        )                                                           # main.py:230-235
```

```python
class ApiError(BaseModel):
    """The only error shape the API returns. Never carries internal detail."""
```

**The failure.** A caller uploading a non-PDF receives
`{"code": "not_pdf", "message": "That file is not a PDF", "detail": "magic bytes
were b'PK\\x03\\x04'"}` — a field that is not in the schema, so the generated
client cannot see it, on a path where no redaction runs. `JSONResponse` bypasses
`response_model`, so nothing catches the divergence. The content is harmless
today (bytes from the caller's own file); the defect is that the one class of
text `errors.py` exists to police — free text from an exception — has an
unredacted route to the client, and the next `UploadError` raised from an
`OSError` (whose `str()` carries the filename and path) would ship it while
`ApiError`'s docstring still says "Never carries internal detail."

**Smallest fix.** Return `errors.safe_error(e.code, e.message)` in the envelope
shape the other 400s use, and either drop `e.detail` or add a redacted `detail`
field to `ApiError` so the contract states it.

---

### F7 — MEDIUM: two routes accept query parameters and never reject unknown ones

**`backend/app/main.py:944`–`951`** (`/api/market/preview`) and
**`main.py:391`–`404`** (`…/chunk`, which takes `force`).

**What is wrong.** `reject_unknown_params` is absent from both, so a mistyped
parameter is silently ignored and the caller is answered as though it had been
applied — the exact failure `api_utils.py` was written for ("a client that
mistyped a filter believed it had filtered when it had not").

```python
def market_preview(
    phrase: str = Query(..., min_length=1, max_length=2000),
    country: str | None = Query(None, max_length=8),
    freshness_days: int | None = Query(None, ge=1, le=3650),
    scope: access.AccessScope = Depends(access.current_scope),
):                                                                  # main.py:944-951
```

**The failure.** `GET /api/market/preview?phrase=…&freshness=30` (or
`freshness_days_=30`, or `region=GB`) returns 200 with `freshness_days: null`
and `country: null`, and the operator reviewing what would leave the machine is
shown a payload whose freshness and country they believe they set. That is the
one thing this route exists to guarantee — "A preview that omitted them showed
an object that was never sent - the defect this route was rewritten to close."
On `…/chunk`, `?forced=true` returns 200 with the short-circuited result, so a
caller who asked for a rebuild is handed the stale chunks and a success.

**Smallest fix.** Add `request: Request` and
`reject_unknown_params(request, {"phrase", "country", "freshness_days"})` /
`reject_unknown_params(request, {"force"})` as the first line of each, matching
the 20 routes that already do it.

---

### F8 — LOW: `/api/market/findings` and `/api/market/preview-query` resolve a scope and discard it, under a comment saying they are scoped

**`backend/app/main.py:874`–`890`**.

**What is wrong.** Both routes take `scope` and neither references it; the
section comment states the property they do not have, and miscounts the routes
it is describing (there are four market routes, two of which do use the scope).

```python
# No network call exists in this build. Both routes are scoped like every
# other, not because a sample is sensitive, but so that adding a real provider
# later cannot introduce an unscoped route by inheriting this shape.

@app.get("/api/market/findings", response_model=schemas.MarketFindings)
def market_findings(scope: access.AccessScope = Depends(access.current_scope)):
    """Illustrative rows, every one labelled as a sample."""
    return market_mod.findings()                                    # main.py:874-882
```

**The failure.** No corpus data leaks — `findings()` reads a bundled sample file
and `preview_query()` echoes the caller's own words — so the failure is the
comment, not the payload: the stated reason for the parameter ("so that adding a
real provider later cannot introduce an unscoped route by inheriting this
shape") is false of the code beside it, and the shape being inherited is a
parameter resolved on every request and dropped. That is the artefact entry 15
records, in the place a future provider is most likely to be wired in.

**Smallest fix.** Either use the scope — bound `preview_query` with
`analysis_mod._corpus_filenames(scope)` the way `/api/market/preview` does — or
delete the parameter and rewrite the comment to say these two routes need no
scope and why.

---

### F9 — LOW: the admin banner claims a non-admin gets 404; an unauthenticated caller gets served in the default mode

**`backend/app/main.py:1413`–`1427`**, `admin.current_admin` at
**`admin.py:215`–`221`**.

**What is wrong.** The comment above the seven admin routes states the boundary
unconditionally, and `current_admin` returns `None` — i.e. admits the request —
for a caller with no identity when `AUTH_MODE` is `disabled`, which is the
default (`config.py:51`).

```python
# EVERY ROUTE HERE DEPENDS ON `admin.current_admin`, AND A NON-ADMIN GETS 404.
```

```python
    user_id = auth_mod.resolve_user_id(request)
    if user_id is None:
        from .access import AUTH_DISABLED

        if settings.auth_mode == AUTH_DISABLED:
            return None                                             # admin.py:215-220
```

**The failure.** On a default-configured deployment, anyone who reaches the port
can `POST /api/admin/users` and receive a one-time setup token,
`DELETE /api/admin/users/{id}`, and `PUT`/`DELETE /api/admin/grants` — writing
the `document_role_access` rows that are the whole authorisation decision, with
`actor` `None` so the audit row names nobody. The concession is argued honestly
in `current_admin`'s own docstring, but the argument given there is about
*reads* ("`access.unrestricted_scope()` already hands every caller every
document"), and it does not cover a write that survives a later switch to
`demo_required`. The defect at the routes is the flat claim above them.

**Smallest fix.** Amend the banner to state the mode dependency, and require an
identified admin for the four writing routes regardless of mode (`current_admin`
already raises for an identified non-admin in both modes).

---

### F10 — LOW: three 400 bodies do not match the error model their route declares

**`backend/app/main.py:323`–`331`** (`delete_document`),
**`main.py:1160`–`1166`** (`delete_conversation`), and the same route as F6.

**What is wrong.** `schemas.ERRORS_400` declares `ApiError` (a flat
`code`/`message`/…), while the bodies are `ErrorEnvelope`-shaped and carry extra
top-level keys; `JSONResponse` skips `response_model`, so nothing detects it.

```python
            content={"detail": errors.safe_error(
                errors.CONFIRM_REQUIRED,
                "pass confirm=true to delete; this cannot be undone",
                document_id=document_id,
            )} | {"filename": doc["filename"], "retrievable_chunks": doc["chunk_count"]},
```

**The failure.** A generated client typed from the OpenAPI document reads
`error.code` on a 400 and finds `undefined`, because the field is at
`error.detail.code`; `filename` and `retrievable_chunks` — which the confirm
dialog needs — are not in the schema at all, so a typed client cannot reach them
without casting. Same family as the untyped-200 defect the codebase already has
a guard for, on the error side where no guard runs.

**Smallest fix.** Declare `ERRORS_400` as `ErrorEnvelope` and give the two
delete routes a small declared model carrying the extra fields, or move
`filename`/`retrievable_chunks` inside the envelope's `detail`.

---

### F11 — LOW: `/api/progress/{progress_id}` is unauthenticated and its docstring understates what it returns

**`backend/app/main.py:647`–`663`**, payload built at
**`backend/app/progress.py:118`–`129`**.

**What is wrong.** The route is unauthenticated by design and the id is chosen
by the client, but the docstring describes the payload as narrower than it is
and the id is never bound to the caller who created it.

```python
    Unauthenticated, and carries no document content - a stage name, a count
    and a clock. The id is chosen by the client; guessing one reveals only
    that somebody is asking a question, which /api/health already reveals
    through `busy`.                                                 # main.py:652-655
```

**The failure.** The record also carries `detail` and a full `history`: with
`stage` values from `answer.py:621` and `search.py:721`/`810`, that is
`"3 sources"`, `"12 of 40 candidates"`, `"5 passages"`, plus per-stage timings.
Those are counts about another caller's retrieval against documents the reader
may not hold, with no stated boundary, and they are more than "that somebody is
asking a question". The frontend uses `crypto.randomUUID()`
(`frontend/src/views/ChatView.tsx:276`), so the ids are unguessable in practice
and this is not currently reachable; the defect is that nothing in the server
requires that, and the comment reasons from the weaker payload.

**Smallest fix.** Record the creating scope's `user_id` (or `unrestricted`) in
the `_Entry` and return 404 from `read()` for anybody else; failing that,
correct the docstring to list `detail` and `history` and say the id's
unguessability is the whole control.

---

## 3. Verified clean (the boundary of this review)

Traced from route signature into SQL and found the scope in the `WHERE` clause
or in the id set handed to retrieval: `/api/documents` (GET, `id IN (…)`),
`require_document` on all 16 single-document routes (and it is 404, not 403, for
a document outside scope — `api_utils.py:32`–`58`), `keyword.search`
(`document_id IN (…)` inside the SQL, before `ORDER BY … LIMIT`),
`dense_search` (mask applied to the score vector before top-k, so an
out-of-scope chunk cannot consume a slot), `answer.answer`,
`analysis.gather`/`narrow_to_named` (intersection on the way out),
`classification.narrow_to_scope` (intersection, never a union, and fail-closed
when the filter matches nothing), `classification.coverage` /
`needs_classification`, `chat.list_conversations` (page and `total` both
filtered), `AccessScope.owns_conversation` / `conversation_filter` as the single
ownership rule, `reports.build_snapshot` (refuses a snapshot citing any
document outside scope), `metrics.corpus` / `exclusions` / `jobs` and the two
document loops in `warnings` (all via `metrics._where`).

Error paths checked and clean: every `HTTPException` in both files passes through
`errors.safe_error`, and `errors.redact` collapses anything containing a
traceback marker, a `File "`, `:\` or more than three `/`. `_analysis_or_503`
and the `NotReportable` 422 interpolate exception text but do so through
`safe_error`. `page_image`'s `PageOutOfRange` likewise.
`watcher._unreadable_reason` maps the exception class to a fixed half-sentence
rather than passing `str(exc)`, which would carry the share path.
`admin_list_users` returns no setup-token plaintext. `download_report` sends
`private, no-store` and names the file by report id, never the question.
`403` appears nowhere in either file.

Not reviewed: the frontend, the test suites (read only where they bear on a
finding), `docs/` beyond `status-honesty-audit.md` and
`.claude/commands/review.md`, `contracts/`, `eval/`, `scripts/`, and the
non-route internals of `synthesis.py`, `coverage.py`, `quality.py`,
`intent.py`, `ocr.py`, `vectorcache.py` and `market_providers.py`. I did not
audit `auth.py`'s token handling, the rate limiter, or the ingestion worker.

## 4. Needs runtime confirmation

Static reading settles the code paths above; three things can only be pinned by
calling the API, which I did not do:

1. **F3's magnitude.** The three unscoped sums are corpus-wide by inspection,
   but whether a given deployment's warning renders depends on
   `needs_ocr_pages`/`recognised_pages`/`equation_pages` being non-zero. Two
   requests — one as an ungranted user, one as an administrator — would show the
   identical N beside `corpus.documents: 0`.
2. **F1 and F2 as observed responses.** Both follow from the code, but the
   byte-level proof is a `GET /api/watch/status` and a `GET /api/metrics` with no
   token under each `AUTH_MODE`, diffed against `GET /api/documents` in the same
   second — the method entry 15 was measured with.
3. **F6's declared-vs-actual 400 bodies.** Whether FastAPI's generated OpenAPI
   document shows `ApiError` for these 400s (and therefore what a generated
   client is typed to expect) is worth confirming against `/openapi.json` rather
   than inferred from `responses=`.
