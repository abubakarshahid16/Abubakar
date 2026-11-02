"""#1638 / PR #1641: a checklist `required` row only asks that a field is stated, so it is no
Pass toward an approval and no decided rule (switch `presence_not_pass_enabled`).
Ids M1641-01.. (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_C = APP / "comparison.py"
_K = APP / "clause_coverage.py"
_P = APP / "coverage_pair.py"
_S = APP / "presence_check.py"
_T = "tests/test_1638_presence_not_pass.py"
_TAG = ("presence", "honesty", "approval")


def _m(
    n: int, description: str, path, anchor: str, replacement: str, keyword: str
) -> Mutation:
    return Mutation(
        id=f"M1641-{n:02d}",
        phase=1641,
        description=description,
        path=path,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=_TAG,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        1,
        "the code rule counts a stated row as a Pass, so it can reach Approved",
        _C,
        "@presence_check.not_a_pass  # #1638\n",
        "",
        "only_presence_rows",
    ),
    _m(
        2,
        "the switch is ignored: a presence row stops counting with it off",
        _S,
        "    if not settings.presence_not_pass_enabled:\n        return False\n",
        "",
        "switch_defaults_off",
    ),
    _m(
        3,
        "every checklist item is taken for a presence check, so a compared Pass stops counting",
        _S,
        '            if item["rule"]["kind"] == REQUIRED:\n',
        "            if True:\n",
        "compared_row_still_counts",
    ),
    _m(
        4,
        "a stated row that is not a Pass, or not from a checklist, is taken as stated",
        _S,
        '    if finding.get("origin") != ORIGIN or finding.get("compliance_status") != PASS:\n'
        "        return False\n",
        "",
        "not_every_row_of_the_item",
    ),
    _m(
        5,
        "the recommendation's reason no longer says what was only stated",
        _S,
        '        return {**result, "reason": result["reason"] + words}\n',
        "        return result\n",
        "only_presence_rows",
    ),
    _m(
        6,
        "the one definition counts a stated row as a decided checklist item",
        _P,
        "            if presence_check.is_stated_only(f):  # #1638: never decided\n",
        "            if False:\n",
        "presence_row_is_not_decided",
    ),
    _m(
        7,
        "a truth hit on a stated row is not stated beside the risk",
        _P,
        "        or presence_check.is_stated_only(f)\n",
        "",
        "truth_hit_on_a_stated_row",
    ),
    _m(
        8,
        "the CRS review notes do not name the rows only stated",
        _K,
        "    notes.extend(stated_notes(findings))  # #1638\n",
        "",
        "review_note_names_the_fields",
    ),
)
