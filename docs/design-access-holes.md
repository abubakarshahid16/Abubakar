# Remediation — five access holes

Three were recorded in `docs/design-authentication.md`. Two more were found by
walking every `@app.` decorator in `main.py`. All five are pre-existing, all five
are invisible under `AUTH_MODE=disabled`, and none was introduced by the
access-control work.

## What the code already does, so this design does not re-do it

- `api_utils.require_document` (`api_utils.py:31-57`) **already** collapses
  forbidden into not-found at `:48-49`. The 404/403 discipline exists and is
  tested (`test_access_routes.py:121-143`).
- `access.current_scope` (`access.py:125-146`) needs **zero** lines changed.
- `search`/`answer` take `allowed_document_ids` keyword-only and filter in the
  query. **Retrieval is not part of any hole.**
- `conversations.owner_user_id` and its index already exist (`db.py:386-395`).
  **Migration work for hole 2: zero.**

---

## HOLE 4 — `/api/metrics` is unscoped and leaks filenames

**Nobody listed this one.** `main.py:125-138` declares
`scope: AccessScope = Depends(access.current_scope)` and **never reads it** —
the same defect as `list_conversations`, in a route no audit flagged.

`metrics_mod.snapshot` is corpus-wide by construction:

| Source | What it exposes |
|---|---|
| `metrics.py:106-118` `jobs()["failures"]` | `SELECT id, filename, error_code, error_message` — **real ids and filenames** |
| `metrics.py:248-281` `warnings()` | Filenames embedded in free text: `f"{r['filename']} finished processing but search can see none of it."` |
| `ingest.py:165` | `current_document` — a real document id |
| `metrics.py:50-96` | Corpus-wide counts and character totals across all tenants |

This directly contradicts `/api/health`'s own docstring, which says the full
worker status "still exists, on /api/metrics, **which is scoped**"
(`main.py:100`, repeated verbatim in `client.ts:35-38`). Health was deliberately
narrowed to hide `current_document` because *"an unauthenticated caller learned
that a specific document existed and was being processed"*. **That exact fact,
plus filenames, is on `/api/metrics` for any caller regardless of grants.**

Remediation is not small. `jobs()`, `warnings()`, `corpus()`, `exclusions()`,
`throughput()` and the worker's `current_document` all need
`allowed_document_ids` threaded through, keyword-only. The filenames are inside
free-text strings, so this is a **rewrite of those strings, not a filter**.
`stage_runs` has a nullable `document_id` — an unattributable sample is
**excluded with a reason and counted**, not silently dropped, and a scoped metric
computed over a subset must say so. Unmeasured stays null.

**And fix the two now-false docstrings.** A comment asserting a security property
nothing enforces is worse than no comment, because the next reader trusts it.

---

## HOLE 5 — The upload dedupe oracle

`upload.py:110-113` returns the existing record on a SHA-256 match, and
`main.py:154` returns `upload_mod.to_api(row)` — the **full record of a document
the caller has no grant on**: filename, sha256, size, page count, status, error.

Under `demo_required`, uploading a PDF you obtained elsewhere tells you whether
it is already in the corpus, under what filename, and how far it processed.
`require_document` is not on this path — `find_by_hash` queries `documents`
directly.

**Fix:** when `duplicate_of` names a document outside the scope, return the same
success shape built from **the caller's own submission** — filename as sanitised,
size, sha256, all facts they already supplied — with `duplicate_of: null` and no
job. Deduplication still happens on disk; the caller is simply not told someone
else's copy exists.

Related, not a leak today: `doc_id = f"doc_{sha256[:12]}"` (`upload.py:117`)
means document ids are a deterministic function of content, so anyone holding the
bytes can compute the id and probe. `require_document` answers 404 correctly —
but it is a reason never to add a route that treats a document id as a capability.

---

## HOLE 1 — Page images

### The three options, honestly

**Query token** — the credential lands in the dev-server log, uvicorn's log,
`Referer`, browser history, and the disk cache key. This repo already strips
identifying data from logs. A URL-borne credential is copy-pasteable, and a
per-page token is a second signing scheme beside the bearer token. **Reject.**

**Leave open** — the route serves the literal page of the client's
specification. **Reject.**

**Blob fetch through `request()`.** Take it.

### What it requires, exhaustively

`request()` (`client.ts:115-173`) unconditionally calls `response.json()` at
`:154`. Add a sibling `requestBlob()` sharing the failure ladder and **the same
single place the bearer header is attached** — with a comment on both saying so,
because the module's stated principle is "Every call goes through here so two
rules hold everywhere" and a second entry point weakens it.

| Consumer | Change |
|---|---|
| `client.ts:200-221` both URL helpers | **Delete them.** Leaving them exported guarantees the next screen re-introduces the hole |
| `PageImageViewer.tsx:145` | `src` becomes state; effect keyed `[doc.id, selected]`. **`zoom` must not be in the deps** — it is CSS-only (`:148`), and refetching per zoom click is a new leak per click |
| `EvidencePanel.tsx:229-247` | Same, keyed on the existing tuple at `:231`. On failure render a message — today `onError` leaves a broken-image icon, which is exactly how a scope 404 would present |
| `Uploader.tsx:29-30` | Not an image, but the **other** raw transport (`XMLHttpRequest`, for progress). Needs `setRequestHeader("Authorization", …)`. A blob refactor touching only `client.ts` leaves this behind |

### A gain that falls out of this

`main.py:610` sets `X-Answer-Located: 0|1` and **no frontend code reads it**.
`EvidencePanel.tsx:222-227` instead infers "could not be confirmed" from
`question && !passage.highlight` — a different fact (the client-side offset) from
the one the server measured. Under blob the response object is in hand and the
panel can render the server's actual answer. `located: null` when the header is
absent — unmeasured is null, never `false`.

### Object-URL revocation — three leak sites

1. **Replacement** — paging 1 → 2 → 3. Effect cleanup handles it.
2. **Unmount** — drawer closes. Same cleanup.
3. **Race** — page 2's fetch resolves after the user moved to page 3. Needs a
   `cancelled` flag, and on the cancelled path **revoke the blob you just created
   and never set.** This is the one that gets forgotten.

At 150 DPI (up to 300), a leaked render is 300–800 KB. A ten-minute review of a
1,400-page document is thousands of them.

### What is lost: HTTP image caching

`main.py:608` sets `Cache-Control: max-age=86400`. Under `<img src>` repeat views
came from the browser cache with **no request at all**. Under blob, every render
issues a fetch — the HTTP cache may still serve it, but **the decode and the blob
allocation are not avoided**, and the object URL is new each time.

**Honest cost: a real regression in a page-flipping UI on a 15 W machine.** It is
the price of the route being authenticated at all. Do not paper over it with an
in-memory blob cache in the first commit — that is a second cache whose eviction
policy nobody has specified, and an unevicted one is the memory leak wearing a hat.

### The answer-overlay variant has no server-side state

`render_page_with_highlight` (`pageimage.py:78-124`) is pure: rects are recomputed
per request and the cache key is a hash of them. No token, no session, no handle
to keep alive. Both variants are one idempotent GET.

### This breaks existing frontend tests, and that is a cost to state

Three assert on the `src` string and **cannot** pass unchanged:
`ChatView.test.tsx:381`, `:897-899`, `DocumentsView.test.tsx:367`. They become
assertions on **the fetch that was issued** — a stronger test, since it checks the
request the server will actually see. jsdom has no `URL.createObjectURL`, so
`src/test/setup.ts` needs stubs, and the revoke stub is what the leak tests assert
against.

So **"123 frontend tests pass unchanged" breaks on this hole**, independent of
auth mode. Keeping a URL path under `disabled` to preserve that guarantee would
mean the enforced path is never exercised by the tests that actually run — the
exact mistake `unrestricted_scope`'s docstring was written to avoid.

---

## HOLE 2 — Conversations

| Site | Defect |
|---|---|
| `chat.py:257-268` | `owner_user_id` never written |
| `main.py:441` | `scope` taken, discarded; `chat.py:280-298` has no WHERE, and `total` is a global COUNT |
| `main.py:447` | `scope` taken, never used |
| `main.py:458` | **No `scope` parameter at all** — any caller deletes any conversation |
| `main.py:494` | `_require_conversation` unscoped — you can append to, and read the payload of, someone else's conversation |

The payload is the exposure: `schemas.Message.payload: dict | None`
(`schemas.py:449`) is unvalidated, so **quoted document text passes through the
response model untouched.**

### Is "NULL means inaccessible" enforced anywhere? No.

Grep finds `owner_user_id` in exactly two places: the `ALTER TABLE` and the
`CREATE INDEX`. No SELECT, no INSERT, no test. **The comment documents an intent
no code implements.** Say that in the commit message.

### Decision: NULL is inaccessible under `demo_required`, visible under `disabled`

It holds **by construction** — `NULL == user_id` is false in SQL and in Python,
and `scope.unrestricted` short-circuits under `disabled`. There is no `IS NULL`
branch to write, so there is none to invert by accident later.

**The cost, stated:** every conversation ever created becomes invisible the moment
`demo_required` is switched on. Not data loss — rows and messages are intact — but
**it will look like data loss during a demo.** Do not backfill to "the first
seeded user": `db.py:387-391` refuses a DEFAULT because "inventing one would be a
false record", and a backfill is that same invention with an UPDATE. Put the count
in the startup log so it is a stated fact rather than a discovered one.

### `explain_of` is safe; two other paths are not

`chat.py:445-458` binds `conversation_id` in every lookup, so `explain_of`
inherits the gate once `_require_conversation` is scoped. Good as written.

But `chat.py:441` — `document_id = document_id or conversation["document_id"]` —
takes the fallback from the conversation row and **never checks it against the
scope**. It does not leak today, because `answer()` receives
`allowed_document_ids` and filters three layers down. **The outcome is safe; the
reason it is safe is a filter, not the gate.** Add `require_document` at the route
when the fallback is taken, so the guarantee is local.

---

## HOLE 3 — Upload has no scope

Add `request` and `scope` to `main.py:143-144`. Refuse when
`scope.user_id is None and not scope.unrestricted` — **a 401 is correct here
rather than a 404**, because no resource's existence is being protected; the
caller is asking to create one.

This needs `errors.UNAUTHENTICATED` in `CLIENT_ERROR_CODES` **and** `ALL_CODES`,
or `safe_error` coerces it to `internal` at `errors.py:139`. Same code into the
closed `ApiError.code` union in `contracts/types.ts` — hand-written, no codegen.

### Which role gets the grant

| Option | Cost |
|---|---|
| First role | The ordering key is arbitrary — `user_roles` has no precedence column, and inventing one is a schema decision hiding inside an upload route. **Reject** |
| All roles | Deterministic and the **widest possible grant, applied automatically, with no operator in the loop** — in a schema whose defining property is that no row means "everyone". **Reject** |
| **Explicit `role` on upload** | A multipart field, a validation branch (the uploader must hold the role, or upload becomes a grant-to-arbitrary-role primitive), a UI control. Breaks nothing under `disabled` |
| Admin grants later | Zero rules invented. The uploader watches their upload finish and cannot see it |

**Pick: explicit role, optional, with admin-grants-later as the defined behaviour
when omitted.** Recorded in the response, not silent: `granted_to_role: string |
null`, null meaning **not granted**, never `""`.

**The honest answer to "should upload require an explicit role?" — under
`demo_required`, yes.** Inferring it for a single-role user means the rule is
"sometimes explicit, sometimes guessed", and the guessing branch is exercised
least and reviewed never. If the timeline cannot afford the UI control, ship
admin-grants-later: invisible-until-granted is a bad experience but a true one; a
guessed grant is a good experience built on a rule nobody wrote down.

---

## The fixture precondition that matters most

```python
assert settings.auth_mode == access.AUTH_REQUIRED, \
    "fixture ran under `disabled`; every assertion below is vacuous"
```

Four recorded instances of a fixture that could not produce its own condition.
Under `disabled` every negative test in this file passes for the wrong reason.

---

## Order and effort

| # | Work | Est. | Why here |
|---|---|---|---|
| 1 | Three error codes into `errors.py` **and** `contracts/types.ts` | **20 min** | Everything below returns codes. Without it every new code silently becomes `internal` |
| 2 | **Hole 2** backend | **2–3 h** | Highest severity per line changed. No schema, no frontend. **Unauthenticated DELETE closed inside the first hour** |
| 3 | **Hole 3** backend + the dedupe oracle | **2–3 h** | Dedupe fix is ~20 min of it and nobody had listed it |
| 4 | **Hole 4** — `/api/metrics` scoping | **3–4 h** | Free-text filenames mean rewriting those strings, not filtering |
| 5 | "Scope never comes from the request" across all route families | **30 min** | Cheap, and catches a resolver that later grows a fallback |
| 6 | **Hole 1** frontend | **6–8 h** | Largest, touches the most files, the only one that breaks existing tests. Last, so a mid-work stop leaves 2–5 shipped |
| 7 | Copy: split 401 from 403, image failure state, upload message | **1 h** | Cosmetic-looking and load-bearing — the current 401/403 text actively misleads |

**16–20 hours.** Steps 1–5 are ~9 and close every **server-side** hole. Step 6 is
the other half and is entirely frontend.

---

## What this does NOT fix

- **`demo_required` is still not production-safe.** This closes five holes; it is
  not a review of the whole surface.
- **No login exists.** Until `auth.py` lands, `demo_required` means "nobody sees
  anything" and none of these fixes is exercisable by a real user.
- **Legacy conversations become invisible** under `demo_required`, permanently,
  until an attribution tool exists. Deliberate. It will read as data loss.
- **Existing documents have no grants.** Flipping to `demo_required` on a
  populated database yields an empty corpus for every user until
  `seed_access.py --grant` is run per document.
- **Object-URL caching is a real performance regression** in page-flipping. No
  blob cache included, on purpose.
- **Per-user grants do not exist**, only role grants. A document is visible to a
  whole role or to nobody.
- **`audit_events` is written but never read.** No route, no screen, no report —
  events recorded for a future that has not been scheduled.
- **The `payload` dict stays untyped.** Conversations are gated, but no response
  model inspects what is inside, so a future field added to `_PAYLOAD_KEYS`
  reaches the client with no review.
- **Uncertainty not resolved:** whether anything outside `frontend/src` links the
  page-image URLs or posts to `/api/documents`. `frontend/` and `backend/` were
  grepped; `eval/`, `docs/` and `scripts/` were not.
