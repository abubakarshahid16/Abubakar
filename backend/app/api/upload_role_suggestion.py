"""One upload for the whole app (order 14 lane E, owner 16 Nov 2026): what the screens need to know about the suggested role.

    GET /api/document-kinds/role-suggestion   {"enabled": bool, "review_roles": [...]}

`enabled` mirrors `upload_role_suggestion_enabled`; `review_roles` are the roles the AI Submittal Review page lists (contractor
submittals; with the switch on, contract documents too). Read only: no document, no text, no write. Confirming a suggested role
uses the existing role write (POST /api/documents/bulk/role, administrators only), so the role rules, the approval hook and the
audit stay the existing ones.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import access
from ..config import settings

router = APIRouter()

SUBMITTAL, CONTRACT = "CONTRACTOR_SUBMITTAL", "CONTRACT_DOCUMENT"


class UploadRoleSuggestionOut(BaseModel):
    enabled: bool
    review_roles: list[str]


def review_roles() -> list[str]:
    """The roles the review page lists: contractor submittals; with the switch on, contract documents too."""
    return (
        [SUBMITTAL, CONTRACT]
        if settings.upload_role_suggestion_enabled
        else [SUBMITTAL]
    )


@router.get("/api/document-kinds/role-suggestion", response_model=UploadRoleSuggestionOut)
def upload_role_suggestion(
    _scope: access.AccessScope = Depends(access.current_scope),
) -> dict:
    return {
        "enabled": bool(settings.upload_role_suggestion_enabled),
        "review_roles": review_roles(),
    }
