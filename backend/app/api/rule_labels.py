"""POST /api/admin/rule-labels/import: the server stores a label file the label job exported (owner decision 1).

Admin only (a non-admin gets the same 404 as every admin route); with `agent_review_enabled` off every answer is 404
"feature_off" and no table exists. The SERVER writes, because only the server writes the live database. The file must be
a .json file INSIDE the data directory; each row is checked again by code before it is stored (`rule_label_import`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import admin as admin_mod
from .. import rule_label_import, rule_label_schema, schemas
from ..db import connect

router = APIRouter()


class RuleLabelImportBody(BaseModel):
    path: str = Field(
        min_length=1,
        max_length=1024,
        description="a label file under the data directory",
    )


class RuleLabelImportResult(BaseModel):
    read: int = Field(description="rows in the file")
    stored: int = Field(
        description="rows now in the table, new, changed or already identical"
    )
    skipped_changed_quote: int = Field(
        description="rows whose quote hash or page no longer matches the stored rule"
    )
    unknown_rule: int = Field(description="rows whose rule is not in this database")
    refused: int = Field(
        description="rows that failed a check (malformed, approval guard, OCR, the table's own guard)"
    )


@router.post(
    "/api/admin/rule-labels/import",
    response_model=RuleLabelImportResult,
    responses={**schemas.ERRORS_404, **schemas.ERRORS_422},
)
def import_rule_labels(
    body: RuleLabelImportBody, _admin: dict | None = Depends(admin_mod.current_admin)
):
    if not rule_label_schema.switch_on():
        raise HTTPException(status_code=404, detail="feature_off")
    try:
        rows = rule_label_import.read_file(
            rule_label_import.resolve_data_path(body.path)
        )
    except rule_label_import.ImportPathError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return rule_label_import.import_labels(connect(), rows)
