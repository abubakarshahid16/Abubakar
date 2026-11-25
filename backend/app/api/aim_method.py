"""Which review method the ONE Review button runs (order 14, piece E): GET /api/reviews/method.

The screens read the method, the mark and the Local-only sentence from here; the sentences have ONE home, `aim_review_gate`.
`local_available` is a constant true since the local route (planner 25 Nov 2026 22:35): Local only runs the general review on the
local model, and `local_words` says what that means (nothing leaves this computer; not yet scored).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import access, aim_review_gate

router = APIRouter()

#: Local only is available for the general review: it runs on the local model (a constant, not a setting).
LOCAL_AVAILABLE = True


class ReviewMethodOut(BaseModel):
    method: Literal["general", "earlier"]
    old_engine: bool
    local_available: bool
    local_words: str
    mark: str


@router.get(
    "/api/reviews/method",
    dependencies=[Depends(access.current_scope)],
    response_model=ReviewMethodOut,
)
def review_method() -> ReviewMethodOut:
    """The method the Review button runs, whether the way back is on, and the fixed words. Writes nothing, calls nothing."""
    return ReviewMethodOut(
        method=aim_review_gate.method(),
        old_engine=aim_review_gate.old_engine_on(),
        local_available=LOCAL_AVAILABLE,
        local_words=aim_review_gate.LOCAL_PLAN_WORDS,
        mark=aim_review_gate.AI_MARK,
    )
