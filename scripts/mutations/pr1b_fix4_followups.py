"""Release 1b follow-ups of the order 139 part 2 work (#1179): rows split by
engineer wording keep distinct, stable permanent-number keys; a leader tie
cannot move a group's key. `crs_mapping.py` is in the danger zone (rule 6).
The integrator renames the ids to the PR number."""

from __future__ import annotations

from ._base import APP, Mutation

_M = APP / "crs_mapping.py"
_T = "tests/test_139_crs_one_per_field.py"
_TAGS = ("honesty", "critical")


def _m(
    n: str, description: str, anchor: str, replacement: str, keyword: str
) -> Mutation:
    return Mutation(
        id=f"M1b2-{n}",
        phase=1002,
        description=description,
        path=_M,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=_TAGS,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "rows split by wording share the field's key again (one number for two rows, "
        "the second '#2' by sheet place)",
        "                if group is anchor\n",
        "                if True\n",
        "rows_split_by_wording_carry_distinct_stable_keys",
    ),
    _m(
        "02",
        "the split row that keeps the field's key is no longer the engineer's row first",
        "                not all(_confirmed(f) for f in g),\n",
        "                False,\n",
        "field_key_stays_with_the_engineers_row",
    ),
    _m(
        "03",
        "the split row that keeps the field's key is no longer the larger one",
        "                -len(g),\n",
        "                0,\n",
        "field_key_stays_with_the_engineers_row",
    ),
    _m(
        "04",
        "every row split off by wording gets the same key (the wording is left out)",
        '                else comment_key("wording split", natural, group_key.rsplit(":e", 1)[-1])\n',
        '                else comment_key("wording split", natural)\n',
        "field_key_stays_with_the_engineers_row",
    ),
    _m(
        "05",
        "a row split off a non-field group is taken for a field row by the number code "
        "(its own key is not among its member keys)",
        '            if _group_key(f)[0] != "field":\n',
        "            if False:\n",
        "not_taken_for_a_field_row",
    ),
    _m(
        "06",
        "a comment's permanent-number key includes its clause, so the finding that "
        "leads a group across standards decides the number",
        '        f.get("contractor_page"),\n'
        '        f.get("origin") == _DATASHEET_ORIGIN,\n'
        "    )\n\n\n"
        '#: The "Review notes"',
        '        f.get("contractor_page"), f.get("standard_clause"),\n'
        '        f.get("origin") == _DATASHEET_ORIGIN,\n'
        "    )\n\n\n"
        '#: The "Review notes"',
        "keeps_its_number_key_whichever_finding_leads",
    ),
)
