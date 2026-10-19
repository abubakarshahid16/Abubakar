"""Order 139 part 2, item 5 (#779): every CRS line has plain COMPANY Comments
text or is not issued, and the sheet is ranked - out of limit, missing value,
engineer to check - on every row kind. `crs_mapping.py` and `crs_export.py`
are in the danger zone (rule 6). Ids M1178-01..16 (rule 12)."""

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
        id=f"M1178-{n}",
        phase=1178,
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
        "01",
        "the rank is left out of the sort key (rows go by page again)",
        _M,
        '    return (priority, *_row_order(group), str(key or ""))\n',
        '    return (*_row_order(group), str(key or ""))\n',
        _TM,
        "rows_rank_out_of_limit_then_missing_then_engineer_to_check",
    ),
    _m(
        "02",
        "the datasheet page is left out of the sort key inside a rank",
        _M,
        '    return (priority, *_row_order(group), str(key or ""))\n',
        '    return (priority, *_row_order(group)[1:], str(key or ""))\n',
        _TM,
        "within_a_rank_rows_go_by_page_then_clause",
    ),
    _m(
        "03",
        "an unconfirmed AI/web item's COMPANY Comments is empty again",
        _M,
        '            "comment": text if confirmed else unconfirmed_comment,\n',
        '            "comment": text if confirmed else "",\n',
        _TM,
        "every_internal_row_has_company_comment_text",
    ),
    _m(
        "04",
        "a value not found is ranked 'Missing value' (asks the contractor)",
        _M,
        "    BUCKET_NOT_FOUND: PRIORITY_ENGINEER_TO_CHECK,\n",
        "    BUCKET_NOT_FOUND: PRIORITY_MISSING_VALUE,\n",
        _TM,
        "not_found_ranks_with_engineer_to_check",
    ),
    _m(
        "05",
        "the sheet's ranking treats a value not found as a blank",
        _M,
        '        item["priority"] = row_priority(item["bucket"], group[0].get("compliance_status"))\n',
        '        item["priority"] = row_priority(\n'
        '            BUCKET_BLANK if item["bucket"] == BUCKET_NOT_FOUND else item["bucket"],\n'
        '            group[0].get("compliance_status"),\n'
        "        )\n",
        _TM,
        "not_found_ranks_with_engineer_to_check",
    ),
    _m(
        "06",
        "the required-vs-cited rows sort without their rank (last again)",
        _M,
        '    return (priority, 10**9, (10**6,), _fold(identifier), str(key or ""))\n',
        '    return (10**6, 10**9, (10**6,), _fold(identifier), str(key or ""))\n',
        _TM,
        "rank_holds_across_every_row_kind",
    ),
    _m(
        "07",
        "a datasheet check out of limit is not ranked first",
        _M,
        '    if kind == BUCKET_CHECK:\n        if compliance_status == "NON_COMPLIANT":\n',
        "    if kind == BUCKET_CHECK:\n        if False:\n",
        _TM,
        "datasheet_check_ranks_by_its_own_status",
    ),
    # ------------------------------------------- crs_export: the Priority column
    _m(
        "08",
        "the Priority column prints the severity ('minor') again",
        _E,
        '                  entry["standard_reference"], entry.get("priority_label", "")]',
        '                  entry["standard_reference"], entry.get("severity", "")]',
        _TE,
        "priority_column_prints_the_rank_word",
    ),
    _m(
        "09",
        "the issue copy prints the internal word for rank 3",
        _E,
        '    return {"priority": priority, "priority_label": priority_word(priority, copy)}\n',
        '    return {"priority": priority, "priority_label": priority_word(priority)}\n',
        _TE,
        "issue_copy_says_clarification_for_rank_three",
    ),
    _m(
        "10",
        "a row with no rank prints a guessed word",
        _E,
        "        return PRIORITY_CARRIED_FORWARD\n    return None\n",
        "        return PRIORITY_CARRIED_FORWARD\n    return 3\n",
        _TE,
        "row_without_priority_prints_nothing",
    ),
    _m(
        "11",
        "a carried-forward row prints no rank",
        _E,
        '    if finding.get("row_kind") == ROW_KIND_CARRIED_FORWARD:\n        return PRIORITY_CARRIED_FORWARD\n',
        "    if False:\n        return PRIORITY_CARRIED_FORWARD\n",
        _TE,
        "row_without_priority_prints_nothing",
    ),
    _m(
        "12",
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
        "13",
        "the issue copy carries a row with no comment text",
        _E,
        "        findings = [f for f in findings if not _no_text(f)]\n",
        "",
        _TE,
        "issue_copy_never_carries_a_row_with_no_text",
    ),
    _m(
        "14",
        "the issue copy leaves rows out without counting them",
        _E,
        "        withheld_no_text = sum(1 for f in findings if _no_text(f))\n",
        "        withheld_no_text = 0\n",
        _TE,
        "issue_copy_never_carries_a_row_with_no_text",
    ),
    _m(
        "15",
        "the internal copy prints an empty COMPANY Comments cell",
        _E,
        "        if comment_missing:\n            comment = EMPTY_COMMENT_TEXT\n",
        "",
        _TE,
        "internal_copy_names_a_row_with_no_text",
    ),
    # ------------- #1178 review: a waiting sentence alone is no text
    _m(
        "16",
        "a waiting sentence with no draft beside it counts as comment text",
        _M,
        "    return text in WAITING_COMMENTS and not draft\n",
        "    return False\n",
        _TE,
        "carried_forward_waiting_sentence_is_never_issued",
    ),
)
