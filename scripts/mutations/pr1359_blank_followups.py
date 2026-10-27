"""Backlog 5 (PR 1359): the two #1324 follow-ups. Blank detection feeds a "contractor to provide"
comment, so it is guarded like the unit and comparison code (rule 6). Ids M1359-01 onwards, phase 1359."""

from __future__ import annotations

from ._base import APP, Mutation

_F = APP / "geometry_blank_cells.py"
_T = "tests/test_243_blank_cell_followups.py"
_TAGS = ("honesty", "o243")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1359-01",
        phase=1359,
        description="a label ending in a bare unit ('Design pressure barg') is a blank again",
        path=_F,
        anchor="    if _ends_in_a_bare_unit(text):\n        return []\n",
        replacement="",
        target=_T,
        tags=_TAGS,
    ),
    Mutation(
        id="M1359-02",
        phase=1359,
        description="a solid dark fill over one cell is background again, so a blacked-out cell is a blank",
        path=_F,
        anchor="    return _area(box) <= ONE_CELL * _area(inner)\n",
        replacement="    return False\n",
        target=_T,
        tags=_TAGS,
    ),
    Mutation(
        id="M1359-03",
        phase=1359,
        description="a dark band behind the whole table is a mark in every cell (no blank anywhere)",
        path=_F,
        anchor="    return _area(box) <= ONE_CELL * _area(inner)\n",
        replacement="    return True\n",
        target=_T,
        tags=_TAGS,
    ),
    Mutation(
        id="M1359-04",
        phase=1359,
        description="a light shaded input cell counts as a dark mark",
        path=_F,
        anchor="    if not fill or len(fill) not in (1, 3) or max(fill) >= DARK_FILL:\n        return False\n",
        replacement="    if not fill:\n        return False\n",
        target=_T,
        tags=_TAGS,
    ),
    Mutation(
        id="M1359-05",
        phase=1359,
        description="the darkness threshold is raised, so a mid-dark shaded input cell reads as a blacked-out mark",
        path=_F,
        anchor="DARK_FILL = 0.35\n",
        replacement="DARK_FILL = 0.6\n",
        target=_T,
        tags=_TAGS,
    ),
    Mutation(
        id="M1359-06",
        phase=1359,
        description="the one-cell size limit is widened, so a dark band behind a row reads as this cell's mark",
        path=_F,
        anchor="ONE_CELL = 2.5\n",
        replacement="ONE_CELL = 4.0\n",
        target=_T,
        tags=_TAGS,
    ),
    Mutation(
        id="M1359-07",
        phase=1359,
        description="a label ending in a time unit ('Service hours') is a lost value again, so a real blank is lost",
        path=_F,
        anchor='    if word in _COUNTED_THINGS or claims.unit_dimension(word) == "time":\n        return False\n',
        replacement="",
        target=_T,
        tags=_TAGS,
    ),
)
