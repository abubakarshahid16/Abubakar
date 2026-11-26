"""Which review method the ONE Review button runs (order 14, piece E): GET /api/reviews/method.

The screens read the method, the mark and the Local-only sentence from here; the sentences have ONE home, `aim_review_gate`.
`local_available` is true while the local route's way back (GENERAL_REVIEW_LOCAL_ENABLED) is on: Local only runs the general review
on the local model, and `local_words` says what that means (nothing leaves this computer; not yet scored); off, `local_words` says
Local only is switched off.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import access, aim_review_gate

router = APIRouter()


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
        local_available=aim_review_gate.local_on(),
        local_words=aim_review_gate.LOCAL_PLAN_WORDS
        if aim_review_gate.local_on()
        else aim_review_gate.LOCAL_SWITCHED_OFF,
        mark=aim_review_gate.AI_MARK,
    )
