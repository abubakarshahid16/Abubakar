"""Routes of the general review (order 14, piece D): a paper's review history and the saved checklists (GET /api/reviews/papers/{document_id}/history, /api/reviews/general/checklists).

BASE BRANCH VERSION (integrator): an empty router, registered in `main.py`. Piece D adds the routes.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()
