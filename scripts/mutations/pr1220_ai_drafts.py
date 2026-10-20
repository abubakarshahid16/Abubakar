"""Order 161 D, second part: one CRS row per field for AI / web drafts, and no
placeholder row. `crs_mapping.py` is in the danger zone (rule 6). PR #1220: ids
M1220-01 onwards, phase 1220."""

from __future__ import annotations

from ._base import APP, Mutation

_S = APP / "crs_ai_drafts.py"
_M = APP / "crs_mapping.py"
_T = "tests/test_161d_ai_drafts.py"
_TAGS = ("honesty", "critical", "161d")


def _m(n, description, path, anchor, replacement, keyword) -> Mutation:
    return Mutation(
        id=f"M1220-{n}",
        phase=1220,
        description=description,
        path=path,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=_TAGS,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "same-field drafts are never merged: the field is two rows again",
        _S,
        "        if len(group) < 2:\n",
        "        if True:\n",
        "one_row_that_keeps_both",
    ),
    _m(
        "02",
        "a difference between the drafts is not said: one reads as the only one",
        _S,
        "    if len(distinct) == 1:\n",
        "    if True:\n",
        "one_row_that_keeps_both",
    ),
    _m(
        "03",
        "a confirmed draft is merged with an unconfirmed one",
        _S,
        "            confirmed,\n",
        "            False,\n",
        "never_merged_with_an_unconfirmed or never_joins_an_unconfirmed",
    ),
    _m(
        "04",
        "AI and web drafts merge into one row",
        _S,
        '                f["origin"],\n',
        '                "x",\n',
        "never_merged_with_each_other",
    ),
    _m(
        "05",
        "a placeholder draft takes a CRS row",
        _S,
        '            f["crs_skip"] = True\n            continue\n',
        "            continue\n",
        "says_nothing_is_no_row",
    ),
    _m(
        "06",
        "an engineer's own words on an empty draft are dropped as a placeholder",
        _S,
        '        if not (confirmed or f.get("engineer_comment")) and is_placeholder(\n',
        "        if is_placeholder(\n",
        "own_words",
    ),
    _m(
        "07",
        "the merged row's number key changes with its drafts",
        _S,
        '        lead["crs_key"] = cm.comment_key("ai drafts of one field", *key[:3], key[4])\n',
        '        lead["crs_key"] = cm.comment_key("ai drafts of one field", *[f["id"] for f in group])\n',
        "key_of_a_merged_row",
    ),
    _m(
        "08",
        "the merged row forgets the keys its drafts were numbered under",
        _S,
        '        lead["crs_member_keys"] = sorted(cm.finding_comment_key(f) for f in group)\n',
        '        lead["crs_member_keys"] = []\n',
        "numbered_under",
    ),
    _m(
        "09",
        "a merged-away draft still takes its own row",
        _M,
        '    if f.get("crs_skip"):\n        return None\n',
        "",
        "one_row_that_keeps_both",
    ),
    _m(
        "10",
        "the screen's grouping never merges the drafts, so the screen and the file disagree",
        _M,
        "    crs_ai_drafts.merge(findings)\n    findings = [f for f in findings if not _rejected(f)]\n",
        "    findings = [f for f in findings if not _rejected(f)]\n",
        "screen_groups",
    ),
    _m(
        "11",
        "two different confirmed drafts merge, and the note for the engineer reaches the contractor's copy",
        _S,
        '                or (_fold(cm._finding_text(f)) if confirmed else ""),\n',
        '                or "",\n',
        "different_confirmed_drafts",
    ),
    _m(
        "12",
        "two groups of one field share a number key",
        _S,
        "*key[:3], key[4])\n",
        "*key[:3])\n",
        "never_share_a_number_key",
    ),
    _m(
        "13",
        "a placeholder draft is on the screen as an open row the file does not have",
        APP / "api" / "run_summary.py",
        '                or f.get("crs_skip")\n',
        "",
        "review_note_on_the_screen",
    ),
    _m(
        "14",
        "the screen is not told that the merged drafts differ",
        _S,
        '        "crs_action": finding.get("crs_differ") or None,\n',
        '        "crs_action": None,\n',
        "screen_is_told",
    ),
)
