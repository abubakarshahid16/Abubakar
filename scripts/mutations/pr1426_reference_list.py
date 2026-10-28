from __future__ import annotations

from ._base import APP, Mutation

TARGET = "tests/test_267_reference_list.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1426-01",
        phase=1426,
        description="a references section is read as requirements again: its sentences are recorded",
        path=APP / "standards.py",
        anchor='if references.step(chunk["section"]):',
        replacement="if False:",
        target=TARGET,
        keyword="references_heading",
        tags=("honesty",),
    ),
    Mutation(
        id="M1426-02",
        phase=1426,
        description="a references list run into one line is recorded as a requirement again",
        path=APP / "standards.py",
        anchor="if requirement_quality.is_reference_list_sentence(sentence):",
        replacement="if False:",
        target=TARGET,
        keyword="run_into_one_line",
        tags=("honesty",),
    ),
    Mutation(
        id="M1426-03",
        phase=1426,
        description="one standard after a references title is enough to drop a sentence",
        path=APP / "requirement_quality.py",
        anchor="if start is None or len(_IDENTIFIER.findall(sentence)) < 2:",
        replacement="if start is None:",
        target=TARGET,
        keyword="one_standard",
        tags=("honesty",),
    ),
    Mutation(
        id="M1426-04",
        phase=1426,
        description="a sentence that merely starts with 'Reference' and cites two standards later is dropped",
        path=APP / "requirement_quality.py",
        anchor='_IDENTIFIER.match(sentence[start.end() :].lstrip(" :-\\u2013\\u2014\\t"))',
        replacement="True",
        target=TARGET,
        keyword="merely_starts",
        tags=("honesty",),
    ),
    Mutation(
        id="M1426-05",
        phase=1426,
        description="the references run never closes: every later section is dropped",
        path=APP / "requirement_quality.py",
        anchor='or here.startswith(self.clause + ".")',
        replacement="or True",
        target=TARGET,
        keyword="after_the_references",
        tags=("honesty",),
    ),
)
