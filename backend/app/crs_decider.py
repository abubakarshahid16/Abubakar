"""Who decided a finding (#892 item 10)."""

from __future__ import annotations


def decider(finding: dict) -> str | None:
    """The engineer who decided this finding: the one who confirmed it, else the one who ACCEPTED it
    (`approved_by`, written with `approval_status = 'accepted'`). The plain accept button writes
    `approved_by`, not `confirmed_by`; a row an engineer accepted must name them, not "AI Review"."""
    if finding.get("confirmed_by"):
        return finding["confirmed_by"]
    if finding.get("approval_status") != "accepted":
        return None
    return finding.get("approved_by")


def tick_done(finding: dict) -> bool:
    """Has an engineer really TICKED this safety row? An edit also confirms a finding
    (`main.update_review_finding`), but it is the engineer's words, perhaps an objection:
    not a tick."""
    if finding.get("engineer_comment"):
        return False
    return bool(
        finding.get("confirmed_by") or finding.get("approval_status") == "accepted"
    )


def tick_state(finding: dict) -> dict:
    """What the view needs of a safety row, beside the words its number keeps."""
    return {
        "tick_done": tick_done(finding),
        "engineer_words": finding.get("engineer_comment") or "",
    }
