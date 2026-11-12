"""One decision on a RULE-CHECK point, written to BOTH decision records in ONE transaction (owner, 12 Nov 2026).

The rule check already had its own record of decisions (`crs_issue_decisions`: accept or reject, with a reason, and the finding itself
marked accepted or rejected). The redesigned page has its own (`review_point_decision`: keep, edit or remove). A point of the rule check
is decided through either door: the page's route or the older finding-decision route. Both call `record_rule_decision`, which writes
  1. the new record,
  2. the old record,
  3. the finding(s) behind the point,
inside one `with conn:` block: all of it or none of it, so the two records cannot be left disagreeing by a failure in the middle or by
two engineers writing at once (SQLite takes one writer at a time). `disagreements` states what the sign route checks: a point whose
two records name opposite answers. Keep and Edit are an accept; Remove is a reject.

An AI line has only the new record (there is nothing older to agree with): `review_point_decisions.decide`.
"""

from __future__ import annotations

from . import crs_issue, review
from . import review_point_decisions as dec
from .db import connect

OLD_OF_NEW = {
    dec.KEEP: crs_issue.ACCEPT,
    dec.EDIT: crs_issue.ACCEPT,
    dec.REMOVE: crs_issue.REJECT,
}
NEW_OF_OLD = {crs_issue.ACCEPT: dec.KEEP, crs_issue.REJECT: dec.REMOVE}
DEFAULT_REASON = {
    dec.KEEP: "Kept in the review page",
    dec.EDIT: "Edited in the review page",
}
DEFAULT_CODE = {dec.KEEP: "kept_as_written", dec.EDIT: "edited_by_engineer"}


def record_rule_decision(
    paper_id: str,
    run_id: str,
    key: str,
    state: str,
    *,
    actor: str,
    finding_ids: list[str] | None = None,
    text: str | None = None,
    reason: str | None = None,
    reason_code: str | None = None,
    click_id: str | None = None,
    original: str | None = None,
    old_door: bool = False,
) -> dict:
    """Write one decision on the rule-check point `key` (its finding id, or its row key) to both records and to every finding behind
    it, in one transaction. Returns the OLD record's row (the shape the older route answers with). Raises `dec.PointRefused` or
    `crs_issue.IssueError` BEFORE anything is written; any other failure rolls everything back."""
    old = OLD_OF_NEW[state]
    listed = (
        crs_issue.REMOVAL_REASONS if old == crs_issue.REJECT else crs_issue.KEEP_REASONS
    )
    if reason_code is not None and reason_code not in listed:
        raise crs_issue.IssueError(
            "the reason is not one of the listed reasons for this decision"
        )
    if reason_code is not None and not " ".join((reason or "").split()):
        reason = listed[
            reason_code
        ]  # a listed reason IS the reason when nothing was typed (the older route's rule)
    if old_door:
        # The OLDER route keeps its own rules and its own words (an accept without a reason, or a short one, is refused with the same
        # sentence as before): nothing is defaulted here; the older record validates inside the transaction.
        text, cleaned = "", " ".join((reason or "").split())
        old_reason = cleaned
    else:
        text, cleaned = dec.check(state, text, reason)
        if reason_code is None and old == crs_issue.ACCEPT:
            reason_code = DEFAULT_CODE[state]
        old_reason = cleaned or DEFAULT_REASON.get(state, "")
    ids = list(dict.fromkeys(finding_ids or [key]))
    conn = connect()
    dec.ensure_schema(
        conn
    )  # every table is made BEFORE the transaction opens (a CREATE inside it would commit it)
    crs_issue.ensure_schema()
    review.ensure_schema()
    changes = crs_issue.finding_changes(old, actor, review.now_iso())
    with conn:
        dec.insert_row(
            conn,
            paper_id,
            f"rc:{key}",
            state,
            actor=actor,
            text=text,
            reason=cleaned or old_reason if state == dec.REMOVE else cleaned,
            original=original,
        )
        row = crs_issue.record_row(
            conn,
            run_id,
            crs_issue.FINDING,
            key,
            old,
            old_reason,
            actor,
            reason_code,
            click_id,
        )
        for fid in ids:
            review.update_in(conn, fid, changes, actor_user_id=actor)
    if (
        reason_code != "kept_in_bulk"
    ):  # rule_trust's spot-check record: derived, outside the decision records
        from . import rule_trust

        rule_trust.record_engineer_decision(
            review.get(key) or {}, old, actor=actor, note=old_reason
        )
    return row


def disagreements(paper_id: str, run_id: str) -> list[str]:
    """The rule-check points of this paper whose two records name opposite answers (the new record says keep or edit and the old says
    reject, or the reverse; or the new record holds a decision the old one never saw). A point decided only in the old record (before
    the page existed) is not a disagreement. Ids only."""
    new = {p: d for p, d in dec.latest(paper_id).items() if p.startswith("rc:")}
    if not new:
        return []
    old: dict[str, str] = {}
    conn = connect()
    for d in conn.execute(  # commit order (rowid), not the clock: two writers in one second are still ordered
        "SELECT subject, decision FROM crs_issue_decisions WHERE review_run_id = ? AND kind = ? ORDER BY rowid",
        (run_id, crs_issue.FINDING),
    ):
        old[d["subject"]] = d["decision"]
    return sorted(
        pid
        for pid, d in new.items()
        if old.get(pid.removeprefix("rc:")) != OLD_OF_NEW[d["state"]]
    )
