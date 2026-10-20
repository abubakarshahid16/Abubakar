"""Order 161 C (163.4): a reason for EVERY finding held for the engineer, so it can be measured.

The stored `reason_code` of a finding is the leading code of its rationale
(`comparison.reason_code_of`), and many held findings carry none: their
rationale is a plain sentence ("the submitted value could not be read as a
quantity"). On the owner's 216400C run that was 161 of the held findings, and
nobody could say why. This module gives every one a reason, WITHOUT changing a
rationale, a stored code or a verdict (display and measurement only):

  1. the stored code, when there is one;
  2. else the program's own leading code in the rationale (`LEADING`);
  3. else what the finding itself shows: no datasheet field was paired
     (`NO_FIELD_PAIRED`), or a field was paired and the value was not decided
     (`VALUE_NOT_DECIDED`). These two are structural labels, not a diagnosis:
     they say where to look, and a count of them says how much is left to name.

General (owner order 143): no standard, field or sheet is named. Read only.
"""

from __future__ import annotations

from . import comparison

NEEDS_ENGINEER_REVIEW = comparison.NEEDS_ENGINEER_REVIEW
NO_FIELD_PAIRED = "no_field_paired"
VALUE_NOT_DECIDED = "value_not_decided"

#: The codes the program itself writes at the start of a rationale, each a
#: constant of `comparison` (so a renamed code cannot go unseen here).
LEADING = (
    comparison.LOW_TRUST_VALUE,
    comparison.AMBIGUOUS_MATCH,
    comparison.PAIRING_NOT_CHECKED,
    comparison.REFUSED_BY_RULE,
    comparison.ASK_REFUSED,
    comparison.ASK_UNREAD,
    comparison.RANGE_LIMIT_REASON,
    comparison.NOMINAL_VALUE_REASON,
    comparison.RELATIVE_LIMIT_REASON,
    comparison.RANGE_VS_EQUALITY,
    comparison.UNIT_MISMATCH,
    comparison.TABLE_ROW_REASON,
)


def reason_of(finding: dict) -> str:
    """The reason a finding was held, never empty (see the module docstring)."""
    code = finding.get("reason_code")
    if code:
        return str(code)
    text = finding.get("ai_rationale") or ""
    for leading in LEADING:
        if text.startswith(leading):
            return leading
    return VALUE_NOT_DECIDED if finding.get("fact_id") else NO_FIELD_PAIRED


def counts(findings: list[dict]) -> dict[str, int]:
    """{reason: how many findings} over the findings held for the engineer
    (NEEDS_ENGINEER_REVIEW, not removed by an engineer), most common first."""
    out: dict[str, int] = {}
    for finding in findings:
        if (
            finding.get("compliance_status") == NEEDS_ENGINEER_REVIEW
            and finding.get("approval_status") != "rejected"
        ):
            reason = reason_of(finding)
            out[reason] = out.get(reason, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))
