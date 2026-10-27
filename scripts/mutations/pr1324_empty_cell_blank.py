"""Order 228.9 remainder (PR 1324): an empty ruled cell is a blank only when
the geometry proves it."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_228_empty_cell_blank.py"
_F = APP / "geometry_blank_cells.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1324-01",
        phase=1324,
        description="one answer in the column is enough to call an empty cell a blank",
        path=_F,
        anchor="MIN_FILLED_ABOVE = 2\n",
        replacement="MIN_FILLED_ABOVE = 0\n",
        target=_T,
        keyword="too_few_answers",
        tags=("honesty",),
    ),
    Mutation(
        id="M1324-02",
        phase=1324,
        description="an image in the cell no longer stops it being a blank",
        path=_F,
        anchor='        if any(_meets(inner, i["bbox"]) for i in page.get_image_info()):\n',
        replacement="        if False:\n",
        target=_T,
        keyword="image_or_a_drawn_shape",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1324-03",
        phase=1324,
        description="a drawn shape in the cell no longer stops it being a blank",
        path=_F,
        anchor='        return not any(_meets(inner, d["rect"]) for d in page.get_drawings())\n',
        replacement="        return True\n",
        target=_T,
        keyword="image_or_a_drawn_shape",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1324-04",
        phase=1324,
        description="a rotated page is trusted to have its cells where the rows say",
        path=_F,
        anchor="    if not box or int(page.rotation) != 0 or text_rotation(page) != 0:\n",
        replacement="    if not box:\n",
        target=_T,
        keyword="rotated_page",
        tags=("honesty",),
    ),
    Mutation(
        id="M1324-05",
        phase=1324,
        description="a word inside the cell no longer stops it being a blank",
        path=_F,
        anchor='        if any(_meets(inner, w[:4]) for w in page.get_text("words")):\n',
        replacement="        if False:\n",
        target=_T,
        keyword="word_inside_the_cell",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1324-06",
        phase=1324,
        description="the page does not confirm candidates: every empty cell is kept",
        path=_F,
        anchor='    return [r for r in rows if not r.get("empty_cell") or cell_is_bare(page, r["bbox"])]\n',
        replacement="    return list(rows)\n",
        target=_T,
        keyword="image_or_a_drawn_shape",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1324-07",
        phase=1324,
        description="a value line under an empty label cell is taken for a label (a false blank)",
        path=_F,
        anchor="    return same * 2 > len(paired)\n",
        replacement="    return True\n",
        target=_T,
        keyword="is_not_a_blank",
        tags=("honesty", "critical"),
    ),
)
