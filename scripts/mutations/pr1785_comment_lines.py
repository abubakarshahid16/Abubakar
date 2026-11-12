"""PR 1785: the three parts of a CRS comment are three lines in the cell (`crs_ai_workbook.comment_cell`). Ids M1785-01.. (rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_P = APP / "crs_ai_workbook.py"
_T = "tests/test_agent_review_crs.py"


def _m(n, desc, anchor, repl, kw):
    return Mutation(id=f"M1785-{n}", phase=1785, description=desc, path=_P, anchor=anchor, replacement=repl,
                    target=_T, keyword=kw, tags=("honesty",))  # fmt: skip


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "the three parts run together on one line again",
        '    text = "\\n".join(lines)\n',
        '    text = " ".join(lines)\n',
        "three_lines",
    ),
    _m(
        "02",
        "a part keeps no full stop (part three runs on)",
        '    lines = [ln if ln[-1] in ".!?" else ln + "." for ln in lines if ln]\n',
        "    lines = [ln for ln in lines if ln]\n",
        "three_lines",
    ),
    _m(
        "03",
        "the comment column is flattened with every other cell",
        "comment_cell(v) if i == lines_col else _cell(v)",
        "_cell(v)",
        "three_lines",
    ),
    _m(
        "04",
        "a comment that starts with an equals sign is a formula",
        '    return " " + text if text[:1] in ("=", "+", "-", "@") else text\n\n\ndef _table',
        "    return text\n\n\ndef _table",
        "still_cleaned",
    ),
)
