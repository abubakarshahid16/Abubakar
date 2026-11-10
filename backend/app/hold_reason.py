"""WHY A DATASHEET CHECK IS HELD FOR THE ENGINEER, as a CODE from a closed set
(Part of #805, Cycle 2; owner order 10 Nov, step 4).

The reason has always been written as prose ("Could not be checked: ...").
Each code below is written AT THE PLACE that prose is written, never parsed
back from it, so a reworded sentence cannot move a finding:

- `APPLICABILITY_NOT_STATED`: whether the item applies depends on a condition
  the sheet does not state (`datasheet_checks.evaluate_item`).
- `APPLICABILITY_SEVERAL_VALUES`: that condition has two different values on
  the sheet (`datasheet_checks.evaluate_item`), also when the item is evaluated
  anyway and its field is absent (`unknown_condition`).
- `APPLICABILITY_NOT_STATED_ABSENT`: the field is not given and whether it is
  needed depends on a condition the sheet does not state
  (`datasheet_checks.evaluate_item`).
- `FIELD_SEVERAL_VALUES`: the checked field, or the field it is checked
  against (`checked_against`), has two different values on the sheet
  (`datasheet_checks.evaluate_item`).
- `DEFERRED_MARKER`: a decided result about a value the sheet marks as
  deferred ("TBA") turned into a query (`deferred_value.hold_results`).
- `OTHER`: any other held result. The named fallback, chosen in ONE place
  (`stored`), never a guess from the words.

`datasheet_checks.store` stores the code in `review_findings.hold_reason_code`
for a finding stored as NEEDS_ENGINEER_REVIEW, and NULL for any other status.
No verdict or count reads it. Only `crs_routing` reads it, behind its own switch (off),
to choose which sheet shows a held row (CRS or the internal list); the switch off, no CRS row changes.
"""

from __future__ import annotations

APPLICABILITY_NOT_STATED = "applicability_not_stated"
APPLICABILITY_SEVERAL_VALUES = "applicability_several_values"
APPLICABILITY_NOT_STATED_ABSENT = "applicability_not_stated_absent"
FIELD_SEVERAL_VALUES = "field_several_values"
DEFERRED_MARKER = "deferred_marker"
OTHER = "other"

#: The closed set. A code outside it is never stored or returned.
CODES = frozenset(
    {
        APPLICABILITY_NOT_STATED,
        APPLICABILITY_SEVERAL_VALUES,
        APPLICABILITY_NOT_STATED_ABSENT,
        FIELD_SEVERAL_VALUES,
        DEFERRED_MARKER,
        OTHER,
    }
)

#: The key a check RESULT carries the code under (in memory, before storing).
KEY = "hold_reason"
#: The `review_findings` column it is stored in.
COLUMN = "hold_reason_code"

_HELD = "NEEDS_ENGINEER_REVIEW"


def stored(result: dict, status: str) -> str | None:
    """The code `datasheet_checks.store` writes for `result` stored with `status`:
    None unless held; the result's own code; else `OTHER`."""
    if status != _HELD:
        return None
    code = result.get(KEY)
    return code if code in CODES else OTHER


def applicability(why: str | None) -> str:
    """The code for "whether it applies depends on a condition": `why` is the
    reason `datasheet_checks._one` gave for the condition (the same test that
    picks the words "does not state it" / "has two different values")."""
    return APPLICABILITY_NOT_STATED if why == "absent" else APPLICABILITY_SEVERAL_VALUES


def unknown_condition(why: str | None) -> str:
    """The code for "the field is not given, and whether it is needed depends on a
    condition" (`when_unknown: "evaluate"`): `why` is the reason `datasheet_checks._one`
    gave for that condition. Two values on the sheet is the several-values case,
    although the words say "which the sheet does not state" for both."""
    return (
        APPLICABILITY_NOT_STATED_ABSENT
        if why == "absent"
        else APPLICABILITY_SEVERAL_VALUES
    )


def checked_against(other: dict | None, why: str | None) -> str:
    """The code for "the field it is checked against is not given / is stated twice":
    the same test that picks those words (`other` and `why` from `_one`)."""
    return OTHER if (other is not None or why == "absent") else FIELD_SEVERAL_VALUES


def of(finding: dict) -> str | None:
    """The stored hold reason code of a finding, or None (not held, written
    before the column existed, or not a code of the closed set)."""
    code = finding.get(COLUMN)
    return code if code in CODES else None
