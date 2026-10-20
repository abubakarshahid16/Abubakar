"""Standards a review held for the engineer, counted where the checked ones are.

A standard that came only from a guessed equipment type is held (order 142):
its requirements are not checked. The run stores WHY in the column
`review_applicable_standards.held_reason` (a code; NULL = not held), written
from the in-memory hold flag, never from the free text of `exclusion_reason`
(order 143). `note()` turns the stored codes into the run's one sentence, over
the standards the caller may read (rule 5: an intersection). Null, never 0
(rule 4): nothing held, or a run stored before the column, gives None.
"""

from __future__ import annotations

from .db import connect

HELD_UNSURE_TYPE = "equipment_unsure"
#: Orders 180.1 item 6: the run's own standards check judged the standard not
#: applicable to this equipment (the type is sure; the standard is not for it).
HELD_NOT_APPLICABLE = "judged_not_applicable"

#: code -> the reason in the sentence. An unknown code is held for the engineer
#: without a reason; it never borrows the unsure wording.
_WHY = {
    HELD_UNSURE_TYPE: " because the equipment type is unsure",
    HELD_NOT_APPLICABLE: " because the run's standards check judged this equipment outside their scope",
}


def mark(
    review_run_id: str, standard_ids: list[str], code: str = HELD_UNSURE_TYPE
) -> None:
    """Flag the held rows of a run. An engineer's own row is never flagged."""
    if not review_run_id or not standard_ids:
        return
    marks = ",".join("?" * len(standard_ids))
    with connect() as conn:
        conn.execute(
            "UPDATE review_applicable_standards SET held_reason = ? "
            "WHERE review_run_id = ? AND included = 0 AND selection_method != 'manual' "
            f"AND standard_document_id IN ({marks})",
            (code, review_run_id, *standard_ids),
        )


def mark_rows(review_run_id: str, selected: dict) -> None:
    """Flag the held rows of a selection, each with its own reason code (a row
    says its `held_code`; one that says none is the unsure-type hold)."""
    by_code: dict[str, list[str]] = {}
    for sid, row in selected.items():
        if row.get("held_for_engineer"):
            by_code.setdefault(row.get("held_code") or HELD_UNSURE_TYPE, []).append(sid)
    for code, ids in by_code.items():
        mark(review_run_id, ids, code)


def note(
    review_run_id: str, allowed_document_ids: frozenset[str] | None
) -> dict | None:
    """The run's held-for-the-engineer note, or None when there is nothing to say."""
    rows = (
        connect()
        .execute(
            "SELECT standard_document_id, held_reason FROM review_applicable_standards "
            "WHERE review_run_id = ? AND included = 0 AND held_reason IS NOT NULL "
            "ORDER BY standard_document_id",
            (review_run_id,),
        )
        .fetchall()
    )
    kept = [
        r
        for r in rows
        if allowed_document_ids is None
        or r["standard_document_id"] in allowed_document_ids
    ]
    if not kept:
        return None
    n = len(kept)
    codes = {r["held_reason"] for r in kept}
    why = _WHY.get(next(iter(codes)), "") if len(codes) == 1 else ""
    verb = "standard was" if n == 1 else "standards were"
    return {
        "count": n,
        "standard_document_ids": [r["standard_document_id"] for r in kept],
        "sentence": (
            f"{n} {verb} held for the engineer{why}; their requirements were not "
            "checked. Counted among the standards in your library that this "
            "review considered."
        ),
    }
