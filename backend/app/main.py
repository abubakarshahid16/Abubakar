from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import chat as chat_mod
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
from . import progress as progress_mod
from . import reports as reports_mod
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
    # Drain the upload queue. Without this a document sits at 'queued'
    # forever while the API reports a job id that means nothing.
    ingest_mod.start_worker()
    # Harvest acronym expansions once at startup rather than lazily on the
    # first question. It scans the whole corpus and takes ~2.5s, which is
    # fine here and is not fine added to a 1.3s answer.
    try:
        acronyms_mod.harvest()
    except Exception:  # noqa: BLE001 - a missing expansion map is not fatal
        pass
    yield
    ingest_mod.stop_worker()


app = FastAPI(
    title="Nabaa",
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
    `alive` and `stalled` stay here because a client that cannot reach the
    backend has to distinguish "down" from "up but stuck", and neither is
    about anybody's documents.
    """
    worker = ingest_mod.get_worker().status()
    return {
        "ok": True,
        "embed_model_present": (settings.embed_model_dir / "tokenizer.json").exists(),
        # Whether an answer model is CONFIGURED, not which one. The exact name
        # and version is fingerprinting material and is on /api/metrics.
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
    """Everything the dashboard shows.

    A value that has not been measured is null rather than zero, and the
    screen is required to say so. Throughput comes from stage runs actually
    recorded; retrieval latency comes from questions actually asked.
    """
    reject_unknown_params(request, set())
    return metrics_mod.snapshot(ingest_mod.get_worker().status())


# --------------------------------------------------------------- documents


@app.post("/api/documents", response_model=schemas.UploadAccepted,
          responses=schemas.ERRORS_400)
async def upload_document(file: UploadFile = File(...)):
    """Stream a PDF to disk. Returns the document record and a job id."""
    try:
        row, job_id, duplicate_of = upload_mod.ingest(file.file, file.filename or "")
    except upload_mod.UploadError as e:
        return JSONResponse(
            status_code=400,
            content={"code": e.code, "message": e.message, "detail": e.detail},
        )
    return {
        "document": upload_mod.to_api(row),
        "job_id": job_id or "",
        "duplicate_of": duplicate_of,
    }


@app.get("/api/documents", response_model=list[schemas.Document],
         responses=schemas.ERRORS_422)
def list_documents(request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    reject_unknown_params(request, set())
    conn = connect()
    # Filtered IN THE QUERY, not after it. Selecting every document and
    # dropping the unauthorised ones in Python would work here because there is
    # no LIMIT - but it is the same shape as the retrieval defect fixed in the
    # previous commit, and the next person to add pagination to this route
    # would silently turn it into that bug. The scope belongs in the WHERE
    # clause on principle, not because this particular query needs it.
    allowed = sorted(scope.allowed_document_ids)
    if not allowed:
        return []
    marks = ",".join("?" * len(allowed))
    rows = conn.execute(
        f"SELECT * FROM documents WHERE id IN ({marks})"
        " ORDER BY uploaded_at DESC",
        allowed,
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
    out = []
    for row in rows:
        doc = upload_mod.to_api(row)
        info = dropped.get(row["id"], {})
        doc["pages_excluded"] = info.get("pages_excluded", 0)
        doc["pages_excluded_characters"] = info.get("characters_dropped", 0)
        doc["pages_excluded_with_clause_headings"] = info.get(
            "pages_with_clause_headings", 0
        )
        out.append(doc)
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
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Hybrid retrieval: FTS5 + dense vectors fused with RRF, then reranked.

    Works keyword-only before any embedding exists and upgrades to hybrid
    automatically as vectors arrive - `mode` in the response says which was
    actually used, rather than the caller having to guess.
    """
    reject_unknown_params(request, {"q", "limit", "document_id", "rerank", "mode"})
    if document_id:
        require_document(document_id, scope)
    if mode not in ("hybrid", "keyword"):
        return JSONResponse(
            status_code=422,
            content={"detail": errors.safe_error(
                errors.INVALID_PARAMETER, "mode must be hybrid or keyword")},
        )
    return search_mod.search(
        q,
        limit=limit,
        document_id=document_id,
        rerank=rerank,
        dense=(mode == "hybrid"),
        allowed_document_ids=scope.allowed_document_ids,
    )


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


def _require_conversation(conversation_id: str) -> dict:
    try:
        return chat_mod.get_conversation(conversation_id)
    except chat_mod.ConversationNotFound:
        raise HTTPException(
            status_code=404,
            detail=errors.safe_error(errors.NOT_FOUND, "no conversation with that id"),
        )


# ------------------------------------------------------------------- auth
#
# Two routes, and `access.current_scope` changes by zero lines: it already
# calls the resolver, already falls to empty_scope() without one, and already
# derives the scope from the grant tables. Authentication supplies WHO;
# authorisation was already deciding WHAT.


@app.post("/api/auth/login", response_model=schemas.LoginResult,
          responses={**schemas.ERRORS_422})
def login(body: schemas.LoginRequest):
    """Exchange credentials for a bearer token.

    Unauthenticated by construction - it is how a caller becomes
    authenticated. It is also the only unauthenticated WRITER in the API, and
    it writes exactly one row (`last_login_at`) on success plus an audit row,
    which is why the rate limiter is in memory rather than a table.
    """
    try:
        return auth_mod.login(body.email, body.password)
    except auth_mod.AuthError as exc:
        headers = ({"Retry-After": str(exc.retry_after)}
                   if exc.retry_after else None)
        raise HTTPException(
            status_code=429 if exc.code == errors.RATE_LIMITED else 401,
            detail=errors.safe_error(exc.code, exc.message),
            headers=headers,
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
    return _analysis_or_503(analysis_mod.summary, body.question, scope,
                            limit=body.limit)


@app.post("/api/analysis/recommendations",
          response_model=schemas.AnalysisRecommendation,
          responses={**schemas.ERRORS_422})
def analysis_recommendations(
        body: schemas.AnalysisRequest,
        scope: access.AccessScope = Depends(access.current_scope)):
    """One advisory recommendation and the checks behind its confidence."""
    return _analysis_or_503(
        analysis_mod.recommendation, body.question, scope, limit=body.limit,
        baseline_document_id=body.baseline_document_id)


@app.post("/api/analysis/gaps", response_model=schemas.AnalysisGaps,
          responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def analysis_gaps(body: schemas.AnalysisRequest,
                  scope: access.AccessScope = Depends(access.current_scope)):
    """Mechanical claim comparison. No model call.

    The baseline comes from the caller or there is none. Choosing one here -
    the oldest document, the one with "standard" in its name - would be the
    system deciding which document is authoritative.
    """
    if body.baseline_document_id:
        # Through require_document, so an id the caller may not read is 404 and
        # is indistinguishable from one that does not exist.
        require_document(body.baseline_document_id, scope)
    return analysis_mod.gaps(body.question, scope, limit=body.limit,
                             baseline_document_id=body.baseline_document_id)


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


@app.get("/api/reports", response_model=schemas.ReportList)
def list_reports(scope: access.AccessScope = Depends(access.current_scope)):
    return reports_mod.list_reports(scope)


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
        filename=f"nabaa-report-{report_id}.pdf",
        headers={"Cache-Control": "private, no-store"},
    )


@app.post("/api/conversations", response_model=schemas.Conversation,
          responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def create_conversation(body: schemas.NewConversation | None = None,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Start a conversation. Optionally scoped to one document."""
    body = body or schemas.NewConversation()
    if body.document_id:
        require_document(body.document_id, scope)
    return chat_mod.create_conversation(
        title=body.title or "New conversation", document_id=body.document_id
    )


@app.get("/api/conversations", response_model=schemas.ConversationList,
         responses=schemas.ERRORS_422)
def list_conversations(
    request: Request,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """Recent conversations, most recently used first, so one can be reopened."""
    reject_unknown_params(request, {"limit", "offset"})
    return chat_mod.list_conversations(limit=limit, offset=offset)


@app.get("/api/conversations/{conversation_id}", response_model=schemas.ConversationDetail,
         responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def get_conversation(conversation_id: str, request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    """A conversation with every turn, including the passages behind each
    answer, so reopening it restores the citations rather than bare text."""
    reject_unknown_params(request, set())
    conversation = _require_conversation(conversation_id)
    return {"conversation": conversation, "messages": chat_mod.get_messages(conversation_id)}


@app.delete("/api/conversations/{conversation_id}", response_model=schemas.DeletedConversation,
            responses={**schemas.ERRORS_400, **schemas.ERRORS_404, **schemas.ERRORS_422})
def delete_conversation(conversation_id: str, request: Request, confirm: bool = Query(False)):
    reject_unknown_params(request, {"confirm"})
    conversation = _require_conversation(conversation_id)
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
    _require_conversation(conversation_id)
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
# `scripts/seed_access.py` for everything except setting a password. Implements
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
