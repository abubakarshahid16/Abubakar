"""GET /api/reviews/runs/{run_id}/page-image - the Sheet's datasheet page
with every card's value underlined on it (#967, the spell-checker view).

An `APIRouter`, like `watch_api`, so main.py includes one line.

WHAT IT DRAWS. The Sheet lists the cards on a page; this route draws their
values on the page image, each underlined in the colour of its card's state
(amber: needs you; grey: answered). The marks are found the way the
side-by-side view finds one finding's box (`evidence_boxes.side`, the
submittal side: the stored quote, the value's stored box, its source line,
the value when it is on the page once, the field's label) and drawn on the
render in PDF user space (`pageimage.render_page_with_marks`), never
overlaid by the browser. A value that cannot be placed safely gets NO mark,
and the headers say how many were placed out of how many were asked, so the
screen can say "3 of 4 values are marked on this page" rather than imply
every value is.

WHAT TRAVELS IN THE URL. Finding ids and their state only - never a value,
a field name or any document text. Every id must belong to this run and sit
on this page, or the request is refused: a mark on the wrong page is worse
than none.

ACCESS. Every finding follows its submittal's grant (404 like every route).
Read only; nothing is written.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse

from . import access, errors
from . import evidence_boxes
from . import pageimage
from . import review as review_mod
from . import schemas
from .api_utils import reject_unknown_params, require_document

router = APIRouter()

#: The most marks one page request may carry (a page has tens of values,
#: not hundreds; the limit bounds the work one request can ask for).
MAX_MARKS = 80
STATES = tuple(pageimage.MARK_COLOURS)


def parse_marks(text: str) -> list[tuple[str, str]]:
    """`id:state,id:state` -> [(id, state)], refusing anything else."""
    out: list[tuple[str, str]] = []
    for part in (p for p in text.split(",") if p):
        finding_id, sep, state = part.partition(":")
        if not sep or not finding_id or state not in STATES:
            raise HTTPException(status_code=422, detail=errors.safe_error(
                errors.INVALID_PARAMETER, f"each mark is <finding id>:<{'|'.join(STATES)}>"))
        out.append((finding_id, state))
    if not out or len(out) > MAX_MARKS:
        raise HTTPException(status_code=422, detail=errors.safe_error(
            errors.INVALID_PARAMETER, f"between 1 and {MAX_MARKS} marks per page"))
    return out


@router.get("/api/reviews/runs/{run_id}/page-image",
            response_class=FileResponse,
            responses={200: {"content": {"image/png": {}},
                             "description": "The datasheet page with every card's value underlined"},
                       **schemas.ERRORS_404, **schemas.ERRORS_422})
def review_run_page_image(
    run_id: str,
    request: Request,
    page: int = Query(..., ge=1),
    marks: str = Query(..., min_length=1, max_length=8000),
    dpi: int = Query(150, ge=50, le=300),
    scope: access.AccessScope = Depends(access.current_scope),
):
    """The run's datasheet page with the given findings' values underlined.
    `X-Marks-Located` / `X-Marks-Total`: how many were placed, out of how
    many were asked. `X-Evidence-Page`: the page drawn."""
    reject_unknown_params(request, {"page", "marks", "dpi"})
    asked = parse_marks(marks)
    document = None
    drawn: list[tuple[list, str]] = []
    located = 0
    for finding_id, state in asked:
        current = review_mod.get(finding_id)
        if (current is None or not scope.may_read(current["document_id"])
                or current.get("review_run_id") != run_id):
            raise HTTPException(status_code=404, detail=errors.safe_error(
                errors.NOT_FOUND, "no review finding with that id in this run"))
        if current.get("contractor_page") != page:
            raise HTTPException(status_code=422, detail=errors.safe_error(
                errors.INVALID_PARAMETER, "a mark must sit on the page drawn"))
        found = evidence_boxes.side(current, "submittal", scope)
        if document is None:
            document = found["document"] or dict(require_document(current["document_id"], scope))
        if found["document"] is not None and found["rects"]:
            drawn.append((found["rects"], state))
            located += 1
    assert document is not None
    if document.get("pagination") == "flow" or not document.get("stored_path"):
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "this document has no printed pages to draw on",
            document_id=document["id"]))
    try:
        path = pageimage.render_page_with_marks(document, page, drawn, dpi=dpi)
    except pageimage.PageOutOfRange as e:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, str(e), document_id=document["id"])) from None
    return FileResponse(path, media_type="image/png", headers={
        "Cache-Control": "private, max-age=3600",
        "X-Marks-Located": str(located),
        "X-Marks-Total": str(len(asked)),
        "X-Evidence-Page": str(page),
    })
