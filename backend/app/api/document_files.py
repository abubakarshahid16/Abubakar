"""A document's pages, page images, original file, workbook, chunks and ledger.

Moved out of main.py with no logic change (planner order 73, #692; system map target structure).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from .. import access, errors, schemas, stored_paths
from .. import applicability as applicability_mod
from .. import highlight as highlight_mod
from .. import page_ledger as page_ledger_mod
from .. import pageimage as pageimage_mod
from .. import workbook as workbook_mod
from ..api_utils import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    reject_unknown_params,
    require_document,
    retrievable_clause,
    validate_retrievable,
)
from ..db import connect

router = APIRouter()


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


@router.get("/api/documents/{document_id}/pages", response_model=schemas.PagesResponse,
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


@router.get("/api/documents/{document_id}/page-ledger", response_model=schemas.PageLedger,
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


@router.get("/api/documents/{document_id}/applicability",
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


@router.get("/api/documents/{document_id}/original",
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
    stored = Path(stored_paths.local(doc["stored_path"]))
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


@router.get("/api/documents/{document_id}/workbook",
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
    stored = Path(stored_paths.local(doc["stored_path"]))
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


@router.get("/api/documents/{document_id}/pages/{page_no}/image",
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


@router.get("/api/documents/{document_id}/chunks", response_model=schemas.ChunkPage,
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


@router.get("/api/documents/{document_id}/excluded", response_model=schemas.ExclusionsResponse,
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
