"""Order 224.1: the AI checks' drafts are a named bucket, never a status, and an exact repeat is marked.

The AI engineering check and the web standards check store DRAFTS. A draft is
not a verdict, so it NEVER gets a `compliance_status` (empty stays empty), and
it is counted in its own bucket, "AI observations (draft, no verdict)", beside
the status counts, never inside "engineer to check".

`settle(run)` runs once after the checks. Drafts that are EXACT repeats (same
observation, same action, same field, same quoted value, same standard) are
marked, not merged and never deleted: the lowest page stays the first reading
and each repeat keeps its own page, tag and quote, and its reason ends "Exact
repeat of the observation on page N." A draft an engineer already decided on
is never touched (`review.UNDECIDED_SQL`). A second call changes nothing.

A draft cannot move the suggested review code: `comparison._recommend_code`
ignores these origins. Counts only in logs, no text.
"""

from __future__ import annotations

import logging

from . import review as review_mod
from .db import connect

AI_ORIGIN = "ai_engineering_check"
WEB_ORIGIN = "web_standard_check"
DRAFT_ORIGINS = (AI_ORIGIN, WEB_ORIGIN)
#: The bucket's key and its name on every count and screen.
DRAFT_BUCKET = "AI_OBSERVATION"
BUCKET_LABEL = "AI observations (draft, no verdict)"
_MARK = "Exact repeat of the observation on page"


def _fold(value: object) -> str:
    return " ".join(str(value or "").lower().split())


def observation_count(review_run_id: str) -> int:
    """How many drafts of the AI and web checks the run holds (the bucket)."""
    marks = ",".join("?" * len(DRAFT_ORIGINS))
    row = (
        connect()
        .execute(
            f"SELECT COUNT(*) AS n FROM review_findings WHERE review_run_id = ?"
            f" AND origin IN ({marks})",
            (review_run_id, *DRAFT_ORIGINS),
        )
        .fetchone()
    )
    return row["n"]


def settle(review_run_id: str) -> dict:
    """Mark the exact repeats among the AI check's undecided drafts. Returns
    counts; idempotent (a second call changes nothing)."""
    conn = connect()
    with conn:
        drafts = conn.execute(
            "SELECT id, finding, required_action, contractor_section, contractor_page,"
            " contractor_evidence_text, standard_document_id, standard_clause, ai_rationale"
            " FROM review_findings WHERE review_run_id = ? AND origin = ?"
            f" AND {review_mod.UNDECIDED_SQL}"
            " ORDER BY COALESCE(contractor_page, 1000000), created_at, id",
            (review_run_id, AI_ORIGIN),
        ).fetchall()
        first_of: dict[tuple, object] = {}
        marked = 0
        for row in drafts:
            key = (
                _fold(row["finding"]),
                _fold(row["required_action"]),
                _fold(row["contractor_section"]),
                _fold(row["contractor_evidence_text"]),
                row["standard_document_id"] or "",
                _fold(row["standard_clause"]),
            )
            first = first_of.setdefault(key, row)
            if first is row or _MARK in (row["ai_rationale"] or ""):
                continue
            page = first["contractor_page"]
            note = (
                f" {_MARK} {page}."
                if page
                else " Exact repeat of an earlier observation."
            )
            conn.execute(
                "UPDATE review_findings SET ai_rationale = ? WHERE id = ?",
                ((row["ai_rationale"] or "").rstrip() + note, row["id"]),
            )
            marked += 1
    logging.getLogger(__name__).info(
        "AI check drafts of run %s: %d exact repeats marked", review_run_id, marked
    )
    return {"marked": marked}
