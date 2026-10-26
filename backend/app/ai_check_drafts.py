"""Order 224 item 4: the AI checks' drafts carry a status, and a repeat is one row.

The AI engineering check and the web standards check store DRAFTS, with no
`compliance_status` (they are not verdicts), and the same observation was
stored once per page, so one relief-valve sheet with four tags showed "valve
size is blank" four times, each time with an empty status.

`settle(run)` runs once after the checks (the review job calls it) and does two
things to the run's drafts:

  * every draft with no status gets NEEDS_ENGINEER_REVIEW ("engineer to
    check"). Never a pass, never a failure.
  * drafts of the AI engineering check that say the SAME thing (same
    observation, same action, same field) on several pages become ONE row, the
    lowest page, whose reason ends "Same observation on pages 2, 3, 4 (tags
    A, B)". The repeats are removed. A draft an engineer already decided on is
    never merged or removed (`review.UNDECIDED_SQL`).

A status does NOT let a draft move the suggested review code: `comparison.
_recommend_code` ignores these origins whatever their status. Counts only in
logs, no text.
"""

from __future__ import annotations

import logging

from . import review as review_mod
from .db import connect

AI_ORIGIN = "ai_engineering_check"
WEB_ORIGIN = "web_standard_check"
DRAFT_ORIGINS = (AI_ORIGIN, WEB_ORIGIN)
#: The status of a draft: "engineer to check". The same word as the engine's.
STATUS = "NEEDS_ENGINEER_REVIEW"


def _fold(value: object) -> str:
    return " ".join(str(value or "").lower().split())


def _tags(conn, submittal_id: str | None, pages: list[int]) -> list[str]:
    """The equipment tags the sheet's values carry on these pages."""
    if not submittal_id or not pages:
        return []
    marks = ",".join("?" * len(pages))
    rows = conn.execute(
        "SELECT DISTINCT equipment_tag FROM submittal_facts WHERE submittal_document_id = ?"
        f" AND equipment_tag IS NOT NULL AND TRIM(equipment_tag) <> '' AND page IN ({marks})"
        " ORDER BY equipment_tag",
        (submittal_id, *pages),
    )
    return [r["equipment_tag"] for r in rows]


def _page_list(pages: list[int]) -> str:
    return ", ".join(str(p) for p in pages)


def settle(review_run_id: str) -> dict:
    """Give every status-less draft of the run its status and merge repeats of
    the AI check. Returns counts; idempotent (a second call changes nothing)."""
    conn = connect()
    marks = ",".join("?" * len(DRAFT_ORIGINS))
    with conn:
        statused = conn.execute(
            f"UPDATE review_findings SET compliance_status = ? WHERE review_run_id = ?"
            f" AND origin IN ({marks}) AND (compliance_status IS NULL OR compliance_status = '')",
            (STATUS, review_run_id, *DRAFT_ORIGINS),
        ).rowcount
        run = conn.execute(
            "SELECT submittal_document_id FROM review_runs WHERE id = ?",
            (review_run_id,),
        ).fetchone()
        submittal = run["submittal_document_id"] if run else None
        drafts = conn.execute(
            "SELECT id, finding, required_action, contractor_section, contractor_page, ai_rationale"
            " FROM review_findings WHERE review_run_id = ? AND origin = ?"
            f" AND {review_mod.UNDECIDED_SQL}"
            " ORDER BY COALESCE(contractor_page, 1000000), created_at, id",
            (review_run_id, AI_ORIGIN),
        ).fetchall()
        groups: dict[tuple, list] = {}
        for row in drafts:
            key = (
                _fold(row["finding"]),
                _fold(row["required_action"]),
                _fold(row["contractor_section"]),
            )
            groups.setdefault(key, []).append(row)
        merged = 0
        for group in groups.values():
            if len(group) < 2:
                continue
            first, repeats = group[0], group[1:]
            pages = sorted(
                {r["contractor_page"] for r in group if r["contractor_page"]}
            )
            tags = _tags(conn, submittal, pages)
            note = (
                f" Same observation on pages {_page_list(pages)}"
                if len(pages) > 1
                else " Same observation repeated"
            )
            note += f" (tags {', '.join(tags)})." if tags else "."
            conn.execute(
                "UPDATE review_findings SET ai_rationale = ? WHERE id = ?",
                ((first["ai_rationale"] or "").rstrip() + note, first["id"]),
            )
            conn.execute(
                f"DELETE FROM review_findings WHERE id IN ({','.join('?' * len(repeats))})",
                [r["id"] for r in repeats],
            )
            merged += len(repeats)
    logging.getLogger(__name__).info(
        "AI check drafts of run %s: %d given a status, %d repeats merged",
        review_run_id,
        statused,
        merged,
    )
    return {"statused": statused, "merged": merged}
