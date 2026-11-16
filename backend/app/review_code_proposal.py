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
WHILE ANY POINT IS STILL TO DECIDE no code that lets the paper proceed (Approved, Approved with Comments) is proposed: a point still to
decide may hold a failure, so such a code would be a guess shown as a decision (honesty rule 4; order 14, first-time-user test 15: the
pump's team file proposed "Approved with Comments" with 35 of 37 points still to decide). The line then reads "No review code proposed
yet: N of M points still to decide" (`still_to_decide_sentence`, N and M the same count the sheet states: "x of M decided"). Only
Rejected / Revise and Resubmit may stand while points are open ("So far: <code>, N of M points still to decide"), by either of its two
branches above: a kept point proven by code not to meet a "shall" rule, or (only with the setting above 0) at least N kept AI "not met"
points; open points cannot undo either. When every point is decided the rule above applies unchanged. "Manual Review Required" is for
ONE reason only: pages of the paper were not read, and it says so.

THE HOMES. The paper's page (`GET /api/reviews/papers/{id}/points` `proposed_code`, the code box) and the team file's sheet 1 print
`propose`'s line. The paths that see ONE RUN, not the paper's list (the older rule check's run summary `GET /api/reviews/runs...`, its
CRS file and its preview), cannot read the list, so they never show an approving code: `run_level` gives "No review code proposed: see
the review page." in its place (a Rejected or Manual Review Required of that run stays: it lets nothing proceed). The contractor file
states only the recorded code.

THE RECORDED CODE (`POST /api/reviews/runs/{id}/code`). The engineer may record any code (he signs), but an approving code while points
are still to decide needs a typed reason (`open_code_refusal`, the route answers 422), and the files say so: the team file "<code>
(recorded with N of M points still to decide: <reason>)", the contractor file "<code> (recorded by the engineer)" (`recorded_words`).
"""

from __future__ import annotations

from . import comparison
from .db import connect

#: The roles of the codes that let the paper proceed (`comparison.CODE_ROLES`).
APPROVING_ROLES = frozenset({"approved", "approved_with_comments"})

#: What a path that sees one run, not the paper's list, shows in place of an approving code.
RUN_LEVEL_NOTE = "No review code proposed: see the review page."


def approving(code: str | None) -> bool:
    """Does `code` (a configured label or a default one) let the paper proceed?"""
    return comparison.code_role(code) in APPROVING_ROLES


def run_level(code: str | None) -> tuple[str | None, str | None]:
    """(the code a one-run path may show, the note in its place): an approving code is never shown there (see the module words)."""
    return (None, RUN_LEVEL_NOTE) if approving(code) else (code, None)


RULE_WORDS = (
    "Rule: a kept point proven by code not to meet a 'shall' rule gives Rejected / Revise and Resubmit; any other kept comment gives "
    "Approved with Comments; nothing kept as a comment gives Approved. Pages not read give Manual Review Required."
)


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def still_to_decide_sentence(undecided: int, of: int, proven_fails: int) -> str:
    """THE one sentence while any point is still to decide and no code may be proposed (the owner may change its words: it changes here
    only). `undecided` of `of`: the same count the sheet states. It names any code-proven Fail on a mandatory rule among the open points,
    so a proven failure is never hidden behind a count."""
    base = f"No review code proposed yet: {undecided} of {_plural(of, 'point', 'points')} still to decide"
    if proven_fails:
        base += f"; {_plural(proven_fails, 'is a code-proven Fail', 'are code-proven Fails')} on {'a mandatory rule' if proven_fails == 1 else 'mandatory rules'}"
    return base + "."


#: Why no code is proposed while points are open (the reason line under the sentence).
WAIT_REASON = "A code that lets the paper proceed is proposed only when every point is decided: a point still to decide may hold a failure."


def removed_fail_sentence(points: list[dict]) -> str:
    """A removed code-proven Fail on a mandatory rule is said, with who removed it and why: the code never drops silently."""
    gone = [
        p
        for p in points
        if (p.get("decision") or {}).get("state") == "remove"
        and p["rank"] == 1
        and p.get("shall", True)
    ]
    if not gone:
        return ""
    d = gone[0]["decision"]
    who = d.get("by") or "an engineer"
    why = f": {d['reason']}" if d.get("reason") else ""
    if len(gone) == 1:
        return f"1 code-proven Fail removed by {who}{why}."
    return f"{len(gone)} code-proven Fails removed (the first by {who}{why})."


def propose(
    points: list[dict],
    *,
    unread_pages: int | None = None,
    resubmit_at: int = 0,
    reviews_ran: bool = False,
) -> dict:
    """{code, reason, line, so_far, undecided, rule, proposed_by}. `points`: the list's points with their `decision` ({state}). A point
    of source "added" is kept by definition. `unread_pages`: pages not read (None: the review holds no page record: said, never 0).
    `resubmit_at`: the setting N (0 = off). `reviews_ran`: a review of this paper really ran (an empty list proposes Approved only then)."""
    if unread_pages:
        return _out(
            comparison.CODE_MANUAL,
            f"{_plural(unread_pages, 'page was', 'pages were')} not read.",
            0,
        )
    if not points:
        if reviews_ran:
            return _out(
                comparison.CODE_APPROVED,
                "The review ran and found no points to decide.",
                0,
            )
        return _out(
            None,
            "No review has run on this paper, so there are no points to decide.",
            0,
        )
    still_open = [
        p
        for p in points
        if not (p.get("decision") or {}).get("state") and p.get("source") != "added"
    ]
    undecided = len(still_open)
    kept = [
        p
        for p in points
        if (p.get("decision") or {}).get("state") in ("keep", "edit")
        or p.get("source") == "added"
    ]
    proven = [p for p in kept if p["rank"] == 1 and p.get("shall", True)]
    ai_not_met = [p for p in kept if p["rank"] in (2, 3) and p.get("shall", True)]
    comments = [p for p in kept if p["rank"] <= 4 or p.get("source") == "added"]
    if proven:
        code, why = (
            comparison.CODE_REJECTED,
            f"{_plural(len(proven), 'kept point is', 'kept points are')} proven by code not to meet a 'shall' rule.",
        )
        if any(
            p.get("strength_unknown") for p in proven
        ):  # the stricter code, said, never silent
            why += " For at least one, the rule's strength is not recorded, so it is treated as mandatory."
    elif resubmit_at > 0 and len(ai_not_met) >= resubmit_at:
        code = comparison.CODE_REJECTED
        why = f"{_plural(len(ai_not_met), 'kept AI not-met point', 'kept AI not-met points')} on 'shall' rules (the company's limit is {resubmit_at})."
    elif comments:
        code = comparison.CODE_APPROVED_WITH_COMMENTS
        why = f"{_plural(len(comments), 'kept comment', 'kept comments')}; none is proven by code to fail a 'shall' rule."
    else:
        code, why = comparison.CODE_APPROVED, "No comment is kept."
    gone = removed_fail_sentence(points)
    if undecided and code != comparison.CODE_REJECTED:
        open_fails = sum(
            1 for p in still_open if p["rank"] == 1 and p.get("shall", True)
        )
        line = still_to_decide_sentence(undecided, len(points), open_fails)
        return _out(None, f"{WAIT_REASON} {gone}".strip(), undecided, line=line)
    return _out(code, f"{why} {gone}".strip(), undecided, of=len(points))


def _line(code: str | None, reason: str, undecided: int, of: int) -> str:
    if code is None:
        return reason
    if undecided:  # only a Rejected code reaches here with points open (`propose`)
        return f"So far: {code}, {undecided} of {_plural(of, 'point', 'points')} still to decide"
    if code == comparison.CODE_MANUAL:
        return f"{code}: {reason}"
    return code


def _out(
    code: str | None,
    reason: str,
    undecided: int,
    *,
    of: int = 0,
    line: str | None = None,
) -> dict:
    if line is None:
        line = _line(code, reason, undecided, of)
    return {
        "code": code,
        "reason": reason,
        "line": line,
        "so_far": bool(undecided),
        "undecided": undecided,
        "rule": RULE_WORDS,
        "proposed_by": "the system; the engineer decides",
    }


# ------------------------------------------------------------------------------------------ the recorded code


def _ensure(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS review_code_open_points (
            review_run_id TEXT PRIMARY KEY,
            undecided INTEGER NOT NULL,
            of_points INTEGER NOT NULL,
            recorded_at TEXT NOT NULL)"""
    )


def open_code_refusal(
    code: str, reason: str | None, undecided: int, of: int
) -> str | None:
    """The plain sentence refusing an approving code recorded while points are still to decide without a typed reason, or None."""
    if undecided and approving(code) and not (reason or "").strip():
        return (
            f"{code} lets the paper proceed while {undecided} of {_plural(of, 'point', 'points')} are still to decide: "
            "type the reason it may proceed now, or decide the points first."
        )
    return None


def remember_open(review_run_id: str, code: str, undecided: int, of: int) -> None:
    """Keep how many points were still to decide when an approving code was recorded (nothing kept otherwise)."""
    from datetime import UTC, datetime

    conn = connect()
    with conn:
        _ensure(conn)
        conn.execute(
            "DELETE FROM review_code_open_points WHERE review_run_id = ?",
            (review_run_id,),
        )
        if undecided and approving(code):
            conn.execute(
                "INSERT INTO review_code_open_points (review_run_id, undecided, of_points, recorded_at) VALUES (?,?,?,?)",
                (
                    review_run_id,
                    undecided,
                    of,
                    datetime.now(UTC).isoformat(timespec="seconds"),
                ),
            )


def _open_at_record(conn, review_run_id: str) -> tuple[int, int] | None:
    _ensure(conn)
    row = conn.execute(
        "SELECT undecided, of_points FROM review_code_open_points WHERE review_run_id = ?",
        (review_run_id,),
    ).fetchone()
    return (int(row[0]), int(row[1])) if row else None


def recorded_words(
    conn,
    review_run_id: str | None,
    code: str | None,
    reason: str | None,
    *,
    undecided: int,
    of: int,
) -> dict[str, str | None]:
    """{"team", "contractor"}: the recorded code as each file (and the page) prints it, None when no code is recorded. An approving
    code recorded with points still to decide says so on the team file, with the engineer's reason; a code recorded before that count
    was kept, with points open now, says how many are open now."""
    if not code:
        return {"team": None, "contractor": None}
    team = code
    if approving(code):
        at = _open_at_record(conn, review_run_id) if review_run_id else None
        why = f": {reason.strip()}" if (reason or "").strip() else ""
        if at:
            team = f"{code} (recorded with {at[0]} of {_plural(at[1], 'point', 'points')} still to decide{why})"
        elif undecided:
            team = f"{code} ({undecided} of {_plural(of, 'point', 'points')} still to decide{why})"
    return {"team": team, "contractor": f"{code} (recorded by the engineer)"}
