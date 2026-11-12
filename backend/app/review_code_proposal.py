"""The PROPOSED review code of the redesigned review page: one stated rule, one line of reason (owner, 12 Nov 2026).

The system proposes, the engineer decides: this only names a code the app already has (`comparison.CODE_*`) and says WHY in one plain
line. The engineer still records the final code (`POST /api/reviews/runs/{id}/code`); nothing here records anything.

THE RULE, read from the points the engineer has decided SO FAR (a removed point counts for nothing; a kept "met" point is not a comment):
  Rejected / Revise and Resubmit   a KEPT point proven by code not to meet a "shall" rule: ALWAYS (owner, 12 Nov 2026); or, only when the
                                   setting `review_code_resubmit_at_kept_mandatory_not_met` N is above 0, at least N kept AI "not met"
                                   points (two readers or one reader) on "shall" rules, with the count in the reason. Off by default:
                                   until a company engineer states the practice, those points propose at most Approved with Comments.
  Approved with Comments           anything else kept as a comment: a not-met point, a question, a point the engineer added.
  Approved                         nothing kept as a comment.
WHILE POINTS ARE UNDECIDED the line reads "So far: <code>, N points still to decide" (the code the rule gives from what is decided so
far); with nothing decided yet it says so instead of proposing a code. "Manual Review Required" is for ONE reason only: pages of the
paper were not read, and it says so.
"""

from __future__ import annotations

from . import comparison

RULE_WORDS = (
    "Rule: a kept point proven by code not to meet a 'shall' rule gives Rejected / Revise and Resubmit; any other kept comment gives "
    "Approved with Comments; nothing kept as a comment gives Approved. Pages not read give Manual Review Required."
)


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def propose(
    points: list[dict], *, unread_pages: int | None = None, resubmit_at: int = 0
) -> dict:
    """{code, reason, line, so_far, undecided, rule, proposed_by}. `points`: the list's points with their `decision` ({state}). A point
    of source "added" is kept by definition. `unread_pages`: pages not read (None: the review holds no page record: said, never 0).
    `resubmit_at`: the setting N (0 = off)."""
    if unread_pages:
        return _out(
            comparison.CODE_MANUAL,
            f"{_plural(unread_pages, 'page was', 'pages were')} not read.",
            0,
        )
    undecided = sum(
        1
        for p in points
        if not (p.get("decision") or {}).get("state") and p.get("source") != "added"
    )
    kept = [
        p
        for p in points
        if (p.get("decision") or {}).get("state") in ("keep", "edit")
        or p.get("source") == "added"
    ]
    decided = len(points) - undecided
    if undecided and not decided:
        return _out(
            None,
            f"Nothing is decided yet: {_plural(undecided, 'point', 'points')} still to decide.",
            undecided,
        )
    proven = [p for p in kept if p["rank"] == 1 and p.get("shall", True)]
    ai_not_met = [p for p in kept if p["rank"] in (2, 3) and p.get("shall", True)]
    comments = [p for p in kept if p["rank"] <= 4 or p.get("source") == "added"]
    if proven:
        code, why = (
            comparison.CODE_REJECTED,
            f"{_plural(len(proven), 'kept point is', 'kept points are')} proven by code not to meet a 'shall' rule.",
        )
    elif resubmit_at > 0 and len(ai_not_met) >= resubmit_at:
        code = comparison.CODE_REJECTED
        why = f"{_plural(len(ai_not_met), 'kept AI not-met point', 'kept AI not-met points')} on 'shall' rules (the company's limit is {resubmit_at})."
    elif comments:
        code = comparison.CODE_APPROVED_WITH_COMMENTS
        why = f"{_plural(len(comments), 'kept comment', 'kept comments')}; none is proven by code to fail a 'shall' rule."
    else:
        code, why = comparison.CODE_APPROVED, "No comment is kept."
    return _out(code, why, undecided)


def _out(code: str | None, reason: str, undecided: int) -> dict:
    if code is None:
        line = reason
    elif undecided:
        line = (
            f"So far: {code}, {_plural(undecided, 'point', 'points')} still to decide"
        )
    elif code == comparison.CODE_MANUAL:
        line = f"{code}: {reason}"
    else:
        line = code
    return {
        "code": code,
        "reason": reason,
        "line": line,
        "so_far": bool(undecided),
        "undecided": undecided,
        "rule": RULE_WORDS,
        "proposed_by": "the system; the engineer decides",
    }
