from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1418-01",
        phase=1418,
        description="a reference word no longer has to start a word: 'hydrogen 5' is read as 'en 5' and the figure is dropped",
        path=APP / "blank_markers.py",
        anchor='r"(?<![A-Za-z0-9])(?:note|',
        replacement='r"(?:note|',
        target="tests/test_1352_placeholder_not_stated.py",
        keyword="not_standing_alone",
        tags=("honesty",),
    ),
    Mutation(
        id="M1418-02",
        phase=1418,
        description="para, fig, annex, appendix, sheet, dwg, spec and rev are not reference words: their numbers cancel the star",
        path=APP / "blank_markers.py",
        anchor="|para|paragraph|fig|figure",
        replacement="",
        target="tests/test_1352_placeholder_not_stated.py",
        keyword="lone_star",
        tags=("honesty",),
    ),
    Mutation(
        id="M1418-03",
        phase=1418,
        description="the digits of a hyphenated code ('KOC-ME-008') are a figure again and cancel the star",
        path=APP / "blank_markers.py",
        anchor="(?<![A-Za-z]-)",
        replacement="",
        target="tests/test_1352_placeholder_not_stated.py",
        keyword="lone_star",
        tags=("honesty",),
    ),
    Mutation(
        id="M1418-04",
        phase=1418,
        description="a signed value ('-5 m') is no longer a figure: the hyphen rule swallows the sign",
        path=APP / "blank_markers.py",
        anchor="(?<![A-Za-z]-)",
        replacement="(?<!-)",
        target="tests/test_1352_placeholder_not_stated.py",
        keyword="not_standing_alone",
        tags=("honesty",),
    ),
)
