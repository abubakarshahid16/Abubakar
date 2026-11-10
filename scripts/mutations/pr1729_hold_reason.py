"""Mutations of the hold reason code a held datasheet check stores (Part of #805
Cycle 2; PR 1729). `datasheet_checks.py` is in the danger zone (CLAUDE.md
rule 6); `hold_reason.py` and `deferred_value.py` are not, so they have
ordinary tests only."""

from __future__ import annotations

from ._base import APP, Mutation

_M = APP / "datasheet_checks.py"
_T = "tests/test_hold_reason_code.py"


def _m(
    n: int, description: str, anchor: str, replacement: str, keyword: str
) -> Mutation:
    return Mutation(
        id=f"M1729-{n:02d}",
        phase=1729,
        description=description,
        path=_M,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=("honesty", "hold_reason"),
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        1,
        "a held checklist result no longer carries its code (every hold is stored as 'other')",
        "        return {**res(NEEDS_ENGINEER_REVIEW, detail, fact, role), why_held.KEY: code}\n",
        "        return res(NEEDS_ENGINEER_REVIEW, detail, fact, role)\n",
        "each_hold_path or store_writes_each_code",
    ),
    _m(
        2,
        "a condition with two values on the sheet is coded as 'not stated'",
        "                return held(why_held.applicability(why), _sentence(\n",
        "                return held(why_held.APPLICABILITY_NOT_STATED, _sentence(\n",
        "each_hold_path or store_writes_each_code",
    ),
    _m(
        3,
        "an absent field under an unknown condition is coded as the condition alone",
        "        return held(why_held.APPLICABILITY_NOT_STATED_ABSENT, _sentence(\n",
        "        return held(why_held.APPLICABILITY_NOT_STATED, _sentence(\n",
        "each_hold_path or store_writes_each_code",
    ),
    _m(
        4,
        "a field with two values on the sheet is coded 'other'",
        "        return held(why_held.FIELD_SEVERAL_VALUES,\n",
        "        return held(why_held.OTHER,\n",
        "each_hold_path or store_writes_each_code",
    ),
    _m(
        5,
        "the store writes no hold reason code",
        '"hold_reason_code": why_held.stored(r, status),',
        '"hold_reason_code": None,',
        "store_writes_each_code or every_stored_code or crs_is_the_same",
    ),
    _m(
        6,
        "the store codes a finding whatever status it is stored with "
        "(a decided pass gets a code)",
        '"hold_reason_code": why_held.stored(r, status),',
        '"hold_reason_code": why_held.stored(r, NEEDS_ENGINEER_REVIEW),',
        "store_writes_each_code",
    ),
)
