"""Routes of the general review (order 14, piece E): which review method the Review button runs (GET /api/reviews/method).

BASE BRANCH VERSION (integrator): an empty router, registered in `main.py`. Piece E adds the routes.
"""

from __future__ import annotations

from fastapi import APIRouter

from .. import (
    aim_review_gate,  # noqa: F401 - piece E's route reads it; imported here so the app reaches it
)

router = APIRouter()
