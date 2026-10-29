"""Order 305.4 part B (PR #1451): the CRS column "AI suggests (internal)" (crs_suggestion.py, crs_export.py,
crs_mapping.py). Ids M1451-01.. (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_S = APP / "crs_suggestion.py"
_E = APP / "crs_export.py"
_M = APP / "crs_mapping.py"
_T = "tests/test_305_ai_suggests.py"
_TAG = ("crs", "ai-suggests")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1451-01",
        phase=1451,
        description="a held rule that said does not meet is shown as Pass",
        path=_S,
        anchor='_WORD = {"COMPLIANT": "Pass", "NON_COMPLIANT": "Fail"}',
        replacement='_WORD = {"COMPLIANT": "Pass", "NON_COMPLIANT": "Pass"}',
        target=_T,
        keyword="does_not_meet_is_a_fail_suggestion",
        tags=_TAG,
    ),
    Mutation(
        id="M1451-02",
        phase=1451,
        description="a verdict code gave is also shown as a suggestion",
        path=_S,
        anchor='"Query" if finding.get("compliance_status") == "NEEDS_ENGINEER_REVIEW" else ""',
        replacement='"Query"',
        target=_T,
        keyword="verdict_code_gave_a_missing_value",
        tags=_TAG,
    ),
    Mutation(
        id="M1451-03",
        phase=1451,
        description="the suggestion is not marked as a suggestion",
        path=_S,
        anchor='    return f"{word} ({\'; \'.join(bits)}) - {NOTE}" if bits else f"{word} - {NOTE}"',
        replacement="    return f\"{word} ({'; '.join(bits)})\" if bits else word",
        target=_T,
        keyword="held_rule_that_said_does_not_meet",
        tags=_TAG,
    ),
    Mutation(
        id="M1451-04",
        phase=1451,
        description="the contractor's copy carries the suggestion",
        path=_E,
        anchor='    return str(finding.get(key) or "") if copy == COPY_INTERNAL else ""',
        replacement='    return str(finding.get(key) or "")',
        target=_T,
        keyword="contractor_copy_never_carries",
        tags=_TAG,
    ),
    Mutation(
        id="M1451-05",
        phase=1451,
        description="the row carries no suggestion",
        path=_M,
        anchor='"ai_suggests": _suggestions(group, _standard_reference),',
        replacement='"ai_suggests": "",',
        target=_T,
        keyword="row_carries_the_suggestion",
        tags=_TAG,
    ),
    Mutation(
        id="M1451-06",
        phase=1451,
        description="the same suggestion is printed once per finding",
        path=_S,
        anchor='    return "\\n".join(dict.fromkeys(line for line in lines if line))',
        replacement='    return "\\n".join(line for line in lines if line)',
        target=_T,
        keyword="each_distinct_suggestion_once",
        tags=_TAG,
    ),
)
