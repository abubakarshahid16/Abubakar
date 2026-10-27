"""Order 233 (#1322): the internal CRS copy's AI Review Comments cell is never
blank, and the note never reaches the issue copy. `crs_export.py` is in the
danger zone (rule 6)."""

from __future__ import annotations

from ._base import APP, Mutation

_M = APP / "crs_export.py"
_T = "tests/test_233_ai_cell.py"
_TAGS = ("honesty", "critical")


def _m(
    n: str, description: str, anchor: str, replacement: str, keyword: str
) -> Mutation:
    return Mutation(
        id=f"M1322-{n}",
        phase=1322,
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
        "the cell ignores the note again (blank cell on a row the AI did not word)",
        '    return text or str(finding.get("ai_cell_note") or "")\n',
        "    return text\n",
        "prints_the_note_on_the_internal_copy_only",
    ),
    _m(
        "02",
        "the note is printed on the issue copy too (a contractor reads our internal note)",
        '    if copy != COPY_INTERNAL:\n        return ""\n    text = str(finding.get("ai_review_comment") or "")\n',
        '    text = str(finding.get("ai_review_comment") or "")\n',
        "prints_the_note_on_the_internal_copy_only",
    ),
    _m(
        "03",
        "the note wins over an AI draft (the draft is hidden)",
        '    return text or str(finding.get("ai_cell_note") or "")\n',
        '    return str(finding.get("ai_cell_note") or "") or text\n',
        "draft_or_the_edited_label_wins",
    ),
)
