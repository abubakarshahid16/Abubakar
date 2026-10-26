"""Code audit 26 Oct, items K7 and K8: the program's account of how it read or decided
never reaches the contractor unnoticed. `crs_mapping.py` is in the danger zone (rule 6).
PR #1300: ids M1300-01 onwards, phase 1300."""

from __future__ import annotations

from ._base import APP, Mutation

_W = "tests/test_152_crs_machine_words.py"
_TAGS = ("honesty", "k7k8")


def _phrase(i: int, phrase: str) -> Mutation:
    return Mutation(
        id=f"M1300-{i:02d}",
        phase=1300,
        description=f"'{phrase}' is no longer an internal phrase the issue gate blocks",
        path=APP / "crs_machine_words.py",
        anchor=f'    "{phrase}",\n',
        replacement="",
        target=_W,
        keyword="machine_words_are_found",
        tags=_TAGS,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _phrase(1, "no field read from"),
    _phrase(2, "validation state"),
    _phrase(3, "page reader"),
    _phrase(4, "automatic result"),
    _phrase(5, "engineer to tick"),
    Mutation(
        id="M1300-06",
        phase=1300,
        description="a not-found row again tells the contractor how the program paired fields",
        path=APP / "crs_mapping.py",
        anchor='            f"Clarification requested: please indicate where the datasheet states "\n',
        replacement='            f"Clarification requested: no field read from the datasheet was paired with "\n',
        target="tests/test_f7_735_clean_crs.py",
        keyword="no_field_was_paired",
        tags=_TAGS,
    ),
    Mutation(
        id="M1300-07",
        phase=1300,
        description="'this engine' is no longer an internal phrase the issue gate blocks",
        path=APP / "crs_machine_words.py",
        anchor='    "this engine",\n',
        replacement="",
        target="tests/test_k78_issue_rows_carry_no_program_voice.py",
        keyword="this_engine",
        tags=_TAGS,
    ),
    Mutation(
        id="M1300-08",
        phase=1300,
        description="a table-number clause prints 'paragraph not identified' again",
        path=APP / "paragraph_ids.py",
        anchor='    return ""\n\n\n_CACHE: dict = {}',
        replacement='    return " (paragraph not identified)" if clause else ""\n\n\n_CACHE: dict = {}',
        target="tests/test_k78_issue_rows_carry_no_program_voice.py",
        keyword="no_paragraph_not_identified",
        tags=_TAGS,
    ),
    Mutation(
        id="M1300-09",
        phase=1300,
        description="a bare blank marker is printed back to the contractor",
        path=APP / "crs_mapping.py",
        anchor='        shown = value if value.strip("_-. ") else ""\n',
        replacement="        shown = value\n",
        target="tests/test_k78_issue_rows_carry_no_program_voice.py",
        keyword="bare_blank_marker",
        tags=_TAGS,
    ),
    Mutation(
        id="M1300-10",
        phase=1300,
        description="a one-clause row says 'clauses'",
        path=APP / "crs_mapping.py",
        anchor="    heading = f\"Supporting clause{'' if n == 1 else 's'} ({n}):\"\n",
        replacement="    heading = f\"Supporting clauses ({n}):\"\n",
        target="tests/test_k78_issue_rows_carry_no_program_voice.py",
        keyword="singular_heading",
        tags=_TAGS,
    ),
)
