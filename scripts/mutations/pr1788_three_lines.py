"""PR 1788: the rule check's CRS comment is three lines (`crs_mapping.engineer_comment_text`, danger zone) and the AI review tab shows
the file's comment (`crs_ai_workbook.screen_text`). Ids M1788-01.. (rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation


def _m(n, desc, path, anchor, repl, target, kw):
    return Mutation(id=f"M1788-{n}", phase=1788, description=desc, path=APP / path, anchor=anchor, replacement=repl,
                    target=target, keyword=kw, tags=("honesty",))  # fmt: skip


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "the rule check's three parts run together on one line again",
        "crs_mapping.py",
        '    return "\\n".join(p for p in (lead, said, todo) if p)',
        '    return " ".join(p for p in (lead, said, todo) if p)',
        "tests/test_crs_mapping.py",
        "three_lines",
    ),
    _m(
        "02",
        "the AI review tab shows the stored reason, not the file's three lines",
        "crs_ai_workbook.py",
        '    return comment_cell(layout_comment(line, *got)) or "" if got else ""',
        '    return ""',
        "tests/test_agent_review_routes.py",
        "three_lines_of_the_files_comment_cell",
    ),
)
