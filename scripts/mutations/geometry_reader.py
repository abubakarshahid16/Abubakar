"""Mutations of `backend/app/geometry_reader.py`."""

from __future__ import annotations

from ._base import APP, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from B5_STANDARDS_INVENTORY --------------------------------------
    #: B5 part 2: standard family, licence status, cover-page backfill, and the
    #: "cited by a submittal" flag on the inventory.
    # #193 section 5.1 - geometry reader (proposal stage, not wired live).
    Mutation(
        id="M550", phase=61,
        description="header rebuild reads only a cell's own column: a parent "
                    "spanning three columns no longer labels its children",
        path=APP / "geometry_reader.py",
        anchor="                if rect[0] <= centre <= rect[2]:\n",
        replacement="                if k == j:\n",
        target="tests/test_geometry_reader.py",
        keyword="parent",
        tags=("extraction",),
    ),
    Mutation(
        id="M551", phase=61,
        description="title rows are never recognised, so a full-width title "
                    "above the header is kept as a header row",
        path=APP / "geometry_reader.py",
        anchor="        if (rect[2] - rect[0]) / width >= TITLE_SPAN_SHARE:\n",
        replacement="        if False:\n",
        target="tests/test_geometry_reader.py",
        keyword="title",
        tags=("extraction",),
    ),
    Mutation(
        id="M552", phase=61,
        description="an underscore field is read as a value instead of blank",
        path=APP / "geometry_reader.py",
        anchor='    if not re.search(r"[^\\W_]", residue):\n',
        replacement="    if False:\n",
        target="tests/test_geometry_reader.py",
        keyword="blank",
        tags=("extraction", "honesty"),
    ),
    Mutation(
        id="M553", phase=61,
        description="number + unit split disabled: '10 barg' keeps no unit",
        path=APP / "geometry_reader.py",
        anchor="    m = _NUM_UNIT.match(stripped)\n",
        replacement="    m = None\n",
        target="tests/test_geometry_reader.py",
        keyword="unit_split or form_label_value or celsius",
        tags=("extraction", "units"),
    ),
    Mutation(
        id="M554", phase=61,
        description="a printed unit label alone becomes a false BLANK "
                    "(addendum 3.7: not found is never blank)",
        path=APP / "geometry_reader.py",
        anchor="        if had_run:\n",
        replacement="        if True:\n",
        target="tests/test_geometry_reader.py",
        keyword="unit_label_alone_is_neither",
        tags=("extraction", "honesty"),
    ),
    Mutation(
        id="M555", phase=61,
        description="the '*' (to be advised) marker is read as a value",
        path=APP / "geometry_reader.py",
        anchor='    star = re.match(r"^\\*\\s*(?P<rest>.*)$", residue)\n',
        replacement="    star = None\n",
        target="tests/test_geometry_reader.py",
        keyword="star_marker_is_a_blank",
        tags=("extraction", "honesty"),
    ),
    Mutation(
        id="M556", phase=61,
        description="a far empty run in another column makes this field blank "
                    "although a filled value sits below it",
        path=APP / "geometry_reader.py",
        anchor="                    and _filled_below(segs, lab, used)):\n",
        replacement="                    and False):\n",
        target="tests/test_geometry_reader.py",
        keyword="far_empty_run_is_not",
        tags=("extraction", "honesty"),
    ),
)
