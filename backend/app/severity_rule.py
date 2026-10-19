"""One rule for a finding's severity word: a failed requirement is never minor.

Plain words. "minor" means one of two things only: a blank (the datasheet does
not state the value) or an item nobody has decided yet (the engineer still has
to check it). "minor" never describes a requirement the datasheet FAILED.
"observation" is for a finding that is met or out of scope, nothing else.

So a finding whose status is NON_COMPLIANT is "major" at the least, and
"critical" when its own item says so. The write side (`datasheet_checks.store`)
and the read side (`crs_mapping.row_severity`, which also reads runs stored
before this rule) both call this module, so there is one rule, not two.
"""

from __future__ import annotations

#: Worst first.
ORDER = ("critical", "major", "minor", "observation")
FAILED = "NON_COMPLIANT"
UNDECIDED = "NEEDS_ENGINEER_REVIEW"
FLOOR_FAILED = "major"
FLOOR_UNDECIDED = "minor"


def _at_least(severity: str, floor: str) -> str:
    """The worse of `severity` and `floor`; a word not in ORDER counts as the floor."""
    word = severity if severity in ORDER else floor
    return min(word, floor, key=ORDER.index)


def stored_severity(status: str | None, item_severity: str | None = None) -> str:
    """The severity to store for a new finding: failed is major or worse."""
    if status == FAILED:
        return _at_least(str(item_severity or "").lower(), FLOOR_FAILED)
    return "observation" if status == "COMPLIANT" else FLOOR_UNDECIDED


def effective_severity(finding: dict) -> str:
    """A stored finding's severity as it must be read, old runs included."""
    word = str(finding.get("severity") or "").lower()
    status = finding.get("compliance_status")
    if status == FAILED:
        return _at_least(word, FLOOR_FAILED)
    if status == UNDECIDED and word in ("", "observation"):
        return FLOOR_UNDECIDED
    return word
