"""Why does a run's CRS show fewer rows or less AI wording than expected?
(order 236). Counts only, never document text. READ ONLY: point it at a copy.

For one run it composes the internal sheet exactly as the preview and the
export do (`main._crs_content`), then reports:
  rows         how many rows, by kind, and how many are engineer-confirmed
  wording      stored AI wordings, how many sit on a row of the sheet NOW, how
               many match no row (the key of the row they were stored for no
               longer exists), and how many sit on a row an engineer owns
  cells        rows with an AI cell text, with the plain-words note, with none
  run          the run's status and whether it was still running when read
"""

from __future__ import annotations

from collections import Counter


def diagnose(run_id: str, scope) -> dict:
    from app import crs_export, crs_wording, main
    from app.db import connect

    rows, meta, _name, _stamp = main._crs_content(run_id, scope, "internal")
    view = crs_export.build_crs_view(rows, meta)["rows"]
    stored = crs_wording.stored(run_id)
    by_key = {r.get("crs_row_key"): r for r in rows if r.get("crs_row_key")}
    run = (
        connect()
        .execute(
            "SELECT status, created_at, updated_at FROM review_runs WHERE id = ?",
            (run_id,),
        )
        .fetchone()
    )
    owned = sum(
        1 for k in stored if k in by_key and by_key[k].get("engineer_confirmed")
    )
    return {
        "run_status": run["status"] if run else None,
        "rows": len(rows),
        "rows_in_view": len(view),
        "rows_by_kind": dict(Counter(r.get("row_kind") for r in rows)),
        "rows_engineer_confirmed": sum(1 for r in rows if r.get("engineer_confirmed")),
        "wording_stored": len(stored),
        "wording_on_a_row_now": sum(1 for k in stored if k in by_key),
        "wording_matching_no_row": sum(1 for k in stored if k not in by_key),
        "wording_on_an_engineers_row": owned,
        "cells_with_text": sum(1 for r in view if r["ai_review_comment"]),
        "cells_blank": sum(1 for r in view if not r["ai_review_comment"]),
    }
