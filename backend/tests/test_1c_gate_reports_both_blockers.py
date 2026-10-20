"""Release 1c: #1188 (a confirmed line with no text blocks the issue) and
#1200 (a machine word in a contractor-facing cell blocks it) both add to
`crs_issue.open_items`' blockers. They were merged by hand in the same lines;
this pins that a sheet with BOTH problems reports BOTH, and that either one
alone reports only itself.

MUTATION PROOF (by hand): drop the machine-words extend and the second test
fails; drop the no-text append and the first fails.

Invented data only.
"""

from __future__ import annotations

from app import crs_issue, datasheet_checks

COVERED = {"pages_total": 1, "pages_not_read_into_fields": []}
CODE = next(k for k in sorted(datasheet_checks.load_rules()["roles"]) if "_" in k)


def _row(n: int, comment: str, **over) -> dict:
    return {
        "finding_id": f"f{n}",
        "document_name": "inv.pdf",
        "page_section": f"p.{n}",
        "comment": comment,
        "comment_by": "AI Review, confirmed by an engineer",
        "row_kind": "missing_information",
        "engineer_confirmed": True,
        **over,
    }


def _blockers(rows):
    return crs_issue.open_items("run-1", rows, COVERED)["blockers"]


def test_a_sheet_with_a_no_text_line_and_a_machine_word_reports_both():
    blockers = _blockers([_row(1, ""), _row(2, f"Field {CODE} is missing.")])
    assert any("no text" in b for b in blockers), blockers
    assert any(CODE in b and "edit its wording" in b for b in blockers), blockers
    assert len(blockers) == 2


def test_each_problem_alone_reports_only_itself():
    only_empty = _blockers([_row(1, ""), _row(2, "Plain words.")])
    assert len(only_empty) == 1 and "no text" in only_empty[0]
    only_word = _blockers(
        [_row(1, "Plain words."), _row(2, f"Field {CODE} is missing.")]
    )
    assert len(only_word) == 1 and CODE in only_word[0]
