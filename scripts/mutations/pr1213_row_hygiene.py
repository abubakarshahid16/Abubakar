"""Order 161 D: a series of items (N1 to N8) is one CRS row listing the items.
`crs_mapping.py` is in the danger zone (rule 6). PR #1213: ids M1213-01 onwards,
phase 1213."""

from __future__ import annotations

from ._base import APP, Mutation

_M = APP / "crs_mapping.py"
_S = APP / "crs_item_series.py"
_T = "tests/test_161d_row_hygiene.py"
_TAGS = ("honesty", "critical", "161d")
_SERIES_GATE = (
    "        if len(variants) < 2 or len(letters) != 1 or len(clause_sets) != 1:\n"
)


def _m(
    n: str,
    description: str,
    anchor: str,
    replacement: str,
    keyword: str,
    path=None,
) -> Mutation:
    return Mutation(
        id=f"M1213-{n}",
        phase=1213,
        description=description,
        path=path or _M,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=_TAGS,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "a series of items is never merged: eight nozzles are eight rows again",
        _SERIES_GATE,
        "        if True:\n",
        "one_row",
        _S,
    ),
    _m(
        "02",
        "labels with different letters merge (H2 content and O2 content become one row)",
        _SERIES_GATE,
        "        if len(variants) < 2 or len(clause_sets) != 1:\n",
        "not_one_series",
        _S,
    ),
    _m(
        "03",
        "items behind different clauses merge, hiding a clause one of them is held to",
        _SERIES_GATE,
        "        if len(variants) < 2 or len(letters) != 1:\n",
        "different_clauses",
        _S,
    ),
    _m(
        "04",
        "items on different datasheet pages merge",
        '            key = (bucket, f.get("contractor_page"), i, masked)\n',
        "            key = (bucket, None, i, masked)\n",
        "different_pages",
        _S,
    ),
    _m(
        "05",
        "a rejected comment makes or extends a series",
        '        if cm._rejected(f) or f.get("crs_item_mark"):\n',
        '        if f.get("crs_item_mark"):\n',
        "rejected_item",
        _S,
    ),
    _m(
        "06",
        "the series row prints the equipment tag in place of each item's mark",
        "            f\"{g.get('crs_item_mark') or g.get('equipment_tag') or 'untagged'} {_provided(g)}\"\n",
        "            f\"{g.get('equipment_tag') or 'untagged'} {_provided(g)}\"\n",
        "repeated_items",
    ),
    _m(
        "07",
        "the screen's grouping never merges the series, so the screen and the file disagree",
        "    crs_item_series.merge(findings)\n    findings = [f for f in findings if not _rejected(f)]\n",
        "    findings = [f for f in findings if not _rejected(f)]\n",
        "screen_groups",
    ),
    _m(
        "08",
        "the items are listed in the order of their values, not their numbers",
        "            for g in sorted(group, key=crs_item_series.in_series_order)))\n",
        "            for g in group))\n",
        "repeated_items",
    ),
)
