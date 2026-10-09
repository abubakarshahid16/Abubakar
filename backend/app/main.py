import json
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from . import admin_explorer as explorer_mod
from . import chat as chat_mod
from . import classification as classification_mod
from . import chunker as chunk_mod
from . import absence as absence_mod
from . import ai_engineering_check as ai_engineering_check_mod
from . import applicability as applicability_mod
from . import comparison as comparison_mod
from . import crs_export as crs_export_mod
from . import crs_mapping as crs_mapping_mod
from . import crs_numbers as crs_numbers_mod
from . import datasheets as datasheets_mod
from . import disciplines as disciplines_mod
from . import extract as extract_mod
from . import ingest as ingest_mod
from . import job_queue as job_queue_mod
from . import review_jobs as review_jobs_mod
from . import document_refs, orphan_guard
from . import page_ledger as page_ledger_mod
from . import highlight as highlight_mod
from . import keyword as keyword_mod
from . import metrics as metrics_mod
from . import answer as answer_mod
from . import search as search_mod
from . import pageimage as pageimage_mod
from . import upload as upload_mod
from . import watcher as watcher_mod
from . import watch_api as watch_api_mod
from . import warmup as warmup_mod
from .api_utils import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    reject_unknown_params,
    require_document,
    retrievable_clause,
    validate_retrievable,
)
from . import access
from . import admin as admin_mod
from . import doc_router as doc_router_mod
from . import playbooks as playbooks_mod
from . import requirement_split as requirement_split_mod
from . import model_memory as model_memory_mod
from . import auth as auth_mod
from . import errors
from . import analysis as analysis_mod
from . import market as market_mod
from . import market_phrase as market_phrase_mod
from . import market_providers as market_providers_mod
from . import market_transport as market_transport_mod
from . import progress as progress_mod
from . import reports as reports_mod
from . import review as review_mod
from . import deliverables as deliverables_mod
from . import notifications as notifications_mod
from . import structured_search as structured_search_mod
from . import risks as risks_mod
from . import standards as standards_mod
from . import standards_inventory as standards_inventory_mod
from . import table_consistency as table_consistency_mod
from . import standards_acquisition as standards_acquisition_mod
from . import submittal_review as submittal_review_mod
from . import workbook as workbook_mod
from . import vector_store as vector_store_mod
from . import schemas
from .config import settings
from .db import connect, init_db


def _log_match_tier() -> None:
    """Say at boot whether the model tier of the matcher is running.

    `uvicorn.error` is the logger that prints "Application startup complete",
    so this lands in the stream the operator is already watching - the same
    reasoning as `auth.install`'s AUTH_MODE line.
    """
    import logging

    log = logging.getLogger("uvicorn.error")
    if settings.match_enabled:
        log.warning(
            "MATCH_ENABLED=true - the model tier of the requirement matcher is "
            "ON. It FAILED its hard gate on 2026-09-19 (six of seven pairings "
            "were false friends, three of them reported NON_COMPLIANT against "
            "the contractor). Every pairing it makes is labelled "
            "match_method=model and must be confirmed by an engineer.")
    else:
        log.info(
            "MATCH_ENABLED=false - requirement matching is deterministic "
            "containment only; the model tier is OFF pending redesign (see "
            "docs/design/model-assisted-matching.md section 10). Findings say "
            "so in their rationale.")


def _log_hooks_path() -> None:
    """Warn at boot when the git hooks are off (app.hooks_check). A log line,
    never a crash: a failing check must not stop the server."""
    import logging

    from . import hooks_check

    try:
        message = hooks_check.hooks_path_warning()
    except Exception:  # noqa: BLE001 - boot must not depend on git
        return
    if message:
        logging.getLogger("uvicorn.error").warning(message)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    init_db()
    # The ONLY wiring authentication needs. It hands access.py an identity
    # resolver and refuses to start on a weak secret when auth is required -
    # at startup rather than at first login, because a system that boots and
    # then rejects everyone looks like a broken deployment.
    auth_mod.install()
    keyword_mod.ensure_schema()
    # A keyword index written by older indexing code (trailing full stops
    # glued onto tokens - "MR0175." unsearchable) is rebuilt from `chunks`
    # here, once, before the worker starts. FTS only: nothing is re-chunked or
    # re-embedded. See keyword.INDEX_VERSION.
    _fts = keyword_mod.migrate_index()
    if _fts["rebuilt"] and _fts["documents"]:
        import logging as _logging

        _logging.getLogger("uvicorn.error").warning(
            "keyword index rebuilt to version %s (was %s): %d documents, "
            "%d chunks, %.1f s", _fts["version"], _fts["from_version"],
            _fts["documents"], _fts["chunks"], _fts["seconds"])
    review_mod.ensure_schema()
    deliverables_mod.ensure_schema()
    risks_mod.ensure_schema()
    submittal_review_mod.ensure_schema()
    # THE DISCIPLINE OVERLAY. `discipline_canonical` is derived from the raw
    # value at every write, so this backfill exists only for rows written
    # before the column did. It is idempotent - it recomputes from `discipline`
    # rather than from the previous canonical - and it never touches the raw
    # column, which is the document's own evidence.
    try:
        disciplines_mod.backfill()
    except Exception:  # noqa: BLE001 - an overlay that fails must not stop boot
        # Imported here, the way `_log_match_tier` above does it: this module
        # has no module-level `logging`, and the CI gate (F821) is what caught
        # the version of this line that assumed otherwise.
        import logging as _logging

        _logging.getLogger("uvicorn.error").exception(
            "discipline canonicalisation backfill failed")
    # A STRUCTURAL MIGRATION, ONCE, AT A MOMENT SOMEBODY CHOSE. It rebuilds
    # submittal_facts so `review_run_id` is nullable and facts are per
    # document. It used to sit inside `ensure_schema`, which every read path
    # calls - so a DROP/CREATE could fire mid-request, from any thread, and the
    # table's shape became a function of execution history. That produced
    # intermittent failures in unrelated tests, including the concurrency test,
    # because DDL on one SQLite connection blocks readers on the others.
    submittal_review_mod.migrate_facts_to_per_document()
    # Same reasoning, same place: a conditional rebuild belongs at startup and
    # never in a function every read path calls.
    submittal_review_mod.migrate_pair_rejections_to_stable_keys()
    # SAY WHICH MATCHER IS RUNNING, at boot, where the operator is already
    # looking. The tier being off changes what a review can find, and an
    # operator who does not know it is off reads "no pairing" as "the machine
    # looked and found nothing".
    _log_match_tier()
    # SAY WHEN THE GIT HOOKS ARE OFF (secret scan, live-checkout guard).
    _log_hooks_path()
    # A REVIEW RUN LEFT `running` BY A DEAD PROCESS IS FAILED, NOT BUSY. Same
    # reasoning as the extraction sweep below, and the same moment: this
    # process has just begun, so a run still marked running belongs to one
    # that is gone. Left alone it locks its submittal out of `POST
    # /api/reviews/run` forever, because that route refuses to start a second
    # run while one is going.
    try:
        submittal_review_mod.fail_orphaned_review_runs()
    except Exception as exc:  # noqa: BLE001 - a sweep that fails must not stop boot
        import logging as _logging
        _logging.getLogger("uvicorn.error").warning("the sweep for review runs left running by a dead process failed (%s); "
                          "such a run may still look busy", type(exc).__name__)
    # Put back any extraction that was `running` when a previous process died.
    # `next_extraction_job` only ever claims `queued` (or a `retrying` job
    # whose backoff is due, #177), so without this an
    # orphaned job is never picked up by anything - the standard is never
    # extracted and the status keeps reporting work in progress that no process
    # is doing. Before the worker starts, so a recovered job is in the queue by
    # the time the worker first looks at it.
    try:
        standards_mod.recover_stale_extraction_jobs()
        review_jobs_mod.recover_stale()
    except Exception as exc:  # noqa: BLE001 - a sweep that fails must not stop boot
        import logging as _logging
        _logging.getLogger("uvicorn.error").warning("the recovery of stale extraction and review jobs failed (%s); "
                          "such a job may stay queued", type(exc).__name__)
    # THE DENSE-SEARCH INDEX: say which backend is active (sqlite-vec, or the
    # exact numpy fallback and why), and backfill/sync the vec0 index from
    # chunk_vectors before the first question pays for it. Never raises.
    vector_store_mod.startup()
    # Drain the upload queue. Without this a document sits at 'queued'
    # forever while the API reports a job id that means nothing.
    ingest_mod.start_worker()
    # Automatic risk detection, off the request path (#478). No-op in tests.
    risks_mod.start_background_detection()
    # The watched folder is OFF unless WATCH_FOLDER is set in backend/.env.
    # start_watcher() returns a reason string rather than raising when it does
    # not start, so a machine with no drop folder boots exactly as before.
    watcher_mod.start_watcher()
    # WARM THE FIRST QUESTION'S COSTS IN THE BACKGROUND: the embedder and
    # reranker sessions and the acronym maps. This used to be
    # `acronyms_mod.harvest()` inline, which raised TypeError (the scope
    # argument is required) inside `except Exception: pass`, so nothing was
    # ever warmed and nothing said so. `warmup` runs in a daemon thread, never
    # blocks this start, never writes the database, and logs any failure.
    warmup_mod.start()
    yield
    risks_mod.stop_background_detection()
    watcher_mod.stop_watcher()
    ingest_mod.stop_worker()


app = FastAPI(
    title="RAG Intelligence System",
    version="0.1.0",
    lifespan=lifespan,
    # A trailing slash previously resolved to the same route via a redirect,
    # so /api/documents/ answered 200. Two spellings of one resource is a
    # contract ambiguity a generated client can trip over.
    redirect_slashes=False,
)


@app.exception_handler(orphan_guard.OrphaningRefused)
async def _orphaning_refused(_request: Request, exc: orphan_guard.OrphaningRefused):
    """B38: ONE answer for all four deleting paths. 409 - the request is
    valid, but it conflicts with the findings that cite what it would delete.
    The count is in the message; the attempt is already in audit_events."""
    return JSONResponse(status_code=409, content={"detail": errors.safe_error(
        errors.ORPHANING_REFUSED, str(exc), document_id=exc.document_id)})

# Vite dev server only. No wildcard - this API serves document content.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# The watched-folder status route lives in its own module so this file stays
# the only place routing is declared, without this file growing a feature.
app.include_router(watch_api_mod.router)

# THE CLAUDE LANE (#222, revived by owner decision 2026-09-25). Every route is
# gated on the reader's two egress flags and answers 409 model_disabled when
# they are off; nothing leaves the machine from here unless both are true.
from . import claude_api as claude_api_mod  # noqa: E402

app.include_router(claude_api_mod.router)


#: The interactive API description. A map of every route, every parameter and
#: every error code - useful on a developer's machine, reconnaissance anywhere
#: else. `docs_url` is fixed when FastAPI() is built, and the auth mode can be
#: changed afterwards (the tests do), so this is decided per request.
_API_DOC_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})


def _api_docs_served() -> bool:
    return settings.auth_mode == access.AUTH_DISABLED or settings.api_docs_enabled


@app.middleware("http")
async def api_docs_gate(request: Request, call_next):
    """404 for /docs, /redoc and /openapi.json unless `_api_docs_served()`.

    The same 404 an unknown route gets, so the answer does not say the
    description exists. `app.openapi()` in-process is unaffected."""
    if request.url.path in _API_DOC_PATHS and not _api_docs_served():
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    return await call_next(request)


#: Routes that expose corpus-derived content (r2 S7). Under any mode but
#: `disabled` a request that names no identity gets 401 here - it used to get
#: 200 and an empty or unscoped answer (vocabulary, templates and baseline rules
#: were not scoped at all). A PREFIX, so a route added under it later is
#: covered without anyone remembering. NOT in this list on purpose:
#: `/api/health` (public), `/api/auth/*` (the login screen calls
#: `/api/auth/me` before it has a token) and `/api/watch/status` (no corpus
#: content: a flag, and a folder name for an admin only).
_IDENTITY_REQUIRED_PREFIXES = (
    "/api/reviews", "/api/classification", "/api/metrics",
    "/api/management/report", "/api/market/search",
)


@app.middleware("http")
async def identity_gate(request: Request, call_next):
    from starlette.concurrency import run_in_threadpool

    path = request.url.path
    if (settings.auth_mode != access.AUTH_DISABLED
            and request.method != "OPTIONS"
            and any(path == p or path.startswith(p + "/") for p in _IDENTITY_REQUIRED_PREFIXES)
            and not await run_in_threadpool(access.request_identity, request)):
        return JSONResponse(status_code=401, content={"detail": errors.safe_error(
            errors.UNAUTHENTICATED, "sign in to continue")})
    return await call_next(request)


@app.middleware("http")
async def trusted_host_gate(request: Request, call_next):
    """Refuse any Host header this server was not configured to answer to.

    DNS REBINDING (audit 2026-09-30): a page on a hostile domain re-points its
    own name at 127.0.0.1 and reads this API as same-origin, so CORS never
    applies - and under AUTH_MODE=disabled every document is served. The
    browser still sends the hostile name in `Host`, which is what this checks.
    The set is read per request (`config.trusted_host_names`), so a test can
    change it and the Vite dev proxy - which forwards the browser's own
    `127.0.0.1:5173` / `localhost:5173` - passes unchanged.

    Registered AFTER `api_docs_gate`, so Starlette runs it FIRST.
    """
    from .config import host_header_name, trusted_host_names

    if host_header_name(request.headers.get("host", "")) not in trusted_host_names(settings):
        return JSONResponse(status_code=400, content={"detail": errors.safe_error(
            errors.INVALID_PARAMETER, "this server does not answer to that host name")})
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Minimal hardening. The server banner is noise an attacker does not need."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if "server" in response.headers:
        del response.headers["server"]
    return response


# ------------------------------------------------------------------ health


@app.get("/api/health", response_model=schemas.Health)
def health():
    """Readiness, and NOTHING ELSE. This is the one unauthenticated route.

    It answers two questions: is the service up, and are the models present.
    Everything it used to carry belonged to somebody - it returned document
    counts, the exact answer-model name and version, free-text last_error and
    stalled_reasons, and current_document, which is a real document id. The UI
    joins that id against the document list to show a filename, so an
    unauthenticated caller learned that a specific document existed and was
    being processed. That is a privacy-boundary problem, not a cosmetic one.

    The full worker status still exists, on /api/metrics, which is scoped.
    THAT SENTENCE WAS FALSE WHEN IT WAS WRITTEN and is true only as of the
    commit that added this note: /api/metrics resolved an access scope and
    discarded it, so `current_document` and `last_error` moved from one
    unscoped route to another. Scoping now happens in `metrics.snapshot`, and
    `_scoped_worker` is what makes this paragraph's claim real.
    `alive` and `stalled` stay here because a client that cannot reach the
    backend has to distinguish "down" from "up but stuck", and neither is
    about anybody's documents.
    """
    worker = ingest_mod.get_worker().status()
    return {
        "ok": True,
        "embed_model_present": (settings.embed_model_dir / "tokenizer.json").exists(),
        # Whether an answer model is CONFIGURED, not which one. The exact name
        # and version is fingerprinting material and is on /api/metrics,
        # which is scoped to the caller's grants as of the commit that
        # added this note - it was not when the field was moved there.
        "answer_model_configured": bool(settings.answer_model),
        "ingestion": {
            "alive": worker["alive"],
            "stalled": worker["stalled"],
            # WHETHER work is happening, never WHICH document. The badge
            # needs this to avoid alarming during a healthy long ingest -
            # `stalled` goes true when nothing has COMPLETED for a while,
            # which is normal mid-embed on a 1,400-page document. A boolean
            # says work is under way; an id would say whose.
            "busy": worker["current_document"] is not None,
        },
    }


@app.get("/api/metrics", response_model=schemas.Metrics, responses=schemas.ERRORS_422)
def metrics(request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Everything the dashboard shows, restricted to what the caller may read.

    A value that has not been measured is null rather than zero, and the
    screen is required to say so. Throughput comes from stage runs actually
    recorded; retrieval latency comes from questions actually asked.

    THIS ROUTE TOOK `scope` AND DISCARDED IT. Resolved on every request and
    never passed on, so the corpus block was byte-identical for an admin, a
    Civil Engineering user with four grants, and a user granted nothing at all
    - measured, all three reporting 12 documents while /api/documents correctly
    returned 6, 4 and 0. Five comments elsewhere in this codebase described
    this endpoint as "the scoped /api/metrics", and that belief is why fields
    were moved here off /api/health.

    ADMIN SEES CORPUS-WIDE FIGURES, AND THAT IS A NEW CAPABILITY. The document
    routes build an administrator's scope from grants like anyone else's
    (`access.scope_for_user`) - an IT+admin user sees exactly the six documents
    IT sees - so this is not an existing power being surfaced. (The ONE
    deliberate exception is the read-only database explorer below, which reads
    every table by owner decision 2026-10-07: "admin can read everything".) It
    is deliberately narrow: aggregate counts only, never document content, and
    `corpus_wide` travels in the payload so the screen can say which kind of
    number it is showing. An admin reading counts for documents they cannot
    open is only defensible if the screen says so out loud.
    """
    reject_unknown_params(request, set())
    # Corpus-wide aggregate counts are a deliberate administrator capability;
    # host telemetry is narrower and must never be admitted merely because the
    # auth mode treats an anonymous caller as unrestricted for document reads.
    # AccessScope already resolved the capability set for this request, so this
    # is both the stronger predicate and the cheaper one.
    corpus_wide = scope.unrestricted or scope.is_admin
    allowed = None if corpus_wide else sorted(scope.allowed_document_ids)
    # The machine's own specifications go to an administrator only (#77). Not
    # a document, so the corpus scoping could never have removed them; and the
    # same flag governs whether the low-memory warning may state free RAM,
    # because gating the block while the prose restates the figure would move
    # the leak rather than close it.
    # `AccessScope.is_admin` intentionally treats AUTH_MODE=disabled as an
    # unrestricted development read scope. Host telemetry is not a document
    # read, so use the actual capability set here and keep the two boundaries
    # separate.
    return metrics_mod.snapshot(
        ingest_mod.get_worker().status(), allowed, corpus_wide,
        "admin" in scope.capabilities)


# --------------------------------------------------------------- documents


@app.get("/api/documents/upload-disciplines", response_model=schemas.UploadDisciplines,
         responses={**schemas.ERRORS_401})
def upload_disciplines(scope: access.AccessScope = Depends(access.current_scope)):
    """The disciplines this caller may make an upload visible to (#609), and
    the default: their own. Empty and not required with authentication off."""
    if scope.user_id is None:
        _require_identity_to_write(scope)
        return {"required": False, "choices": [], "default": []}
    return {"required": True, **access.upload_discipline_choices(scope.user_id)}


@app.post("/api/documents", response_model=schemas.UploadAccepted,
          responses={**schemas.ERRORS_400, **schemas.ERRORS_401, **schemas.ERRORS_422})
async def upload_document(
    file: UploadFile = File(...),
    disciplines: list[str] | None = Form(None),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Accept an identified upload, visible to the disciplines it names (#609).

    With an identity, at least one discipline is required and is checked
    BEFORE the bytes are stored, so no document is left visible to nobody.
    With authentication off every caller reads every document and grants
    decide nothing, so none are asked for or written."""
    _require_identity_to_write(scope)
    admin_role: str | None = None
    discipline_roles: list[str] = []
    if scope.user_id is not None:
        try:
            admin_role, _uploader_is_admin = access.upload_admin_role(scope.user_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        try:
            discipline_roles = access.resolve_upload_disciplines(scope.user_id, disciplines)
        except access.UploadDisciplineRefused as exc:
            raise HTTPException(status_code=422, detail=errors.safe_error(
                errors.INVALID_PARAMETER, str(exc))) from exc
    try:
        row, job_id, duplicate_of = upload_mod.ingest(file.file, file.filename or "")
    except upload_mod.UploadError as e:
        return JSONResponse(
            status_code=400,
            content={"code": e.code, "message": e.message, "detail": e.detail},
        )
    if duplicate_of is None and admin_role is not None and scope.user_id is not None:
        access.grant_uploaded_document_to_admin(row["id"], admin_role, scope.user_id)
        access.grant_uploaded_document_to_disciplines(
            row["id"], discipline_roles, scope.user_id)
    elif duplicate_of is not None and not scope.may_read(duplicate_of):
        return {"document": None, "job_id": "", "duplicate_of": None,
                "awaiting_grant": True}
    # A new upload is readable by its uploader at once: an engineer may only
    # choose their own disciplines, and an administrator holds every document.
    return {
        "document": upload_mod.to_api(row),
        "job_id": job_id or "",
        "duplicate_of": duplicate_of,
        "awaiting_grant": False,
    }


@app.get("/api/documents", response_model=list[schemas.Document],
         responses=schemas.ERRORS_422)
def list_documents(request: Request, response: Response,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    sort: str = Query("uploaded_at"),
    direction: str = Query("desc"),
    q: str | None = Query(None, max_length=200),
    status: str | None = Query(None),
    document_role: list[str] | None = Query(None),
    discipline: list[str] | None = Query(None),
    equipment_type: list[str] | None = Query(None),
    project: list[str] | None = Query(None),
    scope: access.AccessScope = Depends(access.current_scope),
):
    reject_unknown_params(request, {"limit", "offset", "sort", "direction", "q",
                                    "status", "document_role", "discipline",
                                    "equipment_type", "project"})
    sort_columns = {"uploaded_at": "uploaded_at", "filename": "filename",
                    "status": "status", "size_bytes": "size_bytes"}
    if sort not in sort_columns:
        raise HTTPException(status_code=422, detail=errors.safe_error(
            errors.INVALID_PARAMETER, "sort must be one of: uploaded_at, filename, status, size_bytes"))
    if direction not in {"asc", "desc"}:
        raise HTTPException(status_code=422, detail=errors.safe_error(
            errors.INVALID_PARAMETER, "direction must be asc or desc"))
    if status is not None and status not in schemas.DocStatus.__args__:
        raise HTTPException(status_code=422, detail=errors.safe_error(
            errors.INVALID_PARAMETER, "unknown document status"))
    for role in document_role or ():
        # Refused at the boundary, like every other vocabulary on this route.
        # An unknown role would otherwise match nothing and read to the user as
        # "there are no contractor submittals" rather than "that is not a role".
        if role not in schemas.DocumentRole.__args__:
            raise HTTPException(status_code=422, detail=errors.safe_error(
                errors.INVALID_PARAMETER, "unknown document role"))
    # THE METADATA FILTER, AND THE ONE PLACE IT IS APPLIED.
    #
    # It goes through `classification.restrict`, which intersects the matched
    # ids with the scope and returns a NARROWER scope - never an id set
    # assembled here. Two consequences that are the whole point:
    #   * a filter can only ever shrink what this route may see, so no
    #     combination of query parameters can reveal a document the caller
    #     holds no grant for (mutation M11 flips the & to a | and this route's
    #     permission tests fail);
    #   * a filter that matches NOTHING yields an empty scope rather than
    #     falling back to the corpus, because the caller asked for a role and
    #     an empty answer is the honest one (mutation M14).
    wanted = classification_mod.ScopeFilter(
        disciplines=tuple(discipline or ()),
        roles=tuple(document_role or ()),
        equipment_types=tuple(equipment_type or ()),
        projects=tuple(project or ()),
    )
    scope, metadata_filtered = classification_mod.restrict(scope, wanted)
    conn = connect()
    # Filtered IN THE QUERY, not after it. Selecting every document and
    # dropping the unauthorised ones in Python would work here because there is
    # no LIMIT - but it is the same shape as the retrieval defect fixed in the
    # previous commit, and the next person to add pagination to this route
    # would silently turn it into that bug. The scope belongs in the WHERE
    # clause on principle, not because this particular query needs it.
    allowed = sorted(scope.allowed_document_ids)
    # `unrestricted` means "grants do not narrow this caller"; it does NOT mean
    # "ignore the id set". A metadata filter narrows an unrestricted scope's
    # id set while carrying `unrestricted` through untouched (see
    # classification.restrict), so skipping the IN clause on `unrestricted`
    # alone would apply the filter for ordinary users and silently drop it for
    # an administrator - the filter working everywhere except where it is least
    # likely to be noticed.
    enumerate_ids = metadata_filtered or not scope.unrestricted
    if enumerate_ids and not allowed:
        response.headers["X-Total-Count"] = "0"
        response.headers["X-Limit"] = str(limit)
        response.headers["X-Offset"] = str(offset)
        return []
    if not enumerate_ids:
        where: list[str] = []
        params: list[object] = []
    else:
        marks = ",".join("?" * len(allowed))
        where = [f"id IN ({marks})"]
        params = list(allowed)
    if q:
        where.append("LOWER(filename) LIKE ?")
        params.append(f"%{q.strip().lower()}%")
    if status:
        where.append("status = ?")
        params.append(status)
    where_sql = " AND ".join(where) or "1 = 1"
    total = conn.execute(f"SELECT COUNT(*) FROM documents WHERE {where_sql}", params).fetchone()[0]
    order = f"{sort_columns[sort]} {'ASC' if direction == 'asc' else 'DESC'}"
    rows = conn.execute(
        f"SELECT * FROM documents WHERE {where_sql} ORDER BY {order}, id LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    # Excluded PAGES carried on the list, so the card can warn without a
    # second request. The Documents screen said "3 excluded" for chunks and
    # said nothing at all about a dropped page that held an entire clause.
    dropped = {
        r["document_id"]: dict(r)
        for r in conn.execute(
            """SELECT document_id,
                      COUNT(*) AS pages_excluded,
                      COALESCE(SUM(text_length), 0) AS characters_dropped,
                      COALESCE(SUM(clause_headings), 0) AS pages_with_clause_headings
               FROM exclusions WHERE scope = 'page' GROUP BY document_id"""
        )
    }
    # The submittal-review columns the Documents page shows, and the REVIEW
    # STATUS, which is derived from review_runs rather than stored (see
    # schemas.ReviewStatus). Fetched for this page of rows only - a join would
    # be fine here too, but the review tables are owned by another module and
    # this keeps the authority for "has it been reviewed" in that module.
    page_ids = [row["id"] for row in rows]
    review_status = submittal_review_mod.review_status_for(
        page_ids, allowed_document_ids=frozenset(page_ids))
    metadata = {}
    if page_ids:
        marks = ",".join("?" * len(page_ids))
        metadata = {
            r["document_id"]: dict(r)
            for r in conn.execute(
                f"""SELECT document_id, document_role, document_number, title,
                           revision, equipment_type, project, discipline,
                           superseded_by
                    FROM document_classification
                    WHERE document_id IN ({marks})""", page_ids)
        }
    # THE FULL CLASSIFICATION, ON THE LIST. The Documents page used to ask
    # `GET /documents/{id}/classification` once per document (about 100
    # requests on every load). The ids here are exactly the rows this caller's
    # scope already selected above, so nothing is added to what they may read.
    # A document with no classification row gets the same empty record the
    # single route returns.
    classifications = classification_mod.of_documents(page_ids)
    out = []
    for row in rows:
        doc = upload_mod.to_api(row)
        doc["classification"] = {
            **(classifications.get(row["id"]) or classification_mod.empty_record(row["id"])),
            "document_id": row["id"]}
        meta = metadata.get(row["id"], {})
        for field in ("document_role", "document_number", "title", "revision",
                      "equipment_type", "project", "superseded_by"):
            # Null renders as nothing. Absent metadata and a null column are
            # the same answer - not recorded - and neither becomes a default.
            doc[field] = meta.get(field)
        doc["review_status"] = review_status.get(row["id"], "not_reviewed")
        info = dropped.get(row["id"], {})
        doc["pages_excluded"] = info.get("pages_excluded", 0)
        doc["pages_excluded_characters"] = info.get("characters_dropped", 0)
        doc["pages_excluded_with_clause_headings"] = info.get(
            "pages_with_clause_headings", 0
        )
        out.append(doc)
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Limit"] = str(limit)
    response.headers["X-Offset"] = str(offset)
    return out


@app.delete("/api/documents/{document_id}", response_model=schemas.DeletedDocument,
            responses={**schemas.ERRORS_400, **schemas.ERRORS_404, **schemas.ERRORS_422})
def delete_document(document_id: str, request: Request, confirm: bool = Query(False),
    acknowledge_orphaned_findings: bool = Query(False),
    scope: access.AccessScope = Depends(access.current_scope),
    _admin: dict | None = Depends(admin_mod.current_admin),
):
    """Remove a document and everything derived from it.

    ADMIN ONLY (r2 S1): a READ grant lets a caller see a document, not destroy
    it. A non-admin gets the admin surface's silent 404.

    Requires confirm=true - a destructive endpoint should not fire on a
    mistyped URL. Removes chunks, pages, vectors, exclusions, jobs, cached
    page images and the stored PDF.

    B38: deleting a STANDARD cascades into its requirement rows. If review
    findings cite them, the attempt is recorded and refused (409) unless
    acknowledge_orphaned_findings=true.

    Deleting a SUBMITTAL (a contractor's datasheet) cascades directly over
    `review_findings.document_id ... ON DELETE CASCADE` (review.py) - every
    CRS finding ever recorded against it. Same guard, same flag, checked
    over that column instead of `standard_requirements`.
    """
    reject_unknown_params(request, {"confirm", "acknowledge_orphaned_findings"})
    doc = require_document(document_id, scope)
    if not confirm:
        return JSONResponse(
            status_code=400,
            content={"detail": errors.safe_error(
                errors.CONFIRM_REQUIRED,
                "pass confirm=true to delete; this cannot be undone",
                document_id=document_id,
            )} | {"filename": doc["filename"], "retrievable_chunks": doc["chunk_count"]},
        )

    # B38, BEFORE anything is removed: a refusal must leave the document whole.
    orphan_guard.check(
        "document_delete", requirement_where="standard_document_id = ?",
        params=(document_id,), document_id=document_id,
        acknowledge=acknowledge_orphaned_findings,
        actor={"id": scope.user_id} if scope.user_id else None)
    # Same guard, the SUBMITTAL side: review_findings.document_id cascades
    # directly, not through standard_requirements - see orphan_guard.py.
    orphan_guard.check_submittal_delete(
        "submittal_delete", document_id=document_id,
        acknowledge=acknowledge_orphaned_findings,
        actor={"id": scope.user_id} if scope.user_id else None)

    # Reports quote this document. Their FILES go; their ROWS stay, because
    # the record that a report was issued must survive the document.
    reports_mod.on_document_deleted(document_id)

    conn = connect()
    removed = {}
    with conn:
        conn.execute("DELETE FROM chunks_fts WHERE document_id = ?", (document_id,))
        for table in ("chunk_vectors", "exclusions", "chunks", "pages", "jobs"):
            cur = conn.execute(f"DELETE FROM {table} WHERE document_id = ?", (document_id,))
            removed[table] = cur.rowcount
        cur = conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        removed["documents"] = cur.rowcount
        # The record of the delete commits with the delete (ids and counts only).
        document_refs.record_document_deleted(
            conn, document_id, removed,
            actor={"id": scope.user_id, "email": (_admin or {}).get("email")}
            if scope.user_id else None)

    files_removed = 0
    stored = Path(doc["stored_path"])
    if stored.exists():
        stored.unlink()
        files_removed += 1
    cache = settings.data_dir / "page_images"
    if cache.exists():
        for img in cache.glob(f"{doc['sha256'][:16]}_*.png"):
            img.unlink()
            files_removed += 1

    return {
        "deleted": document_id,
        "filename": doc["filename"],
        "rows_removed": removed,
        "files_removed": files_removed,
    }


@app.get("/api/documents/{document_id}", response_model=schemas.Document,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def get_document(document_id: str, request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    reject_unknown_params(request, set())
    require_document(document_id, scope)
    row = connect().execute(
        "SELECT * FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    return upload_mod.to_api(row)


# ------------------------------------------------------------- processing


@app.post("/api/documents/{document_id}/extract", response_model=schemas.ExtractResult,
          responses=schemas.ERRORS_404)
def extract(document_id: str,
    scope: access.AccessScope = Depends(access.current_scope),
    _admin: dict | None = Depends(admin_mod.current_admin),
):
    """Extract pages in batches. Resumes from the last completed batch."""
    require_document(document_id, scope)
    return extract_mod.extract_document(document_id)


@app.post("/api/documents/{document_id}/chunk", response_model=schemas.ChunkResult,
          responses=schemas.ERRORS_404)
def chunk(document_id: str, force: bool = Query(False),
    acknowledge_orphaned_findings: bool = Query(False),
    scope: access.AccessScope = Depends(access.current_scope),
    _admin: dict | None = Depends(admin_mod.current_admin),
):
    """Chunk an extracted document.

    Short-circuits when the document already has chunks and its content has
    not changed, matching how /extract resumes rather than redoing work.
    Pass force=true to rebuild. B38: a rebuild that would cascade away
    requirement rows review findings cite is refused (409) unless
    acknowledge_orphaned_findings=true.
    """
    require_document(document_id, scope)
    return chunk_mod.chunk_document(
        document_id, force=force,
        acknowledge_orphaned_findings=acknowledge_orphaned_findings)


@app.post("/api/documents/{document_id}/embed", response_model=schemas.EmbedResult,
          responses=schemas.ERRORS_404)
def embed(document_id: str,
    scope: access.AccessScope = Depends(access.current_scope),
    _admin: dict | None = Depends(admin_mod.current_admin),
):
    """Embed any retrievable chunks that do not yet have a vector."""
    require_document(document_id, scope)
    worker = ingest_mod.get_worker()
    embedded = worker.embed_pending(document_id)
    worker._finish_if_embedded(document_id)
    row = connect().execute(
        "SELECT chunk_count, embedded_count, status, indexed_at FROM documents WHERE id = ?",
        (document_id,),
    ).fetchone()
    return {
        "document_id": document_id,
        "embedded_this_run": embedded,
        "embedded_count": row["embedded_count"],
        "chunk_count": row["chunk_count"],
        "status": row["status"],
        "indexed_at": row["indexed_at"],
    }


@app.post("/api/documents/{document_id}/index-keyword",
          response_model=schemas.KeywordIndexResult, responses=schemas.ERRORS_404)
def index_keyword(document_id: str,
    scope: access.AccessScope = Depends(access.current_scope),
    _admin: dict | None = Depends(admin_mod.current_admin),
):
    """Build the keyword index for one document. Needs no vectors."""
    require_document(document_id, scope)
    return keyword_mod.index_document(document_id)


@app.get("/api/search", response_model=schemas.SearchResult,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def search(
    request: Request,
    q: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(10, ge=1, le=MAX_LIMIT),
    document_id: str | None = Query(None),
    rerank: bool = Query(True),
    mode: str = Query("hybrid"),
    types: list[str] = Query(default_factory=list),
    disciplines: list[str] = Query(default_factory=list),
    subject_ids: list[str] = Query(default_factory=list),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Hybrid retrieval: FTS5 + dense vectors fused with RRF, then reranked.

    Works keyword-only before any embedding exists and upgrades to hybrid
    automatically as vectors arrive - `mode` in the response says which was
    actually used, rather than the caller having to guess.

    THE CLASSIFICATION FILTER IS OPTIONAL AND MAY ONLY NARROW. Absent, this
    behaves byte for byte as it did before classification existed. Present,
    the caller's scope is intersected with the matching documents BEFORE
    retrieval runs, so a filter naming a subject whose documents they may not
    read yields nothing rather than a leak.

    REPEATABLE QUERY PARAMS rather than a `scope` object, and this is the one
    place the shape differs from the analysis routes. `/api/search` is a GET
    with no request body to put an object in; encoding one into a query
    string would mean the frontend building JSON into a URL, which is a
    source of encoding bugs and unreadable logs. `?subject_ids=a&subject_ids=b`
    is the idiomatic form and stays cacheable.
    """
    reject_unknown_params(request, {"q", "limit", "document_id", "rerank",
                                    "mode", "types", "disciplines",
                                    "subject_ids"})
    if document_id:
        require_document(document_id, scope)
    if mode not in ("hybrid", "keyword"):
        return JSONResponse(
            status_code=422,
            content={"detail": errors.safe_error(
                errors.INVALID_PARAMETER, "mode must be hybrid or keyword")},
        )
    wanted = _scope_filter(types, disciplines, subject_ids)
    narrowed, applied = classification_mod.restrict(scope, wanted)
    result = search_mod.search(
        q,
        limit=limit,
        document_id=document_id,
        rerank=rerank,
        dense=(mode == "hybrid"),
        # THE INTERSECTION, and the only id set that reaches retrieval.
        allowed_document_ids=narrowed.allowed_document_ids,
    )
    return {**result, "applied_scope": _applied(wanted, applied, narrowed)}


@app.get("/api/answer", response_model=schemas.AnswerResult,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def get_answer(
    request: Request,
    q: str = Query(..., min_length=1, max_length=500),
    tier: str = Query("extract"),
    document_id: str | None = Query(None),
    # None = settings.answer_top_k, the one top-k (answer.gate_candidates).
    limit: int | None = Query(None, ge=1, le=5),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Answer a question against the indexed documents.

    tier=extract   (default) the top passage verbatim, no model involved
    tier=generated             up to 3 passages summarised by the local model
                               (CLAUDE_CONTEXT_PASSAGES on the Claude lane)

    The response always carries answer_type, so a quotation and generated
    prose can never be confused.
    """
    reject_unknown_params(request, {"q", "tier", "document_id", "limit"})
    if document_id:
        require_document(document_id, scope)
    if tier not in ("extract", "generated"):
        return JSONResponse(
            status_code=422,
            content={"detail": errors.safe_error(
                errors.INVALID_PARAMETER, "tier must be extract or generated")},
        )
    return answer_mod.answer(
        q, tier=tier, document_id=document_id, limit=limit,
        allowed_document_ids=scope.allowed_document_ids,
    )


# ---------------------------------------------------------- conversations


def _require_owned_conversation(conversation_id: str, scope: access.AccessScope) -> dict:
    """The conversation, if it exists AND the caller owns it. Otherwise 404.

    THE PREDECESSOR ASKED ONLY "DOES THIS ROW EXIST" (#81). With no token at
    all, GET /api/conversations returned 200 and 80 conversations; GET on one of
    them returned 13,491 bytes including the cited passage text verbatim -
    corpus content, reaching a caller for whom /api/documents correctly
    returned [] in the same second. The document was unreachable by every
    scoped route and readable through conversation history.

    Same rule as `require_document`: a conversation the caller may not read is
    collapsed into the identical not-found path, so it is INDISTINGUISHABLE
    from one that never existed. A 403 would confirm the conversation is real,
    which is the fact ownership was protecting. And nothing of the hidden row -
    not its title - reaches the refusal.

    WHO OWNS WHAT is decided in exactly one place, `AccessScope.owns_conversation`
    - not here, not per route. The 81 legacy rows with owner NULL are assigned
    to the admin capability and denied to ordinary users (plan line 1017); an
    unidentified caller owns nothing. The unrestricted scope (auth off) sees
    everything, as it always did; that is what keeps the pre-existing suite
    meaning what it means.
    """
    row: dict | None
    try:
        row = chat_mod.get_conversation(conversation_id)
    except chat_mod.ConversationNotFound:
        row = None
    if row is not None and not scope.owns_conversation(row.get("owner_user_id")):
        row = None          # fall through to the identical not-found path
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=errors.safe_error(errors.NOT_FOUND, "no conversation with that id"),
        )
    return row


def _require_identity_to_write(scope: access.AccessScope) -> None:
    """A conversation nobody owns is one nobody can ever read again.

    Under `demo_required` a caller with no identity resolves to an empty scope,
    and every READ correctly returns nothing. A WRITE that succeeded would
    manufacture an orphan - the same shape as #79 on uploads - so it is refused
    with the same 401 /api/auth/me gives, rather than accepted into a void.
    """
    if scope.unrestricted or scope.user_id:
        return
    raise HTTPException(
        status_code=401,
        detail=errors.safe_error(errors.UNAUTHENTICATED, "sign in to continue"),
    )


def _actor_from_scope(scope: access.AccessScope) -> dict | None:
    """Who to name in the audit trail for an ENGINEER'S action.

    `admin.current_admin` is the wrong dependency for these: it is a GATE as
    well as a lookup, and a non-admin gets its deliberately silent 404. That
    is right for the admin surface and wrong for an engineer's own work - it
    made recording a final review code (section 15, an engineer's action)
    impossible for anyone but an admin, and said "not found" while doing it.
    This resolves the name without deciding anything about permission; the
    route's own scope has already done that.
    """
    if not scope.user_id:
        return None
    row = connect().execute("SELECT id, email FROM users WHERE id = ?",
                            (scope.user_id,)).fetchone()
    return dict(row) if row else {"id": scope.user_id}


# ------------------------------------------------------------------- auth
#
# Two routes, and `access.current_scope` changes by zero lines: it already
# calls the resolver, already falls to empty_scope() without one, and already
# derives the scope from the grant tables. Authentication supplies WHO;
# authorisation was already deciding WHAT.


@app.post("/api/auth/login", response_model=schemas.LoginResult,
          responses={**schemas.ERRORS_422})
def login(body: schemas.LoginRequest, request: Request):
    """Exchange credentials for a bearer token.

    Unauthenticated by construction - it is how a caller becomes
    authenticated. It is also the only unauthenticated WRITER in the API, and
    it writes exactly one row (`last_login_at`) on success plus an audit row,
    which is why the rate limiter is in memory rather than a table.
    """
    try:
        # The client host bounds the Argon2 work. Without it the only budget
        # was keyed on the email in the body, which the caller picks per
        # request - so a fresh address each time met an empty bucket and every
        # request paid a 64 MiB verify. `request.client` is None for some
        # transports (a raw ASGI test call), and None simply means the email
        # bucket alone applies.
        client_host = request.client.host if request.client else None
        return auth_mod.login(body.email, body.password,
                              client_host=client_host)
    except auth_mod.AuthError as exc:
        headers = ({"Retry-After": str(exc.retry_after)}
                   if exc.retry_after else None)
        raise HTTPException(
            status_code=429 if exc.code == errors.RATE_LIMITED else 401,
            detail=errors.safe_error(exc.code, exc.message),
            headers=headers,
        )


@app.post("/api/auth/password/reset", response_model=schemas.PasswordResetResult,
          responses={**schemas.ERRORS_401, **schemas.ERRORS_422})
def reset_password(body: schemas.PasswordResetRequest):
    """Redeem a shown-once setup/reset token for a new password."""
    try:
        return admin_mod.redeem_password_token(body.token, body.password)
    except auth_mod.AuthError as exc:
        raise HTTPException(
            status_code=422 if exc.code == errors.WEAK_PASSWORD else 401,
            detail=errors.safe_error(exc.code, exc.message),
        )


@app.get("/api/auth/me", response_model=schemas.AuthStatus,
         responses={**schemas.ERRORS_401})
def me(request: Request,
       scope: access.AccessScope = Depends(access.current_scope)):
    """Who the caller is, and whether signing in is required at all.

    The frontend calls this once at startup, and the ANSWER decides the
    screen: 401 means show the login form, `required: false` means
    authentication is off and there is nothing to sign in to.

    Under `disabled` this is 200 with no user. Telling an anonymous caller
    that authentication is off is not a leak, because under `disabled` that
    same caller can already read every document; showing them a login form
    they cannot use would be the actual defect.
    """
    if settings.auth_mode == access.AUTH_DISABLED:
        return {"required": False, "user": None}

    user_id = scope.user_id or auth_mod.resolve_user_id(request)
    described = auth_mod.describe(user_id) if user_id else None
    if described is None:
        raise HTTPException(
            status_code=401,
            detail=errors.safe_error(errors.UNAUTHENTICATED,
                                     "sign in to continue"),
        )
    return {"required": True, "user": described}


@app.post("/api/auth/revoke/{user_id}", response_model=schemas.TokenRevocationResult,
          responses={**schemas.ERRORS_404})
def revoke_user_tokens(user_id: str,
                       _actor: dict | None = Depends(admin_mod.current_admin)):
    """Invalidate every currently issued token for a user.

    Only administrators can force a logout. The token epoch is incremented
    atomically, so existing bearer tokens fail on their next request while a
    subsequent login receives the new epoch.
    """
    if not auth_mod.revoke_user_tokens(user_id):
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no such user"))
    return {"user_id": user_id, "revoked": True}


@app.get("/api/progress/{progress_id}", response_model=schemas.Progress,
         responses={**schemas.ERRORS_401, **schemas.ERRORS_404})
def read_progress(progress_id: str,
                  scope: access.AccessScope = Depends(access.current_scope)):
    """What the machine is doing, as reported by the work itself.

    P5: AUTHENTICATED, AND ONLY TO THE ONE WHO ASKED. It carries no document
    content, but it did say to anyone at all what another user was doing and
    when; now an entry is read back only by the identity that started it (a
    stranger gets the same 404 as an unknown id), and with sign-in required
    an anonymous caller gets 401 - the same rule as every other route.
    """
    if not scope.unrestricted and not scope.user_id:
        raise HTTPException(status_code=401, detail=errors.safe_error(
            errors.UNAUTHENTICATED, "sign in to continue"))
    state = progress_mod.read(progress_id, reader=scope.user_id,
                              unrestricted=scope.unrestricted)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=errors.safe_error(errors.NOT_FOUND, "no such request"),
        )
    return state


# ---------------------------------------------------------------- analysis
#
# Three engines, one shape: retrieve inside the caller's scope, run a pure
# function over the evidence, return it. `summary` and `recommendations` call
# the local model; `gaps` does not - a mechanical comparison must not depend on
# a model being up.


def _analysis_scope(body, scope: access.AccessScope):
    """`(narrowed scope, applied echo)`. The one place analysis narrows.

    Written once and used by all three engines, so a filter cannot apply to
    the summary and silently not to the gap analysis - which would put two
    panels on one screen answering about different slices of the corpus.
    """
    wanted = _scope_filter(
        getattr(body.scope, "types", None), getattr(body.scope, "disciplines", None),
        getattr(body.scope, "subject_ids", None))
    narrowed, applied = classification_mod.restrict(scope, wanted)
    return narrowed, _applied(wanted, applied, narrowed)


def _analysis_or_503(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except analysis_mod.ModelUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=errors.safe_error(
                errors.MODEL_UNAVAILABLE,
                f"the local answer model could not be reached ({exc})"),
        )


@app.post("/api/analysis/summary", response_model=schemas.AnalysisSummary,
          responses={**schemas.ERRORS_422})
def analysis_summary(body: schemas.AnalysisRequest,
                     scope: access.AccessScope = Depends(access.current_scope)):
    """Generated prose over retrieved evidence, every sentence cited.

    A sentence citing nothing, or carrying a number that appears in no span it
    cites, is DROPPED and reported in `dropped_sentences` - never rendered with
    a warning beside it, because the number would still be on screen.
    """
    narrowed, echo = _analysis_scope(body, scope)
    result = _analysis_or_503(analysis_mod.summary, body.question, narrowed,
                              limit=body.limit)
    return {**result, "applied_scope": echo}


@app.post("/api/analysis/recommendations",
          response_model=schemas.AnalysisRecommendation,
          responses={**schemas.ERRORS_422})
def analysis_recommendations(
        body: schemas.AnalysisRequest,
        scope: access.AccessScope = Depends(access.current_scope)):
    """One advisory recommendation and the checks behind its confidence."""
    narrowed, echo = _analysis_scope(body, scope)
    result = _analysis_or_503(
        analysis_mod.recommendation, body.question, narrowed, limit=body.limit,
        baseline_document_id=body.baseline_document_id)
    return {**result, "applied_scope": echo}


@app.post("/api/analysis/gaps", response_model=schemas.AnalysisGaps,
          responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def analysis_gaps(body: schemas.AnalysisRequest,
                  scope: access.AccessScope = Depends(access.current_scope)):
    """Mechanical claim comparison. No model call.

    A caller may explicitly choose a baseline. For an engineering submittal,
    a configured review rule can select one automatically; the manual choice
    always wins and every choice remains visible in the returned comparison.
    """
    if body.baseline_document_id:
        # Through require_document, so an id the caller may not read is 404 and
        # is indistinguishable from one that does not exist.
        require_document(body.baseline_document_id, scope)
    selected_baseline = body.baseline_document_id
    if body.document_id:
        require_document(body.document_id, scope)
        selection = review_mod.resolve_baseline(
            body.document_id, body.baseline_document_id,
            allowed_document_ids=scope.allowed_document_ids)
        selected_baseline = selection["document_id"] if selection else None
        if selected_baseline and selected_baseline != body.baseline_document_id:
            require_document(selected_baseline, scope)
    # THE BASELINE IS CHECKED AGAINST THE CALLER'S OWN SCOPE, above, and not
    # against the narrowed one. A caller may nominate a baseline they may read
    # and then filter the comparison to a subject that baseline is not in;
    # refusing that would make the filter silently reject a legitimate
    # baseline, which reads as the baseline being wrong.
    narrowed, echo = _analysis_scope(body, scope)
    result = analysis_mod.gaps(body.question, narrowed, limit=body.limit,
                               baseline_document_id=selected_baseline,
                               comparison_type=body.comparison_type)
    return {**result, "applied_scope": echo}


# ------------------------------------------------------- classification
#
# WHAT A DOCUMENT IS. Not who may read it. Every route here is scoped like
# every other, and the classification tables are never joined to the access
# tables - see classification.py and
# tests/test_classification_independence.py.
#
# WHO MAY DO WHAT, and the split is deliberate:
#   * use the filter, see the vocabulary, see scoped counts - EVERY user. The
#     Process engineer filtering IS the feature.
#   * suggest at upload - whoever uploads.
#   * CONFIRM or CHANGE - the admin capability, because a wrong
#     classification misroutes searches for everyone rather than only for the
#     person who set it.


def _scope_filter(types, disciplines, subject_ids) -> classification_mod.ScopeFilter:
    return classification_mod.ScopeFilter(
        types=tuple(types or ()), disciplines=tuple(disciplines or ()),
        subject_ids=tuple(subject_ids or ()))


def _applied(wanted: classification_mod.ScopeFilter, applied: bool,
             narrowed: access.AccessScope) -> dict:
    """The echo. Says what was applied and how much was reachable after it."""
    return {
        "applied": applied,
        **wanted.as_api(),
        "documents_in_scope": len(narrowed.allowed_document_ids),
    }


@app.get("/api/classification/vocabulary",
         response_model=schemas.ClassificationVocabulary)
def classification_vocabulary(
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """The filter vocabulary, plus this caller's needs-classification count.

    THE VOCABULARY IS NOT SCOPED AND THE COUNT IS. A discipline the caller
    cannot read stays listed: discipline names are project structure, not
    evidence that a document exists, and hiding one teaches a user the system
    is broken rather than that they need access. The count is a statement
    about documents, so it is bounded by what they may read.
    """
    reject_unknown_params(request, set())
    return {**classification_mod.vocabulary(),
            "needs_classification":
                classification_mod.needs_classification(scope)}


@app.get("/api/classification/coverage",
         response_model=schemas.ClassificationCoverage)
def classification_coverage(
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Counts per axis, scoped, with `in_register` NULL when none is loaded."""
    reject_unknown_params(request, set())
    return classification_mod.coverage(scope)


@app.get("/api/documents/{document_id}/classification",
         response_model=schemas.DocumentClassification,
         responses={**schemas.ERRORS_404})
def get_document_classification(
    document_id: str,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """404 outside the caller's scope - the same answer every read path gives,
    and the reason they are 404 rather than 403: a 403 confirms the document
    exists."""
    require_document(document_id, scope)
    row = classification_mod.of_document(document_id)
    if row is None:
        # In scope but never classified. An empty, honest record rather than a
        # 404: the document exists and the caller may read it, and "not
        # classified yet" is the answer.
        return classification_mod.empty_record(document_id)
    return {**row, "document_id": document_id}


@app.put("/api/documents/{document_id}/classification",
         response_model=schemas.DocumentClassification,
         responses={**schemas.ERRORS_404})
def put_document_classification(
    document_id: str,
    body: schemas.ClassificationUpdate,
    scope: access.AccessScope = Depends(access.current_scope),
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """CONFIRM or CHANGE a classification. THE ADMIN CAPABILITY IS REQUIRED.

    A wrong classification misroutes searches for EVERYONE, not only for the
    person who set it, so this needs a role that answers for everyone.
    `admin_mod.current_admin` is the same gate the admin surface uses and
    answers 404 rather than 403 to a non-admin - saying nothing about whether
    the document exists.

    The document must ALSO be in the caller's scope. An administrator holds
    every grant in practice, but the check is not skipped on that basis: the
    two questions are separate and this route asks both.
    """
    require_document(document_id, scope)
    classification_mod.confirm(
        document_id, doc_type=body.doc_type, discipline=body.discipline,
        doc_class=body.doc_class, subject_ids=body.subject_ids,
        confirmed_by=(actor or {}).get("id"),
        # The submittal-review metadata. `document_role` arrived through
        # `schemas.DocumentRole`, so an unknown role was already refused with a
        # 422 naming the field and cannot reach the column.
        metadata={name: getattr(body, name)
                  for name in classification_mod.METADATA_FIELDS},
        equipment_tags=body.equipment_tags)
    row = classification_mod.of_document(document_id) or {}
    return {**row, "document_id": document_id}


@app.get("/api/playbooks", response_model=schemas.PlaybookList, responses={**schemas.ERRORS_404})
def list_playbooks(scope: access.AccessScope = Depends(access.current_scope)):
    """The review playbooks (data files): what each expects a document of its
    kind to contain, the standard clause each element comes from, and whether a
    discipline engineer has signed it off. A file that cannot be used is listed
    with the reason, never dropped."""
    found, broken = playbooks_mod.available()
    return {"playbooks": [
        {"id": pb.id, "title": pb.title, "version": pb.version, "document_kind": pb.document_kind,
         "signed_off": pb.signed_off, "sign_off": pb.sign_off, "clauses_verified": pb.clauses_verified,
         "notice": playbooks_mod.notice(pb), "elements": len(pb.elements)}
        for pb in found.values()], "unusable": broken}


@app.post("/api/documents/{document_id}/playbook-review", response_model=schemas.PlaybookReport,
          responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def playbook_review(
    document_id: str,
    body: schemas.PlaybookReviewRequest,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Review one document the caller may read against a playbook: per element
    present, unclear, missing, could not be checked, or standard not held (never
    "met"). Cited by the passage's locator. `use_ai` lets the LOCAL model propose
    a quote for an element the cue words did not settle; a proposal is kept only
    when its quote is verbatim in the passage it names."""
    require_document(document_id, scope)
    found, _broken = playbooks_mod.available()
    playbook = found.get(body.playbook_id)
    if playbook is None:
        raise HTTPException(status_code=422, detail={
            "code": "unknown_playbook", "message": f"no usable playbook {body.playbook_id!r}"})
    proposer = playbooks_mod.task_proposer() if body.use_ai else None
    return playbooks_mod.review(document_id, playbook, allowed_document_ids=scope.allowed_document_ids,
                                proposer=proposer)


@app.get("/api/document-kinds", response_model=schemas.DocumentKindVocabulary,
         responses={**schemas.ERRORS_404})
def get_document_kinds(scope: access.AccessScope = Depends(access.current_scope)):
    """The document types the router knows, and how many of the caller's OWN
    documents are in each routing state (rule 5: a count states whose
    documents it counts)."""
    allowed = None if scope.unrestricted else scope.allowed_document_ids
    return {"kinds": doc_router_mod.kinds(), "counts": doc_router_mod.counts(allowed)}


@app.put("/api/documents/{document_id}/kind", response_model=schemas.DocumentClassification,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def put_document_kind(
    document_id: str,
    body: schemas.DocumentKindUpdate,
    scope: access.AccessScope = Depends(access.current_scope),
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """A person confirms (or corrects) the document type the router suggested.
    Admin-gated like the rest of classification; a kind outside the vocabulary
    is a 422 naming it. Classification is not access control: this changes what
    the document is called, never who may read it."""
    require_document(document_id, scope)
    try:
        doc_router_mod.confirm(document_id, body.kind, (actor or {}).get("id"))
    except doc_router_mod.UnknownKind as exc:
        raise HTTPException(status_code=422, detail={
            "code": "unknown_document_kind", "message": str(exc)}) from exc
    row = classification_mod.of_document(document_id) or {}
    return {**row, "document_id": document_id}


@app.post("/api/admin/document-kinds/route", response_model=schemas.DocumentKindRouted,
          responses={**schemas.ERRORS_404})
def route_document_kinds(_admin: dict | None = Depends(admin_mod.current_admin)):
    """Route every document that has no routing yet (or an older router's).
    Documents already in the library when the router arrived need this once.
    Confirmed kinds are never touched. Returns counts only."""
    return doc_router_mod.route_unrouted()


@app.post("/api/documents/bulk/role", response_model=schemas.BulkRoleResult,
          responses={**schemas.ERRORS_404, **schemas.ERRORS_422,
                     207: {"model": schemas.BulkRoleResult,
                           "description": "Some documents were not updated; "
                                          "`failed` names each one"}})
def bulk_set_document_role(
    body: schemas.BulkRoleUpdate,
    request: Request,
    response: Response,
    scope: access.AccessScope = Depends(access.current_scope),
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """Set one role on many documents. THE SAME PERMISSION, N TIMES.

    THE GATE IS NOT LOOSENED FOR BULK, and that is the only interesting thing
    about this route. `admin_mod.current_admin` is the identical dependency
    `put_document_classification` uses, and `require_document(id, scope)` is
    run for EVERY id rather than once for the first or not at all. A bulk
    endpoint is the classic place for an authorisation check to become a
    formality - it is written once, the loop is inside, and nobody notices that
    the loop does not re-ask. Here the loop IS the asking.

    Unknown and out-of-scope ids get the SAME `not_found` answer, for the
    reason `require_document` gives: a distinct refusal for "exists but not
    yours" is an existence oracle, and it would be a worse one here than
    anywhere else - a caller could probe forty ids per request.

    NOT ALL-OR-NOTHING, DELIBERATELY. The valid documents are written and the
    invalid ones are named. A bulk action's ids come from a list the person has
    been looking at for a while, and the common failure is one document deleted
    in another tab; refusing the other thirty-nine because of it makes them
    redo the selection to achieve exactly what this request already could. The
    status goes to 207 when anything failed, so a client that checks only the
    status code still cannot read a partial write as a complete one.

    It sets the ROLE ALONE (`classification.set_role`), not a classification.
    Reusing the PUT would replace the whole record and wipe the title, revision
    and project on every document selected - a bulk action must not destroy
    metadata that nobody asked it to touch.

    NOT ACCESS CONTROL (rule 5). A role says what a document is for; the grant
    tables say who may read it, and nothing here writes one.
    """
    reject_unknown_params(request, set())
    # Order-preserving dedup. The same id twice is a UI that double-counted,
    # not a request to write twice, and leaving it would report the document
    # once as updated and once as unchanged in the same response.
    ids = list(dict.fromkeys(body.document_ids))

    updated: list[str] = []
    unchanged: list[str] = []
    failed: list[dict] = []
    for document_id in ids:
        try:
            require_document(document_id, scope)
        except HTTPException:
            failed.append({"document_id": document_id, "reason": "not_found"})
            continue
        changed = classification_mod.set_role(document_id, body.document_role)
        (updated if changed else unchanged).append(document_id)

    if failed:
        response.status_code = 207
    # One audit row for the request, not one per document: this was a single
    # decision by a single person, and forty rows would bury the next one.
    # Ids are counted rather than listed - `detail` is response-safe only.
    admin_mod._audit(
        "documents.role_bulk_set", actor, "document", None,
        detail=(f"{body.document_role}: {len(updated)} changed, "
                f"{len(unchanged)} already held it, {len(failed)} not found "
                f"of {len(ids)} requested"))
    return {"document_role": body.document_role, "requested": len(ids),
            "updated": updated, "unchanged": unchanged, "failed": failed}


# ----------------------------------------------------------------- market
#
# No network call happens with the market lane's egress flags off (the
# shipped default) - `market_transport.transport()` below returns None in
# that state, so `search_all` reports "no transport supplied" rather than
# silently calling out. With both flags on, `market_search` DOES call a real
# provider over the phrase the caller previewed and approved. Every route
# here is scoped like every other, not because a sample is sensitive, but so
# that this flag-gated provider call inherits that shape rather than
# introducing an unscoped route the day it is turned on (corrected 2026-09-28,
# code-review audit finding #45 - the previous comment said no network call
# "exists in this build" at all, which the gated call below already
# contradicted).


@app.get("/api/market/findings", response_model=schemas.MarketFindings)
def market_findings(scope: access.AccessScope = Depends(access.current_scope)):
    """Illustrative rows, every one labelled as a sample."""
    return market_mod.findings()


@app.post("/api/market/preview-query", response_model=schemas.MarketQueryPreview)
def market_preview_query(body: schemas.MarketQueryRequest,
                         scope: access.AccessScope = Depends(access.current_scope)):
    """Build the object that would leave the machine. Do not send it.

    Takes the caller's own words. It must never be built from retrieved
    document text: that would exfiltrate the client's specification to a
    search engine one phrase at a time.
    """
    return market_mod.preview_query(body.query, body.country, body.freshness_days)


def _record_market_audit(rows, scope: access.AccessScope) -> None:
    """Persist one `audit_events` row per outbound query.

    THE EXISTING MECHANISM, NOT A SECOND ONE. `audit_events` is the
    append-only table `admin._audit` and `auth` already write to, and
    `market_providers.audit_record` builds rows whose keys are its columns -
    so this inserts them without translating, and a translation layer is where
    a field quietly stops being recorded.

    IT IS WRITTEN HERE BECAUSE IT CANNOT BE WRITTEN THERE. `market_providers`
    is forbidden to import `db` - enforced by AST inspection - precisely so
    the market feature cannot reach the corpus. Importing `db` there to write
    an audit row would hand the leakiest module in the system a live database
    handle. So that module builds the row and this route stores it.

    `detail` is the phrase VERBATIM. Safe by the only argument that matters:
    it is the text already judged fit to hand to a third party, so it is
    certainly fit for a local table. Not hashed and not summarised, because
    the single question this row exists to answer is "what exactly left this
    machine", and a digest cannot answer it.

    NEVER RAISES INTO THE CALLER, the same discipline as `admin._audit`. An
    unwritable audit row must not fail a request that has already been made -
    and note the ordering that follows from that: rows are written AFTER the
    calls, so a crash between the two loses the record of a query that did
    leave. That is a real gap and the honest fix is a write-ahead record,
    which is more machinery than a feature nobody has enabled needs. Recorded
    here rather than discovered later.
    """
    actor = "unauthenticated" if scope.user_id is None else scope.user_id
    try:
        conn = connect()
        with conn:
            for row in rows:
                conn.execute(
                    """INSERT INTO audit_events
                           (at, actor_user_id, actor_username, action,
                            resource_type, resource_id, outcome, detail)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (row["at"], scope.user_id, actor[:200], row["action"],
                     row["resource_type"], row["resource_id"], row["outcome"],
                     row["detail"]),
                )
    except Exception as exc:  # noqa: BLE001 - an unwritable audit must not fail the request
        # P5: NOT SILENT - the query already left; the missing record is logged.
        errors.record_failure(exc, stage="market_audit")


@app.get("/api/market/preview", response_model=schemas.MarketPreview)
def market_preview(
    phrase: str = Query(..., min_length=1, max_length=2000),
    country: str | None = Query(None, max_length=8),
    freshness_days: int | None = Query(None, ge=1, le=3650),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """What WOULD leave, per tier, and nothing is sent. Safe to call always.

    THE SCRUBBING HAPPENS HERE, and this is the only place in the request
    path that knows the corpus filenames. `phrase` arrives as the user's own
    words - a question, typically - and `market_phrase.market_phrase` reduces
    it to a whitelisted phrase or to None. `None` is returned as `phrase:
    null` and means NO SEARCH IS POSSIBLE; a caller that falls back to the raw
    text has broken the only guarantee that matters.

    THE FILENAMES ARE SCOPE-BOUND. `analysis._corpus_filenames(scope)` returns
    only names this caller may read, which is the right list for two separate
    reasons: a name they cannot see is not one they can ask about, and it
    means the strip list cannot itself become a way to enumerate the corpus.

    `country` and `freshness_days` are accepted and threaded through, because
    they appear in every payload a search sends. A preview that omitted them
    showed an object that was never sent - the defect this route was rewritten
    to close.
    """
    safe = market_phrase_mod.market_phrase(
        phrase, analysis_mod._corpus_filenames(scope))
    return market_providers_mod.preview(
        safe, country=country, freshness_days=freshness_days)


@app.post("/api/market/search", response_model=schemas.MarketSearchResult)
def market_search(body: schemas.MarketSearchRequest,
                  scope: access.AccessScope = Depends(access.current_scope)):
    """Run the configured tiers, or return the labelled samples with the flag
    off. NO TRANSPORT IS CONSTRUCTED HERE.

    `fetch` is left unset deliberately, so this route cannot open a socket in
    this build even with both flags on: `search_all` refuses with "no
    transport supplied" and reports a failure. Wiring a transport is a
    separate, reviewable change and is not part of this one.

    THE PHRASE IS RE-SCRUBBED SERVER-SIDE rather than trusted from the client.
    The browser previewed a scrubbed phrase, but a POST body can carry
    anything, and "the client already checked" is not a control. Scrubbing
    again here means the only text that can reach a provider is text this
    server derived.

    `audit` is stripped by `market_providers.to_api`. The rows it holds are for
    the persistence call site, not for a browser - shipping them would put a
    record of every outbound query into any page that calls this endpoint.
    `response_model` is the second, independent guard on that: even if a
    caller bypassed `to_api`, an undeclared field cannot be serialised.
    """
    raw = body.phrase or ""
    country = body.country
    freshness = body.freshness_days
    safe = market_phrase_mod.market_phrase(
        raw, analysis_mod._corpus_filenames(scope))
    # THE TRANSPORT, AND IT IS None UNLESS BOTH FLAGS ARE TRUE. No client is
    # constructed with the flags off, so the off state is the ABSENCE of a
    # transport rather than an unused one - `search_all` then reports "no
    # transport supplied" rather than appearing to work. This one line is what
    # makes flipping two flags the entire change on the day egress is
    # approved: no code lands that day.
    result = market_providers_mod.search_all(
        safe, fetch=market_transport_mod.transport(),
        country=country, freshness_days=freshness)
    _record_market_audit(result.get("audit") or (), scope)
    return market_providers_mod.to_api(result)


# ---------------------------------------------------------------- reports
#
# A report IS client document content - it quotes it - so every route takes
# the scope and the check is owner AND still authorised for every cited
# document. A report the caller may not see is 404, never 403: a 403 confirms
# it exists and which documents it cites, which is itself the leak.


def _report_or_404(fn, *args):
    try:
        return fn(*args)
    except reports_mod.ReportNotFound:
        raise HTTPException(
            status_code=404,
            detail=errors.safe_error(errors.NOT_FOUND, "no report with that id"),
        )


@app.post("/api/reports", response_model=schemas.ReportRecord,
          responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def generate_report(body: schemas.GenerateReport,
                    scope: access.AccessScope = Depends(access.current_scope)):
    """Freeze one answered message and render it. Renders from the snapshot only."""
    try:
        return reports_mod.generate(body.message_id, scope)
    except reports_mod.ReportNotFound:
        raise HTTPException(
            status_code=404,
            detail=errors.safe_error(errors.NOT_FOUND, "no message with that id"),
        )
    except reports_mod.NotReportable as exc:
        raise HTTPException(
            status_code=422,
            detail=errors.safe_error(errors.INVALID_PARAMETER, str(exc)),
        )


@app.get("/api/reports", response_model=schemas.ReportList,
         responses=schemas.ERRORS_422)
def list_reports(request: Request,
                 limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
                 offset: int = Query(0, ge=0),
                 sort: str = Query("created_at"),
                 direction: str = Query("desc"),
                 q: str | None = Query(None, max_length=200),
                 scope: access.AccessScope = Depends(access.current_scope)):
    reject_unknown_params(request, {"limit", "offset", "sort", "direction", "q"})
    if sort not in {"created_at", "question"}:
        raise HTTPException(status_code=422, detail=errors.safe_error(
            errors.INVALID_PARAMETER, "sort must be created_at or question"))
    if direction not in {"asc", "desc"}:
        raise HTTPException(status_code=422, detail=errors.safe_error(
            errors.INVALID_PARAMETER, "direction must be asc or desc"))
    return reports_mod.list_reports(scope, limit=limit, offset=offset,
                                    sort=sort, direction=direction, query=q)


@app.get("/api/reports/{report_id}/verify", response_model=schemas.ReportVerification,
         responses={**schemas.ERRORS_404})
def verify_report(report_id: str,
                  scope: access.AccessScope = Depends(access.current_scope)):
    return _report_or_404(reports_mod.verify, report_id, scope)


@app.get("/api/reports/{report_id}/download",
         # response_class, not just `responses`: without it FastAPI adds a
         # default application/json entry alongside the PDF, and an endpoint
         # that claims to return JSON and returns bytes is the untyped-200
         # defect wearing a content type. A binary response has no JSON
         # schema, and DECLARING that is different from declaring nothing.
         response_class=FileResponse,
         responses={**schemas.ERRORS_404,
                    200: {"content": {"application/pdf": {}},
                          "description": "The report PDF"}})
def download_report(report_id: str,
                    scope: access.AccessScope = Depends(access.current_scope)):
    path = _report_or_404(reports_mod.stored_path, report_id, scope)
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=errors.safe_error(errors.NOT_FOUND, "no report with that id"),
        )
    # private, no-store - NOT the max-age page images use. A page image is a
    # fragment; this is the assembled evidence with quoted client text in it.
    # The download name is the server-assigned id, never the question.
    return FileResponse(
        path, media_type="application/pdf",
        filename=f"rag-intelligence-report-{report_id}.pdf",
        headers={"Cache-Control": "private, no-store"},
    )


# ------------------------------------------------------- engineering reviews

@app.get("/api/reviews/templates", response_model=schemas.ReviewTemplateList,
         responses=schemas.ERRORS_422)
def list_review_templates(
    request: Request,
    discipline: str | None = Query(None),
    deliverable_type: str | None = Query(None),
    active_only: bool = Query(True),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """List versioned, governed review templates available to the caller."""
    reject_unknown_params(request, {"discipline", "deliverable_type", "active_only"})
    return {"templates": review_mod.list_templates(
        active_only=active_only, discipline=discipline,
        deliverable_type=deliverable_type,
    )}


@app.post("/api/reviews/templates", response_model=schemas.ReviewTemplate,
          responses={**schemas.ERRORS_401, **schemas.ERRORS_422})
def create_review_template(
    body: schemas.ReviewTemplateCreate,
    scope: access.AccessScope = Depends(access.current_scope),
    _actor: dict | None = Depends(admin_mod.current_admin),
):
    """Register a client-approved review template; versions never overwrite.

    THE ADMIN CAPABILITY IS REQUIRED: a template governs every reviewer's
    checklist, not only the author's.
    """
    _require_identity_to_write(scope)
    return review_mod.create_template(body.model_dump(), created_by=scope.user_id)


@app.get("/api/reviews/baseline-rules", response_model=schemas.ReviewBaselineRuleList)
def list_review_baseline_rules(scope: access.AccessScope = Depends(access.current_scope)):
    return {"rules": review_mod.list_baseline_rules()}


@app.post("/api/reviews/baseline-rules", response_model=schemas.ReviewBaselineRule,
          responses=schemas.ERRORS_401)
def create_review_baseline_rule(body: schemas.ReviewBaselineRuleCreate,
                                scope: access.AccessScope = Depends(access.current_scope),
                                _actor: dict | None = Depends(admin_mod.current_admin)):
    # GLOBAL SETTING: the admin capability, via the same gate the admin surface
    # uses (404 to a non-admin). Identity alone let any signed-in engineer
    # change it for everyone (audit 2026-09-30).
    _require_identity_to_write(scope)
    payload = body.model_dump()
    return review_mod.create_baseline_rule(payload)


@app.patch("/api/reviews/baseline-rules/{rule_id}", response_model=schemas.ReviewBaselineRule,
           responses=schemas.ERRORS_404)
def update_review_baseline_rule(rule_id: str, body: schemas.ReviewBaselineRuleCreate,
                                scope: access.AccessScope = Depends(access.current_scope),
                                _actor: dict | None = Depends(admin_mod.current_admin)):
    # GLOBAL SETTING: the admin capability, via the same gate the admin surface
    # uses (404 to a non-admin). Identity alone let any signed-in engineer
    # change it for everyone (audit 2026-09-30).
    _require_identity_to_write(scope)
    item = review_mod.update_baseline_rule(rule_id, body.model_dump())
    if item is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "baseline rule not found"))
    return item


@app.get("/api/reviews/baseline-selection/{document_id}",
         response_model=schemas.ReviewBaselineSelection,
         responses=schemas.ERRORS_404)
def select_review_baseline(document_id: str, scope: access.AccessScope = Depends(access.current_scope)):
    require_document(document_id, scope)
    selection = review_mod.auto_select_baseline(
        document_id, allowed_document_ids=scope.allowed_document_ids)
    if selection is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "no configured baseline matches"))
    return selection


@app.post("/api/reviews/report", response_class=FileResponse,
          responses={**schemas.ERRORS_401, **schemas.ERRORS_404,
                     200: {"content": {"application/pdf": {}},
                           "description": "Engineering review PDF"}})
def export_review_report(
    body: schemas.ReviewReportRequest,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Export a document's evidence-linked review record as a PDF."""
    _require_identity_to_write(scope)
    require_document(body.document_id, scope)
    try:
        path = review_mod.render_report(
            body.document_id, allowed_document_ids=scope.allowed_document_ids)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "review document not found"))
    return FileResponse(path, media_type="application/pdf",
                        filename=f"engineering-review-{body.document_id}.pdf",
                        headers={"Cache-Control": "private, no-store"})

def _document_scope(allowed_document_ids) -> tuple[str, list[str]]:
    """A WHERE clause restricting documents to the caller's grants.

    An EMPTY grant set is `1 = 0`, never "no restriction" - the
    deliverables.py defect this codebase keeps re-checking for.
    """
    if not allowed_document_ids:
        return " WHERE 1 = 0", []
    marks = ",".join("?" for _ in allowed_document_ids)
    return f" WHERE d.id IN ({marks})", sorted(allowed_document_ids)


def _now_date() -> str:
    """Today, as the CRS prints it. The only date this system actually knows
    about an export is the day it was made."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _missing_references(submittal_id: str, allowed: frozenset[str]) -> list[str]:
    """Standards this submittal CITES that the library does not hold.

    Lifted out of the dashboard, which computed exactly this inline, so the
    CRS gap rows and the Active Standards tile cannot drift into two answers
    to one question. Read from the submittal's own chunk text rather than by
    re-running applicability selection.
    """
    text = " ".join(
        row["text"] or "" for row in connect().execute(
            "SELECT text FROM chunks WHERE document_id = ?", (submittal_id,)))
    names = datasheets_mod.referenced_standards(text)
    # THE RULE LIVES IN applicability.missing_references, and is only CALLED
    # here. This helper used to carry its own copy, which compared an
    # identifier against a dict keyed by document id - so every cited
    # standard was "missing", and the CRS told a contractor that six standards
    # held in the library were unavailable. See that function's docstring.
    #
    # Reported in the submittal's own spelling ("32-SAMSS-004", never
    # "32SAMSS004"); ordered by the normalised key so the CRS rows are stable.
    missing = applicability_mod.missing_references(
        applicability_mod._library(allowed), names)
    return sorted(missing, key=applicability_mod.normalise_identifier)


def _standards_change(run: dict, scope: access.AccessScope) -> dict | None:
    """Owner order 2e: WHY THE IN-SCOPE COUNT MOVED BETWEEN RUNS.

    The applicability decision is stored per run (`review_applicable_standards`),
    so the change is a diff against the previous run of the same submittal:
    which standards were added and which removed, by name, under the caller's
    grants. None when there is no earlier run to compare with.
    """
    previous = connect().execute(
        "SELECT id FROM review_runs WHERE submittal_document_id = ? AND id != ?"
        " AND created_at < ? ORDER BY created_at DESC LIMIT 1",
        (run["submittal_document_id"], run["id"], run.get("created_at") or "")).fetchone()
    if previous is None:
        return None

    def in_scope(run_id: str) -> dict[str, str]:
        return {r["standard_document_id"]: r["filename"] or r["standard_document_id"]
                for r in connect().execute(
                    "SELECT a.standard_document_id, d.filename FROM review_applicable_standards a"
                    " LEFT JOIN documents d ON d.id = a.standard_document_id"
                    " WHERE a.review_run_id = ? AND a.included = 1", (run_id,))
                if scope.may_read(r["standard_document_id"])}

    now, before = in_scope(run["id"]), in_scope(previous["id"])
    return {"previous_run_id": previous["id"],
            "added": sorted(now[k] for k in now.keys() - before.keys()),
            "removed": sorted(before[k] for k in before.keys() - now.keys())}


def _run_summary(run: dict, scope: access.AccessScope) -> dict:
    """One review run as every screen shows it.

    ONE DEFINITION OF "HOW MANY FINDINGS, OF WHAT". The runs list, the
    dashboard's recent table and the code-decision response all return this
    shape, and three copies of it would drift into three different answers to
    the same question.

    COUNTED IN SQL. Loading every finding to count them read 1,580 rows per
    run - fourteen thousand across nine runs - to produce six numbers, and
    the list spent seconds on it before rendering. The run is already scoped
    by its caller, so these aggregates inherit that scope.
    """
    by_status = {
        row["compliance_status"]: row["n"]
        for row in connect().execute(
            "SELECT compliance_status, COUNT(*) AS n FROM review_findings"
            " WHERE review_run_id = ? AND compliance_status IS NOT NULL"
            " GROUP BY compliance_status", (run["id"],))
    }
    findings_total = connect().execute(
        "SELECT COUNT(*) AS n FROM review_findings WHERE review_run_id = ?",
        (run["id"],)).fetchone()["n"]
    tags = [
        row["equipment_tag"] for row in connect().execute(
            "SELECT DISTINCT equipment_tag FROM review_findings"
            " WHERE review_run_id = ? AND equipment_tag IS NOT NULL"
            " ORDER BY equipment_tag", (run["id"],))
    ]
    job = review_jobs_mod.job_for_run(run["id"])
    outcome = comparison_mod.run_outcome(
        run["id"], allowed_document_ids=scope.allowed_document_ids) or {}
    document = connect().execute(
        "SELECT filename FROM documents WHERE id = ?",
        (run["submittal_document_id"],)).fetchone()
    return {
        "review_run_id": run["id"],
        "submittal_document_id": run["submittal_document_id"],
        "submittal_filename": document["filename"] if document else None,
        "equipment_tags": tags,
        "status": run.get("status") or "pending",
        "created_at": run.get("created_at"),
        "completed_at": run.get("completed_at"),
        "standards_in_scope": connect().execute(
            "SELECT COUNT(*) AS n FROM review_applicable_standards"
            " WHERE review_run_id = ? AND included = 1",
            (run["id"],)).fetchone()["n"],
        "findings_total": findings_total,
        "by_status": by_status,
        "recommended_code": outcome.get("recommended_code"),
        # 2g: plain words for the engineer; the technical sentence under
        # "Details". A run stored before 2g gets its plain sentence derived
        # from the same stored counts.
        "recommended_reason": comparison_mod.plain_outcome(outcome)[0],
        "recommended_details": comparison_mod.plain_outcome(outcome)[1],
        # The client's configured code labels, in policy order, so the screen
        # offers exactly the labels `record_engineer_code` accepts.
        "review_codes": list(comparison_mod.review_codes()),
        "failure_reason": outcome.get("error"),
        # THE ENGINEER'S DECISION BESIDE THE MACHINE'S, never instead of it.
        "engineer_final_code": run.get("engineer_final_code"),
        "override_reason": run.get("override_reason"),
        "decided_by": run.get("decided_by"),
        # THE NAME A READER RECOGNISES, carried by the run's own join rather
        # than a lookup per row. Null when the decision's user row is gone
        # (`decided_by` is ON DELETE SET NULL), and null renders as nothing.
        "decided_by_name": run.get("decided_by_name"),
        "decided_at": run.get("decided_at"),
        "completeness": outcome.get("completeness"),
        "page_coverage": outcome.get("page_coverage"),
        "table_values_not_compared": outcome.get("table_values_not_compared") or [],
        "requirements_not_applied": outcome.get("requirements_not_applied") or [],
        # #678: every requirement in scope in one of three groups; a run stored
        # before this existed has only its counts, so its reasons say so.
        "requirement_split": (outcome.get("requirement_split")
                              or requirement_split_mod.from_counts(outcome.get("unchecked_counts"))),
        "applicability": outcome.get("applicability"),
        # P3: the background job running this review - progress and cancel.
        "job": job,
        # 2e: which standards came into or left scope since the previous run.
        "standards_change": _standards_change(run, scope),
        # 2026-09-27: the AI engineering check's own outcome for this run -
        # null when it never ran (off, or the Claude lane is off), and NEVER
        # silent when it did: a truncated or budget-refused reply is a fact
        # on the run, with the plain-English boundary sentence a reviewer
        # reads directly (`ai_engineering_check._plain_status`).
        "ai_check_status": ai_engineering_check_mod.ai_check_status(
            run["id"], allowed_document_ids=scope.allowed_document_ids),
        # #633: the web standards check's own outcome, same rule.
        "web_check_status": _json_column(run.get("web_check_status")),
        # #633: findings written before a failed run stopped are PARTIAL.
        "partial_findings": outcome.get("partial_findings") or 0,
    }


def _json_column(raw) -> dict | None:
    """A JSON object stored in a TEXT column, or None (never ran, or malformed)."""
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


@app.post("/api/reviews/runs/{review_run_id}/code",
          response_model=schemas.ReviewRunSummary,
          responses={**schemas.ERRORS_401, **schemas.ERRORS_404,
                     **schemas.ERRORS_422})
def decide_review_code(
    review_run_id: str,
    body: schemas.ReviewCodeDecision,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """The engineer's FINAL review code for a run.

    SECTION 15: the AI performs the review and recommends a code; the
    engineer's final action is governance, not the initial review. Both are
    stored - the recommendation is untouched here - so a screen can show what
    the machine said beside what the engineer decided.

    A reason is REQUIRED when the two differ. That rule lives in
    `comparison.record_engineer_code` and is enforced there rather than in
    this signature, because a client that simply omitted the field would
    otherwise be deciding whether the rule applied to it.

    AN ENGINEER'S ROUTE, NOT AN ADMIN'S. This depended on
    `admin.current_admin` for the audit actor alone, and that dependency is a
    gate: every non-admin engineer got its silent 404, so the screen said
    "not found" about a run it had just listed. Found by signing in as an
    ordinary engineer and pressing the button.
    """
    _require_identity_to_write(scope)
    actor = _actor_from_scope(scope)
    reject_unknown_params(request, set())
    if submittal_review_mod.get_review_run(
            review_run_id,
            allowed_document_ids=scope.allowed_document_ids) is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no review run with that id"))
    try:
        comparison_mod.record_engineer_code(
            review_run_id, code=body.code, reviewer=scope.user_id,
            override_reason=body.override_reason,
            allowed_document_ids=scope.allowed_document_ids, actor=actor)
    except comparison_mod.ComparisonError as exc:
        raise HTTPException(status_code=422, detail=errors.safe_error(
            errors.INVALID_PARAMETER, str(exc))) from exc
    # The final code is the moment a sheet can be issued: every comment an
    # engineer has confirmed must carry its permanent number by then.
    _mint_crs_numbers(review_run_id, scope)
    run = submittal_review_mod.get_review_run(
        review_run_id, allowed_document_ids=scope.allowed_document_ids)
    return _run_summary(run, scope)


@app.get("/api/reviews/dashboard", response_model=schemas.ReviewDashboard,
         responses=schemas.ERRORS_422)
def review_dashboard(
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """The four cards of master plan section 20, under the caller's grants.

    COUNTED IN SQL OVER THE SCOPED SET, never by loading rows to count them -
    the runs list learned that the hard way when counting 14,000 findings in
    Python made the page unusable.
    """
    reject_unknown_params(request, set())
    allowed = scope.allowed_document_ids
    where, args = _document_scope(allowed)

    submittals = [
        row["id"] for row in connect().execute(
            "SELECT d.id FROM documents d JOIN document_classification c"
            " ON c.document_id = d.id" + where +
            " AND c.document_role = 'CONTRACTOR_SUBMITTAL'", args)
    ]
    standards_available = connect().execute(
        "SELECT COUNT(*) AS n FROM documents d JOIN document_classification c"
        " ON c.document_id = d.id" + where +
        " AND c.document_role = 'COMPANY_STANDARD'", args).fetchone()["n"]

    runs = submittal_review_mod.list_review_runs(allowed_document_ids=allowed)
    reviewed = {run["submittal_document_id"] for run in runs
                if (run.get("status") or "") == "completed"}
    running = sum(1 for run in runs if (run.get("status") or "") == "running")
    awaiting = sum(1 for run in runs
                   if (run.get("status") or "") == "completed"
                   and not run.get("engineer_final_code"))

    # NEEDS ATTENTION, AND IT SAYS WHY. A bare tile reading "3" is a number a
    # reader has to trust; the breakdown is what makes it checkable.
    reasons: dict[str, int] = {}
    for run in runs:
        outcome = comparison_mod.run_outcome(
            run["id"], allowed_document_ids=allowed) or {}
        code = run.get("engineer_final_code") or outcome.get("recommended_code")
        if (run.get("status") or "") == "failed":
            reasons["the run failed"] = reasons.get("the run failed", 0) + 1
        # BY ROLE, not by label: the labels are the client's to configure
        # (reference/review_codes.json, CRS quick wins 2026-09-27).
        elif comparison_mod.code_role(code) == "revise_and_resubmit":
            reasons["rejected"] = reasons.get("rejected", 0) + 1
        elif comparison_mod.code_role(code) == "manual_review":
            key = "not enough was read to recommend a code"
            reasons[key] = reasons.get(key, 0) + 1

    # WHAT THE SUBMITTALS CITE THAT THE LIBRARY DOES NOT HOLD. Read from the
    # submittals' own chunk text, which is two documents here, rather than by
    # re-running the applicability selection for a tile.
    referenced: set[str] = set()
    missing: set[str] = set()
    if submittals:
        library = applicability_mod._library(allowed)
        for document_id in submittals:
            text = " ".join(
                row["text"] or "" for row in connect().execute(
                    "SELECT text FROM chunks WHERE document_id = ?",
                    (document_id,)))
            names = datasheets_mod.referenced_standards(text)
            # THE SAME RULE THE CRS USES, from its one home. This inline copy
            # compared identifiers against document ids and reported every
            # cited standard missing: the tile read "21 of 21 cited standards
            # are not in the library" from phase 6 until this line.
            for name in names:
                referenced.add(applicability_mod.normalise_identifier(name))
            for name in applicability_mod.missing_references(library, names):
                missing.add(applicability_mod.normalise_identifier(name))

    recent = [_run_summary(run, scope) for run in runs[:5]]
    return {
        "submittals_total": len(submittals),
        "submittals_awaiting_review": sum(
            1 for document_id in submittals if document_id not in reviewed),
        "standards_available": standards_available,
        "standards_referenced_total": len(referenced),
        "standards_referenced_missing": len(missing),
        "reviews_running": running,
        "reviews_awaiting_decision": awaiting,
        "reviews_total": len(runs),
        "needs_attention": sum(reasons.values()),
        "needs_attention_reasons": reasons,
        "recent": recent,
    }


@app.get("/api/reviews/runs", response_model=schemas.ReviewRunList,
         responses=schemas.ERRORS_422)
def list_review_runs(
    request: Request,
    document_id: str | None = Query(None, description="only this submittal's runs"),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Every review run over a submittal the caller may read.

    The counts are computed here rather than on the screen so that one
    definition of "how many findings, of what" exists. `findings_total` is the
    denominator for `by_status`; a screen showing a status count without it
    would be printing a percentage with no population (CLAUDE.md rule 4).
    """
    reject_unknown_params(request, {"document_id"})
    if document_id is not None:
        require_document(document_id, scope)
    runs = submittal_review_mod.list_review_runs(
        allowed_document_ids=scope.allowed_document_ids,
        submittal_document_id=document_id)
    return {"runs": [_run_summary(run, scope) for run in runs]}


@app.get("/api/reviews/runs/{review_run_id}/standards",
         response_model=schemas.ReviewRunStandardList,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def review_run_standards(
    review_run_id: str,
    request: Request,
    include_excluded: bool = Query(False),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Which standards this run compared against, and WHY each one is there.

    The reason and the method are passed through unchanged. A semantic match
    says in its own words that it is not a citation, and a screen that
    summarised that away would turn "something was retrieved" into "this
    standard applies" - the substitution section 23 forbids.
    """
    reject_unknown_params(request, {"include_excluded"})
    if submittal_review_mod.get_review_run(
            review_run_id,
            allowed_document_ids=scope.allowed_document_ids) is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no review run with that id"))
    return _run_standards_payload(review_run_id, scope, include_excluded)


def _run_standards_payload(review_run_id: str, scope: access.AccessScope,
                           include_excluded: bool) -> dict:
    rows = submittal_review_mod.list_applicable_standards(
        review_run_id, allowed_document_ids=scope.allowed_document_ids,
        include_excluded=include_excluded)
    out = []
    for row in rows:
        document = connect().execute(
            "SELECT filename FROM documents WHERE id = ?",
            (row["standard_document_id"],)).fetchone()
        out.append({
            "standard_document_id": row["standard_document_id"],
            "filename": document["filename"] if document else None,
            "selection_method": row.get("selection_method"),
            "selection_reason": row.get("selection_reason"),
            "confidence": row.get("confidence"),
            "included": bool(row.get("included", 1)),
            "exclusion_reason": row.get("exclusion_reason"),
            "evidence_page": row.get("evidence_page"),
            "evidence_quote": row.get("evidence_quote"),
            "scope_decision": row.get("scope_decision"),
        })
    outcome = comparison_mod.run_outcome(
        review_run_id, allowed_document_ids=scope.allowed_document_ids) or {}
    return {"standards": out,
            "missing_references": outcome.get("missing_references") or []}


@app.post("/api/reviews/runs/{review_run_id}/standards/override",
          response_model=schemas.ReviewRunStandardList,
          responses={**schemas.ERRORS_401, **schemas.ERRORS_404,
                     **schemas.ERRORS_409, **schemas.ERRORS_422})
def override_review_standard(
    review_run_id: str,
    body: schemas.StandardOverrideRequest,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """P2: an engineer adds or removes a standard, with a reason, and the run's
    findings are recomputed from the new list.

    THE ENGINEER'S OWN ACT: a signed-in caller, named in the audit row (written
    in the same transaction as the selection). Both documents must be readable
    - a hidden one is the same 404 as a missing one. REFUSED (409) when the
    run carries an engineer's final code (that decision was made about these
    findings; start a new review), while it is still running, or when the
    caller cannot read every standard the run already uses - recomputing under
    a narrower view would silently drop another engineer's requirements.
    Cited standards the library does not hold stay MISSING_LOCALLY: adding a
    different standard does not make a missing one present.
    """
    reject_unknown_params(request, set())
    _require_identity_to_write(scope)
    if not scope.user_id:
        raise HTTPException(status_code=401, detail=errors.safe_error(
            errors.UNAUTHENTICATED, "an override must name the engineer who made it"))
    run = submittal_review_mod.get_review_run(
        review_run_id, allowed_document_ids=scope.allowed_document_ids)
    if run is None or not scope.may_read(body.standard_document_id):
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no review run or standard with that id"))
    if run.get("engineer_final_code"):
        raise HTTPException(status_code=409, detail=errors.safe_error(
            errors.INVALID_PARAMETER,
            "this run carries an engineer's final code; start a new review to change its standards"))
    if (run.get("status") or "") == "running":
        raise HTTPException(status_code=409, detail=errors.safe_error(
            errors.INVALID_PARAMETER, "this review is still running"))
    in_use = {r["standard_document_id"] for r in connect().execute(
        "SELECT standard_document_id FROM review_applicable_standards"
        " WHERE review_run_id = ? AND included = 1", (review_run_id,))}
    if not in_use <= scope.allowed_document_ids:
        raise HTTPException(status_code=409, detail=errors.safe_error(
            errors.INVALID_PARAMETER,
            "you cannot read every standard this review uses, so it cannot be recomputed under your view"))
    outcome = comparison_mod.run_outcome(
        review_run_id, allowed_document_ids=scope.allowed_document_ids) or {}
    try:
        applicability_mod.override(
            review_run_id, body.standard_document_id, include=body.include,
            reason=body.reason, allowed_document_ids=scope.allowed_document_ids,
            actor=_actor_from_scope(scope))
    except applicability_mod.ApplicabilityError as exc:
        raise HTTPException(status_code=422, detail=errors.safe_error(
            errors.INVALID_PARAMETER, str(exc))) from exc
    comparison_mod.run_comparison(
        review_run_id, allowed_document_ids=scope.allowed_document_ids,
        reference_coverage=(outcome.get("completeness") or {}).get("reference_coverage"),
        missing_references=[m["identifier"] for m in outcome.get("missing_references") or []])
    return _run_standards_payload(review_run_id, scope, include_excluded=True)


@app.post("/api/reviews/run", response_model=schemas.ReviewRunSummary,
          responses={**schemas.ERRORS_401, **schemas.ERRORS_404,
                     **schemas.ERRORS_422})
def start_review_run(
    body: schemas.ReviewRunRequest,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """Select the applicable standards and compare, for one submittal.

    ADMIN-GATED, like queueing a standard for extraction: this writes findings
    that an engineer will act on, and it re-runs the selection that decides
    which standards were even considered.

    ONE RUN AT A TIME PER DOCUMENT. A second concurrent run over the same
    submittal would have both writing findings into the same table for the
    same document, and `replace=True` deletes the other's work mid-flight. The
    refusal names the run already going rather than silently queueing behind
    it.
    """
    _require_identity_to_write(scope)
    reject_unknown_params(request, set())
    document_id = body.submittal_document_id
    require_document(document_id, scope)
    # P3: QUEUED, NOT RUN HERE. The run and its job are created together under
    # one write lock (no second active review of this submittal), and the
    # worker runs it under THIS caller's grants. The response is the queued
    # run with its job, so the screen can show progress and offer cancel.
    try:
        run_id, _job_id = review_jobs_mod.enqueue(
            document_id, allowed_document_ids=scope.allowed_document_ids,
            requested_by=scope.user_id)
    except review_jobs_mod.ReviewAlreadyActive as exc:
        raise HTTPException(status_code=409, detail=errors.safe_error(
            errors.INVALID_PARAMETER,
            f"a review of this submittal is already queued or running ({exc.args[0]})")) from exc
    return next(r for r in list_review_runs(
        request=request, document_id=document_id, scope=scope,
    )["runs"] if r["review_run_id"] == run_id)


@app.get("/api/reviews/findings", response_model=schemas.ReviewFindingList,
         responses=schemas.ERRORS_422)
def list_review_findings(
    request: Request,
    document_id: str | None = Query(None),
    status: schemas.ReviewStatus | None = Query(None),
    review_run_id: str | None = Query(
        None, description="only this comparison run's findings"),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """List review findings only for documents the caller may read.

    `review_run_id` NARROWS, IT DOES NOT WIDEN. The document scope is applied
    exactly as before and independently: a run id belonging to a submittal the
    caller cannot read returns nothing, rather than becoming a way to reach
    findings the grant tables withhold. That is CLAUDE.md rule 5's shape - a
    filter may only ever intersect with what a caller may already see.
    """
    reject_unknown_params(request, {"document_id", "status", "review_run_id"})
    if document_id is not None:
        require_document(document_id, scope)
    return {"findings": review_mod.list_findings(
        document_id=document_id, status=status, review_run_id=review_run_id,
        allowed_document_ids=scope.allowed_document_ids,
    )}


@app.post("/api/reviews/findings", response_model=schemas.ReviewFinding,
          responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_422})
def create_review_finding(
    body: schemas.ReviewFindingCreate,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Persist a cited AI finding for human engineering workflow."""
    _require_identity_to_write(scope)
    require_document(body.document_id, scope)
    if body.baseline_document_id:
        require_document(body.baseline_document_id, scope)
    if body.owner_user_id and not scope.unrestricted and not scope.is_admin and body.owner_user_id != scope.user_id:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "review owner not found"))
    return review_mod.create(body.model_dump(), created_by=scope.user_id)


@app.patch("/api/reviews/findings/{finding_id}", response_model=schemas.ReviewFinding,
           responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_422})
def update_review_finding(
    finding_id: str,
    body: schemas.ReviewFindingUpdate,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Update workflow fields without changing the original evidence."""
    _require_identity_to_write(scope)
    current = review_mod.get(finding_id)
    if current is None or not scope.may_read(current["document_id"]):
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no review finding with that id"))
    if body.owner_user_id and not scope.unrestricted and not scope.is_admin and body.owner_user_id != scope.user_id:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "review owner not found"))
    changes = body.model_dump(exclude_unset=True)
    # Owner order section 3: AN EDITED COMMENT IS THE ENGINEER'S, so saving
    # it confirms it - and a confirmed finding survives a re-run, where an
    # unconfirmed edit would silently vanish with the rest.
    if changes.get("engineer_comment"):
        changes["confirmed"] = True
    # CONFIRMATION IS THE CALLER'S OWN. `confirmed` is a flag on the body; the
    # NAME comes from the authenticated scope and can never be supplied by the
    # client, because a confirmation that can be attributed to someone else is
    # worth nothing to the engineer whose name is on it. An anonymous caller
    # cannot confirm - `_require_identity_to_write` above has already refused.
    if changes.pop("confirmed", None):
        if scope.user_id is None:
            # AN ANONYMOUS CONFIRMATION IS NOT A CONFIRMATION, and accepting
            # one would be worse than refusing it: `review.update` drops a
            # None, so the route would answer 200 having recorded nothing and
            # the engineer would believe the pairing was signed for.
            raise HTTPException(status_code=401, detail=errors.safe_error(
                errors.UNAUTHENTICATED,
                "a confirmation must name the engineer who made it"))
        changes["confirmed_by"] = scope.user_id
        changes["confirmed_at"] = review_mod.now_iso()
    # B10: AN APPROVAL OR DISPOSITION IS THE CALLER'S OWN, for the same reason.
    # The name is never read from the body (the schema has no field for it),
    # and an anonymous caller cannot decide a finding.
    if changes.get("approval_status") in ("accepted", "rejected") or changes.get("disposition"):
        if scope.user_id is None:
            raise HTTPException(status_code=401, detail=errors.safe_error(
                errors.UNAUTHENTICATED,
                "an approval must name the engineer who made it"))
        changes["approved_by"] = scope.user_id
        changes["approved_at"] = review_mod.now_iso()
    updated = review_mod.update(
        finding_id, changes, actor_user_id=scope.user_id
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no review finding with that id"))
    # A confirmed, accepted or re-worded comment is the engineer's: it gets
    # its permanent CRS number now, not at export (which writes nothing).
    _mint_crs_numbers(current.get("review_run_id"), scope)
    # r2 S2: the reply is a read of the finding too.
    review_mod.withhold_unreadable_standards([updated], scope.allowed_document_ids)
    return updated


@app.post("/api/reviews/pairs/reject", response_model=schemas.PairRejection,
          responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_422})
def reject_review_pair(
    body: schemas.PairRejectionCreate,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Refuse a pairing so no future run proposes it again.

    THE CORRECTION AN ENGINEER MAKES MOST OFTEN. A matcher - containment or
    model - pairs a clause with the wrong field; without this the same wrong
    pairing returns on every re-run and the engineer learns that correcting
    the machine achieves nothing.

    Scoped exactly like `GET /api/reviews/findings`. A caller who may not read
    the finding gets the same 404 as one asking about a finding that does not
    exist, because a different answer would confirm it does.
    """
    _require_identity_to_write(scope)
    try:
        rejection = comparison_mod.reject_pair_for_finding(
            body.finding_id, rejected_by=scope.user_id,
            reason=body.reason or None,
            allowed_document_ids=scope.allowed_document_ids)
    except comparison_mod.ComparisonError as exc:
        raise HTTPException(status_code=422, detail=errors.safe_error(
            errors.INVALID_PARAMETER, str(exc))) from exc
    if rejection is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no review finding with that id"))
    return rejection


@app.get("/api/reviews/findings/{finding_id}/history",
         response_model=schemas.ReviewFindingEventList,
         responses=schemas.ERRORS_404)
def review_finding_history(
    finding_id: str,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Return the immutable response/approval/disposition audit trail."""
    current = review_mod.get(finding_id)
    if current is None or not scope.may_read(current["document_id"]):
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no review finding with that id"))
    return {"events": review_mod.history(finding_id)}


# ------------------------------------------------------------- deliverables / WBS

def _deliverable_visible(item: dict, scope: access.AccessScope) -> bool:
    """May this caller touch this deliverable? (r2 S3)

    A deliverable tied to a document follows that document's grant. One with NO
    document used to be open to every identified caller, including one with no
    grant at all; it now needs the admin capability or at least one grant.
    """
    document_id = item.get("document_id")
    if document_id:
        return scope.may_read(document_id)
    return scope.is_admin or bool(scope.allowed_document_ids)


@app.get("/api/deliverables", response_model=schemas.DeliverableList,
         responses=schemas.ERRORS_422)
def list_deliverables(scope: access.AccessScope = Depends(access.current_scope)):
    return {"deliverables": deliverables_mod.list_items(allowed_document_ids=scope.allowed_document_ids)}


@app.get("/api/deliverables/expected", response_model=schemas.ExpectedDeliverableList)
def expected_deliverables(wbs_code: str | None = None,
                          scope: access.AccessScope = Depends(access.current_scope)):
    deliverables_mod.infer_expectations(allowed_document_ids=scope.allowed_document_ids)
    return {"deliverables": deliverables_mod.expected_missing(
        wbs_code=wbs_code, allowed_document_ids=scope.allowed_document_ids)}


@app.get("/api/search/structured", response_model=schemas.StructuredSearchList)
def structured_search(q: str, kind: str | None = None,
                      scope: access.AccessScope = Depends(access.current_scope)):
    if kind not in {None, "deliverable", "finding", "risk", "stakeholder"}:
        raise HTTPException(status_code=422, detail="unsupported structured-search kind")
    # B42: `is_admin` is already "unrestricted or holds the admin capability",
    # the same test `owns_conversation` applies to a row with no owner - so the
    # unowned rule is stated once, in access.py, and read from there.
    return {"results": structured_search_mod.search(
        q, kind=kind, allowed_document_ids=scope.allowed_document_ids,
        include_unowned=scope.is_admin)}


@app.get("/api/risks", response_model=schemas.RiskList)
def list_risks(risk_type: str | None = None,
               scope: access.AccessScope = Depends(access.current_scope)):
    if risk_type is not None and risk_type not in risks_mod.RISK_TYPES:
        raise HTTPException(status_code=422, detail="unsupported risk type")
    # READ ONLY (#478, #608). Detection used to run here on every GET, looping
    # over every finding and emailing per risk. It runs in the background
    # (`risks_mod.start_background_detection`) and from POST /api/risks/detect.
    return {"risks": risks_mod.list_items(risk_type=risk_type, allowed_document_ids=scope.allowed_document_ids)}


@app.post("/api/risks/detect", response_model=schemas.RiskDetectionResult,
          responses={**schemas.ERRORS_404})
def detect_risks(_actor: dict | None = Depends(admin_mod.current_admin)):
    """Run automatic risk detection now. Admin only (404 to anyone else, the
    admin surface's convention). Single-flight; sends at most one digest."""
    return risks_mod.run_detection()


@app.get("/api/reviews/findings/{finding_id}/traceability", response_model=schemas.ReviewTraceability)
def finding_traceability(finding_id: str, scope: access.AccessScope = Depends(access.current_scope)):
    item = review_mod.traceability(finding_id, allowed_document_ids=scope.allowed_document_ids)
    if item is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "no finding with that id"))
    return item


@app.post("/api/risks", response_model=schemas.Risk,
          responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_422})
def create_risk(body: schemas.RiskCreate, scope: access.AccessScope = Depends(access.current_scope)):
    """Record a risk. The same rules as every other writer (audit 2026-09-30):

    an identity is required, anything it points at must be readable by the
    caller (a risk on a hidden document, deliverable or source finding is a
    write into somebody else's record), and an ordinary user may only name themselves as
    owner. Length limits live on `schemas.RiskCreate`.
    """
    _require_identity_to_write(scope)
    if body.risk_type not in risks_mod.RISK_TYPES:
        raise HTTPException(status_code=422, detail="unsupported risk type")
    if body.document_id:
        require_document(body.document_id, scope)
    if body.deliverable_id:
        linked = deliverables_mod.get(body.deliverable_id)
        if linked is None or not _deliverable_visible(linked, scope):
            raise HTTPException(status_code=404, detail=errors.safe_error(
                errors.NOT_FOUND, "no deliverable with that id"))
    if body.source_finding_id:
        # The finding a risk cites is read with its document (audit leftover
        # 2026-09-30): one on a document the caller may not read answers the
        # same 404 as one that does not exist.
        source = review_mod.get(body.source_finding_id)
        if source is None or not scope.may_read(source["document_id"]):
            raise HTTPException(status_code=404, detail=errors.safe_error(
                errors.NOT_FOUND, "no finding with that id"))
    if body.owner_user_id and not scope.is_admin and body.owner_user_id != scope.user_id:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "risk owner not found"))
    return risks_mod.create(body.model_dump())


@app.post("/api/deliverables", response_model=schemas.Deliverable,
          responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_422})
def create_deliverable(body: schemas.DeliverableCreate,
                       scope: access.AccessScope = Depends(access.current_scope)):
    _require_identity_to_write(scope)
    if body.document_id:
        require_document(body.document_id, scope)
    if body.parent_id and deliverables_mod.get(body.parent_id) is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "parent WBS node not found"))
    return deliverables_mod.create(body.model_dump(), created_by=scope.user_id)


@app.patch("/api/deliverables/{deliverable_id}", response_model=schemas.Deliverable,
           responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_422})
def update_deliverable(deliverable_id: str, body: schemas.DeliverableUpdate,
                       scope: access.AccessScope = Depends(access.current_scope)):
    _require_identity_to_write(scope)
    # AUTHORISE BEFORE WRITING. The read check used to run on the row
    # `update` RETURNED, so a caller without a grant on the deliverable's
    # document got a 404 while their change had already been committed
    # (audit 2026-09-30). The existing row is checked first, then written.
    existing = deliverables_mod.get(deliverable_id)
    if existing is None or not _deliverable_visible(existing, scope):
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "no deliverable with that id"))
    changes = body.model_dump(exclude_unset=True)
    if changes.get("document_id"):
        require_document(changes["document_id"], scope)
    if changes.get("parent_id") and deliverables_mod.get(changes["parent_id"]) is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "parent WBS node not found"))
    try:
        item = deliverables_mod.update(deliverable_id, changes, actor_user_id=scope.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if item is None or not _deliverable_visible(item, scope):
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "no deliverable with that id"))
    return item


@app.get("/api/deliverables/{deliverable_id}/history", response_model=schemas.DeliverableEventList,
         responses=schemas.ERRORS_404)
def deliverable_history(deliverable_id: str, scope: access.AccessScope = Depends(access.current_scope)):
    item = deliverables_mod.get(deliverable_id)
    if item is None or not _deliverable_visible(item, scope):
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "no deliverable with that id"))
    return {"events": deliverables_mod.history(deliverable_id)}


@app.get("/api/deliverables/{deliverable_id}/stakeholders",
         response_model=schemas.DeliverableStakeholderList,
         responses=schemas.ERRORS_404)
def deliverable_stakeholders(deliverable_id: str, scope: access.AccessScope = Depends(access.current_scope)):
    item = deliverables_mod.get(deliverable_id)
    if item is None or not _deliverable_visible(item, scope):
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "no deliverable with that id"))
    return {"stakeholders": deliverables_mod.stakeholders(deliverable_id)}


@app.put("/api/deliverables/{deliverable_id}/stakeholders",
         response_model=schemas.DeliverableStakeholderList,
         responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_422})
def replace_deliverable_stakeholders(
    deliverable_id: str, body: schemas.DeliverableStakeholderUpdate,
    scope: access.AccessScope = Depends(access.current_scope),
):
    _require_identity_to_write(scope)
    item = deliverables_mod.get(deliverable_id)
    if item is None or not _deliverable_visible(item, scope):
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "no deliverable with that id"))
    return {"stakeholders": deliverables_mod.replace_stakeholders(
        deliverable_id, [a.model_dump() for a in body.assignments], actor_user_id=scope.user_id)}


@app.get("/api/deliverables/{deliverable_id}/workspace",
         response_model=schemas.WbsWorkspace, responses=schemas.ERRORS_404)
def deliverable_workspace(deliverable_id: str, scope: access.AccessScope = Depends(access.current_scope)):
    item = deliverables_mod.workspace(
        deliverable_id, allowed_document_ids=scope.allowed_document_ids)
    if item is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "no deliverable with that id"))
    return item


@app.get("/api/deliverables/alerts", response_model=schemas.DeliverableAlertList)
def deliverable_alerts(scope: access.AccessScope = Depends(access.current_scope)):
    return {"alerts": deliverables_mod.alerts(allowed_document_ids=scope.allowed_document_ids)}


@app.get("/api/management/reminders", response_model=schemas.ReminderEventList)
def management_reminders(scope: access.AccessScope = Depends(access.current_scope)):
    return {"reminders": deliverables_mod.reminder_events(allowed_document_ids=scope.allowed_document_ids)}


@app.post("/api/management/reminders/{reminder_id}/ack", response_model=schemas.ReminderEvent,
          responses=schemas.ERRORS_404)
def acknowledge_management_reminder(reminder_id: str, scope: access.AccessScope = Depends(access.current_scope)):
    reminder = next((item for item in deliverables_mod.reminder_events(allowed_document_ids=scope.allowed_document_ids)
                     if item["id"] == reminder_id), None)
    if reminder is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "no reminder with that id"))
    item = deliverables_mod.acknowledge_reminder(reminder_id)
    if item is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "no reminder with that id"))
    return item


@app.get("/api/management/summary", response_model=schemas.ManagementSummary)
def management_summary(scope: access.AccessScope = Depends(access.current_scope)):
    items = deliverables_mod.list_items(allowed_document_ids=scope.allowed_document_ids)
    alerts = deliverables_mod.alerts(allowed_document_ids=scope.allowed_document_ids)
    findings = review_mod.list_findings(allowed_document_ids=scope.allowed_document_ids)
    by_status = {status: sum(1 for item in items if item["status"] == status)
                 for status in {item["status"] for item in items}}
    by_severity = {severity: sum(1 for item in findings if item["severity"] == severity)
                   for severity in {item["severity"] for item in findings}}
    by_review_status = {status: sum(1 for item in findings if item["status"] == status)
                        for status in {item["status"] for item in findings}}
    escalated = sum(1 for item in findings if item["escalation_level"] > 0)
    return {"deliverables_total": len(items), "deliverables_by_status": by_status,
            "review_findings_total": len(findings), "findings_by_severity": by_severity,
            "findings_by_status": by_review_status, "escalated_findings": escalated,
            "overdue_alerts": len(alerts), "alerts": alerts}


@app.post("/api/management/summary/email", response_model=schemas.NotificationSendResponse,
          responses=schemas.ERRORS_401)
def email_management_summary(scope: access.AccessScope = Depends(access.current_scope)):
    _require_identity_to_write(scope)
    items = deliverables_mod.list_items(allowed_document_ids=scope.allowed_document_ids)
    alerts = deliverables_mod.alerts(allowed_document_ids=scope.allowed_document_ids)
    findings = review_mod.list_findings(allowed_document_ids=scope.allowed_document_ids)
    summary = {"deliverables_total": len(items), "overdue_alerts": len(alerts),
               "escalated_findings": sum(1 for item in findings if item["escalation_level"] > 0)}
    sent = notifications_mod.send_daily_summary(summary, actor_user_id=scope.user_id)
    return {"sent": sent}


@app.get("/api/management/summary/schedule", response_model=schemas.SummarySchedule)
def get_summary_schedule(scope: access.AccessScope = Depends(access.current_scope)):
    return {"schedule": settings.summary_schedule, "weekday_utc": settings.summary_weekday_utc, "hour_utc": settings.summary_hour_utc}


@app.put("/api/management/summary/schedule", response_model=schemas.SummarySchedule)
def set_summary_schedule(body: schemas.SummarySchedule,
                         scope: access.AccessScope = Depends(access.current_scope),
                         _actor: dict | None = Depends(admin_mod.current_admin)):
    # GLOBAL SETTING: the admin capability, via the same gate the admin surface
    # uses (404 to a non-admin). Identity alone let any signed-in engineer
    # change it for everyone (audit 2026-09-30).
    _require_identity_to_write(scope)
    settings.summary_schedule = body.schedule
    settings.summary_weekday_utc = body.weekday_utc
    settings.summary_hour_utc = body.hour_utc
    return body


@app.get("/api/management/escalation-rules", response_model=schemas.EscalationRuleList)
def list_escalation_rules(scope: access.AccessScope = Depends(access.current_scope)):
    return {"rules": deliverables_mod.escalation_rules()}


@app.get("/api/management/report", response_class=FileResponse,
         responses={200: {"content": {"application/pdf": {}}, "description": "Management PDF"}})
def management_report(scope: access.AccessScope = Depends(access.current_scope)):
    path = deliverables_mod.render_management_report(allowed_document_ids=scope.allowed_document_ids)
    return FileResponse(path, media_type="application/pdf", filename="epc-management-report.pdf",
                        headers={"Cache-Control": "private, no-store"})


@app.put("/api/management/escalation-rules/{level}", response_model=schemas.EscalationRule,
         responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_422})
def update_escalation_rule(level: int, body: schemas.EscalationRule,
                           scope: access.AccessScope = Depends(access.current_scope),
                           _actor: dict | None = Depends(admin_mod.current_admin)):
    # GLOBAL SETTING: the admin capability, via the same gate the admin surface
    # uses (404 to a non-admin). Identity alone let any signed-in engineer
    # change it for everyone (audit 2026-09-30).
    _require_identity_to_write(scope)
    item = deliverables_mod.update_escalation_rule(level, body.model_dump(exclude={"level"}))
    if item is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "no escalation rule with that level"))
    return item


@app.post("/api/conversations", response_model=schemas.Conversation,
          responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def create_conversation(body: schemas.NewConversation | None = None,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Start a conversation, owned by the caller. Optionally scoped to one document."""
    _require_identity_to_write(scope)
    body = body or schemas.NewConversation()
    if body.document_id:
        require_document(body.document_id, scope)
    return chat_mod.create_conversation(
        title=body.title or "New conversation", document_id=body.document_id,
        owner_user_id=scope.user_id,
    )


@app.get("/api/conversations", response_model=schemas.ConversationList,
         responses=schemas.ERRORS_422)
def list_conversations(
    request: Request,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """The CALLER'S recent conversations, most recently used first.

    Filtered on owner IN THE QUERY - page and `total` both - by the same rule
    `_require_owned_conversation` applies per row, spelled as a WHERE clause by
    `scope.conversation_filter()`. With no token this route returned every
    conversation in the system, question text included (#81); an unauthenticated
    caller now filters on owner None, which matches no row in SQL, and does not
    include the unowned. The admin capability does: the legacy NULL-owner rows
    are assigned to it.
    """
    reject_unknown_params(request, {"limit", "offset"})
    where = scope.conversation_filter()
    if where is None:
        return chat_mod.list_conversations(limit=limit, offset=offset)
    owner, include_unowned = where
    return chat_mod.list_conversations(limit=limit, offset=offset, owner=owner,
                                       include_unowned=include_unowned)


@app.get("/api/conversations/{conversation_id}", response_model=schemas.ConversationDetail,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def get_conversation(conversation_id: str, request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """A conversation with every turn, including the passages behind each
    answer, so reopening it restores the citations rather than bare text."""
    reject_unknown_params(request, set())
    conversation = _require_owned_conversation(conversation_id, scope)
    return {"conversation": conversation, "messages": chat_mod.get_messages(
        conversation_id, allowed_document_ids=scope.allowed_document_ids,
        user_key=scope.user_id or "")}


@app.delete("/api/conversations/{conversation_id}", response_model=schemas.DeletedConversation,
            responses={**schemas.ERRORS_400, **schemas.ERRORS_404, **schemas.ERRORS_422})
def delete_conversation(conversation_id: str, request: Request, confirm: bool = Query(False),
    scope: access.AccessScope = Depends(access.current_scope),
):
    # THIS ROUTE HAD NO SCOPE AT ALL (#80). An unauthenticated DELETE returned
    # 200, removed another user's conversation, and echoed its title back.
    # The ownership check runs BEFORE the confirm check, so an unowned id gets
    # the same 404 whether or not confirm=true was passed - a 400 "pass
    # confirm=true" on a hidden conversation would confirm it exists.
    reject_unknown_params(request, {"confirm"})
    conversation = _require_owned_conversation(conversation_id, scope)
    if not confirm:
        return JSONResponse(
            status_code=400,
            content={"detail": errors.safe_error(
                errors.CONFIRM_REQUIRED, "pass confirm=true to delete this conversation")},
        )
    messages = conversation["message_count"]
    chat_mod.delete_conversation(conversation_id)
    return {
        "deleted": conversation_id,
        # A conversation has a TITLE. This said "filename" because the
        # document-delete response shape was copied without renaming the
        # field, so a client reading it built a wrong model of what it had
        # deleted - and the mistake was invisible, because a conversation
        # title looks exactly as plausible under that key as a filename does.
        "title": conversation["title"],
        # No files_removed: a conversation deletes no files, and reporting a
        # truthful-looking 0 for a thing that never applies is how a field
        # stops meaning anything.
        "rows_removed": {"conversations": 1, "messages": messages},
    }


@app.get("/api/chat/models", response_model=schemas.ChatModels, responses=schemas.ERRORS_422)
def chat_models(request: Request, scope: access.AccessScope = Depends(access.current_scope)):
    """What the composer's Model menu may offer: only engines that can run
    here, with the reason one cannot (never a key). Signed-in callers only."""
    reject_unknown_params(request, set())
    if not scope.unrestricted and not scope.user_id:
        raise HTTPException(status_code=401, detail=errors.safe_error(
            errors.UNAUTHENTICATED, "sign in to continue"))
    from . import chat_model, chat_web
    web_ok, web_why = chat_web.available()
    return {**chat_model.available_models(), "web_available": web_ok, "web_reason": web_why}


@app.post("/api/conversations/{conversation_id}/ask", response_model=schemas.AskResult,
          responses={**schemas.ERRORS_400, **schemas.ERRORS_404, **schemas.ERRORS_422})
def ask(conversation_id: str, body: schemas.AskRequest,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Ask inside a conversation, resolving follow-ups from earlier questions.

    Only previous USER questions inform the resolution. A previous ANSWER is
    never evidence and never reaches retrieval or the prompt.

    Set `explain_of` to upgrade an existing extract answer to Tier 2 rather
    than asking again - the reader pressing Explain is not asking a new
    question, and should not get a duplicate turn in their transcript.
    """
    _require_owned_conversation(conversation_id, scope)
    if body.document_id:
        require_document(body.document_id, scope)
    # An empty question is not a client error - it is somebody pressing enter.
    # It classifies as "empty" and gets the guidance reply, like any other
    # input that was never a document question.
    try:
        progress_mod.start(body.progress_id, owner=scope.user_id)
        # `finally`, so an answer that raises still closes its record rather
        # than leaving a client polling a stage that will never advance.
        try:
            return chat_mod.ask(
                conversation_id,
                body.question,
                tier=body.tier,
                document_id=body.document_id,
                limit=body.limit,
                explain_of=body.explain_of,
                allowed_document_ids=scope.allowed_document_ids,
                progress_id=body.progress_id,
                model=body.model,
                include_unowned_records=scope.is_admin,
                document_ids=_picked_documents(body, scope),
                web=body.web,
            )
        finally:
            progress_mod.finish(body.progress_id)
    except chat_mod.MessageNotFound:
        raise HTTPException(
            status_code=404,
            detail=errors.safe_error(
                errors.NOT_FOUND, "no answered message with that id in this conversation"),
        )


def _picked_documents(body: schemas.AskRequest, scope: access.AccessScope) -> frozenset[str] | None:
    """The documents picked with "@ a document", each checked readable - a
    404 for one that is not, the same answer as for one that does not exist.
    `chat.ask` then intersects them with the caller's permission anyway."""
    if not body.document_ids:
        return None
    for document_id in body.document_ids:
        require_document(document_id, scope)
    return frozenset(body.document_ids)


def _chat_action_errors(fn):
    """chat_actions' refusals, as the API states them."""
    from . import chat_actions
    try:
        return fn()
    except chat_actions.NotFound:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no such answer or comment in this conversation"))
    except (chat_actions.NothingToFile, chat_actions.UndoClosed) as exc:
        raise HTTPException(status_code=409, detail=errors.safe_error(
            errors.INVALID_PARAMETER, str(exc)))


@app.post("/api/conversations/{conversation_id}/messages/{message_id}/feedback",
          response_model=schemas.ChatFeedback,
          responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_422})
def chat_feedback(conversation_id: str, message_id: str, body: schemas.ChatFeedbackRequest,
                  scope: access.AccessScope = Depends(access.current_scope)):
    """ "Was this right?" on one answer: the caller's own, replaced if they
    change their mind. Stored on this machine only."""
    from . import chat_actions
    _require_identity_to_write(scope)
    _require_owned_conversation(conversation_id, scope)
    return _chat_action_errors(lambda: chat_actions.set_feedback(
        conversation_id, message_id, user_key=scope.user_id or "",
        helpful=body.helpful, note=body.note))


@app.post("/api/conversations/{conversation_id}/messages/{message_id}/web-search",
          response_model=schemas.Message,
          responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_409,
                     **schemas.ERRORS_422})
def chat_web_search(conversation_id: str, message_id: str,
                    scope: access.AccessScope = Depends(access.current_scope)):
    """ "Search once": run the one web search a consent turn offered.

    Takes NO text from the client. The phrase sent is exactly the one the
    consent turn showed and stored, re-checked against the market lane's
    whitelist before it leaves (chat_web.search), claimed atomically so it
    runs once, sent through the market transport, audited like every market
    query, and answered as a new turn citing the web as the web."""
    from . import chat_web
    _require_identity_to_write(scope)
    _require_owned_conversation(conversation_id, scope)
    try:
        result, audit = chat_web.search(conversation_id, message_id,
                                        allowed_document_ids=scope.allowed_document_ids)
    except chat_web.NotFound:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no web question with that id in this conversation"))
    except chat_web.Refused as exc:
        raise HTTPException(status_code=409, detail=errors.safe_error(
            errors.INVALID_PARAMETER, str(exc)))
    _record_market_audit(audit, scope)
    result["route"] = "web"
    result.update(chat_mod.chat_presentation.present(result))
    conn = connect()
    return chat_mod._insert_message(
        conn, conversation_id, role="assistant", text=result["answer"],
        answer_type=result["answer_type"], reason=None, payload=chat_mod._payload(result))


@app.post("/api/conversations/{conversation_id}/messages/{message_id}/comment",
          response_model=schemas.FiledComment,
          responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_409,
                     **schemas.ERRORS_422})
def file_chat_comment(conversation_id: str, message_id: str, body: schemas.FileCommentRequest,
                      scope: access.AccessScope = Depends(access.current_scope)):
    """ "Add to comment sheet": file a drafted comment, as the caller wrote or
    kept it, as a finding on the submittal the answer drew on. Only a person
    pressing the button files anything; the model never does."""
    from . import chat_actions
    _require_identity_to_write(scope)
    _require_owned_conversation(conversation_id, scope)
    filed = _chat_action_errors(lambda: chat_actions.file_comment(
        conversation_id, message_id, text=body.text, user_id=scope.user_id,
        allowed_document_ids=scope.allowed_document_ids))
    # An engineer's own comment: numbered the moment it is filed.
    _mint_crs_numbers((filed or {}).get("review_run_id"), scope)
    return filed


@app.delete("/api/conversations/{conversation_id}/messages/{message_id}/comment/{finding_id}",
            response_model=schemas.WithdrawnComment,
            responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_409,
                       **schemas.ERRORS_422})
def withdraw_chat_comment(conversation_id: str, message_id: str, finding_id: str,
                          scope: access.AccessScope = Depends(access.current_scope)):
    """Undo a filing - by the person who filed it, within minutes, while
    nobody has changed the finding. After that it is changed on the review."""
    from . import chat_actions
    _require_identity_to_write(scope)
    _require_owned_conversation(conversation_id, scope)
    return _chat_action_errors(lambda: chat_actions.withdraw_comment(
        conversation_id, message_id, finding_id, user_id=scope.user_id))


#: A pipeline stage, as the streamed step list shows it. "generating" is not
#: here: the model call announces itself (chat_model), because a general
#: answer never passes through the document pipeline's stages.
_STEP_LABELS = {
    "retrieving": "Searching your documents",
    "reranking": "Ranking the closest passages",
    "reading": "Reading the best sources",
}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/conversations/{conversation_id}/ask/stream", response_class=StreamingResponse,
          responses={200: {"content": {"text/event-stream": {}},
                           "description": "turn, step, delta, sources, verification, notice, "
                                          "then done (the full answer) or error"},
                     **schemas.ERRORS_404, **schemas.ERRORS_422})
async def ask_stream(conversation_id: str, body: schemas.AskRequest, request: Request,
                     scope: access.AccessScope = Depends(access.current_scope)):
    """`ask`, streamed as Server-Sent Events (owner order 2026-09-26, 2e).

    THE SAME ANSWER as the non-streaming route - `chat.ask` builds it - with
    its progress, its text and its Stop visible while it is written. Events:
    `turn` {turn_id}, `step` {label, count, done}, `delta` {text} (a document
    sentence only once its quote verified - chat_stream), `sources`,
    `verification`, `notice` {text}, then `done` (the full AskResult) or
    `error`. A reader who closes the page stops the provider call too.
    """
    import asyncio
    import threading

    from . import chat_stream

    _require_owned_conversation(conversation_id, scope)
    if body.document_id:
        require_document(body.document_id, scope)
    picked = _picked_documents(body, scope)
    turn = chat_stream.open_turn(owner=scope.user_id, conversation_id=conversation_id)

    def work() -> None:
        token = chat_stream.bind(turn)
        progress_mod.start(turn.id, owner=scope.user_id)

        def on_stage(name, detail):
            if name in _STEP_LABELS:
                count = int(detail.split()[0]) if detail and detail.split()[0].isdigit() else None
                turn.emit("step", {"label": _STEP_LABELS[name], "count": count, "done": False})

        progress_mod.listen(turn.id, on_stage)
        try:
            result = chat_mod.ask(
                conversation_id, body.question, tier=body.tier, document_id=body.document_id,
                limit=body.limit, explain_of=body.explain_of,
                allowed_document_ids=scope.allowed_document_ids, progress_id=turn.id,
                model=body.model, include_unowned_records=scope.is_admin,
                document_ids=picked, web=body.web)
            final = schemas.AskResult.model_validate(result).model_dump(mode="json")
            if final.get("sources"):
                turn.emit("sources", {"sources": final["sources"]})
            if final.get("verification"):
                turn.emit("verification", final["verification"])
            for notice in final.get("notices") or []:
                turn.emit("notice", {"text": notice})
            turn.emit("done", final)
        except chat_mod.MessageNotFound:
            turn.emit("error", errors.safe_error(
                errors.NOT_FOUND, "no answered message with that id in this conversation"))
        except Exception as exc:  # noqa: BLE001 - reported on the stream, never a hung client
            errors.record_failure(exc, stage="chat_stream")
            turn.emit("error", errors.safe_error(errors.INTERNAL, "the answer could not be completed"))
        finally:
            progress_mod.unlisten(turn.id)
            progress_mod.finish(turn.id)
            chat_stream.unbind(token)
            turn.close()

    threading.Thread(target=work, daemon=True, name=f"chat-{turn.id}").start()

    async def events():
        yield _sse("turn", {"turn_id": turn.id})
        while True:
            if await request.is_disconnected():
                turn.cancel.set()
            try:
                item = turn.events.get_nowait()
            except Exception:  # queue.Empty
                await asyncio.sleep(0.05)
                continue
            if item is None:
                return
            yield _sse(*item)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/conversations/{conversation_id}/ask/{turn_id}/cancel",
          response_model=schemas.CancelledTurn,
          responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def cancel_turn(conversation_id: str, turn_id: str, request: Request,
                scope: access.AccessScope = Depends(access.current_scope)):
    """Stop a streamed answer. The provider call is closed, the ledger records
    what it cost, and the turn is stored as cancelled with what the reader was
    shown. Only the turn's owner may stop it; any other turn id is 404."""
    from . import chat_stream

    reject_unknown_params(request, set())
    _require_owned_conversation(conversation_id, scope)
    turn = chat_stream.find(turn_id, owner=scope.user_id, unrestricted=scope.unrestricted)
    if turn is None or turn.conversation_id != conversation_id:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no answer being written with that id"))
    turn.cancel.set()
    return {"turn_id": turn_id, "cancelled": True}


# ------------------------------------------------------------------ pages


@app.get("/api/documents/{document_id}/pages", response_model=schemas.PagesResponse,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def document_pages(
    request: Request,
    document_id: str,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    scope: access.AccessScope = Depends(access.current_scope),
):
    reject_unknown_params(request, {"limit", "offset"})
    require_document(document_id, scope)
    rows = connect().execute(
        """SELECT page_no, char_count, needs_ocr, equation_heavy, batch_no,
                  substr(text, 1, 300) AS preview
           FROM pages WHERE document_id = ? ORDER BY page_no LIMIT ? OFFSET ?""",
        (document_id, limit, offset),
    ).fetchall()
    total = connect().execute(
        "SELECT COUNT(*) FROM pages WHERE document_id = ?", (document_id,)
    ).fetchone()[0]
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "pages": [
            dict(r) | {
                "needs_ocr": bool(r["needs_ocr"]),
                "equation_heavy": bool(r["equation_heavy"]),
            }
            for r in rows
        ],
    }


@app.get("/api/documents/{document_id}/page-ledger", response_model=schemas.PageLedger,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def document_page_ledger(
    request: Request,
    document_id: str,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Every page of one document with its per-stage outcome (master order B3).

    SCOPED LIKE THE DOCUMENT: out of scope reads as not found. READ-ONLY: the
    ledger is refreshed by ingestion, fact extraction and review runs, never
    by a GET. A document with no ledger rows yet returns an empty list and a
    `pages_total` of null - "not accounted for", never "zero pages".
    Ids, statuses, counts and rule names only; never page text.
    """
    reject_unknown_params(request, set())
    require_document(document_id, scope)
    return {"document_id": document_id,
            "pages": page_ledger_mod.rows(document_id),
            "coverage": page_ledger_mod.coverage(document_id)}


@app.get("/api/documents/{document_id}/applicability",
         response_model=list[schemas.ApplicabilityStatus],
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def document_applicability(
    request: Request,
    document_id: str,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Every standard in the library, classified for THIS submittal into
    applicable-and-assessable, applicable-but-needs-another-document,
    not-applicable-with-a-reason, or unknown (B5, per the master order).

    READ-ONLY and RECOMPUTED, never a stored verdict - the same reason
    `select()`'s own selection is never persisted as a claim about the
    present without being asked to re-run.
    """
    reject_unknown_params(request, set())
    require_document(document_id, scope)
    return applicability_mod.applicability_with_reasons(
        document_id, allowed_document_ids=scope.allowed_document_ids)


#: Media types for the preview surfaces. A CLOSED MAP with an
#: `application/octet-stream` default, never `mimetypes.guess_type`: the
#: filename is user-supplied, and letting it choose the Content-Type is how a
#: document becomes `text/html` and runs in the reader's origin. Only the types
#: this product previews are named, and everything else downloads.
_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".xls": "application/vnd.ms-excel",
}


def _media_type_for(filename: str) -> str:
    return _MEDIA_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream")


@app.get("/api/documents/{document_id}/original",
         response_class=FileResponse,
         responses={200: {"content": {"application/octet-stream": {}},
                          "description": "The original uploaded bytes"},
                    **schemas.ERRORS_404})
def document_original(
    document_id: str,
    request: Request,
    download: bool = Query(False),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """The ORIGINAL uploaded file, byte for byte.

    Serves the preview surfaces (embedded PDF viewer, workbook preview) and the
    "download original" action, which are the same bytes and must not be two
    different answers.

    SCOPED LIKE EVERY OTHER DOCUMENT READ. `require_document` answers 404 for a
    document outside the caller's scope, so this route cannot become the one
    place a caller reaches content they hold no grant for - which is exactly
    what an unauthenticated preview URL would be. Deleting this check is
    mutation M13.

    `Content-Disposition` is `inline` for preview and `attachment` for
    download, and the filename is quoted rather than interpolated raw: a
    filename is user-supplied text and a bare newline in a header is a header
    injection.
    """
    reject_unknown_params(request, {"download"})
    doc = require_document(document_id, scope)
    stored = Path(doc["stored_path"])
    if not stored.exists():
        # The row outlived its bytes. Said plainly rather than served as an
        # empty file, which would read as a blank document.
        return JSONResponse(
            status_code=404,
            content={"detail": errors.safe_error(
                errors.NOT_FOUND, "the stored original is no longer on disk",
                document_id=document_id)},
        )
    safe_name = str(doc["filename"]).replace("\r", " ").replace("\n", " ").replace('"', "'")
    disposition = "attachment" if download else "inline"
    return FileResponse(
        stored,
        media_type=_media_type_for(safe_name),
        headers={
            "Content-Disposition": f'{disposition}; filename="{safe_name}"',
            # Private: this is document content, and a shared cache holding it
            # would outlive the grant that allowed the read.
            "Cache-Control": "private, max-age=0, no-store",
        },
    )


# ------------------------------------------------------------- standards
#
# THE LIBRARY IS LOGICALLY SEPARATE AND PHYSICALLY THE SAME DATABASE. These
# routes read the same `documents` and `chunks` rows as everything else, under
# the same grants, through the same scope. "A dedicated library" is a statement
# about what a reader sees, never about where the bytes live.


@app.get("/api/standards", response_model=list[schemas.StandardSummary],
         responses=schemas.ERRORS_422)
def list_standards(
    request: Request,
    include_superseded: bool = Query(True),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Every COMPANY_STANDARD the caller may read.

    The role decides what belongs in the library; the grants decide what this
    caller may see. They are ANDed in the query, so the library is always a
    subset of what the caller already holds.
    """
    reject_unknown_params(request, {"include_superseded"})
    return standards_mod.list_standards(
        allowed_document_ids=scope.allowed_document_ids,
        include_superseded=include_superseded)


@app.get("/api/standards/inventory",
         response_model=list[schemas.StandardInventoryEntry],
         responses=schemas.ERRORS_422)
def standards_inventory(
    request: Request,
    include_superseded: bool = Query(True),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """The standards inventory (B5 part 2): every COMPANY_STANDARD the
    caller may read, with family, licence status, source-file hash, and
    whether any submittal the caller may read cites it.

    Same scope rule as `/api/standards` (CLAUDE.md rule 5): the role decides
    what belongs in the library, the grants decide what this caller may see,
    ANDed - never widened by this route.
    """
    reject_unknown_params(request, {"include_superseded"})
    return standards_inventory_mod.inventory_rows(
        allowed_document_ids=scope.allowed_document_ids,
        include_superseded=include_superseded)


@app.get("/api/standards/cited-but-not-held",
         response_model=list[schemas.CitedButNotHeld],
         responses=schemas.ERRORS_422)
def standards_cited_but_not_held(
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Every standard cited by a submittal or a SAES requirement's own
    normative reference that is NOT in the local library, with where it was
    cited - the missing list for the CRS and for the owner to take to the
    standards body.

    Same scope rule as every other standards route (CLAUDE.md rule 5): the
    caller's own grants bound which submittals and which standards this can
    ever see - never widened by this route.
    """
    reject_unknown_params(request, set())
    return standards_inventory_mod.cited_but_not_held(
        allowed_document_ids=scope.allowed_document_ids)


@app.get("/api/standards/missing",
         response_model=list[schemas.MissingStandard],
         responses=schemas.ERRORS_422)
def standards_missing(
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Standards beyond the library - API, ASME, ASTM, ISO, IEC, NFPA, NACE,
    NORSOK, and the client's own - that a submittal or a SAES requirement
    cites and the library does not hold, each with the publisher's own
    catalogue page and whether it has been requested. Nothing is fetched:
    every one of these is sold under licence (standards_acquisition.py).
    Scope: exactly the cited-but-not-held list's (CLAUDE.md rule 5)."""
    reject_unknown_params(request, set())
    return standards_acquisition_mod.missing_standards(
        allowed_document_ids=scope.allowed_document_ids)


@app.post("/api/standards/missing/request",
          response_model=schemas.StandardRequestResult,
          responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_422})
def request_missing_standard(
    body: schemas.StandardRequestBody,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Record that a missing standard has been asked for, under the signed-in
    engineer's name. Only a standard on the caller's own missing list."""
    _require_named_reviewer(scope, "requesting a standard")
    try:
        return standards_acquisition_mod.mark_requested(
            body.identifier, user_id=scope.user_id, note=body.note,
            allowed_document_ids=scope.allowed_document_ids)
    except standards_acquisition_mod.AcquisitionError as exc:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, str(exc)))


@app.post("/api/standards/{document_id}/provenance",
          response_model=schemas.StandardProvenance,
          responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_422})
def record_standard_provenance(
    document_id: str,
    body: schemas.ExternalCopyBody,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Mark an uploaded standard as a copy obtained externally - the client's
    "stored, hashed, cited and marked as externally obtained" - recording
    where it came from, the file's hash, and who recorded it."""
    _require_named_reviewer(scope, "recording where a standard came from")
    try:
        return standards_acquisition_mod.record_external_copy(
            document_id, identifier=body.identifier,
            obtained_from=body.obtained_from, user_id=scope.user_id,
            allowed_document_ids=scope.allowed_document_ids)
    except standards_acquisition_mod.AcquisitionError as exc:
        status = 404 if "no such" in str(exc) else 422
        raise HTTPException(status_code=status, detail=errors.safe_error(
            errors.NOT_FOUND if status == 404 else errors.INVALID_PARAMETER, str(exc)))


@app.get("/api/standards/{document_id}/provenance",
         response_model=schemas.StandardProvenanceRead,
         responses={**schemas.ERRORS_404})
def get_standard_provenance(
    document_id: str,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Where a held standard's copy came from, or null when nothing was
    recorded (not claimed either way)."""
    if document_id not in scope.allowed_document_ids:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no such standard"))
    return {"provenance": standards_acquisition_mod.provenance_of(document_id)}


@app.get("/api/standards/{document_id}/clauses",
         response_model=list[schemas.StandardClause],
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def standard_clauses(
    document_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """The clause hierarchy, read from the chunks the document already has."""
    reject_unknown_params(request, set())
    require_document(document_id, scope)
    return standards_mod.clause_hierarchy(
        document_id, allowed_document_ids=scope.allowed_document_ids)


@app.get("/api/standards/{document_id}/requirements",
         response_model=list[schemas.StandardRequirement],
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def standard_requirements(
    document_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    reject_unknown_params(request, set())
    require_document(document_id, scope)
    return standards_mod.list_requirements(
        document_id, allowed_document_ids=scope.allowed_document_ids)


@app.post("/api/standards/{document_id}/requirements/extract",
          response_model=schemas.StandardExtraction,
          responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def extract_standard_requirements(
    document_id: str,
    request: Request,
    acknowledge_orphaned_findings: bool = Query(False),
    scope: access.AccessScope = Depends(access.current_scope),
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """Re-read a standard and record every obligation it states.

    THE ADMIN CAPABILITY IS REQUIRED. Extraction replaces the unconfirmed rows
    for a standard, which changes what every later reader sees, so it needs the
    role that answers for everyone - the same reasoning as classification.
    Confirmed rows are never deleted. B38: replacing rows review findings cite
    is refused (409) unless acknowledge_orphaned_findings=true.
    """
    reject_unknown_params(request, {"acknowledge_orphaned_findings"})
    require_document(document_id, scope)
    return standards_mod.extract_requirements(
        document_id, allowed_document_ids=scope.allowed_document_ids, actor=actor,
        acknowledge_orphaned_findings=acknowledge_orphaned_findings)


@app.get("/api/standards/{document_id}/tables",
         response_model=schemas.TableReport,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def standard_tables(
    document_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Every table of a standard, parsed or explicitly UNPARSED.

    The unparsed ones are the point: `parsed_fraction` is the honest measure of
    how much of a standard's tabular content was actually read, and a
    requirement set with the sentences and none of the tables looks complete
    while missing the numbers an engineer checks against.
    """
    reject_unknown_params(request, set())
    require_document(document_id, scope)
    return standards_mod.table_report(
        document_id, allowed_document_ids=scope.allowed_document_ids)


@app.get("/api/documents/{document_id}/table-consistency",
         response_model=schemas.TableConsistency,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def document_table_consistency(
    document_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Internal consistency of the document's numeric tables (#531): bands that
    overlap or leave a gap, a Total that is not the sum, a column that is not
    its own stated formula. Each finding names the page, chunk, rows and cells.
    It never says a table is consistent: `checks_run` says what was checked and
    a table with nothing to check is counted as such. Scope: the caller's
    grants (404 for a document they may not read)."""
    reject_unknown_params(request, set())
    require_document(document_id, scope)
    return table_consistency_mod.check_document(
        document_id, allowed_document_ids=scope.allowed_document_ids)


@app.get("/api/standards/conflicts",
         response_model=list[schemas.RequirementConflict],
         responses=schemas.ERRORS_422)
def standard_conflicts(
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Fields two standards limit differently. SURFACED, NEVER RESOLVED.

    Only over standards the caller may read, so a conflict involving a document
    they hold no grant for is not shown at all - rather than shown with one
    side missing, which would disclose that the other side exists.
    """
    reject_unknown_params(request, set())
    return standards_mod.conflicts(allowed_document_ids=scope.allowed_document_ids)


@app.get("/api/standards/verification-queue",
         response_model=list[schemas.StandardRequirement],
         responses=schemas.ERRORS_422)
def standard_verification_queue(
    request: Request,
    limit: int = Query(200, ge=1, le=500),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Requirements awaiting a human, across every standard the caller may read."""
    reject_unknown_params(request, {"limit"})
    rows = standards_mod.verification_queue(
        allowed_document_ids=scope.allowed_document_ids, limit=limit)
    return [
        {**row, "exceptions": standards_mod.requirements_3b.decode_exceptions(
            row.get("exceptions"))}
        for row in rows
    ]


@app.post("/api/standards/requirements/{requirement_id}/decision",
          response_model=schemas.RequirementDecisionResult,
          responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def decide_standard_requirement(
    requirement_id: str,
    body: schemas.RequirementDecisionRequest,
    acknowledge_orphaned_findings: bool = Query(False),
    scope: access.AccessScope = Depends(access.current_scope),
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """Confirm, edit or reject an extracted requirement. ADMIN, and AUDITED.

    A correction sets `extraction_method` to 'human': after it the row is a
    person's statement rather than a machine's guess, and nothing downstream
    may present it as extracted. B38: rejecting a requirement review findings
    cite is refused (409) unless acknowledge_orphaned_findings=true.
    """
    try:
        return standards_mod.decide_requirement(
            requirement_id, decision=body.decision,
            allowed_document_ids=scope.allowed_document_ids,
            actor=actor, edits=body.edits,
            acknowledge_orphaned_findings=acknowledge_orphaned_findings)
    except standards_mod.RequirementError as exc:
        raise HTTPException(status_code=422, detail=errors.safe_error(
            errors.INVALID_PARAMETER, str(exc))) from exc


@app.post("/api/standards/{document_id}/requirements/extract-async",
          response_model=schemas.ExtractionJob,
          responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def queue_standard_extraction(
    document_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """Queue extraction on the EXISTING worker rather than blocking this request.

    Master plan section 26 asks that long-running work use the background job
    mechanism and expose progress without blocking. Section 24 allows one
    worker and puts background standard reprocessing LAST, so this queues onto
    the ingestion worker and is drained only when no document needs processing.
    """
    reject_unknown_params(request, set())
    require_document(document_id, scope)
    # INTERACTIVE (#177): an administrator is waiting on this one, so it
    # runs ahead of the backfill the ingestion hook queues for every standard.
    job_id = standards_mod.enqueue_extraction(
        document_id, actor=actor, priority=job_queue_mod.PRIORITY_INTERACTIVE)
    return {"job_id": job_id, "document_id": document_id, "state": "queued"}


@app.get("/api/jobs", response_model=schemas.JobList,
         responses={**schemas.ERRORS_422})
def list_jobs(
    request: Request,
    document_id: str | None = Query(None),
    state: str | None = Query(None),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """B11: background jobs on documents the caller may read."""
    reject_unknown_params(request, {"document_id", "state"})
    return {"jobs": job_queue_mod.list_jobs(
        allowed_document_ids=scope.allowed_document_ids,
        document_id=document_id, state=state)}


@app.get("/api/jobs/{job_id}", response_model=schemas.Job,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def get_job(job_id: str, request: Request,
            scope: access.AccessScope = Depends(access.current_scope)):
    """B11: one job - 404 when absent or on a document the caller cannot read."""
    reject_unknown_params(request, set())
    job = job_queue_mod.get_job(job_id, allowed_document_ids=scope.allowed_document_ids)
    if job is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no job with that id"))
    return job


@app.post("/api/jobs/{job_id}/cancel", response_model=schemas.Job,
          responses={**schemas.ERRORS_404, **schemas.ERRORS_409, **schemas.ERRORS_422})
def cancel_job(
    job_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """B11: withdraw a job that has not started. The same administrators who may
    queue work may withdraw it, and only on documents they can read. A running
    or finished job is refused with 409 and its state - never reported as
    cancelled when it was not."""
    reject_unknown_params(request, set())
    if job_queue_mod.get_job(job_id, allowed_document_ids=scope.allowed_document_ids) is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no job with that id"))
    job = job_queue_mod.get_job(job_id, allowed_document_ids=scope.allowed_document_ids)
    if job["stage"] == review_jobs_mod.STAGE:
        # P3: a running review stops at its next step; the response says it
        # is still running with cancellation requested - never "cancelled".
        cancelled, state = review_jobs_mod.cancel(job_id, actor_user_id=(actor or {}).get("id"))
    else:
        cancelled, state = job_queue_mod.cancel(job_id, actor_user_id=(actor or {}).get("id"))
    if not cancelled:
        raise HTTPException(status_code=409, detail=errors.safe_error(
            errors.INVALID_PARAMETER,
            f"this job can no longer be cancelled; it is {state}"))
    return job_queue_mod.get_job(job_id, allowed_document_ids=scope.allowed_document_ids)


@app.get("/api/standards/{document_id}/extraction-state",
         response_model=schemas.ExtractionJob,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def standard_extraction_state(
    document_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    reject_unknown_params(request, set())
    require_document(document_id, scope)
    state = standards_mod.extraction_job_state(
        document_id, allowed_document_ids=scope.allowed_document_ids)
    return state or {"state": "none"}


@app.get("/api/standards/{document_id}/revisions",
         response_model=list[schemas.StandardSummary],
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def standard_revisions(
    document_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Every revision of the same standard number the caller may read."""
    reject_unknown_params(request, set())
    require_document(document_id, scope)
    return standards_mod.revision_history(
        document_id, allowed_document_ids=scope.allowed_document_ids)


@app.post("/api/standards/{document_id}/supersede",
          response_model=schemas.SupersedeRequest,
          responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def supersede_standard(
    document_id: str,
    body: schemas.SupersedeRequest,
    scope: access.AccessScope = Depends(access.current_scope),
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """Mark a standard as replaced, or clear the mark. ADMIN, and AUDITED.

    A superseded standard stops being SELECTED for new reviews and stays fully
    readable and citable - an engineer must still be able to open the revision
    a submittal was reviewed against last year.
    """
    require_document(document_id, scope)
    try:
        result = standards_mod.supersede(
            document_id, body.superseded_by,
            allowed_document_ids=scope.allowed_document_ids, actor=actor)
    except standards_mod.RequirementError as exc:
        raise HTTPException(status_code=422, detail=errors.safe_error(
            errors.INVALID_PARAMETER, str(exc), document_id=document_id)) from exc
    return {"superseded_by": result["superseded_by"]}


@app.get("/api/documents/{document_id}/workbook",
         response_model=schemas.WorkbookPreview,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def document_workbook(
    document_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """A read-only view of a stored workbook: sheets, and populated cells.

    Scoped like every other document read - `require_document` answers 404
    outside the caller's scope.

    THE ORIGINAL IS NOT TOUCHED. This reads the stored bytes and returns a
    projection of them; `GET .../original` still serves the file itself,
    unchanged. A preview is never the authority for what the workbook says.
    """
    reject_unknown_params(request, set())
    doc = require_document(document_id, scope)
    stored = Path(doc["stored_path"])
    if not str(doc["filename"]).lower().endswith(".xlsx") or not stored.exists():
        # Not a workbook, or the bytes are gone. Both are "there is nothing to
        # preview here", and neither is an error the reader can act on.
        return JSONResponse(
            status_code=404,
            content={"detail": errors.safe_error(
                errors.NOT_FOUND, "no workbook to preview for that document",
                document_id=document_id)},
        )
    try:
        return workbook_mod.read_sheets(stored)
    except workbook_mod.WorkbookError as exc:
        # The file passed upload validation and still cannot be read now.
        # Reported as a 422 about THIS file rather than a 500: nothing is
        # broken on the server.
        raise HTTPException(status_code=422, detail=errors.safe_error(
            errors.INVALID_PARAMETER, "that workbook could not be read",
            document_id=document_id)) from exc


@app.get("/api/documents/{document_id}/pages/{page_no}/image",
         response_class=FileResponse,
         responses={200: {"content": {"image/png": {}}, "description": "Rendered page"},
                    **schemas.ERRORS_404, **schemas.ERRORS_422})
def page_image(
    document_id: str,
    page_no: int,
    request: Request,
    dpi: int = Query(150, ge=50, le=300),
    chunk_id: str | None = Query(None),
    q: str | None = Query(None, max_length=500),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Render one page to PNG on demand, cached by content hash.

    The durable answer to degraded equations and flattened tables: whatever
    the extracted text lost, the reader can see the real page.

    Pass `chunk_id` and `q` together to have the answering span BOXED on the
    image. An engineer who sees the answer outlined on the specification page
    they already know stops having to trust the extraction at all.

    When the span cannot be located the page is returned WITHOUT a box and
    `X-Answer-Located: 0` says so. Never a box in a plausible-looking wrong
    place: one wrong box and no box is ever trusted again.
    """
    reject_unknown_params(request, {"dpi", "chunk_id", "q"})
    doc = require_document(document_id, scope)
    if dict(doc).get("pagination") == "flow":
        # A Word document has no printed pages: rendering it would show a
        # layout that matches none of its reading pages or citations.
        return JSONResponse(
            status_code=404,
            content={"detail": errors.safe_error(
                errors.NOT_FOUND, "a Word document has no printed pages; it is cited by "
                "heading path and paragraph", document_id=document_id)},
        )

    rects: list[tuple[float, float, float, float]] = []
    if chunk_id and q:
        # The answering span depends on the QUESTION, so it is recomputed here
        # rather than stored: the same passage highlights differently for two
        # different questions, and passing the text itself would not fit in a
        # URL. Given the chunk and the question, the span is derived by exactly
        # the same code the answer used.
        located = highlight_mod.for_chunk(document_id, chunk_id, q)
        rects = located.get("rects", [])

    try:
        if rects:
            path = pageimage_mod.render_page_with_highlight(doc, page_no, rects, dpi=dpi)
        else:
            path = pageimage_mod.render_page(doc, page_no, dpi=dpi)
    except pageimage_mod.PageOutOfRange as e:
        return JSONResponse(
            status_code=404,
            content={"detail": errors.safe_error(errors.NOT_FOUND, str(e), document_id=document_id)},
        )
    headers = {"Cache-Control": "max-age=86400"}
    if chunk_id and q:
        # Stated in a header so the caller can say "location could not be
        # confirmed" instead of the reader assuming an unboxed page means the
        # answer is not on it.
        headers["X-Answer-Located"] = "1" if rects else "0"
    return FileResponse(path, media_type="image/png", headers=headers)


# ----------------------------------------------------------------- chunks


@app.get("/api/documents/{document_id}/chunks", response_model=schemas.ChunkPage,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def document_chunks(
    request: Request,
    document_id: str,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    retrievable: str = Query("true"),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Chunks for a document.

    retrievable = "true"  (default) only chunks search can see
                  "false"           only the excluded ones, for inspection
                  "all"             everything
    """
    reject_unknown_params(request, {"limit", "offset", "retrievable"})
    require_document(document_id, scope)
    retrievable = validate_retrievable(retrievable)
    clause = retrievable_clause(retrievable)
    conn = connect()
    rows = conn.execute(
        f"""SELECT id, ordinal, page_start, page_end, section, kind, token_count,
                   content_hash, retrievable, quality_flags, locator, text
            FROM chunks WHERE document_id = ?{clause}
            ORDER BY ordinal LIMIT ? OFFSET ?""",
        (document_id, limit, offset),
    ).fetchall()
    total = conn.execute(
        f"SELECT COUNT(*) FROM chunks WHERE document_id = ?{clause}", (document_id,)
    ).fetchone()[0]
    return {
        "total_matching": total,
        "limit": limit,
        "offset": offset,
        "chunks": [dict(r) | {"retrievable": bool(r["retrievable"])} for r in rows],
    }


@app.get("/api/documents/{document_id}/excluded", response_model=schemas.ExclusionsResponse,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def document_excluded(
    request: Request,
    document_id: str,
    limit: int = Query(50, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Everything excluded from search, with the rule that excluded it.

    Nothing is dropped silently: every excluded page and chunk is recorded
    here with its reason and the text that was dropped.
    """
    reject_unknown_params(request, {"limit", "offset"})
    require_document(document_id, scope)
    conn = connect()
    summary = [
        dict(r)
        for r in conn.execute(
            """SELECT scope, rule, COUNT(*) AS count,
                      SUM(text_length) AS characters_dropped,
                      COALESCE(SUM(clause_headings), 0) AS clause_heading_pages
               FROM exclusions WHERE document_id = ?
               GROUP BY scope, rule ORDER BY clause_heading_pages DESC, count DESC""",
            (document_id,),
        )
    ]
    rows = conn.execute(
        """SELECT scope, page_start, page_end, chunk_id, rule, reason,
                  text_length, text_sample, clause_headings
           FROM exclusions WHERE document_id = ?
           ORDER BY clause_headings DESC, page_start, id LIMIT ? OFFSET ?""",
        (document_id, limit, offset),
    ).fetchall()
    total = conn.execute(
        "SELECT COUNT(*) FROM exclusions WHERE document_id = ?", (document_id,)
    ).fetchone()[0]
    return {
        "total": total,
        "summary": summary,
        "limit": limit,
        "offset": offset,
        "excluded": [dict(r) for r in rows],
    }


# ------------------------------------------------------------------ admin
#
# The administration screen: users, disciplines and document grants, replacing
# `scripts/seed_access.py`, including one-time password setup and reset. Implements
# `docs/design-admin-screen.md`, which was written before these routes existed.
#
# EVERY ROUTE HERE DEPENDS ON `admin.current_admin`, AND A NON-ADMIN GETS 404.
# Not 403. A 403 confirms both that the route exists and that the caller found
# the thing it guards, and the admin surface is the most interesting one on
# this API to probe. It is the same rule `require_document` already follows for
# a document the caller may not read, and it is why these routes take
# `current_admin` rather than `current_scope`: the question is not which
# documents this request may see, it is whether this request may be here at
# all.


@app.post("/api/admin/models/unload", response_model=schemas.AdminModelsFreed,
          responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def admin_free_model_memory(request: Request,
                            actor: dict | None = Depends(admin_mod.current_admin)):
    """Give back the memory the local models hold (#666): ask Ollama to unload
    every resident model (keep_alive 0). A non-admin gets the same 404 as every
    other route here. Nothing is sent but model names; the next question pays a
    cold load, which the button's label says."""
    reject_unknown_params(request, set())
    return model_memory_mod.free_all()


@app.get("/api/admin/users", response_model=schemas.AdminUserList,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def admin_list_users(request: Request,
                     actor: dict | None = Depends(admin_mod.current_admin)):
    """Every user, with disciplines and the "no discipline" warning.

    Carries NO setup token, for any user, ever - only its SHA-256 is stored,
    so there is no plaintext here to return.
    """
    reject_unknown_params(request, set())
    return admin_mod.list_users()


@app.post("/api/admin/users", response_model=schemas.AdminUserCreated,
          status_code=201,
          responses={**schemas.ERRORS_404, **schemas.ERRORS_409,
                     **schemas.ERRORS_422})
def admin_create_user(body: admin_mod.CreateUserRequest,
                      actor: dict | None = Depends(admin_mod.current_admin)):
    """Create a user and return a one-time setup token.

    NO PASSWORD IS ACCEPTED OR RETURNED, and there is no parameter for one.
    The reasons are argued in the contract: `seed_access.py` guarantees that a
    password can only ever arrive by being typed interactively twice, an admin
    who types someone's password knows it, and a password in a request body is
    a password in a log - which this project found in a 422 handler that
    echoed the submitted body back.
    """
    return admin_mod.create_user(body, actor)


@app.delete("/api/admin/users/{user_id}",
            response_model=schemas.AdminUserDeactivated,
            responses={**schemas.ERRORS_404, **schemas.ERRORS_409})
def admin_deactivate_user(user_id: str,
                          actor: dict | None = Depends(admin_mod.current_admin)):
    """Deactivate a user. Idempotent, and never a delete.

    An admin cannot deactivate themselves: without that rule the last admin
    can lock everyone out of a system whose only other door is a terminal.
    """
    return admin_mod.deactivate_user(user_id, actor)


@app.post("/api/admin/users/{user_id}/password-reset",
          response_model=schemas.AdminUserCreated,
          responses={**schemas.ERRORS_404})
def admin_issue_password_reset(
        user_id: str,
        actor: dict | None = Depends(admin_mod.current_admin)):
    """Issue a replacement shown-once token; never accept a password here."""
    return admin_mod.issue_password_reset(user_id, actor)


@app.get("/api/admin/disciplines", response_model=schemas.AdminDisciplineList,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def admin_list_disciplines(request: Request,
                           actor: dict | None = Depends(admin_mod.current_admin)):
    """Disciplines with user and document counts.

    A discipline with no documents is flagged, because everyone in it logs in
    successfully and then sees an empty corpus - which during a demo looks
    exactly like broken search rather than a missing grant.
    """
    reject_unknown_params(request, set())
    return admin_mod.list_disciplines()


@app.get("/api/admin/grants", response_model=schemas.AdminGrantList,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def admin_list_grants(request: Request,
                      actor: dict | None = Depends(admin_mod.current_admin)):
    """Documents and the disciplines that can see them.

    A document nobody can see is flagged: it is invisible in every search and
    looks like a broken upload.
    """
    reject_unknown_params(request, set())
    return admin_mod.list_grants()


@app.put("/api/admin/grants", response_model=schemas.AdminGrantResult,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def admin_grant(body: admin_mod.GrantRequest,
                actor: dict | None = Depends(admin_mod.current_admin)):
    """Grant a document to a discipline. Idempotent - a retried click cannot
    double-grant and cannot fail."""
    return admin_mod.grant(body, actor)


@app.delete("/api/admin/grants", response_model=schemas.AdminGrantResult,
            responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def admin_revoke_grant(body: admin_mod.GrantRequest,
                       actor: dict | None = Depends(admin_mod.current_admin)):
    """Revoke a document from a discipline. 200 whether or not it was granted.

    The document leaves that discipline's members' search results on their NEXT
    REQUEST: `access.scope_for_user` re-runs the grant-table join every request
    and caches nothing, so deleting the row IS the invalidation. See
    `admin.revoke_grant`, where that is stated at the line it happens.
    """
    return admin_mod.revoke_grant(body, actor)


# ------------------------------------------ the read-only database explorer
#
# THE SAME GATE AS EVERY OTHER ADMIN ROUTE, and that is the point: this is the
# single most interesting surface on the API to probe, because it names every
# table in the system. `admin.current_admin` answers a non-admin with 404, so
# a caller who is not an admin cannot even learn that these routes exist.
#
# A WINDOW, NOT A WORKBENCH. Three GETs and nothing else - no POST, no PATCH,
# no DELETE, and no request model anywhere that accepts a value to store. An
# explorer that could write would be a second, unaudited path into every table
# the real endpoints guard with scope checks and honesty invariants.
#
# THE EXPLORER READS EVERY TABLE, NOT ONLY WHAT THE ADMIN'S GRANTS COVER. That is
# a decision, not an oversight (owner, 2026-10-07: "admin can read everything").
# It is why the gate above matters, why credential columns are masked, and why
# the document routes' grant-based scope is NOT a statement about this screen.
# If an administrator must one day be limited to granted documents here too,
# `admin_explorer.read_rows` is where that filter goes.
#
# CREDENTIAL MATERIAL IS MASKED IN `admin_explorer`, before it reaches the
# wire. Not in the UI: a browser's network tab renders a JSON response just
# fine, so masking on the client would be decoration over a disclosure.


@app.get("/api/admin/db/tables", response_model=schemas.AdminDbTableList,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def admin_db_tables(request: Request,
                    actor: dict | None = Depends(admin_mod.current_admin)):
    """Every user table with its row count. SQLite internals excluded."""
    reject_unknown_params(request, set())
    return {"tables": explorer_mod.list_tables(connect())}


@app.get("/api/admin/db/tables/{name}", response_model=schemas.AdminDbTableInfo,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def admin_db_table(name: str, request: Request,
                   actor: dict | None = Depends(admin_mod.current_admin)):
    """One table's columns, with type, nullability and whether its values are
    masked.

    An unknown table is 404 - the same answer a non-admin gets for the whole
    route - so probing for a table name tells a caller nothing they did not
    already have.
    """
    reject_unknown_params(request, set())
    info = explorer_mod.table_info(connect(), name)
    if info is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no such table"))
    return info


@app.get("/api/admin/db/tables/{name}/rows", response_model=schemas.AdminDbRows,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def admin_db_rows(
    name: str,
    request: Request,
    limit: int = Query(50, ge=1, description="rows to return; capped server-side"),
    offset: int = Query(0, ge=0, description="rows to skip"),
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """A page of rows, with the whole table's count beside it.

    The cap lives in `admin_explorer.MAX_ROWS` and is applied there whatever
    this route is asked for, so a caller cannot page the entire corpus into
    one response by asking loudly.
    """
    reject_unknown_params(request, {"limit", "offset"})
    page = explorer_mod.read_rows(connect(), name, limit=limit, offset=offset)
    if page is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no such table"))
    return page


# ---------------------------------------------- the Comment Resolution Sheet
#
# ONE COMPOSITION, TWO RENDERINGS. The .xlsx a client receives and the preview
# an engineer reads on screen are the same content: `_crs_content` decides
# what the sheet says, `crs_export.build_crs_view` shapes it, and the export
# draws that view into the client's template. Two code paths that could
# disagree about what the CRS says is the defect this project has been
# fighting - a preview showing something other than the delivered file would
# be worse than no preview at all.


def _crs_submittal_label(document) -> str:
    """The CRS header's "Submittal No.": a recorded number if an engineer
    entered one, else the document's own number with its revision, else ""."""
    if document is None:
        return ""
    recorded = (document["transmittal_number"] or "").strip()
    if recorded:
        return recorded
    number = (document["document_number"] or "").strip()
    if not number:
        return ""
    revision = re.sub(r"(?i)^rev(ision)?\.?\s*", "", (document["revision"] or "").strip())
    return f"{number} Rev {revision}" if revision else number


def _crs_scope_of(submittal_id: str) -> tuple[str, str]:
    """(crs scope key, printed label) for one submittal: its DOCUMENT NUMBER's
    sequence (read from its own page by the classifier, stable across
    revisions), or the sequence it was fixed to when its first comment was
    numbered. Never the transmittal number, which changes every submission."""
    row = connect().execute(
        "SELECT document_number FROM document_classification WHERE document_id = ?",
        (submittal_id,)).fetchone()
    number = (row["document_number"] if row is not None else None) or ""
    return crs_numbers_mod.scope_of_document(submittal_id, number)


def _mint_crs_numbers(review_run_id: str | None, scope: access.AccessScope) -> None:
    """Give every CRS comment an engineer has made their own its permanent
    number (`crs_numbers`). Called by the WRITE routes that make a comment an
    engineer's - a finding edited, confirmed or accepted, a comment filed from
    chat, the final code recorded - never by the export or preview.

    The rows are composed exactly as the export composes them, so the keys
    minted here are the keys the export looks up. An unconfirmed machine draft
    gets no number: it is not a comment yet, and may never be issued.

    NEVER FAILS THE CALLER'S SAVE. The engineer's decision is already stored
    when this runs; a failure here is logged and the numbers are minted by the
    next write on the run, rather than answering 500 about a saved decision.
    """
    if not review_run_id:
        return
    import logging
    try:
        run = submittal_review_mod.get_review_run(
            review_run_id, allowed_document_ids=scope.allowed_document_ids)
        if run is None:
            return
        rows, meta, _name, _stamp = _crs_content(review_run_id, scope, "internal")
        submittal_id = run["submittal_document_id"]
        crs_scope, label = _crs_scope_of(submittal_id)
        # Carried-forward rows are already numbered and are not this run's to
        # re-snapshot; every other confirmed row is numbered (if new) and its
        # snapshot refreshed, so a later carry-forward prints what it last said.
        mine = [row for row in rows
                if row.get("engineer_confirmed") and row.get("crs_row_key")
                and row.get("row_kind") != crs_mapping_mod.ROW_KIND_CARRIED_FORWARD]
        if mine:
            crs_numbers_mod.assign(
                crs_scope, label, [row["crs_row_key"] for row in mine],
                document_id=submittal_id, review_run_id=review_run_id,
                snapshots={row["crs_row_key"]: row for row in mine},
                user_id=scope.user_id)
        # A comment confirmed (so numbered) and then rejected is withdrawn -
        # never issued, never carried forward (audit 2026-09-30).
        if meta.get("rejected_row_keys"):
            crs_numbers_mod.withdraw(crs_scope, meta["rejected_row_keys"],
                                     user_id=scope.user_id)
    except HTTPException:
        return
    except Exception:  # noqa: BLE001 - see docstring: never fail a saved decision
        logging.getLogger(__name__).warning(
            "CRS numbers not minted for run %s; the next write will retry",
            review_run_id, exc_info=True)


def _display_names(user_ids: set[str]) -> dict[str, str]:
    """{user id: display name} for the ids that have a non-empty display name
    on record. An id with none is absent - the caller prints the id rather
    than invent a name."""
    ids = sorted(i for i in user_ids if i)
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    return {r["id"]: r["display_name"] for r in connect().execute(
        f"SELECT id, display_name FROM users WHERE id IN ({marks})", tuple(ids))
        if r["display_name"]}


def _prior_rejections(submittal_id: str, allowed: frozenset[str]
                      ) -> dict[str, tuple[str | None, str | None]]:
    """{comment key: (rejected by, rejected at)} for every comment an engineer
    rejected on ANY run of this submittal the caller may read - the latest
    rejection per key. Read only; keys as `crs_mapping.finding_comment_key`
    gives them, over the same CRS context the rows are built from."""
    runs = [r["id"] for r in connect().execute(
        "SELECT id FROM review_runs WHERE submittal_document_id = ?", (submittal_id,))]
    rejected: list[dict] = []
    for run_id in runs:
        rejected.extend(f for f in submittal_review_mod.list_run_findings(
            run_id, allowed_document_ids=allowed)
            if f.get("approval_status") == "rejected")
    if not rejected:
        return {}
    comparison_mod.attach_crs_context(rejected)
    out: dict[str, tuple[str | None, str | None]] = {}
    for f in sorted(rejected, key=lambda f: f.get("approved_at") or ""):
        out[crs_mapping_mod.finding_comment_key(f)] = (f.get("approved_by"), f.get("approved_at"))
    return out


def _crs_content(review_run_id: str, scope: access.AccessScope, copy: str = "internal"
                 ) -> tuple[list[dict], dict, str, str]:
    """One run's CRS rows and meta, with the scope question asked once.

    Returns (rows, meta, submittal filename, date stamp). A run the caller may
    not read, or one that is not there, raises 404 here - the same answer for
    both, because a different one would confirm the run exists.

    MASTER PLAN SECTIONS 13 AND 17. `crs_mapping` decides which findings enter
    a CRS and as what text; `crs_export` renders it. This composes them and
    supplies the meta, and every field of that meta comes from real data or is
    left BLANK:

      document_title          the submittal's own filename
      submittal_number        the submittal's own number: one an engineer
                              recorded in the metadata editor, else its
                              document number and revision read from its page
                              (`_crs_submittal_label`),
                              and BLANK when it carried none
      date_issued             today - the date this file was exported, which
                              is the only date this system actually knows
      company_transmittal     BLANK. Nobody has issued one.
      contractor_transmittal  BLANK. The contractor has not responded.
      recommended_code        the run's recommendation, and its reason, both
                              verbatim - never re-worded here

    A blank transmittal number renders as NOTHING rather than as a plausible
    placeholder. A CRS carrying an invented transmittal number is a document
    that lies about its own provenance to whoever receives it.
    """
    allowed = scope.allowed_document_ids
    run = submittal_review_mod.get_review_run(
        review_run_id, allowed_document_ids=allowed)
    if run is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no review run with that id"))

    submittal_id = run["submittal_document_id"]
    # LEFT JOIN, not an inner one: a submittal that was never classified has
    # no metadata row, and it must still export - with its number blank.
    document = connect().execute(
        "SELECT d.filename AS filename, c.transmittal_number AS transmittal_number,"
        " c.document_number AS document_number, c.revision AS revision"
        " FROM documents d"
        " LEFT JOIN document_classification c ON c.document_id = d.id"
        " WHERE d.id = ?", (submittal_id,)).fetchone()
    submittal_name = document["filename"] if document else submittal_id
    # THE SUBMITTAL'S OWN NUMBER. Not the company's transmittal and not the
    # contractor's - those name the covering transmittals and are blank below.
    # A number an engineer RECORDED for it (the metadata editor's field) wins;
    # otherwise the document's own number and revision as printed on its page
    # (read by the classifier, `_document_number_hits`). CORRECTED 2026-09-29:
    # this used to read the recorded field alone, described as "captured at
    # upload" - no upload captures it, it was empty on every real submittal,
    # and the sheet printed a blank while the document number sat unused.
    # A submittal with neither leaves this blank; never a placeholder.
    submittal_number = _crs_submittal_label(document)

    findings = submittal_review_mod.list_run_findings(
        review_run_id, allowed_document_ids=allowed)

    # THE STANDARD'S NAME, NOT ITS ID. `crs_mapping` falls back to
    # `standard_document_id` when no name is given, and a CRS whose
    # Page/Section column read `doc_a3df49861559` would be asking an engineer
    # to recognise a hash - the same defect the findings table had.
    names = {
        row["id"]: row["filename"] for row in connect().execute(
            "SELECT id, filename FROM documents")
    }
    for finding in findings:
        finding["standard_name"] = names.get(finding.get("standard_document_id"))
    # CRS quick wins: the clause's parsed limit and the field as the datasheet
    # printed it, for the engineer-voice comment (read-only lookups by id).
    comparison_mod.attach_crs_context(findings)
    # Owner order 2d/2f: a confirmed AI engineering check item is printed
    # "confirmed by <name>" - the engineer's display name, never their id.
    # Section 3: an edited comment names its editor the same way. 2d-2: a
    # confirmed web standards check item does too.
    # Audit 2026-09-30: EVERY confirmed comment, not only AI/web items and
    # edits - a plain confirmed requirement comment printed the raw user id.
    confirmers = {f["confirmed_by"] for f in findings if f.get("confirmed_by")}
    if confirmers:
        marks = ",".join("?" for _ in confirmers)
        people = {r["id"]: r["display_name"] for r in connect().execute(
            f"SELECT id, display_name FROM users WHERE id IN ({marks})", tuple(confirmers))}
        for finding in findings:
            # A name only when one is on record - never invented; the id
            # stays the fallback in `crs_mapping`.
            if people.get(finding.get("confirmed_by")):
                finding["confirmed_by_name"] = people[finding["confirmed_by"]]

    outcome = comparison_mod.run_outcome(
        review_run_id, allowed_document_ids=allowed) or {}
    # B3: the pages this run could not read into fields, AS STORED ON THE RUN,
    # so the CRS names the same pages the findings were decided on.
    unread = ((outcome.get("page_coverage") or {})
              .get("pages_not_read_into_fields") or [])
    missing = _missing_references(submittal_id, allowed)
    rows = crs_mapping_mod.build_crs_rows(findings, missing, submittal_name,
                                          unread_pages=unread)
    # PERMANENT COMMENT NUMBERS, READ ONLY. Minted by the write routes that
    # make a comment an engineer's (`_mint_crs_numbers`); this composition
    # serves the export and the preview, which write nothing.
    crs_scope, _crs_label = _crs_scope_of(submittal_id)
    crs_keys = crs_numbers_mod.row_keys(rows)
    numbered = crs_numbers_mod.lookup(crs_scope, crs_keys)
    # A REJECTED COMMENT IS NEVER ISSUED (audit 2026-09-30). Its key is not a
    # row of this sheet, so the carry-forward below printed it as "carried
    # forward from an earlier review". Its keys go to `_mint_crs_numbers`
    # (the write that follows every rejection), which withdraws the number.
    meta_rejected_keys = sorted(
        crs_mapping_mod.rejected_comment_keys(findings) - set(crs_keys))
    for row, key in zip(rows, crs_keys):
        row["crs_row_key"] = key
        if key in numbered and numbered[key].get("status") == crs_numbers_mod.WITHDRAWN:
            # A draft re-raising a comment an engineer rejected: it keeps no
            # number and is NOT an engineer's confirmation.
            continue
        if key in numbered:
            record = numbered[key]
            row["crs_ref"] = record["ref"]
            row["crs_status"] = crs_numbers_mod.resolution_cell(record)
            row["crs_response"] = crs_numbers_mod.response_cell(record)
            # A NUMBER IS AN ENGINEER'S CONFIRMATION, CARRIED. It is only ever
            # minted for a comment an engineer made theirs, and the key is the
            # comment's subject including the value the sheet states - so the
            # same comment raised again by a re-run or on a resubmittal is the
            # one already confirmed, and is issued as such.
            row["engineer_confirmed"] = True
    # A DRAFT THE ENGINEER ALREADY REJECTED SAYS SO (audit leftover
    # 2026-09-30). A new run of the same submittal raises the same comment
    # again as an unconfirmed draft; it is kept (a new run may be right), but
    # the engineer is never asked twice blind: its byline names who rejected
    # it and when, from the rejection on record. Never on a confirmed row.
    rejections = _prior_rejections(submittal_id, allowed)
    carried = crs_numbers_mod.open_elsewhere(crs_scope, set(crs_keys))
    people = _display_names(
        {by for by, _at in rejections.values() if by}
        | {who for who in (crs_mapping_mod.byline_person(r.get("comment_by"))
                           for r in carried) if who})
    for row in rows:
        seen = rejections.get(row.get("comment_key") or "")
        if seen is None or row.get("engineer_confirmed"):
            continue
        by, at = seen
        note = "previously rejected" + (
            f" by {people.get(by) or by}" if by else "") + (
            f" on {at[:10]}" if at else "")
        row["previously_rejected"] = note
        row["comment_by"] = " - ".join(p for p in (row.get("comment_by"), note) if p)
    # CARRY-FORWARD (industry practice): an Open comment from an earlier run
    # or revision of this submittal that this run no longer raises stays on
    # the sheet until a reviewer closes it - never dropped because a later
    # run stopped producing it. Read only, from what the comment last said.
    # A comment an engineer rejected before issue is WITHDRAWN (not Open) by
    # `_mint_crs_numbers`, so `open_elsewhere` never returns it. A byline
    # snapshotted before bylines printed names ("confirmed by eng-1") is
    # resolved to the display name here when one is on record (audit
    # leftover 2026-09-30) - never invented.
    for record in carried:
        rows.append({
            "finding_id": "",
            "document_name": record.get("document_name") or submittal_name,
            "page_section": record.get("page_section") or "",
            "comment": record.get("comment") or "",
            "comment_by": " - ".join(p for p in (
                crs_mapping_mod.resolve_byline(record.get("comment_by"), people),
                "carried forward from an earlier review") if p),
            "standard_reference": record.get("standard_reference") or "",
            "row_kind": crs_mapping_mod.ROW_KIND_CARRIED_FORWARD,
            "engineer_confirmed": True,
            "crs_row_key": record["row_key"],
            "crs_ref": record["ref"],
            "crs_status": crs_numbers_mod.resolution_cell(record),
            "crs_response": crs_numbers_mod.response_cell(record),
        })
    # #633: THE PARTS THIS REVIEW COULD NOT CHECK, one list for every export. A
    # sheet for a run that failed, stopped, or left large parts unchecked must
    # never look like a complete review.
    unchecked = absence_mod.unchecked_parts(
        run_status=run.get("status"), outcome=outcome,
        partial_findings=int(outcome.get("partial_findings") or 0),
        ai_status=ai_engineering_check_mod.ai_check_status(
            review_run_id, allowed_document_ids=allowed),
        web_status=_json_column(run.get("web_check_status")))
    stamp = _now_date()
    meta = {
        "document_title": submittal_name,
        "submittal_number": submittal_number,
        # Never printed. Half of the key each row's stable reference is
        # minted from, so re-exporting this run quotes the same references.
        "review_run_id": review_run_id,
        "date_issued": stamp,
        # Left blank on purpose - see above. Absent, not invented.
        "company_transmittal": "",
        "contractor_transmittal": "",
        "date_responded": "",
        "recommended_code": run.get("engineer_final_code")
                            or outcome.get("recommended_code") or "",
        "recommended_code_reason": (
            run.get("override_reason") if run.get("engineer_final_code")
            else comparison_mod.plain_outcome(outcome)[0]) or "",
        # B10: WHO DECIDED IT. The AI recommends; only an engineer decides. A
        # CRS carrying the AI's code must say it is not yet a decision.
        "recommended_code_status": (
            crs_export_mod.CODE_DECIDED_BY_ENGINEER if run.get("engineer_final_code")
            else crs_export_mod.CODE_NOT_YET_DECIDED if outcome.get("recommended_code")
            else ""),
        "applicable_standards": _crs_standards(review_run_id, submittal_id, allowed),
        # "internal" (with "AI Review Comments") or "issue" (to the contractor).
        "copy": copy,
        # 2f: the engineer's internal notes, on their own sheet.
        "review_notes": crs_mapping_mod.build_review_notes(findings, missing, unread) + [
            {"note": "Not checked", "standard": "", "count": None, "detail": part["line"]}
            for part in unchecked],
        "unchecked_parts": [part["line"] for part in unchecked],
        "incomplete_notice": absence_mod.notice_for(unchecked),
        # Never printed: the keys of this run's rejected comments, for
        # `_mint_crs_numbers` to withdraw.
        "rejected_row_keys": meta_rejected_keys,
    }
    return rows, meta, submittal_name, stamp


def _crs_standards(review_run_id: str, submittal_id: str,
                   allowed: frozenset[str]) -> list[dict]:
    """B5: the CRS's "Applicable standards" sheet - every standard the run
    considered, under the caller's grants (a standard they may not read is
    not listed), applied ones first, then the cited standards not held.

    The names come from the scoped rows only, never from an unscoped read of
    every filename in the database."""
    rows = submittal_review_mod.list_applicable_standards(
        review_run_id, allowed_document_ids=allowed, include_excluded=True)
    ids = [r["standard_document_id"] for r in rows]
    names = {}
    if ids:
        marks = ",".join("?" for _ in ids)
        names = {r["id"]: r["filename"] for r in connect().execute(
            f"SELECT id, filename FROM documents WHERE id IN ({marks})", ids)}
    out = []
    for row in rows:
        included = bool(row.get("included", 1))
        evidence = ""
        if row.get("evidence_page") is not None:
            evidence = f"page {row['evidence_page']}"
            if row.get("evidence_quote"):
                evidence += f": {row['evidence_quote']}"
        out.append({
            "standard": names.get(row["standard_document_id"]) or "",
            "status": (crs_export_mod.STATUS_APPLIED if included
                       else crs_export_mod.STATUS_CONSIDERED),
            "method": row.get("selection_method") or "",
            "reason": (row.get("selection_reason") or "") + (
                "" if included else f" - {row.get('exclusion_reason') or ''}"),
            "evidence": evidence,
        })
    for ref in _missing_references(submittal_id, allowed):
        # 2g: plain words on the sheet the engineer and client read.
        out.append({"standard": ref, "status": crs_export_mod.STATUS_NOT_IN_LIBRARY,
                    "method": "referenced",
                    "reason": "cited by the submittal and not held locally; "
                              "its requirements were not checked",
                    "evidence": ""})
    return out


def _readiness_payload(submittal_document_id: str, scope: access.AccessScope) -> dict:
    """Owner order section 3: the readiness strip's own numbers - shared by
    the GET route and the re-extraction route below, so "what changed" is
    computed once and cannot drift into two answers (CLAUDE.md rule 8)."""
    allowed = scope.allowed_document_ids
    page_ledger_mod.refresh(submittal_document_id, as_submittal=True)
    pages = page_ledger_mod.coverage(submittal_document_id)
    missing = _missing_references(submittal_document_id, allowed)
    runs = submittal_review_mod.list_review_runs(
        allowed_document_ids=allowed, submittal_document_id=submittal_document_id)
    # The latest COMPLETED run: a failed or still-running one produced no
    # result to compare against.
    last = next((r for r in runs if r.get("status") == "completed"), None)
    changes: list[str] = []
    if last is not None:
        since = last.get("completed_at") or last.get("updated_at") or ""
        newer_facts = connect().execute(
            "SELECT COUNT(*) FROM submittal_facts WHERE submittal_document_id = ?"
            " AND superseded_at IS NULL AND COALESCE(updated_at, created_at) > ?",
            (submittal_document_id, since)).fetchone()[0]
        if newer_facts:
            changes.append(f"{newer_facts} datasheet value(s) read since the last run")
        newer_standards = [r["filename"] for r in connect().execute(
            "SELECT d.id, d.filename FROM documents d JOIN document_classification c"
            " ON c.document_id = d.id WHERE c.document_role = 'COMPANY_STANDARD'"
            " AND d.uploaded_at > ?", (since,)) if scope.may_read(r["id"])]
        if newer_standards:
            changes.append(f"{len(newer_standards)} standard(s) added to the library since the "
                           f"last run: {', '.join(newer_standards[:5])}")
    held = [r["filename"] for r in connect().execute(
        "SELECT DISTINCT d.id, d.filename FROM review_applicable_standards a"
        " JOIN documents d ON d.id = a.standard_document_id"
        " WHERE a.review_run_id = ? AND a.included = 1", ((last or {}).get("id"),))
        if scope.may_read(r["id"])] if last else []
    return {
        "submittal_document_id": submittal_document_id,
        "pages_total": pages.get("pages_total"),
        "pages_read": len(pages.get("fact_pages") or []),
        "unread_pages": pages.get("pages_not_read_into_fields") or [],
        # HONESTY GROUP (2026-09-27): the ledger has always recorded WHY a
        # page did not read into fields (`page_ledger.coverage`'s own
        # `not_read_reasons`, keyed by page); this route simply never carried
        # it past `unread_pages`, so the strip could say a page was unread
        # but never say why - the same "not mentioned" silence CLAUDE.md rule
        # 4 forbids elsewhere. Keyed by the page number AS A STRING because
        # that is what a JSON object key is.
        "unread_page_reasons": pages.get("not_read_reasons") or {},
        "standards_cited": len(held) + len(missing),
        "standards_held": held,
        "standards_missing": missing,
        "last_run_id": (last or {}).get("id"),
        "nothing_changed": last is not None and not changes,
        "changes": changes,
    }


@app.get("/api/reviews/readiness/{submittal_document_id}",
         response_model=schemas.ReviewReadiness,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def review_readiness(
    submittal_document_id: str, request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Owner order section 3: the readiness strip. Pages read (N of M) and the
    standards the submittal cites, held and missing, under the caller's
    grants - and whether anything changed since the last run, so a re-run
    that cannot say anything new is asked about first.

    404 when the caller may not read the submittal, like every review route.
    """
    reject_unknown_params(request, set())
    require_document(submittal_document_id, scope)
    return _readiness_payload(submittal_document_id, scope)


@app.post("/api/reviews/readiness/{submittal_document_id}/reread-pages",
          response_model=schemas.ReviewReadiness,
          responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def review_reread_pages(
    submittal_document_id: str, request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Owner order section 3: "Read unread pages" - re-run extraction on this
    ONE submittal so a page the ledger says is unread gets another try (the
    rule/geometry readers first, vision only where B7 says they still fail).

    NOTHING IS DELETED. `datasheets.extract_facts(replace=True)` supersedes a
    stale fact rather than removing it (#179) - a page that is re-read finds
    the same value again, or a different one, but a value nobody could
    re-derive from this run is never simply erased.

    NO PASS/FAIL HERE. This route reads fields; it does not compare them to
    anything and writes no compliance verdict - that is `run_comparison`'s
    job, on a later, explicit review run.

    404 when the caller may not read the submittal, like every review route.
    """
    reject_unknown_params(request, set())
    require_document(submittal_document_id, scope)
    datasheets_mod.extract_facts(
        submittal_document_id, allowed_document_ids=scope.allowed_document_ids,
        replace=True)
    return _readiness_payload(submittal_document_id, scope)


@app.get("/api/reviews/vision-reader-status",
         response_model=schemas.VisionReaderStatus,
         responses=schemas.ERRORS_422)
def review_vision_reader_status(
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Can the vision reader (Claude, page images) be used right now, and if
    not, what to change - the line beside "Read unread pages".

    ABOUT THE SERVICE, NOT ANYBODY'S DOCUMENTS: it names no document and
    reads none, so it asks only for a resolved scope like every other review
    route. At most one GET /v1/models a minute (cached in `vision_reader`),
    which costs no tokens and carries no document content.
    """
    reject_unknown_params(request, set())
    from . import vision_reader
    return vision_reader.reader_status()


@app.get("/api/reviews/runs/{review_run_id}/crs",
         response_class=Response,
         # A binary download still declares what it returns. Every other
         # route here does, `test_every_endpoint_declares_a_typed_success_
         # response` enforces it, and it is what lets a client know from the
         # schema alone that this answers with a spreadsheet, not JSON. Same
         # shape as `/api/documents/{document_id}/original`.
         responses={200: {"content": {
                              "application/vnd.openxmlformats-officedocument"
                              ".spreadsheetml.sheet": {}},
                          "description": "The Comment Resolution Sheet"},
                    **schemas.ERRORS_404, **schemas.ERRORS_409, **schemas.ERRORS_422})
def export_review_crs(
    review_run_id: str,
    request: Request,
    copy: Literal["internal", "issue"] = "internal",
    scope: access.AccessScope = Depends(access.current_scope),
):
    """The run's findings as a Comment Resolution Sheet (.xlsx).

    SCOPED EXACTLY LIKE THE FINDINGS THEMSELVES, and READ ACCESS SUFFICES.
    Exporting is not a decision - it writes nothing, changes no run and
    records no judgement - so it asks the same question `GET
    /api/reviews/findings` asks: may this caller read this submittal. A run
    they may not read is 404, indistinguishable from one that is not there.

    THE CONTENT IS `_crs_content`'S, NOT THIS ROUTE'S, and the preview route
    beside it reads the very same composition - which is why the two cannot
    say different things about the same run. What is left here is the
    rendering and the filename: `crs_export.build_crs` draws the client's own
    template, and the meta - including the deliberately BLANK transmittal
    numbers - is documented where it is built.

    THE "ISSUE TO CONTRACTOR" COPY IS GATED (safety group, 2026-09-27): a copy
    meant to leave the building must carry a human's decision, not just the
    machine's recommendation. `copy=issue` with no `engineer_final_code` on
    the run is refused with 409 rather than exported with a recommendation
    dressed up as a decision. The "internal" copy is unaffected - an engineer
    reviewing their own work in progress needs no gate.
    """
    reject_unknown_params(request, {"copy"})
    if copy == "issue":
        run = submittal_review_mod.get_review_run(
            review_run_id, allowed_document_ids=scope.allowed_document_ids)
        if run is None:
            raise HTTPException(status_code=404, detail=errors.safe_error(
                errors.NOT_FOUND, "no review run with that id"))
        if not run.get("engineer_final_code"):
            raise HTTPException(status_code=409, detail=errors.safe_error(
                errors.CODE_NOT_DECIDED,
                "an engineer must record the final code before this run can "
                "be issued to the contractor"))
    rows, meta, submittal_name, stamp = _crs_content(review_run_id, scope, copy)
    workbook = crs_export_mod.build_crs(rows, meta)

    safe = "".join(
        ch for ch in Path(submittal_name).stem if ch.isalnum() or ch in "-_")
    # Owner order 2f: the file name says which copy it is.
    filename = (f"CRS_{safe or 'submittal'}_{stamp}_"
                f"{crs_export_mod.COPY_FILE_SUFFIX[copy]}.xlsx")
    return Response(
        content=workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/reviews/runs/{review_run_id}/crs/preview",
         response_model=schemas.CrsPreview,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def preview_review_crs(
    review_run_id: str,
    request: Request,
    copy: Literal["internal", "issue"] = "internal",
    scope: access.AccessScope = Depends(access.current_scope),
):
    """The same Comment Resolution Sheet, as JSON a browser can render.

    A SIBLING OF THE DOWNLOAD, NOT A SECOND OPINION. Both routes compose
    through `_crs_content` and shape through `crs_export.build_crs_view`; the
    export then draws that view into the client's template. So the table an
    engineer reads on screen and the file the client receives cannot disagree
    about a row, a citation, a label or the recommended code - and
    `test_the_preview_rows_are_the_rows_in_the_workbook` holds them to it.

    THE SAME SCOPE AS THE EXPORT, AND READ ACCESS SUFFICES. Previewing writes
    nothing, changes no run and records no judgement, so it asks the question
    the export asks: may this caller read this submittal. A run they may not
    read is 404, indistinguishable from one that is not there.

    Contractor's Response comes back EMPTY rather than missing - it belongs
    to the contractor. Final Resolution is the company's: "Open"/"Closed" on
    a numbered comment (`crs_numbers`), empty on an unnumbered draft. The
    sheet has seven columns whether or not anyone has answered yet.
    """
    reject_unknown_params(request, {"copy"})
    rows, meta, _submittal_name, _stamp = _crs_content(review_run_id, scope, copy)
    return crs_export_mod.build_crs_view(rows, meta)


def _crs_run_scope(review_run_id: str, scope: access.AccessScope) -> tuple[str, str, str]:
    """(crs scope key, printed label, submittal id) for a run the caller may
    read, or 404 - the same 404 for a run that is not there."""
    run = submittal_review_mod.get_review_run(
        review_run_id, allowed_document_ids=scope.allowed_document_ids)
    if run is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no review run with that id"))
    submittal_id = run["submittal_document_id"]
    crs_scope, label = _crs_scope_of(submittal_id)
    return crs_scope, label, submittal_id


def _crs_comment(review_run_id: str, crs_ref: str, scope: access.AccessScope) -> tuple[str, int]:
    """(crs scope key, seq) of a numbered comment that belongs to THIS run's
    submittal, or 404. A number from another submittal is 404,
    indistinguishable from one that is not there, exactly as an unreadable
    run is."""
    crs_scope, label, _submittal = _crs_run_scope(review_run_id, scope)
    parsed = crs_numbers_mod.parse_ref(crs_ref)
    if parsed is None or parsed[0] != label or crs_numbers_mod.get(crs_scope, parsed[1]) is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no CRS comment with that number on this run"))
    return crs_scope, parsed[1]


def _require_named_reviewer(scope: access.AccessScope, what: str) -> None:
    """A decision nobody signed is not a decision - the rule the finding route
    applies to a confirmation."""
    _require_identity_to_write(scope)
    if scope.user_id is None:
        raise HTTPException(status_code=401, detail=errors.safe_error(
            errors.UNAUTHENTICATED, f"{what} must name the person who did it"))


@app.post("/api/reviews/runs/{review_run_id}/crs/comments/{crs_ref}/status",
          response_model=schemas.CrsComment,
          responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_422})
def set_crs_comment_status(
    review_run_id: str,
    crs_ref: str,
    body: schemas.CrsCommentStatusUpdate,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Close (or re-open) one numbered CRS comment - its Final Resolution.

    ONLY THE REVIEWER CLOSES A COMMENT (industry practice): a signed-in
    caller who may read this run's submittal, recorded by name from the
    session, never from the body, with an optional closing note.
    """
    _require_named_reviewer(scope, "closing a comment")
    reject_unknown_params(request, set())
    crs_scope, seq = _crs_comment(review_run_id, crs_ref, scope)
    return crs_numbers_mod.set_status(crs_scope, seq, body.status,
                                      user_id=scope.user_id, note=body.note)


@app.post("/api/reviews/runs/{review_run_id}/crs/comments/{crs_ref}/response",
          response_model=schemas.CrsComment,
          responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_422})
def record_crs_comment_response(
    review_run_id: str,
    crs_ref: str,
    body: schemas.CrsCommentResponseUpdate,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Record the contractor's reply to one comment when it arrived some
    other way than the returned sheet. Recorded as entered by the signed-in
    engineer, so nobody reads it as the contractor's own entry. A reply with
    no code keeps none."""
    _require_named_reviewer(scope, "recording a reply")
    reject_unknown_params(request, set())
    crs_scope, seq = _crs_comment(review_run_id, crs_ref, scope)
    return crs_numbers_mod.set_response(
        crs_scope, seq, code=body.code, text=body.text, user_id=scope.user_id,
        source=crs_numbers_mod.SOURCE_RECORDED)


@app.get("/api/reviews/runs/{review_run_id}/crs/comments/{crs_ref}/history",
         response_model=schemas.CrsCommentHistory,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def crs_comment_history(
    review_run_id: str,
    crs_ref: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Everything that happened to one numbered comment, oldest first: when
    it was numbered, every reply recorded or imported, every close and
    re-open - who and when. READ ONLY; read access suffices."""
    reject_unknown_params(request, set())
    crs_scope, seq = _crs_comment(review_run_id, crs_ref, scope)
    record = crs_numbers_mod.get(crs_scope, seq)
    events = crs_numbers_mod.history(crs_scope, seq)
    # A PERSON'S NAME, NEVER THEIR ID - the rule the sheet's "confirmed by"
    # already follows. An id with no user row left is shown as it is.
    ids = {e["by"] for e in events if e.get("by")}
    if ids:
        marks = ",".join("?" for _ in ids)
        names = {r["id"]: r["display_name"] for r in connect().execute(
            f"SELECT id, display_name FROM users WHERE id IN ({marks})", tuple(ids))}
        for e in events:
            e["by"] = names.get(e.get("by"), e.get("by"))
    return {"ref": record["ref"], "events": events}


#: A returned CRS is a small spreadsheet; anything larger is not one.
CRS_REPLY_MAX_BYTES = 10 * 1024 * 1024


@app.post("/api/reviews/runs/{review_run_id}/crs/reply",
          response_model=schemas.CrsReplyImport,
          responses={**schemas.ERRORS_401, **schemas.ERRORS_404, **schemas.ERRORS_422})
def import_crs_reply(
    review_run_id: str,
    request: Request,
    file: UploadFile = File(...),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Import the contractor's returned Comment Resolution Sheet.

    Each row is matched ONLY by its permanent number ("CRS-<no>-NNN" in Item
    No) - never by position - and must belong to this run's submittal. Its
    "Contractor's Response" is stored with the response code it leads with
    (Accepted / Accepted with comment / Rejected / Clarification needed), or
    with NO code when it leads with none: a reply is never read as agreement.
    Every row with an Item No is accounted for in exactly one count.

    Recorded as imported by the signed-in engineer. Statuses are NOT changed:
    a reply is not a closure - only the reviewer closes a comment.
    """
    from . import crs_reply
    _require_named_reviewer(scope, "importing a reply sheet")
    reject_unknown_params(request, set())
    crs_scope, label, _submittal = _crs_run_scope(review_run_id, scope)
    data = file.file.read(CRS_REPLY_MAX_BYTES + 1)
    if len(data) > CRS_REPLY_MAX_BYTES:
        raise HTTPException(status_code=422, detail=errors.safe_error(
            errors.INVALID_PARAMETER, "the file is larger than 10 MB; a CRS is not"))
    try:
        replies = crs_reply.read_replies(data)
    except crs_reply.ReplySheetError as exc:
        raise HTTPException(status_code=422, detail=errors.safe_error(
            errors.INVALID_PARAMETER, str(exc))) from exc

    counts = {"updated": 0, "updated_without_code": 0, "no_response": 0,
              "not_a_crs_number": 0, "other_submittal": 0, "unknown_number": 0}
    rows = []
    for reply in replies:
        parsed = crs_numbers_mod.parse_ref(reply["item"])
        if parsed is None:
            key, outcome = "not_a_crs_number", "not a CRS number"
        elif parsed[0] != label:
            key, outcome = "other_submittal", "another submittal's number"
        elif crs_numbers_mod.get(crs_scope, parsed[1]) is None:
            key, outcome = "unknown_number", "no such number"
        elif not reply["response"]:
            key, outcome = "no_response", "no response"
        else:
            code, text = crs_numbers_mod.parse_response(reply["response"])
            crs_numbers_mod.set_response(
                crs_scope, parsed[1], code=code, text=text, user_id=scope.user_id,
                source=crs_numbers_mod.SOURCE_IMPORT)
            key = "updated" if code else "updated_without_code"
            outcome = "updated" if code else "updated, no response code stated"
        counts[key] += 1
        rows.append({"row": reply["row"], "item": reply["item"][:80], "outcome": outcome})
    return {"rows_read": len(replies), **counts, "rows": rows}
