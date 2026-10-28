"""Order 283.3 (PR 1419): a CRS row whose standard the datasheet does not cite says so.
`crs_mapping.py` and `crs_cited.py` are in the danger zone (rule 6). Ids M1419-01 onwards, phase 1419."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_283_standard_cited_label.py"
_CITED = APP / "crs_cited.py"
_TAGS = ("honesty", "o283")


def _m(n, description, anchor, replacement, keyword=None, path=_CITED):
    return Mutation(
        id=f"M1419-{n:02d}",
        phase=1419,
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
        1,
        "a standard whose name is not a known family is called not cited",
        " or standard_ids.parse(name) is None",
        "",
        "never_called_not_cited",
    ),
    _m(
        2,
        "no cited list is read as an empty list, so every row is labelled",
        '(standards_check or {}).get("cited")\n    if cited is None:',
        '(standards_check or {}).get("cited") or []\n    if cited is None:',
        "without_a_cited_list",
    ),
    _m(
        3,
        "a kind B datasheet check is labelled as not cited",
        'finding.get("origin") == _CHECK_ORIGIN or ',
        "",
        "names_its_own_source",
    ),
    _m(
        4,
        "a row is labelled when ANY of its standards is uncited",
        "not all(_not_cited(f, cited) for f in group)",
        "not any(_not_cited(f, cited) for f in group)",
        "among_others",
    ),
    _m(
        5,
        "the match is inverted: a cited standard is called not cited",
        "return not any(standard_ids.same_standard(c, name) for c in cited)",
        "return any(standard_ids.same_standard(c, name) for c in cited)",
        "cited_standard_is_unchanged",
    ),
    _m(
        6,
        "a person's own wording is overwritten by the label",
        '        if not row.get("edited"):\n',
        "        if True:\n",
        "engineers_own_wording",
    ),
    _m(
        7,
        "the row is not flagged standard_cited false",
        '        row["standard_cited"] = False\n',
        "        pass\n",
        "says_so_and_stays_a_row",
    ),
    _m(
        8,
        "the review no longer calls the label at all",
        "    crs_cited.mark(rows, findings, standards_check)\n",
        "    pass\n",
        "says_so_and_stays_a_row",
        path=APP / "crs_mapping.py",
    ),
    _m(
        9,
        "a row already marked is marked again (the label doubles)",
        '        if not group or row.get("standard_cited") is False:\n',
        "        if not group:\n",
        "marks_once",
    ),
)
