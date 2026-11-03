"""The AI senior review, step 3 of "the best CRS" (Part of #805, owner order 3 Nov 2026). OFF by default; this file is the entry point.

Design (see the step 3 design note): review = A (the code checks the review already makes) + B (an AI reading that ONLY adds rows A lacks).
B is given A's stored values, the whole headed section of the document and the full clause text; it is asked twice, a third time by the
stronger model on a disagreement, and a row still split is left to the engineer. Every row carries a document quote and a clause quote
that CODE verifies; every figure is compared by `figure_compare`; B never creates a Pass (a "complies" stays an internal "stated" row).

This first part holds only the switch and the entry point, so that the later parts (clause pack, reader, verifier, hook into the lane-6
proposals) each land small and reachable. With the switch off, or before those parts exist, it does nothing and says so.
"""

from __future__ import annotations

from . import figure_compare
from .config import settings

OFF = "off"
NOT_BUILT = "not_built"


def run_for_job(review_run_id: str, requester) -> dict:
    """Called once per review after the CRS rows are numbered. Changes nothing while the switch is off."""
    del review_run_id, requester  # the reader arrives in a later part
    if not settings.ai_senior_review_enabled:
        return {"state": OFF}
    return {"state": NOT_BUILT}


def figure_verdict(
    document_quote: str, clause_quote: str
) -> figure_compare.FigureResult | None:
    """The one door through which a figure is decided in this review: code only, never the model's own value."""
    return figure_compare.compare(document_quote, clause_quote)
