"""Routes of the general review (order 14, piece C): the general review's results page and its file (GET /api/reviews/papers/{document_id}/general, .../general/sheet).

BASE BRANCH VERSION (integrator): an empty router, registered in `main.py`. Piece C adds the routes.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()
