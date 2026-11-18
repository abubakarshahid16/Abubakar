"""Routes of the general review (order 14, piece D): a paper's review history and the saved checklists.

    GET /api/reviews/papers/{document_id}/history   every review of the paper the caller may read, newest first (general and earlier)
    GET /api/reviews/general/checklists             the saved checklists (admin only)

They only read, and they are served whichever method the Review button runs (stored general runs stay readable). A paper the caller
may not read answers 404, like one that does not exist; a checklist route for a non-admin answers 404 too (a 403 would confirm it).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from .. import access, aim_review_history, aim_review_store, schemas
from .. import admin as admin_mod
from ..api_utils import reject_unknown_params, require_document
from ..db import connect

router = APIRouter()


class HistoryFile(BaseModel):
    label: str
    url: str


class HistoryRun(BaseModel):
    run_id: str
    version: str
    part: str
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    points: int | None = None
    files: list[HistoryFile]


class HistoryOut(BaseModel):
    paper_document_id: str
    boundary: str
    runs: list[HistoryRun]


class SavedChecklist(BaseModel):
    key: str
    kind: str | None = None
    equipment_type: str | None = None
    items: int | None = None
    books: list[str]
    built_from: str
    made_at: str
    made_by_run: str | None = None
    usd: float | None = None
    sha256: str
    current: bool


class ChecklistsOut(BaseModel):
    checklists: list[SavedChecklist]


@router.get(
    "/api/reviews/papers/{document_id}/history",
    response_model=HistoryOut,
    responses={**schemas.ERRORS_404},
)
def paper_history(
    document_id: str,
    request: Request,
    scope: access.AccessScope = Depends(access.current_scope),
):
    reject_unknown_params(request, set())
    require_document(document_id, scope)
    return aim_review_history.history(
        connect(), document_id, scope.allowed_document_ids
    )


@router.get(
    "/api/reviews/general/checklists",
    response_model=ChecklistsOut,
    responses={**schemas.ERRORS_404},
)
def saved_checklists(
    request: Request,
    _admin: dict | None = Depends(admin_mod.current_admin),
):
    reject_unknown_params(request, set())
    return {"checklists": aim_review_store.checklists(connect())}
