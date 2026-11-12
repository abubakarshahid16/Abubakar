"""PR 1767 (order 13, part B): the normal reviewer's CRS in the one layout. `crs_export.py` (danger zone, rule 6) hands the workbook to
`crs_normal` and fixes the header geometry; `crs_normal.py` holds the Status mapping and the two extra sheets. Ids M1767-01..
(named after the PR, rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_N = APP / "crs_normal.py"
_E = APP / "crs_export.py"
_T = "tests/test_crs_one_layout.py"
_TAGS = ("honesty", "critical")


def _m(
    n: str, desc: str, path, anchor: str, repl: str, target: str, kw: str
) -> Mutation:
    return Mutation(
        id=f"M1767-{n}", phase=1767, description=desc, path=path, anchor=anchor, replacement=repl,
        target=target, keyword=kw, tags=_TAGS,
    )  # fmt: skip


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "an unknown kind at rank 1 is a Fail (a Fail no code comparison proved)",
        _N,
        "    if row_kind in CODE_COMPARED_KINDS and priority == PRIORITY_OUT_OF_LIMIT:\n        return STATUS_FAIL\n",
        "    if priority == PRIORITY_OUT_OF_LIMIT:\n        return STATUS_FAIL\n",
        _T,
        "every_row_kind",
    ),
    _m(
        "02",
        "a safety tick is a Query (a code-reached Pass is lost)",
        _N,
        "    if row_kind == ROW_KIND_SAFETY_TICK:\n        return STATUS_PASS\n",
        "    if row_kind == ROW_KIND_SAFETY_TICK:\n        return STATUS_QUERY\n",
        _T,
        "every_row_kind or stated_rule",
    ),
    _m(
        "03",
        "an AI engineering check is shown as a Fail (an AI draft read as proven)",
        _N,
        "    if row_kind in _AI_ROW_KINDS:\n        return STATUS_AI\n",
        "    if row_kind in _AI_ROW_KINDS:\n        return STATUS_FAIL\n",
        _T,
        "every_row_kind or stated_rule",
    ),
    _m(
        "04",
        "the table header moves up one row (the header block no longer fits above it)",
        _E,
        "(len(HEADER_FIELDS) - 1) + 2  # order 13",
        "(len(HEADER_FIELDS) - 1) + 1  # order 13",
        _T,
        "ten_columns",
    ),
    _m(
        "05",
        "the document title is read from the wrong header row",
        _E,
        'HEADER_ROW_OF["document_title"] = 5\n',
        'HEADER_ROW_OF["document_title"] = 6\n',
        "tests/test_crs_export.py",
        "header_block_carries_the_meta",
    ),
    _m(
        "06",
        "the issue copy to the contractor carries the generated-by sentence",
        _N,
        '    if internal:\n        out["sentence"]',
        '    if True:\n        out["sentence"]',
        _T,
        "contractor_facing_copy",
    ),
    _m(
        "07",
        "the contractor-facing copy is coloured by Status (a colour says which comments were drafts)",
        APP / "crs_ai_workbook.py",
        '        view["plain"] = True\n',
        '        view["plain"] = False\n',
        "tests/test_agent_review_crs.py",
        "names_an_internal_judgement",
    ),
    _m(
        "08",
        "the Priority cell is left empty on every row",
        _N,
        'row["priority_label"] = words.priority(status, {}, words.ORDER_AI_NOT_MET)',
        'row["priority_label"] = ""',
        _T,
        "stated_rule",
    ),
    _m(
        "09",
        "the reply tip is not put on the Contractor's Response cells",
        _N,
        "        ws.add_data_validation(tip)\n",
        "        pass\n",
        "tests/test_crs_permanent_numbers.py",
        "asks_for_a_response_code_on_every_reply_cell",
    ),
    _m(
        "10",
        "body cells no longer wrap (a long comment or several numbers on one line run off the cell)",
        APP / "crs_layout.py",
        'horizontal=cell.alignment.horizontal, vertical="top", wrap_text=True',
        'horizontal=cell.alignment.horizontal, vertical="top", wrap_text=False',
        "tests/test_agent_review_crs.py",
        "styled_by_code",
    ),
    _m(
        "11",
        "the contractor-facing copy carries the Status (it would say which comments were drafts)",
        _N,
        'row["status"] = status if internal else ""',
        'row["status"] = status',
        _T,
        "contractor_facing_copy",
    ),
)
