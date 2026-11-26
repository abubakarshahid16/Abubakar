"""THE LEARNER, v1 (planner 26 Nov 2026 16:03): a comment an engineer REJECTED before is not raised again as if new.

A comment of this review whose rule (standard, clause and field) was rejected by an engineer on an EARLIER finished review of the
same kind of paper, and whose rejection still stands (the latest decision there), is not shown among the comments. It moves to
the team-only section "Rejected before", with the note "rejected before on <date>, reason: <the engineer's words>". It never
disappears: the page, the team file and the counts show it; it is never sent to the contractor. A comment this review's engineer
already decided stays where it is.

Behind `LEARNER_REJECTED_BEFORE_ENABLED`, OFF by default: until a scored read says it helps, every review is exactly as before.
Rule 5: a rejection on a paper the viewer may not read is never used for that viewer (its reason could carry that paper's words).
No model, no socket; reads only.
"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar

log = logging.getLogger(__name__)

#: At most this many earlier reviews of the kind are read (newest first).
MAX_EARLIER = 20
NOTE = "rejected before on {day}, reason: {reason}"

_INSIDE: ContextVar[bool] = ContextVar("learner_inside", default=False)


def enabled() -> bool:
    from .config import settings

    return bool(getattr(settings, "learner_rejected_before_enabled", False))


def rule_key(comment: dict) -> tuple[str, str, str] | None:
    """(standard, clause, field), normalised; None when the comment names no standard or no clause (no rule to match)."""
    std = " ".join(str(comment.get("standard") or "").lower().split())
    clause = " ".join(str(comment.get("clause") or "").lower().split())
    field = " ".join(str(comment.get("field") or "").lower().split())
    return (std, clause, field) if std and clause else None


def _kind(run: dict) -> str:
    try:
        identity = json.loads(run.get("identity_json") or "{}")
    except (TypeError, ValueError):
        return ""
    return " ".join(str((identity or {}).get("kind") or "").lower().split())


def _may_read(scope, paper_id: str) -> bool:
    if scope is None or getattr(scope, "is_admin", False):
        return True
    may = getattr(scope, "may_read", None)
    return bool(may(paper_id)) if callable(may) else False


def rejections(conn, run: dict, scope=None) -> dict[tuple[str, str, str], dict]:
    """{rule key: {"day", "reason", "run_id"}} of the comments rejected on earlier finished reviews of the same kind of paper whose
    rejection still stands, newest rejection first per rule."""
    from . import aim_review_store, aim_review_view
    from .aim_review_decisions import REJECT, key_of
    from .aim_review_store import DECISIONS

    kind = _kind(run)
    if not kind or not aim_review_store.has_tables(conn):
        return {}
    earlier = conn.execute(
        f"SELECT * FROM {aim_review_store.RUNS} WHERE status = 'done' AND run_id != ? AND created_at < ?"
        " ORDER BY created_at DESC LIMIT ?",
        (run["run_id"], run.get("created_at") or "", MAX_EARLIER * 5),
    ).fetchall()
    out: dict[tuple[str, str, str], dict] = {}
    read = 0
    for row in earlier:
        old = dict(row)
        if _kind(old) != kind or not _may_read(scope, old["paper_document_id"]):
            continue
        decided = conn.execute(
            f"SELECT comment_key, state, reason, decided_at FROM {DECISIONS} WHERE run_id = ? AND part = 'comment'"
            " ORDER BY decided_at, rowid",
            (old["run_id"],),
        ).fetchall()
        latest = {
            d["comment_key"]: d for d in decided
        }  # the latest decision of each comment
        rejected = {k: d for k, d in latest.items() if d["state"] == REJECT}
        if not rejected:
            continue
        read += 1
        if read > MAX_EARLIER:
            break
        token = _INSIDE.set(True)
        try:
            old_view = aim_review_view.build(
                conn, aim_review_store.run(conn, old["run_id"]) or old
            )
        except Exception as exc:  # noqa: BLE001 - an earlier review that cannot be read teaches nothing; the log says why
            log.warning(
                "learner: earlier review %s not read (%s)",
                old["run_id"],
                type(exc).__name__,
            )
            continue
        finally:
            _INSIDE.reset(token)
        for c in old_view.get("comments") or []:
            key, d = rule_key(c), rejected.get(key_of(c))
            if key is None or d is None or key in out:
                continue
            out[key] = {
                "day": str(d["decided_at"] or "")[:10],
                "reason": d["reason"] or "",
                "run_id": old["run_id"],
            }
    return out


def split(
    conn, run: dict, comments: list[dict], scope=None, tiles: dict | None = None
) -> tuple[list[dict], list[dict]]:
    """(the comments still raised, the comments moved to "Rejected before" with their note). A moved comment leaves the summary
    tiles (`tiles`: the count per severity, changed in place). With the switch off, or while an earlier review is being read for
    this, nothing moves."""
    if not enabled() or _INSIDE.get():
        return comments, []
    before = rejections(conn, run, scope)
    if not before:
        return comments, []
    kept, moved = [], []
    for c in comments:
        hit = before.get(rule_key(c)) if c.get("decision") is None else None
        if hit is None:
            kept.append(c)
            continue
        moved.append(
            {
                **c,
                "rejected_before": {
                    **hit,
                    "note": NOTE.format(day=hit["day"], reason=hit["reason"]),
                },
            }
        )
        if tiles is not None and c.get("severity") in tiles:
            tiles[c["severity"]] -= 1
    return kept, moved
