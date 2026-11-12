"""Small pure helpers of the AI reviewer job (moved unchanged out of `agent_review_jobs`, file size): the run's stop sentence and
the equipment facts of the rule block. No I/O."""

from __future__ import annotations

from . import crs_ai_header as crs_header
from .db import connect

EQUIPMENT_LINES = (
    "another equipment type",
    "the paper names no equipment",
    "the paper names equipment the equipment list does not know",
    "the paper's equipment could not be read",
)


def _stop_text(runner, plan: dict) -> str | None:
    if runner is not None and runner.stopped:
        same = not runner.stop_text or runner.stop_text == runner.stopped
        return runner.stopped if same else f"{runner.stopped}: {runner.stop_text}"
    return plan.get("stop")


def _equipment_facts(block: dict) -> dict:
    """What the paper's equipment state means for the rules: the state word, and the summary sentences about equipment (counts
    only, no document text) that the summary and Rules used routes show."""
    eq = block.get("equipment") or {}
    notes = [
        ln
        for ln in block.get("summary_lines") or []
        if str(ln).startswith(EQUIPMENT_LINES)
    ]
    return {
        "state": eq.get("paper_equipment_state"),
        "types": eq.get("paper_types") or [],
        "notes": notes,
        "candidates": block.get("candidates"),
    }


def _header_facts(submittal: str, equipment_type: str | None) -> dict:
    """The CRS header block's facts (project, document number, title, revision, date, discipline) as the app holds them."""
    with connect() as conn:
        return crs_header.document_header(conn, submittal, equipment_type)
