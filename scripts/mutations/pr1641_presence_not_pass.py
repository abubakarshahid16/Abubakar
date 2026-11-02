"""#1638 / PR #1641: a checklist `required` row only asks that a field is stated, so it is no
Pass toward an approval and no decided rule (switch `presence_not_pass_enabled`).
Ids M1641-01.. (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_C = APP / "comparison.py"
_G = APP / "checklist_scope.py"
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
        "every checklist item is taken as compared, so no presence row is told",
        _S,
        '            if item["rule"]["kind"] != REQUIRED:\n',
        "            if True:\n",
        "only_presence_rows",
    ),
    _m(
        4,
        "a row that is not a Pass, or not from a checklist, is taken as stated",
        _S,
        '    if finding.get("origin") != ORIGIN or finding.get("compliance_status") != PASS:\n'
        "        return False\n",
        "",
        "not_every_row_of_the_item",
    ),
    _m(
        5,
        "a stated row beside a real Pass no longer stops the approval",
        _S,
        '        if result["code"] == approved:\n',
        "        if False:\n",
        "caps_the_recommendation",
    ),
    _m(
        6,
        "the one definition counts a stated row as a decided checklist item",
        _P,
        "            if stated:  # never decided\n",
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
    _m(
        9,
        "a row whose item cannot be told counts as a Pass: fails open",
        _S,
        "    return check not in compared_ids()\n",
        "    return bool(check) and check not in compared_ids()\n",
        "no_item_id_fails_closed",
    ),
    _m(
        10,
        "the cache is stamped by the overlay folder, so an edit in place is missed",
        _S,
        "    return tuple((str(f), f.stat().st_mtime_ns, f.stat().st_size) for f in files)\n",
        "    return (str(overlay), overlay.stat().st_mtime_ns if overlay.is_dir() else 0)\n",
        "edited_in_place",
    ),
    _m(
        11,
        "an approval with comments is left standing beside a stated row",
        _S,
        '        if result["code"] == with_comments:\n',
        "        if False:\n",
        "no_approval_with_comments",
    ),
    _m(
        12,
        "the plain reason loses the count",
        _C,
        "@presence_check.says_how_many  # #1638\n",
        "",
        "gated_run_says_it_too",
    ),
    _m(
        13,
        "a standard only stated items cite is still set aside, out of the unchecked-share gate",
        _G,
        "    covered_ids = set(covered_ids) - back\n",
        "    covered_ids = set(covered_ids)\n",
        "does_not_govern or gives_back_only",
    ),
    _m(
        14,
        "a standard with compared items is given back too",
        _G,
        "    return sorted(set(standards(checklist)) - asks_more)\n",
        "    return sorted(set(standards(checklist)))\n",
        "compared_items_still_governs",
    ),
)
