"""#1200 (order 152.2): the machine-words gate. `crs_mapping.py` is in the
danger zone (rule 6), and #1200 added the `engineer_worded` marker that tells
the scan which AI / web item text is the engineer's own."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_1200_engineer_worded_marker.py"
_ANCHOR = '                "engineer_worded": bool(f.get("engineer_comment")),\n'

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1200-01",
        phase=1200,
        description="an AI/web item an engineer edited is never marked as theirs: their own wording is blocked as machine words",
        path=APP / "crs_mapping.py",
        anchor=_ANCHOR,
        replacement='                "engineer_worded": False,\n',
        target=_T,
        keyword="edited_is_marked_and_not_scanned",
        tags=("honesty", "crs"),
    ),
    Mutation(
        id="M1200-02",
        phase=1200,
        description="every AI/web item is marked as the engineer's own: machine words in a confirmed item reach the contractor",
        path=APP / "crs_mapping.py",
        anchor=_ANCHOR,
        replacement='                "engineer_worded": True,\n',
        target=_T,
        keyword="only_confirmed_is_machine_text",
        tags=("honesty", "critical", "crs"),
    ),
)
