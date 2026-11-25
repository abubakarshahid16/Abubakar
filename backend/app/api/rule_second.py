"""POST /api/admin/rule-second/import: the server adds a second-model approval file the pass exported (planner, 25 Nov
2026). Admin only; switch off: 404 "feature_off". The file must be a .json file INSIDE the data directory; every approval
is checked again against the live book (`rule_second_import`); a review queued or running: 409, nothing written.
`dry_run`: the same checks and counts, nothing written."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import admin as admin_mod
from .. import rule_label_import, rule_label_schema, rule_second_import, schemas
from ..db import connect

router = APIRouter()


class RuleSecondImportBody(BaseModel):
    path: str = Field(
        min_length=1,
        max_length=1024,
        description="a second-approval file under the data directory",
    )
    dry_run: bool = Field(
        default=True, description="check and count only; nothing is written"
    )


@router.post(
    "/api/admin/rule-second/import",
    responses={**schemas.ERRORS_404, **schemas.ERRORS_422},
)
def import_rule_second(
    body: RuleSecondImportBody, _admin: dict | None = Depends(admin_mod.current_admin)
) -> dict:
    if not rule_label_schema.switch_on():
        raise HTTPException(status_code=404, detail="feature_off")
    try:
        data = rule_second_import.read_file(
            rule_label_import.resolve_data_path(body.path)
        )
    except (
        rule_label_import.ImportPathError,
        rule_second_import.NotASecondFile,
    ) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    try:
        return rule_second_import.import_second(connect(), data, dry_run=body.dry_run)
    except rule_second_import.ReviewRunning:
        raise HTTPException(
            status_code=409,
            detail="a review is queued or running; import after it ends",
        ) from None
