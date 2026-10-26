"""Order 224.1: the AI checks' drafts are a named bucket, never a status, and an exact repeat is marked.

The AI engineering check and the web standards check store DRAFTS. A draft is
not a verdict, so it NEVER gets a `compliance_status` (empty stays empty), and
it is counted in its own bucket, "AI observations (draft, no verdict)", beside
the status counts, never inside "engineer to check".

`settle(run)` runs after the checks (the review job and the `/ai-check` and
`/web-check` routes call it). Drafts of one check that are EXACT repeats
(same observation, action, field, quoted value, and the same standard or source
address NAMED in the draft's reason) are
marked, not merged and never deleted: the lowest page stays the first reading
and each repeat keeps its own page, tag and quote, and its reason ends "Exact
repeat of the observation on page N." A draft an engineer already decided on
is never touched (`review.UNDECIDED_SQL`). A second call changes nothing.

A draft cannot move the suggested review code: `comparison._recommend_code`
ignores these origins. Counts only in logs, no text.
"""

from __future__ import annotations

import logging
import re

from . import review as review_mod
from .db import connect

AI_ORIGIN = "ai_engineering_check"
WEB_ORIGIN = "web_standard_check"
DRAFT_ORIGINS = (AI_ORIGIN, WEB_ORIGIN)
#: SQL for "is a draft of the AI or web check" (a constant, no user text).
DRAFT_SQL = f"origin IN ('{AI_ORIGIN}', '{WEB_ORIGIN}')"
#: The bucket's key and its name on every count and screen.
DRAFT_BUCKET = "AI_OBSERVATION"
BUCKET_LABEL = "AI observations (draft, no verdict)"
_MARK = "Exact repeat of"
#: The check writes the standard a draft relates to into its reason, never a
#: document id, so that sentence is the draft's "which standard".
_RELATES = re.compile(r"Relates to: (.*?)\.(?:\s|$)")
#: The web check names its source by address instead.
_SOURCE = re.compile(r"Source: .*?(https?://\S+?)[.,]?(?:\s|$)")


def _fold(value: object) -> str:
    return " ".join(str(value or "").lower().split())


def _standard_of(rationale: str | None) -> str:
    """The standard (AI check) or source address (web check) the draft names,
    folded; "" when none is named."""
    found = _RELATES.search(rationale or "") or _SOURCE.search(rationale or "")
    return _fold(found.group(1)) if found else ""


def settle(review_run_id: str) -> dict:
    """Mark the exact repeats among the undecided drafts of the AI and web checks.
    Returns counts; idempotent (a second call changes nothing)."""
    conn = connect()
    with conn:
        drafts = conn.execute(
            "SELECT id, finding, required_action, contractor_section, contractor_page,"
            " contractor_evidence_text, ai_rationale, origin"
            " FROM review_findings WHERE review_run_id = ? AND origin IN (?, ?)"
            f" AND {review_mod.UNDECIDED_SQL}"
            " ORDER BY COALESCE(contractor_page, 1000000), created_at, id",
            (review_run_id, *DRAFT_ORIGINS),
        ).fetchall()
        first_of: dict[tuple, object] = {}
        marked = 0
        for row in drafts:
            key = (
                row["origin"],
                _fold(row["finding"]),
                _fold(row["required_action"]),
                _fold(row["contractor_section"]),
                _fold(row["contractor_evidence_text"]),
                _standard_of(row["ai_rationale"]),
            )
            first = first_of.setdefault(key, row)
            if first is row or _MARK in (row["ai_rationale"] or ""):
                continue
            page = first["contractor_page"]
            note = (
                f" {_MARK} the observation on page {page}."
                if page
                else f" {_MARK} an earlier observation."
            )
            conn.execute(
                "UPDATE review_findings SET ai_rationale = ? WHERE id = ?",
                ((row["ai_rationale"] or "").rstrip() + note, row["id"]),
            )
            marked += 1
    logging.getLogger(__name__).info(
        "AI and web check drafts of run %s: %d exact repeats marked",
        review_run_id,
        marked,
    )
    return {"marked": marked}
