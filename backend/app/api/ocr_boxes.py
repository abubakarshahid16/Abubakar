"""POST /api/admin/ocr-boxes/import: the server stores the OCR boxes of a rule book's scanned pages (order 12, N7).

Admin only (a non-admin gets the same 404 as every admin route); with `agent_review_enabled` off every answer is 404
"feature_off" and no table exists. The SERVER writes, because only the server writes the live database. The file must be a
.json file INSIDE the data directory; each page is checked again by code before it is stored (`ocr_box_import`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import admin as admin_mod
from .. import ocr_box_import, rule_label_import, rule_label_schema, schemas
from ..db import connect

router = APIRouter()


class OcrBoxImportBody(BaseModel):
    path: str = Field(
        min_length=1,
        max_length=1024,
        description="an OCR box file under the data directory",
    )


class OcrBoxImportResult(BaseModel):
    read: int = Field(description="pages in the file")
    stored: int = Field(description="pages newly stored")
    unchanged: int = Field(description="pages already stored with the same boxes")
    refused: dict[str, int] = Field(
        description="pages refused, by cause word (revision, text, score, role, page, conflict ...)"
    )
    refused_total: int = Field(description="the sum of the refused counts")


@router.post(
    "/api/admin/ocr-boxes/import",
    response_model=OcrBoxImportResult,
    responses={**schemas.ERRORS_404, **schemas.ERRORS_422},
)
def import_ocr_boxes(
    body: OcrBoxImportBody, _admin: dict | None = Depends(admin_mod.current_admin)
):
    if not rule_label_schema.switch_on():
        raise HTTPException(status_code=404, detail="feature_off")
    try:
        pages, sha = ocr_box_import.read_file(
            rule_label_import.resolve_data_path(body.path)
        )
    except rule_label_import.ImportPathError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return ocr_box_import.import_pages(connect(), pages, sha)
