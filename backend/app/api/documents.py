"""Documents: upload, list, read, delete, the ingest steps and the bulk role change.

Moved out of main.py with no logic change (planner order 73, #692; system map target structure).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import JSONResponse

from .. import access, document_refs, errors, orphan_guard, schemas, stored_paths
from .. import admin as admin_mod
from .. import chunker as chunk_mod
from .. import classification as classification_mod
from .. import extract as extract_mod
from .. import fts_index as keyword_mod
from .. import ingest as ingest_mod
from .. import reports as reports_mod
from .. import review as review_mod
from .. import submittal_review as submittal_review_mod
from .. import table_consistency as table_consistency_mod
from .. import upload as upload_mod
from ..api_utils import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    _require_identity_to_write,
    reject_unknown_params,
    require_document,
)
from ..config import settings
from ..db import connect

router = APIRouter()


@router.get("/api/documents/upload-disciplines", response_model=schemas.UploadDisciplines,
            responses={**schemas.ERRORS_401})
def upload_disciplines(scope: access.AccessScope = Depends(access.current_scope)):
    """The disciplines this caller may make an upload visible to (#609), and
    the default: their own. Empty and not required with authentication off."""
    if scope.user_id is None:
        _require_identity_to_write(scope)
        return {"required": False, "choices": [], "default": []}
    return {"required": True, **access.upload_discipline_choices(scope.user_id)}


@router.post("/api/documents", response_model=schemas.UploadAccepted,
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


@router.get("/api/documents", response_model=list[schemas.Document],
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


@router.delete("/api/documents/{document_id}", response_model=schemas.DeletedDocument,
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

    # Reports quote this document: their FILES go, their ROWS stay (the record survives).
    reports_mod.on_document_deleted(document_id)

    conn = connect()
    removed = {"review_pdfs_of_citing_submittals": document_refs.remove_citing_report_files(document_id)}  # #1053: before the cascade
    actor = {"id": scope.user_id, "email": (_admin or {}).get("email")} if scope.user_id else None
    with conn:
        removed.update(document_refs.erase_document_text(  # #436: its copied text goes too
            conn, document_id, doc["filename"], actor=actor))
        removed["canonical_field_names"] = document_refs.forget_quotes(conn, document_id)  # #437, before the chunk cascade
        conn.execute("DELETE FROM chunks_fts WHERE document_id = ?", (document_id,))
        for table in ("chunk_vectors", "exclusions", "chunks", "pages", "jobs"):
            cur = conn.execute(f"DELETE FROM {table} WHERE document_id = ?", (document_id,))
            removed[table] = cur.rowcount
        cur = conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        removed["documents"] = cur.rowcount
        # The record of the delete commits with the delete (ids and counts only).
        document_refs.record_document_deleted(conn, document_id, removed, actor=actor)

    files_removed = 0
    stored = Path(stored_paths.local(doc["stored_path"]))
    if stored.exists():
        stored.unlink()
        files_removed += 1
    if (cache := settings.data_dir / "page_images").exists():
        for img in cache.glob(f"{doc['sha256'][:16]}_*.png"):
            img.unlink()
            files_removed += 1
    files_removed += review_mod.remove_report_files(document_id) + removed.pop("review_pdfs_of_citing_submittals")  # #437, #1053: audited, not in the response

    return {
        "deleted": document_id,
        "filename": doc["filename"],
        "rows_removed": removed,
        "files_removed": files_removed,
    }


@router.get("/api/documents/{document_id}", response_model=schemas.Document,
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


@router.post("/api/documents/{document_id}/extract", response_model=schemas.ExtractResult,
             responses=schemas.ERRORS_404)
def extract(document_id: str,
    scope: access.AccessScope = Depends(access.current_scope),
    _admin: dict | None = Depends(admin_mod.current_admin),
):
    """Extract pages in batches. Resumes from the last completed batch."""
    require_document(document_id, scope)
    return extract_mod.extract_document(document_id)


@router.post("/api/documents/{document_id}/chunk", response_model=schemas.ChunkResult,
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


@router.post("/api/documents/{document_id}/embed", response_model=schemas.EmbedResult,
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


@router.post("/api/documents/{document_id}/index-keyword",
             response_model=schemas.KeywordIndexResult, responses=schemas.ERRORS_404)
def index_keyword(document_id: str,
    scope: access.AccessScope = Depends(access.current_scope),
    _admin: dict | None = Depends(admin_mod.current_admin),
):
    """Build the keyword index for one document. Needs no vectors."""
    require_document(document_id, scope)
    return keyword_mod.index_document(document_id)


@router.get(
    "/api/documents/{document_id}/table-consistency",
    response_model=table_consistency_mod.TableConsistency,
    responses={**schemas.ERRORS_404, **schemas.ERRORS_422},
)
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
        document_id, allowed_document_ids=scope.allowed_document_ids
    )


@router.post("/api/documents/bulk/role", response_model=schemas.BulkRoleResult,
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
