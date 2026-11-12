"""#1503 / PR 1509 CRS export quality: each entry breaks one rule of the export;
backend/tests/test_1503_crs_export_quality.py must notice."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_1503_crs_export_quality.py"
_TAG = ("c1_1509", "crs", "export_quality")
_Q = APP / "crs_export_quality.py"
_E = APP / "crs_export.py"


def _m(n, desc, path, anchor, repl, kw):
    return Mutation(
        id=f"M1509-{n:02d}",
        phase=1509,
        description=desc,
        path=path,
        anchor=anchor,
        replacement=repl,
        target=_T,
        keyword=kw,
        tags=_TAG,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        1,
        "a later draft on the same section and clause is a new row again",
        _Q,
        "        if key is None or key not in first_of:\n",
        "        if True:\n",
        "joins_the_first_row",
    ),
    _m(
        2,
        "a safety tick and a carried-forward comment are merged like any draft",
        _Q,
        '_NEVER_MERGED = ("safety_tick", "carried_forward")\n',
        "_NEVER_MERGED = ()\n",
        "never_merged",
    ),
    _m(
        3,
        "a draft and a confirmed row on one key are merged into one comment",
        _Q,
        '        row.get("engineer_confirmed") is True,\n    )\n',
        "        False,\n    )\n",
        "not_merged_into_one",
    ),
    _m(
        4,
        "a row with no comment is exported again",
        _Q,
        '        r for r in rows if r.get("engineer_confirmed") is True or not has_no_text(r)\n',
        "        r for r in rows\n",
        "dropped_and_counted",
    ),
    _m(
        5,
        "a row with no page says nothing about the page again",
        _Q,
        '    return f"{head} - {text}" if text else head\n',
        "    return text\n",
        "page_not_found",
    ),
    _m(
        6,
        "a long comment is not cut and the overflow stays in the comment",
        _Q,
        "        if rest:\n",
        "        if False:\n",
        "cut_at_350 or ai_column_only",
    ),
    _m(
        7,
        "the contractor copy carries the Internal sheet",
        _E,
        '    if internal and view.get("export_quality"):  # #1503: Reasoning, Rule trust\n',
        '    if view.get("export_quality"):  # #1503: Reasoning, Rule trust\n',
        "no_internal_sheet",
    ),
    _m(
        8,
        "the not-yet-proven sentence stays in the comment",
        _Q,
        "    if flag not in text:\n        return text, False\n",
        "    if True:\n        return text, False\n",
        "no_internal_words or no_internal_sheet",
    ),
    _m(
        9,
        "the standards sheet lists the considered-not-applied standards again",
        _Q,
        '    shown = [s for s in standards if s.get("status") != considered_status]\n',
        "    shown = standards\n",
        "applied_and_not_in_library",
    ),
    _m(
        10,
        "a purchasing spec is a design standard (upload required) again",
        _Q,
        "    if _PURCHASING.search(text):\n        return KIND_PURCHASING\n",
        "    if False:\n        return KIND_PURCHASING\n",
        "prefix_table",
    ),
    _m(
        11,
        "a row with no usable rank prints a blank Priority again",
        _Q,
        "    return _BY_RANK.get(rank, PRIORITY_ENGINEER_TO_CHECK)\n",
        '    return _BY_RANK.get(rank, "")\n',
        "fixed_words",
    ),
    _m(
        13,
        "an equipment tag such as P101 counts as a page again",
        _Q,
        '_HAS_PAGE = re.compile(r"(?<![A-Za-z0-9])(?:pp?\\.\\s*|pages?\\s+)\\d", re.I)\n',
        '_HAS_PAGE = re.compile(r"(?<![A-Za-z])(?:pp?|pages?)\\.?\\s*\\d", re.I)\n',
        "equipment_tag",
    ),
    _m(
        14,
        "the requested action is cut from a long comment again",
        _Q,
        "    if not action or len(parts[action[-1]]) >= limit:\n",
        "    if True:\n",
        "requested_action",
    ),
    _m(
        15,
        "a cut falls between a number and its unit again",
        _Q,
        '        while at > 0 and marker == " " and _bad_space(text, at):\n',
        "        while False:\n",
        "number_from_its_unit",
    ),
)
