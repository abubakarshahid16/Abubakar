"""Order 228.1-228.3: the program's own names stay out of the contractor's Standard Reference.
`crs_mapping.py` and its row helpers are in the danger zone (rule 6). PR #1317: ids M1317-01
onwards, phase 1317."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_228_crs_reference_internal_names.py"
_TAGS = ("honesty", "o228")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1317-01",
        phase=1317,
        description="a check with no source prints the program's check id in the Standard Reference",
        path=APP / "crs_reference.py",
        anchor='        return "Datasheet check"\n',
        replacement='        return "Datasheet check " + check_id(finding)\n',
        target=_T,
        tags=_TAGS,
    ),
    Mutation(
        id="M1317-02",
        phase=1317,
        description="the standard an AI draft relates to keeps the engine sentence that follows it",
        path=APP / "crs_reference.py",
        anchor='.split(" Written by ")[0].rstrip(".")',
        replacement='.rstrip(".")',
        target=_T,
        tags=_TAGS,
    ),
    Mutation(
        id="M1317-03",
        phase=1317,
        description="the note that merged drafts differ is part of the draft's words again",
        path=APP / "crs_ai_drafts.py",
        anchor="    return numbered, note  # the note is the screen's action line, never the comment (228.3)\n",
        replacement='    return f"{note} {numbered}", note\n',
        target="tests/test_161d_ai_drafts.py",
        tags=_TAGS,
    ),
    Mutation(
        id="M1317-04",
        phase=1317,
        description="the check's id is lost from the internal reasoning cell too",
        path=APP / "crs_reference.py",
        anchor='            f"Check: {check_id(finding)}" if check_id(finding) else "",\n',
        replacement='            "",\n',
        target=_T,
        tags=_TAGS,
    ),
)
