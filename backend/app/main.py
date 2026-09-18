from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import chat as chat_mod
from . import classification as classification_mod
from . import chunker as chunk_mod
from . import extract as extract_mod
from . import ingest as ingest_mod
from . import highlight as highlight_mod
from . import keyword as keyword_mod
from . import metrics as metrics_mod
from . import acronyms as acronyms_mod
from . import answer as answer_mod
from . import search as search_mod
from . import pageimage as pageimage_mod
from . import upload as upload_mod
from . import watcher as watcher_mod
from . import watch_api as watch_api_mod
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
from . import submittal_review as submittal_review_mod
from . import workbook as workbook_mod
from . import schemas
from .config import settings
from .db import connect, init_db


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
    review_mod.ensure_schema()
    deliverables_mod.ensure_schema()
    risks_mod.ensure_schema()
    submittal_review_mod.ensure_schema()
    # A STRUCTURAL MIGRATION, ONCE, AT A MOMENT SOMEBODY CHOSE. It rebuilds
    # submittal_facts so `review_run_id` is nullable and facts are per
    # document. It used to sit inside `ensure_schema`, which every read path
    # calls - so a DROP/CREATE could fire mid-request, from any thread, and the
    # table's shape became a function of execution history. That produced
    # intermittent failures in unrelated tests, including the concurrency test,
    # because DDL on one SQLite connection blocks readers on the others.
    submittal_review_mod.migrate_facts_to_per_document()
    # Drain the upload queue. Without this a document sits at 'queued'
    # forever while the API reports a job id that means nothing.
    ingest_mod.start_worker()
    # The watched folder is OFF unless WATCH_FOLDER is set in backend/.env.
    # start_watcher() returns a reason string rather than raising when it does
    # not start, so a machine with no drop folder boots exactly as before.
    watcher_mod.start_watcher()
    # Harvest acronym expansions once at startup rather than lazily on the
    # first question. It scans the whole corpus and takes ~2.5s, which is
    # fine here and is not fine added to a 1.3s answer.
    try:
        acronyms_mod.harvest()
    except Exception:  # noqa: BLE001 - a missing expansion map is not fatal
        pass
    yield
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
        "answer_model_present": bool(settings.answer_model),
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

    ADMIN SEES CORPUS-WIDE FIGURES, AND THAT IS A NEW CAPABILITY. `access.py`
    grants an administrator no read bypass - an IT+admin user sees exactly the
    six documents IT sees - so this is not an existing power being surfaced. It
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


@app.post("/api/documents", response_model=schemas.UploadAccepted,
          responses={**schemas.ERRORS_400, **schemas.ERRORS_401})
async def upload_document(
    file: UploadFile = File(...),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Accept an identified upload and place it in admin-only review."""
    _require_identity_to_write(scope)
    admin_role: str | None = None
    uploader_is_admin = scope.unrestricted
    if scope.user_id is not None:
        try:
            admin_role, uploader_is_admin = access.upload_admin_role(scope.user_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        row, job_id, duplicate_of = upload_mod.ingest(file.file, file.filename or "")
    except upload_mod.UploadError as e:
        return JSONResponse(
            status_code=400,
            content={"code": e.code, "message": e.message, "detail": e.detail},
        )
    if duplicate_of is None and admin_role is not None and scope.user_id is not None:
        access.grant_uploaded_document_to_admin(row["id"], admin_role, scope.user_id)
    elif duplicate_of is not None and not scope.may_read(duplicate_of):
        return {"document": None, "job_id": "", "duplicate_of": None,
                "awaiting_grant": True}
    return {
        "document": upload_mod.to_api(row),
        "job_id": job_id or "",
        "duplicate_of": duplicate_of,
        "awaiting_grant": not uploader_is_admin and duplicate_of is None,
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
    out = []
    for row in rows:
        doc = upload_mod.to_api(row)
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
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Remove a document and everything derived from it.

    Requires confirm=true - a destructive endpoint should not fire on a
    mistyped URL. Removes chunks, pages, vectors, exclusions, jobs, cached
    page images and the stored PDF.
    """
    reject_unknown_params(request, {"confirm"})
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
):
    """Extract pages in batches. Resumes from the last completed batch."""
    require_document(document_id, scope)
    return extract_mod.extract_document(document_id)


@app.post("/api/documents/{document_id}/chunk", response_model=schemas.ChunkResult,
          responses=schemas.ERRORS_404)
def chunk(document_id: str, force: bool = Query(False),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Chunk an extracted document.

    Short-circuits when the document already has chunks and its content has
    not changed, matching how /extract resumes rather than redoing work.
    Pass force=true to rebuild.
    """
    require_document(document_id, scope)
    return chunk_mod.chunk_document(document_id, force=force)


@app.post("/api/documents/{document_id}/embed", response_model=schemas.EmbedResult,
          responses=schemas.ERRORS_404)
def embed(document_id: str,
    scope: access.AccessScope = Depends(access.current_scope),
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
    limit: int = Query(3, ge=1, le=5),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Answer a question against the indexed documents.

    tier=extract   (default) the top passage verbatim, no model involved
    tier=generated             2-3 passages summarised by the local model

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
         responses={**schemas.ERRORS_404})
def read_progress(progress_id: str):
    """What the machine is doing, as reported by the work itself.

    Unauthenticated, and carries no document content - a stage name, a count
    and a clock. The id is chosen by the client; guessing one reveals only
    that somebody is asking a question, which /api/health already reveals
    through `busy`.
    """
    state = progress_mod.read(progress_id)
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
        return {"document_id": document_id, "doc_type": None,
                "discipline": None, "doc_class": None, "register_id": None,
                "suggested_by": classification_mod.SOURCE_NONE,
                "confirmed_by": None, "confirmed_at": None,
                "confirmed": False, "subjects": []}
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


# ----------------------------------------------------------------- market
#
# No network call exists in this build. Both routes are scoped like every
# other, not because a sample is sensitive, but so that adding a real provider
# later cannot introduce an unscoped route by inheriting this shape.


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
    except Exception:  # noqa: BLE001 - an unwritable audit must not fail the request
        pass


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
):
    """Register a client-approved review template; versions never overwrite."""
    _require_identity_to_write(scope)
    return review_mod.create_template(body.model_dump(), created_by=scope.user_id)


@app.get("/api/reviews/baseline-rules", response_model=schemas.ReviewBaselineRuleList)
def list_review_baseline_rules(scope: access.AccessScope = Depends(access.current_scope)):
    return {"rules": review_mod.list_baseline_rules()}


@app.post("/api/reviews/baseline-rules", response_model=schemas.ReviewBaselineRule,
          responses=schemas.ERRORS_401)
def create_review_baseline_rule(body: schemas.ReviewBaselineRuleCreate,
                                scope: access.AccessScope = Depends(access.current_scope)):
    _require_identity_to_write(scope)
    payload = body.model_dump()
    return review_mod.create_baseline_rule(payload)


@app.patch("/api/reviews/baseline-rules/{rule_id}", response_model=schemas.ReviewBaselineRule,
           responses=schemas.ERRORS_404)
def update_review_baseline_rule(rule_id: str, body: schemas.ReviewBaselineRuleCreate,
                                scope: access.AccessScope = Depends(access.current_scope)):
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
        path = review_mod.render_report(body.document_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "review document not found"))
    return FileResponse(path, media_type="application/pdf",
                        filename=f"engineering-review-{body.document_id}.pdf",
                        headers={"Cache-Control": "private, no-store"})

@app.get("/api/reviews/findings", response_model=schemas.ReviewFindingList,
         responses=schemas.ERRORS_422)
def list_review_findings(
    request: Request,
    document_id: str | None = Query(None),
    status: schemas.ReviewStatus | None = Query(None),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """List review findings only for documents the caller may read."""
    reject_unknown_params(request, {"document_id", "status"})
    if document_id is not None:
        require_document(document_id, scope)
    return {"findings": review_mod.list_findings(
        document_id=document_id, status=status,
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
    updated = review_mod.update(
        finding_id, body.model_dump(exclude_unset=True), actor_user_id=scope.user_id
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no review finding with that id"))
    return updated


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
    return {"results": structured_search_mod.search(
        q, kind=kind, allowed_document_ids=scope.allowed_document_ids)}


@app.get("/api/risks", response_model=schemas.RiskList)
def list_risks(risk_type: str | None = None,
               scope: access.AccessScope = Depends(access.current_scope)):
    if risk_type is not None and risk_type not in risks_mod.RISK_TYPES:
        raise HTTPException(status_code=422, detail="unsupported risk type")
    risks_mod.detect_automatic_risks(allowed_document_ids=scope.allowed_document_ids)
    return {"risks": risks_mod.list_items(risk_type=risk_type, allowed_document_ids=scope.allowed_document_ids)}


@app.get("/api/reviews/findings/{finding_id}/traceability", response_model=schemas.ReviewTraceability)
def finding_traceability(finding_id: str, scope: access.AccessScope = Depends(access.current_scope)):
    item = review_mod.traceability(finding_id, allowed_document_ids=scope.allowed_document_ids)
    if item is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "no finding with that id"))
    return item


@app.post("/api/risks", response_model=schemas.Risk)
def create_risk(body: schemas.RiskCreate, scope: access.AccessScope = Depends(access.current_scope)):
    if body.risk_type not in risks_mod.RISK_TYPES:
        raise HTTPException(status_code=422, detail="unsupported risk type")
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
    changes = body.model_dump(exclude_unset=True)
    if changes.get("document_id"):
        require_document(changes["document_id"], scope)
    if changes.get("parent_id") and deliverables_mod.get(changes["parent_id"]) is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "parent WBS node not found"))
    try:
        item = deliverables_mod.update(deliverable_id, changes, actor_user_id=scope.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if item is None or (item.get("document_id") and not scope.may_read(item["document_id"])):
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "no deliverable with that id"))
    return item


@app.get("/api/deliverables/{deliverable_id}/history", response_model=schemas.DeliverableEventList,
         responses=schemas.ERRORS_404)
def deliverable_history(deliverable_id: str, scope: access.AccessScope = Depends(access.current_scope)):
    item = deliverables_mod.get(deliverable_id)
    if item is None or (item.get("document_id") and not scope.may_read(item["document_id"])):
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "no deliverable with that id"))
    return {"events": deliverables_mod.history(deliverable_id)}


@app.get("/api/deliverables/{deliverable_id}/stakeholders",
         response_model=schemas.DeliverableStakeholderList,
         responses=schemas.ERRORS_404)
def deliverable_stakeholders(deliverable_id: str, scope: access.AccessScope = Depends(access.current_scope)):
    item = deliverables_mod.get(deliverable_id)
    if item is None or (item.get("document_id") and not scope.may_read(item["document_id"])):
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
    if item is None or (item.get("document_id") and not scope.may_read(item["document_id"])):
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
def set_summary_schedule(body: schemas.SummarySchedule, scope: access.AccessScope = Depends(access.current_scope)):
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
                           scope: access.AccessScope = Depends(access.current_scope)):
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
    return {"conversation": conversation, "messages": chat_mod.get_messages(conversation_id)}


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
        progress_mod.start(body.progress_id)
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
            )
        finally:
            progress_mod.finish(body.progress_id)
    except chat_mod.MessageNotFound:
        raise HTTPException(
            status_code=404,
            detail=errors.safe_error(
                errors.NOT_FOUND, "no answered message with that id in this conversation"),
        )


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
    scope: access.AccessScope = Depends(access.current_scope),
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """Re-read a standard and record every obligation it states.

    THE ADMIN CAPABILITY IS REQUIRED. Extraction replaces the unconfirmed rows
    for a standard, which changes what every later reader sees, so it needs the
    role that answers for everyone - the same reasoning as classification.
    Confirmed rows are never deleted.
    """
    reject_unknown_params(request, set())
    require_document(document_id, scope)
    return standards_mod.extract_requirements(
        document_id, allowed_document_ids=scope.allowed_document_ids, actor=actor)


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
    scope: access.AccessScope = Depends(access.current_scope),
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """Confirm, edit or reject an extracted requirement. ADMIN, and AUDITED.

    A correction sets `extraction_method` to 'human': after it the row is a
    person's statement rather than a machine's guess, and nothing downstream
    may present it as extracted.
    """
    try:
        return standards_mod.decide_requirement(
            requirement_id, decision=body.decision,
            allowed_document_ids=scope.allowed_document_ids,
            actor=actor, edits=body.edits)
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
    job_id = standards_mod.enqueue_extraction(document_id, actor=actor)
    return {"job_id": job_id, "document_id": document_id, "state": "queued"}


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
                   content_hash, retrievable, quality_flags, text
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
