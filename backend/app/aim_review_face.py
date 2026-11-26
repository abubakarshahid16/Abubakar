"""THE FACE OF A FILE ON THE REVIEWS LIST (lead-4's walk of the live app, 26 Nov 2026): which of a paper's general reviews its row
shows and opens, in ONE place, for the Reviews list and the dashboard alike.

THE RULE: the newest SIGNED review (its sign-off still matches the decisions), else the newest review made on Claude, else the
newest review. A review made on the local model (a rough draft: `aim_review_gate.LOCAL_ROUGH_DRAFT`) is the face only when the paper has
nothing else; otherwise it is listed folded under the face, named by its engine words. Whatever is the face, its row names the
engine (`engine_words`: "Claude", or the local model's rough-draft label from `aim_review_gate`). Reads only.
"""

from __future__ import annotations

import sqlite3

SIGNED, CHANGED, NOT_SIGNED = "signed", "changed", "not_signed"
CLAUDE, LOCAL, UNKNOWN = "claude", "local", "unknown"
#: A run counts as FINISHED only when it ended with a whole review (review of update 12, N7): a failed or stopped run is never
#: preferred as a file's face over a finished review.
FINISHED = "done"
#: The face row's note when a newer review of the paper exists (lead-4, 26 Nov 2026: so the signed-first face never hides it).
NEWER_UNSIGNED = "A newer review exists, not signed"


def engine_words(engine: str) -> str:
    """The row's engine words: "Claude", or the local model's rough-draft label (`aim_review_gate.LOCAL_ROUGH_DRAFT`)."""
    from . import aim_review_gate

    if engine == LOCAL:
        return f"Local model: {aim_review_gate.LOCAL_ROUGH_DRAFT}"
    return "engine not recorded" if engine == UNKNOWN else "Claude"


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
        return UNKNOWN  # an unreadable run is never called Claude (review of update 12, N7)


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
    """The face run id of each paper among `rows` (dicts with review_run_id, submittal_document_id, created_at, status, engine
    and general_signoff), by THE RULE, among FINISHED runs first: newest signed, else newest finished on Claude, else newest
    finished (a local draft). A paper with no finished run shows its newest run still going, else its newest run (a failure is
    shown, never hidden)."""

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
        done = [r for r in runs if r.get("status") == FINISHED]
        face = (
            newest([r for r in done if r.get("general_signoff") == SIGNED])
            or newest([r for r in done if r.get("engine") == CLAUDE])
            or newest(done)
            or newest([r for r in runs if r.get("status") in ("queued", "running")])
            or newest(runs)
        )
        out.add(str(face["review_run_id"]))
    return out


def newer_words(rows: list[dict], face_id: str) -> str | None:
    """The face row's note naming the newest review of the same paper that is newer than the face (never signed: a newer signed
    one would be the face), with its engine words; None when the face is the newest."""
    face = next((r for r in rows if str(r["review_run_id"]) == face_id), None)
    if face is None:
        return None
    key = lambda r: (str(r.get("created_at") or ""), str(r["review_run_id"]))  # noqa: E731
    newer = [
        r
        for r in rows
        if r["submittal_document_id"] == face["submittal_document_id"]
        and r.get("status") not in ("failed", "cancelled")
        and key(r) > key(face)
    ]
    if not newer:
        return None
    return f"{NEWER_UNSIGNED} ({engine_words(max(newer, key=key).get('engine') or UNKNOWN)})"
