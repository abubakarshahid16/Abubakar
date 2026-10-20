"""PR #1121 (order 95 piece 6b): an edited CRS comment keeps the AI's wording
beside it, on the internal copy only. `crs_mapping.py` and `crs_export.py` are
in the danger zone (rule 6)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_95_ai_wording.py"
_TAGS = ("honesty", "critical")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1121-01",
        phase=1121,
        description="an edited row loses the machine wording",
        path=APP / "crs_mapping.py",
        anchor='                "ai_comment": machine,\n',
        replacement='                "ai_comment": text,\n',
        target=_T,
        keyword="keeps_the_machine_wording_and_says",
        tags=_TAGS,
    ),
    Mutation(
        id="M1121-02",
        phase=1121,
        description="a datasheet check's machine wording is the generic comment text",
        path=APP / "crs_mapping.py",
        anchor="            if blanks or kind != ROW_KIND_DATASHEET_CHECK:\n",
        replacement="            if True:\n",
        target=_T,
        keyword="datasheet_check_keeps_its_own",
        tags=_TAGS,
    ),
    Mutation(
        id="M1121-03",
        phase=1121,
        description="an edited row is not marked edited",
        path=APP / "crs_mapping.py",
        anchor='                "edited": text.strip() != machine.strip(),\n',
        replacement='                "edited": False,\n',
        target=_T,
        keyword="keeps_the_machine_wording_and_says",
        tags=_TAGS,
    ),
    Mutation(
        id="M1121-04",
        phase=1121,
        description="the contractor's copy carries the AI wording",
        path=APP / "crs_export.py",
        anchor='    if copy != COPY_INTERNAL:\n        return ""\n    text = str(',
        replacement='    if False:\n        return ""\n    text = str(',
        target=_T,
        keyword="issue_copy_does_not",
        tags=_TAGS,
    ),
    Mutation(
        id="M1121-05",
        phase=1121,
        description="the internal copy never prints the AI wording",
        path=APP / "crs_export.py",
        anchor='        return f"{AI_WORDING_LABEL}: {ai_wording}"\n',
        replacement="        return text\n",
        target=_T,
        keyword="issue_copy_does_not",
        tags=_TAGS,
    ),
    Mutation(
        id="M1121-06",
        phase=1121,
        description="an unedited row prints the AI wording a second time",
        path=APP / "crs_export.py",
        anchor='    if not text and finding.get("edited") is True and ai_wording:\n',
        replacement="    if not text and ai_wording:\n",
        target=_T,
        keyword="unedited_row_prints_its_comment_once",
        tags=_TAGS,
    ),
    Mutation(
        id="M1121-07",
        phase=1121,
        description="an edit that keeps the machine's words prints them twice",
        path=APP / "crs_mapping.py",
        anchor='                "edited": text.strip() != machine.strip(),\n',
        replacement='                "edited": bool(f.get("engineer_comment")),\n',
        target=_T,
        keyword="not_printed_twice",
        tags=_TAGS,
    ),
)
