"""The clause structure of the standards (`clause_structure`, read by `StandardText.spans`; owner, 16 Nov 2026): numbered clauses written like body text are found from the book's
own evidence; nothing that only LOOKS like a clause number cuts a clause. Each entry deletes one control; `tests/test_clause_structure.py` must notice.
Ids M1838-01 onwards (CLAUDE.md rule 12); the PR number is provisional until the PR is opened."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_clause_structure.py"
_CS = APP / "clause_structure.py"
_SS = APP / "subject_scope.py"
_TAGS = ("honesty", "critical", "clauses")


def _m(
    n: int, description: str, path, anchor: str, replacement: str, keyword: str
) -> Mutation:
    return Mutation(
        id=f"M1838-{n:02d}",
        phase=1838,
        description=description,
        path=path,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=_TAGS,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        1,
        "a clause number need not be the immediate successor of the last clause in the book's own sequence",
        _CS,
        "        successor = last is not None and immediate_successor(ident, last)\n",
        "        successor = True\n",
        "not_the_next_clause",
    ),
    _m(
        2,
        "the line before a body-text clause need not end a sentence (a wrapped cross-reference opens a clause)",
        _CS,
        "        elif not sentence_ok:\n",
        "        elif False:\n",
        "wrapped_line_that_starts",
    ),
    _m(
        3,
        "a running header or footer with a section number can open a clause",
        _CS,
        '        if re.sub(r"\\d+", "#", line) in running:\n            out.rejected["running line"] += 1\n        elif not successor:',
        '        if False:\n            out.rejected["running line"] += 1\n        elif not successor:',
        "running_header",
    ),
    _m(
        4,
        "a lower-case first word (a decimal ratio, a reference) is accepted as the start of a clause",
        _CS,
        '        elif not word.group("w")[0].isupper():\n',
        "        elif False:\n",
        "missed_clause_breaks_the_chain",
    ),
    _m(
        5,
        "a unit, month or cross-reference word after the number is accepted as the start of a clause",
        _CS,
        "        elif not shape_ok:\n",
        "        elif False:\n",
        "reference_unit_or_date_word",
    ),
    _m(
        6,
        "a table row or contents entry is accepted as a clause",
        _CS,
        "            and not _is_table_or_contents_entry(rest)\n",
        "",
        "table_row_that_ends",
    ),
    _m(
        7,
        "the lines of a contents page can open a clause",
        _CS,
        "        if head is not None or i in contents:\n",
        "        if head is not None:\n",
        "lines_of_a_contents_page",
    ),
    _m(
        8,
        "a number alone on its line is a clause whatever follows it",
        _CS,
        "            elif not following[:1].isupper():\n",
        "            elif False:\n",
        "number_alone_whose_next_line",
    ),
    _m(
        9,
        "a one-component number can end a clause for certain (a table row inside it)",
        _CS,
        '                "." in head[1]\n',
        "                True\n",
        "one_component_number",
    ),
    _m(
        10,
        "an id that is not the immediate successor of the clause ends it for certain (a header with a later section number)",
        _SS,
        "(index in self.body.sure and clause_structure.is_next(head[1], clause[1]))",
        "(index in self.body.sure)",
        "what_only_looks_like",
    ),
    _m(
        11,
        "a bare number (a page number) can end a clause for certain",
        _SS,
        "(index not in self.bare or index in self.body.sure)",
        "True",
        "bare_page_number",
    ),
)
