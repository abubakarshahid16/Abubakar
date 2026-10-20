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
        '        if cm._rejected(f) or cm._confirmed(f) or f.get("crs_item_mark"):\n',
        '        if cm._confirmed(f) or f.get("crs_item_mark"):\n',
        "rejected_item",
        _S,
    ),
    _m(
        "06",
        "the series row prints the item's mark in place of the equipment tag",
        '            f"{crs_item_series.item_name(g)} {_provided(g)}"\n',
        "            f\"{g.get('crs_item_mark') or g.get('equipment_tag') or 'untagged'} {_provided(g)}\"\n",
        "which_tag_has_which_value",
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
    _m(
        "09",
        "an engineer-confirmed comment is merged into a series and re-labelled",
        '        if cm._rejected(f) or cm._confirmed(f) or f.get("crs_item_mark"):\n',
        '        if cm._rejected(f) or f.get("crs_item_mark"):\n',
        "confirmed_comment",
        _S,
    ),
    _m(
        "10",
        "a bare number counts as an item index (two ratings become 'items')",
        'INDEX_TOKEN = re.compile(r"^([A-Za-z]{1,3})(\\d{1,3})$")\n',
        'INDEX_TOKEN = re.compile(r"^([A-Za-z]{0,3})(\\d{1,3})$")\n',
        "ratings_and_sizes",
        _S,
    ),
    _m(
        "11",
        "the merged row loses the per-item number keys earlier runs stored",
        '        crs_item_series.own_label(f) or f.get("matched_phrase") or f.get("contractor_section"),\n',
        '        f.get("crs_field_label") or f.get("matched_phrase") or f.get("contractor_section"),\n',
        "number_keys",
    ),
    _m(
        "12",
        "the series row forgets the keys its items' own rows were numbered under",
        '        cm.field_comment_key(cm._bucket_of(g), cm._fold(g["crs_item_label"]))\n',
        '        ""\n',
        "issued_on_an_items_own_row",
        _S,
    ),
)
