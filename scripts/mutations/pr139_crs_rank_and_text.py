"""Order 139 part 2, item 5 (#779): every CRS line has plain COMPANY Comments
text or is not issued, and the sheet is ranked - out of limit, missing value,
engineer to check - on every row kind. `crs_mapping.py` and `crs_export.py`
are in the danger zone (rule 6). Placeholder ids M139-4x/5x until the PR
exists (rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_M = APP / "crs_mapping.py"
_E = APP / "crs_export.py"
_TM = "tests/test_139_crs_priority_and_text.py"
_TE = "tests/test_139_crs_file_empty_guard.py"
_TAGS = ("honesty", "critical")


def _m(
    n: str, desc: str, path, anchor: str, repl: str, target: str, kw: str
) -> Mutation:
    return Mutation(
        id=f"M139-{n}",
        phase=139,
        description=desc,
        path=path,
        anchor=anchor,
        replacement=repl,
        target=target,
        keyword=kw,
        tags=_TAGS,
    )


MUTATIONS: tuple[Mutation, ...] = (
    # ------------------------------------------------ crs_mapping: the rank
    _m(
        "41",
        "the rank is left out of the sort key (rows go by page again)",
        _M,
        '    return (priority, *_row_order(group), str(key or ""))\n',
        '    return (*_row_order(group), str(key or ""))\n',
        _TM,
        "rows_rank_out_of_limit_then_missing_then_engineer_to_check",
    ),
    _m(
        "42",
        "the datasheet page is left out of the sort key inside a rank",
        _M,
        '    return (priority, *_row_order(group), str(key or ""))\n',
        '    return (priority, *_row_order(group)[1:], str(key or ""))\n',
        _TM,
        "within_a_rank_rows_go_by_page_then_clause",
    ),
    _m(
        "43",
        "an unconfirmed AI/web item's COMPANY Comments is empty again",
        _M,
        '            "comment": text if confirmed else unconfirmed_comment,\n',
        '            "comment": text if confirmed else "",\n',
        _TM,
        "every_internal_row_has_company_comment_text",
    ),
    _m(
        "44",
        "a value not found is ranked 'Missing value' (asks the contractor)",
        _M,
        "    BUCKET_NOT_FOUND: PRIORITY_ENGINEER_TO_CHECK,\n",
        "    BUCKET_NOT_FOUND: PRIORITY_MISSING_VALUE,\n",
        _TM,
        "not_found_ranks_with_engineer_to_check",
    ),
    _m(
        "45",
        "the finding loop ranks every missing-information row as a blank",
        _M,
        "                BUCKET_BLANK if paired(f) else BUCKET_NOT_FOUND\n",
        "                BUCKET_BLANK\n",
        _TM,
        "not_found_ranks_with_engineer_to_check",
    ),
    _m(
        "46",
        "the required-vs-cited rows sort without their rank (last again)",
        _M,
        '    return (priority, 10 ** 9, (10 ** 6,), _fold(identifier), str(key or ""))\n',
        '    return (10 ** 6, 10 ** 9, (10 ** 6,), _fold(identifier), str(key or ""))\n',
        _TM,
        "rank_holds_across_every_row_kind",
    ),
    _m(
        "47",
        "a datasheet check out of limit is not ranked first",
        _M,
        '    if kind == BUCKET_CHECK:\n        if compliance_status == "NON_COMPLIANT":\n',
        "    if kind == BUCKET_CHECK:\n        if False:\n",
        _TM,
        "datasheet_check_ranks_by_its_own_status",
    ),
    # ------------------------------------------- crs_export: the Priority column
    _m(
        "51",
        "the Priority column prints the severity ('minor') again",
        _E,
        '                  entry["standard_reference"], entry.get("priority_label", "")]',
        '                  entry["standard_reference"], entry.get("severity", "")]',
        _TE,
        "priority_column_prints_the_rank_word",
    ),
    _m(
        "52",
        "the issue copy prints the internal word for rank 3",
        _E,
        '    return {"priority": priority, "priority_label": priority_word(priority, copy)}\n',
        '    return {"priority": priority, "priority_label": priority_word(priority)}\n',
        _TE,
        "issue_copy_says_clarification_for_rank_three",
    ),
    _m(
        "53",
        "a row with no rank prints a guessed word",
        _E,
        "        return PRIORITY_CARRIED_FORWARD\n    return None\n",
        "        return PRIORITY_CARRIED_FORWARD\n    return 3\n",
        _TE,
        "row_without_priority_prints_nothing",
    ),
    _m(
        "54",
        "a carried-forward row prints no rank",
        _E,
        '    if finding.get("row_kind") == ROW_KIND_CARRIED_FORWARD:\n        return PRIORITY_CARRIED_FORWARD\n',
        "    if False:\n        return PRIORITY_CARRIED_FORWARD\n",
        _TE,
        "row_without_priority_prints_nothing",
    ),
    _m(
        "58",
        "the view re-sorts the rows (the order is not the sheet's)",
        _E,
        "    rows = []\n    seen: set[str] = set()\n",
        '    findings = sorted(findings, key=lambda f: str(f.get("comment") or ""))\n'
        "    rows = []\n    seen: set[str] = set()\n",
        _TE,
        "file_keeps_the_sheets_order",
    ),
    # ------------------------------------- crs_export: the empty-comment guard
    _m(
        "55",
        "the issue copy carries a row with no comment text",
        _E,
        "        findings = [f for f in findings if not _no_text(f)]\n",
        "",
        _TE,
        "issue_copy_never_carries_a_row_with_no_text",
    ),
    _m(
        "56",
        "the issue copy leaves rows out without counting them",
        _E,
        "        withheld_no_text = sum(1 for f in findings if _no_text(f))\n",
        "        withheld_no_text = 0\n",
        _TE,
        "issue_copy_never_carries_a_row_with_no_text",
    ),
    _m(
        "57",
        "the internal copy prints an empty COMPANY Comments cell",
        _E,
        "        if comment_missing:\n            comment = EMPTY_COMMENT_TEXT\n",
        "",
        _TE,
        "internal_copy_names_a_row_with_no_text",
    ),
)
