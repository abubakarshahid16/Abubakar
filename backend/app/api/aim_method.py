"""Which review method the ONE Review button runs (order 14, piece E): GET /api/reviews/method.

The screens read the method, the mark and the Local-only sentence from here; the sentences have ONE home, `aim_review_gate`.
`local_available` is a constant false today: the general review does not run on the local model yet.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import access, aim_review_gate

router = APIRouter()

#: The general review has no local engine today (a constant, not a setting).
LOCAL_AVAILABLE = False


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
        local_words=aim_review_gate.LOCAL_NOT_AVAILABLE,
        mark=aim_review_gate.AI_MARK,
    )
