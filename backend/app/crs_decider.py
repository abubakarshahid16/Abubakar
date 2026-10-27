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
