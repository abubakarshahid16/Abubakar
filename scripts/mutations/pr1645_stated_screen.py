"""#1638 / PR #1645: a stated row is never read as checked, on the screen's data and the CRS
cell (switch `presence_not_pass_enabled`). Ids M1645-01.. (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_M = APP / "crs_mapping.py"
_K = APP / "crs_checklist.py"
_R = APP / "review_tiers.py"
_T = "tests/test_1638_stated_screen.py"
_TAG = ("presence", "honesty", "crs")


def _m(
    n: int, description: str, path, anchor: str, replacement: str, keyword: str
) -> Mutation:
    return Mutation(
        id=f"M1645-{n:02d}",
        phase=1645,
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
        'a stated row\'s reasoning on the CRS reads "Result: meets"',
        _M,
        "        status = crs_checklist.result_status(f)\n",
        '        status = f.get("compliance_status")\n',
        "reasoning_of_any_group",
    ),
    _m(
        2,
        "a stated safety-tick row's comment says it meets the standard",
        _M,
        "{crs_checklist.tick_words(f, trust_words(f) or 'automatic rule')}",
        "meets the standard ({trust_words(f) or 'automatic rule'})",
        "tick_comment_and_its_reasoning",
    ),
    _m(
        3,
        "the words for a stated row are used on a compared row too",
        _K,
        '    return f"meets the standard ({trust})"\n',
        '    return f"stated, not checked ({trust})"\n',
        "compared_tick_still_says_meets",
    ),
    _m(
        4,
        'the screen\'s tiers call a stated row "Met"',
        _R,
        '    if finding.get("stated_only") or presence_check.is_stated_only(finding):\n',
        "    if False:\n",
        "stated_row_is_not_met",
    ),
)
