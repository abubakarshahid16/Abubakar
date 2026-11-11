"""POST /api/admin/rule-equipment/import: the server stores an equipment label file the lab labeller exported (order 16.2).

Admin only; with `agent_review_enabled` off every answer is 404 "feature_off" and no table exists. The SERVER writes, because
only the server writes the live database. The file must be a .json file INSIDE the data directory; each row is checked again by
code before it is stored (`rule_equipment`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import admin as admin_mod
from .. import rule_equipment, rule_label_import, rule_label_schema, schemas
from ..db import connect

router = APIRouter()


class RuleEquipmentImportBody(BaseModel):
    path: str = Field(
        min_length=1,
        max_length=1024,
        description="an equipment label file under the data directory",
    )


class RuleEquipmentImportResult(BaseModel):
    read: int = Field(description="rows in the file")
    stored: int = Field(
        description="rows now in the table, new, changed or already identical"
    )
    refused: int = Field(
        description="rows that failed a check (key, state, the list, the models, the table's own guard)"
    )


@router.post(
    "/api/admin/rule-equipment/import",
    response_model=RuleEquipmentImportResult,
    responses={**schemas.ERRORS_404, **schemas.ERRORS_422},
)
def import_rule_equipment(
    body: RuleEquipmentImportBody,
    _admin: dict | None = Depends(admin_mod.current_admin),
):
    if not rule_label_schema.switch_on():
        raise HTTPException(status_code=404, detail="feature_off")
    try:
        rows = rule_equipment.read_file(rule_label_import.resolve_data_path(body.path))
    except (rule_label_import.ImportPathError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return rule_equipment.import_rows(connect(), rows)
