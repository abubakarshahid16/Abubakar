"""THE FACE OF A FILE ON THE REVIEWS LIST (lead-4's walk of the live app, 26 Nov 2026): which of a paper's general reviews its row
shows and opens, in ONE place, for the Reviews list and the dashboard alike.

THE RULE: the newest SIGNED review (its sign-off still matches the decisions), else the newest review made on Claude, else the
newest review. A review made on the local model (a rough draft, not scored as reliable) is the face only when the paper has
nothing else; otherwise it is listed folded under the face, named by its engine words. Whatever is the face, its row names the
engine (`engine_words`: "Claude" or "Local model: rough draft, not scored as reliable"). Reads only.
"""

from __future__ import annotations

import sqlite3

SIGNED, CHANGED, NOT_SIGNED = "signed", "changed", "not_signed"
CLAUDE, LOCAL = "claude", "local"


def engine_words(engine: str) -> str:
    """The row's engine words: "Claude", or the local model's rough-draft label (`aim_review_gate.LOCAL_ROUGH_DRAFT`)."""
    from . import aim_review_gate

    return (
        f"Local model: {aim_review_gate.LOCAL_ROUGH_DRAFT}"
        if engine == LOCAL
        else "Claude"
    )


def engine_of(conn, run: dict) -> str:
    """ "local" when the run was made on the local model (its own calls, or its plan said Local only), else "claude"."""
    from . import aim_review_local_view

    try:
        return (
            LOCAL
            if aim_review_local_view.engine_of(conn, dict(run))["local"]
            else CLAUDE
        )
    except (sqlite3.Error, KeyError, TypeError):
        return CLAUDE


def signoff_state(conn, run_id: str) -> str:
    """ "signed" while the sign-off still matches the engineer's decisions, "changed" when a decision came after it, else
    "not_signed"."""
    from . import aim_review_signoff as so

    if not so._has(conn):
        return NOT_SIGNED
    row = so.latest(conn, run_id)
    if row is None:
        return NOT_SIGNED
    return SIGNED if row["decisions_digest"] == so.digest(conn, run_id) else CHANGED


def face_ids(rows: list[dict]) -> set[str]:
    """The face run id of each paper among `rows` (dicts with review_run_id, submittal_document_id, created_at, engine and
    general_signoff), by THE RULE."""

    def newest(xs: list[dict]) -> dict | None:
        return max(
            xs,
            key=lambda r: (str(r.get("created_at") or ""), str(r["review_run_id"])),
            default=None,
        )

    by_paper: dict[str, list[dict]] = {}
    for r in rows:
        by_paper.setdefault(str(r["submittal_document_id"]), []).append(r)
    out = set()
    for runs in by_paper.values():
        face = (
            newest([r for r in runs if r.get("general_signoff") == SIGNED])
            or newest([r for r in runs if r.get("engine") != LOCAL])
            or newest(runs)
        )
        out.add(str(face["review_run_id"]))
    return out
