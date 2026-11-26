"""A SIGNED REVIEW KEEPS THE COMMENTS IT WAS SIGNED WITH (G7 audit, lead-4, 26 Nov 2026).

The engineer's decisions are named by the lines each comment covered (`aim_review_decisions.key_of`). A later update may group the
same lines differently; a signed review then showed its signed comments split into smaller ones with no decision, beside a
sign-off that still stands and a contractor copy (kept byte for byte) that has the signed groups. Here, for a review with a
sign-off, the comments whose lines ALL fall inside ONE group decided up to the sign-off are joined back into that group, by the
review's own lossless merge (`aim_review_view._same_point`: every line's own words, pages and quotes). Lines in no signed group,
and every review with no sign-off, keep today's grouping. Comments and confirmations are joined only within their own part.
Reads only; no model.
"""

from __future__ import annotations

import logging
import sqlite3

log = logging.getLogger(__name__)


def _signed_groups(conn, run_id: str) -> dict[str, list[list[int]]]:
    """{part: [the lines of each group decided up to the latest sign-off]}; {} with no sign-off."""
    from . import aim_review_signoff
    from .aim_review_store import DECISIONS

    try:
        if not aim_review_signoff._has(conn):
            return {}
        signed = aim_review_signoff.latest(conn, run_id)
        if signed is None:
            return {}
        rows = conn.execute(
            f"SELECT DISTINCT part, comment_key FROM {DECISIONS} WHERE run_id = ? AND decided_at <= ?",
            (run_id, signed["signed_at"]),
        ).fetchall()
    except (
        sqlite3.Error
    ) as exc:  # an unreadable sign-off: today's grouping stays, and the log says why
        log.warning("signed groups not read for %s (%s)", run_id, type(exc).__name__)
        return {}
    out: dict[str, list[list[int]]] = {}
    for r in rows:
        lines = sorted(
            int(n) for n in str(r["comment_key"]).split(",") if n.strip().isdigit()
        )
        if lines:
            out.setdefault(r["part"], []).append(lines)
    return out


def _group(members: list[dict]) -> dict:
    """One comment of exactly these lines, by the same rules as `aim_review_view._item_comments`."""
    from . import aim_review_view as V

    members = sorted(members, key=lambda m: (m["page"] is None, m["page"] or 0, m["n"]))
    if len(members) == 1:
        m = members[0]
        return {
            **m,
            "lines": [m["n"]],
            "pages": [m["page"]] if m["page"] is not None else [],
        }
    one_field = len({V._field_key(m.get("field")) for m in members}) == 1
    same_words = len({m.get("comment") or "" for m in members}) == 1
    return V._places_of(members) if one_field and same_words else V._same_point(members)


def groups(conn, run: dict, points: list[dict]) -> tuple[list[dict], list[dict]]:
    """`aim_review_view.comments_and_confirmations`; for a SIGNED review, each group it was signed with is rebuilt from its own
    lines when every one of them is still sent and in no other signed group (else never guessed: those lines keep today's
    grouping), and the lines in no signed group are grouped as today."""
    from . import aim_review
    from . import aim_review_view as V

    signed = _signed_groups(conn, run["run_id"])
    if not signed:
        return V.comments_and_confirmations(points)
    by_n = {p["n"]: p for p in points}
    sendable = {p["n"] for p in points if aim_review.sendable(p)}
    used: set[int] = set()
    kept: dict[str, list[dict]] = {"comment": [], "confirmation": []}
    for part in ("comment", "confirmation"):
        for lines in signed.get(part, []):
            if all(n in sendable for n in lines) and not used & set(lines):
                kept[part].append(_group([by_n[n] for n in lines]))
                used |= set(lines)
    rest_c, rest_f = V.comments_and_confirmations(
        [p for p in points if p["n"] not in used]
    )
    return (
        sorted([*kept["comment"], *rest_c], key=lambda g: g["n"]),
        sorted([*kept["confirmation"], *rest_f], key=lambda g: g["n"]),
    )
