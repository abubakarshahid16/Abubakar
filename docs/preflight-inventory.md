# Preflight inventory

What the repository actually contains, verified on **2026-09-05** against
commit `cec7731` on branch `chore/60-sec-001-upload-ceiling-and-reachability`.

Required by §0 of `NABAA-SUNDAY-POC-EXECUTION.md` before any enterprise code.
The plan states its own precedence rule:

> *"If this reference differs from the repository, the repository and its
> passing tests are authoritative."*

So every mismatch below resolves in the repository's favour. Nothing here is a
criticism of the plan — a plan written before the code moved is expected to
drift, and finding the drift now is cheaper than an auth commit assuming a
schema that is not there.

---

## Mismatches found — read this section first

| Plan says | Repository has | Severity |
|---|---|---|
| 494 backend tests | **504** | Stale count |
| 99 frontend tests | **123** | Stale count |
| `backend/app/routers/auth.py`, `routers/admin.py`, `routers/analysis.py` | **No `app/routers/` package exists.** Every route lives in `main.py` | Structural — the plan already hedges this with *"if router structure permits"* |
| `search(query, *, allowed_document_ids, selected_document_ids, limit)` | `search(question, limit=10, candidates=None, document_id=None, rerank=True, dense=True) -> dict` | **Every parameter differs**: name, keyword-only-ness, scoping model, return type |
| *"the repository's SQLite variable limit"* | **32,766** (`sqlite3.Connection.getlimit`, Python 3.12) | Now measured, not assumed |
| *"the existing migration style"* | Additive-only `_migrate()`; `PRAGMA table_info` then `ALTER TABLE ADD COLUMN`. **No version table, no down-migrations, no transaction wrapper** | The plan's *"migration transaction"* has no precedent to follow |

Everything else the plan names by path **exists**.

---

## 1. Modules named in §4A

All twelve exist at the stated paths:

`db.py` · `main.py` · `schemas.py` · `search.py` · `keyword.py` ·
`vectorcache.py` · `answer.py` · `chat.py` · `metrics.py` · `errors.py` ·
`config.py` · `upload.py`

Frontend, all five exist: `views/ChatView.tsx`,
`components/chat/AnswerCard.tsx`, `views/DocumentsView.tsx`,
`components/DocumentCard.tsx`, `views/DashboardView.tsx`.

**`vectorcache.py` is real** — worth stating because it is the newest of these
and the plan's surgical change depends on it.

### Modules the plan proposes to create — none exist yet

`auth.py` · `access.py` · `analysis.py` · `evidence.py` · `feedback.py` ·
`market.py` · `reports.py` · `routers/`

---

## 2. The retrieval signature — the largest single mismatch

The plan's request-scoped contract:

```python
def search(query: str, *, allowed_document_ids: frozenset[str],
           selected_document_ids: frozenset[str] | None = None,
           limit: int) -> list[SearchResult]:
```

What `backend/app/search.py:515` actually is:

```python
def search(question: str, limit: int = 10, candidates: int | None = None,
           document_id: str | None = None, rerank: bool = True,
           dense: bool = True) -> dict:
```

Four things to settle before writing auth:

1. **`question`, not `query`.** Callers across `answer.py`, `chat.py`,
   `main.py`, `eval/` and the test suite use the current name.
2. **Scoping today is a single optional `document_id`**, not a set. There is no
   notion of an authorized set anywhere in retrieval.
3. **Returns a `dict`**, not `list[SearchResult]`. The dict carries `hits`,
   `mode`, `timings`, `keyword_candidates`, `dense_candidates`,
   `heading_precedence` — the explainability payload the dashboard and eval
   read. A change to `list[SearchResult]` is not surgical; it is a contract
   break across the reachability sweep, the eval harness and the UI.
4. **Nothing is keyword-only.** Making `allowed_document_ids` required and
   keyword-only is the right shape for a security parameter — the plan's
   instinct that *"the default must never mean all documents"* is sound — but
   it touches every existing call site, so it is a deliberate refactor and not
   an additive change.

---

## 3. Database

**Tables that exist:** `documents`, `jobs`, `pages`, `page_ocr`, `chunks`,
`chunk_vectors`, `exclusions`, `conversations`, `messages`, `stage_runs`, plus
the FTS5 shadow tables (`chunks_fts` and its `_config`/`_content`/`_data`/
`_docsize`/`_idx` companions).

**`jobs` columns**, since §4A names the table:
`id`, `document_id`, `stage`, `state`, `pages_total`, `pages_done`,
`last_completed_batch`, `retries`, `error_code`, `error_message`,
`started_at`, `updated_at`.

There is **no user, tenant, grant, project or role table**. Every access-control
table the plan needs is new.

### Migration pattern — what "the existing style" actually is

`db.py::_migrate()`, called from `init_db()` on every connection setup:

```python
have = {r["name"] for r in conn.execute("PRAGMA table_info(chunks)")}
if have and "retrievable" not in have:
    conn.execute("ALTER TABLE chunks ADD COLUMN retrievable INTEGER NOT NULL DEFAULT 1")
```

Properties a new migration must match:

- **Additive only.** Columns are added; none is dropped or retyped.
- **Idempotent by inspection**, not by a version number. There is no
  `schema_version` table and no migration history.
- **Defaults are chosen so existing rows are correct without a backfill**, and
  where that reasoning is non-obvious it is written down (see ADR-0006 on
  `text_source`).
- **No transaction wrapper and no down-migration.** The plan asks for a
  "migration transaction"; there is no precedent, so that is a new pattern to
  introduce deliberately rather than a convention to follow.

**SQLite variable limit: 32,766**, read from the live connection. A
parameterised `IN (?, ?, …)` over a 20-document prototype is far inside it; the
plan's caution about the 1,200-document corpus is about SQL size and plan
quality, not about hitting this ceiling.

---

## 4. Routers

There is **no `app/routers/` package.** `main.py` declares every route with
`@app.get` / `@app.post` decorators directly. Introducing `APIRouter` is a new
structural pattern — permitted by the plan's *"if router structure permits"*
hedge, and worth doing given `main.py`'s size, but it is a decision rather than
an existing convention to extend.

---

## 5. Type contracts — hand-written, not generated

`contracts/types.ts` line 1:

```
// Shared API types. Hand-written, source of truth for the UI.
// Backend mirrors these in Pydantic models.
```

- **Nothing generates it.** There is no codegen step, no OpenAPI export, no
  build task. TypeScript and Pydantic are kept in step **by hand**.
- The frontend consumes it by re-export: `frontend/src/types/api.ts` is two
  lines, `export * from "../../../contracts/types"`.
- **The compiler is the only enforcement**, and only in one direction. Adding a
  required field to `types.ts` breaks `tsc` until every fixture supplies it —
  which is how the `text_source` and `recognised_pages` additions were caught.
  A field added to Pydantic and **not** to `types.ts` is silently invisible to
  the UI; nothing detects that.

This matters for the plan's §8 instruction that *"new response fields are
required unless absence is meaningful"*: required-ness is enforced on the
frontend by `tsc`, and on the backend by nothing but review.

---

## 6. Commands

```bash
# backend - from backend/, where pytest.ini lives
cd backend && python -m pytest -q            # 504 passed, 1 deselected, ~3m30s
python -m pytest -m slow                     # the deselected one: builds a real ONNX session

# frontend - from frontend/
npm run test                                 # 123 passed, ~15s
npx tsc -b                                   # typecheck
npm run lint                                 # oxlint

# python lint, from the repository root
python -m ruff check backend/ eval/          # 121 findings; see below

# the app
cd backend && python run.py                  # 127.0.0.1:8000
cd frontend && npm run dev                   # 127.0.0.1:5173
```

**Test counts as of this inventory: backend 504, frontend 123.** The plan cites
494 and 99. Both plan figures are stale, not wrong-in-kind — the suites have
grown.

---

## 7. Lint baseline

Ruff was introduced this session and had never run against this codebase.
First run: **137 findings**. After fixing only the correctness-relevant ones —
12 unused imports and one closure defect — **121 remain**, of which 46 are
auto-fixable.

The remainder is style (`I001` import order, `PTH123` `open()` vs
`Path.open()`, `UP017` `datetime.UTC`) and is **deliberately untouched**: a
57-file diff during a feature sprint is how a real change gets lost.

One finding is worth carrying forward: `chunker.py` `B023`, a closure over the
loop variables `page_no` and `section`. It was benign — every call sat inside
the iteration that defined it — but that was a property of the call sites, not
of the function. `page_no` is now bound as a default and `section` is passed
explicitly, because `section` is reassigned mid-loop and freezing it would have
silently mis-filed every heading.

---

## 8. Frozen for this sprint

Per the plan's own instruction, and because the entire evidence base in
`docs/benchmarks.md` is measured against them:

chunk sizes · quality thresholds · model quantisation · rerank thresholds ·
OCR settings · measured retrieval heuristics.

The known consequence is recorded in `docs/limitations.md`: on a controls
catalogue whose atomic unit is a table row rather than a paragraph, citations
name the chapter containing a control rather than the control itself. Measured
on NIST SP 800-53r5. Not fixed, deliberately.

---

## 9. Departure recorded: `search()` keeps its dict

Resolved 2026-09-05, before any authentication code.

`search()` now takes `allowed_document_ids` as a **required keyword-only
parameter with no default**, and filters at both the FTS5 and dense candidate
stages *before* selection. The plan asked for this and it was right to.

**The return type stays a `dict`, against the plan's `list[SearchResult]`.**
That dict carries `hits`, `mode`, `timings`, `keyword_candidates`,
`dense_candidates` and `heading_precedence` — the explainability payload that
the dashboard, `eval/run_eval.py` and `eval/reachability.py` all read. Changing
it would break four consumers to satisfy a type signature, and the plan's own
precedence rule settles it: *the repository and its passing tests are
authoritative.*

The parameter names also stay as they are: `question`, not `query`.

Every call site that has no scope of its own now passes
`search.every_document_id()` explicitly. That is deliberate friction — when
authentication arrives, each of those is a line somebody changes on purpose,
rather than a default that quietly went on meaning "everything".
