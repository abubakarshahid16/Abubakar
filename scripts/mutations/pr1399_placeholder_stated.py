"""PR 1399: a placeholder value is never "stated" in a checklist item. `datasheet_checks.py` is in
the danger zone (rule 6). Ids M1399-01 onwards, phase 1399."""

from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1399-01",
        phase=1399,
        description="a checklist item judges a value blank from the is_blank flag only: '* m3/h' is stated again",
        path=APP / "datasheet_checks.py",
        anchor="if blank_markers.fact_is_placeholder(fact, figure_wins=True):",
        replacement='if fact.get("is_blank"):',
        target="tests/test_1352_placeholder_not_stated.py",
        keyword="placeholder",
        tags=("honesty",),
    ),
    Mutation(
        id="M1399-02",
        phase=1399,
        description="a checklist item judges the note printed beside a read figure: '10 barg By Contractor' is missing again",
        path=APP / "datasheet_checks.py",
        anchor="if blank_markers.fact_is_placeholder(fact, figure_wins=True):",
        replacement="if blank_markers.fact_is_placeholder(fact):",
        target="tests/test_1352_placeholder_not_stated.py",
        keyword="note_beside_it",
        tags=("honesty",),
    ),
    Mutation(
        id="M1399-03",
        phase=1399,
        description="a figure the reader parsed no longer states the value when the phrase comes first",
        path=APP / "blank_markers.py",
        anchor='shown = str(fact.get("raw_value") or fact.get("field_value") or "")',
        replacement='shown = str(fact.get("field_value") or "")',
        target="tests/test_1352_placeholder_not_stated.py",
        keyword="note_beside_it",
        tags=("honesty",),
    ),
    Mutation(
        id="M1399-04",
        phase=1399,
        description="a figure AFTER the phrase counts too: 'By Contractor 10 barg' is stated from the printed text",
        path=APP / "blank_markers.py",
        anchor="_FIGURE.search(folded[: marker.start()])",
        replacement="_FIGURE.search(folded)",
        target="tests/test_1352_placeholder_not_stated.py",
        keyword="no_figure_before_it",
        tags=("honesty",),
    ),
    Mutation(
        id="M1399-05",
        phase=1399,
        description="a digit inside a unit counts as a figure: 'm3/h TBA' is stated",
        path=APP / "blank_markers.py",
        anchor='_FIGURE = re.compile(r"(?<![A-Za-z_])\\d")',
        replacement='_FIGURE = re.compile(r"\\d")',
        target="tests/test_1352_placeholder_not_stated.py",
        keyword="no_figure_before_it",
        tags=("honesty",),
    ),
    Mutation(
        id="M1399-06",
        phase=1399,
        description="any digit in the shown value states it, a phrase before the digit or not: 'TBA 2025' is stated",
        path=APP / "blank_markers.py",
        anchor="not classify(shown)[0] or figure_beside_note(shown)",
        replacement="True",
        target="tests/test_1352_placeholder_not_stated.py",
        keyword="no_figure_before_it",
        tags=("honesty",),
    ),
)
