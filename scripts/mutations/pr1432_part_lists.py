"""Order 298.2 (PR 1432): a citation naming several parts cites each part. Ids M1432-01 onwards, phase 1432."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_298_part_lists.py"
_TAGS = ("honesty", "o298")


def _m(n, description, anchor, replacement, keyword):
    return Mutation(
        id=f"M1432-{n:02d}",
        phase=1432,
        description=description,
        path=APP / "standard_ids.py",
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=_TAGS,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        1,
        "only the first part of a part list is cited again",
        "for spelling in [raw, *_further_parts(text, raw, end)]:",
        "for spelling in [raw]:",
        "cites_each_of_them",
    ),
    _m(
        2,
        "the list separator '&' is not read",
        r"(?:&|(?i:AND)|/)",
        r"(?:(?i:AND)|/)",
        "cites_each_of_them",
    ),
    _m(
        3,
        "a word after 'and' (digits or roman only are parts) is read as a part",
        '(\\d{1,2}|[IVX]{1,4})\\b"',
        '(\\w{1,4})\\b"',
        "what_is_not_named",
    ),
    _m(
        4,
        "a comma-led quantity is read as a part (the separator '/' becomes ',')",
        r"(?:&|(?i:AND)|/)",
        r"(?:&|(?i:AND)|/|,)",
        "quantity_after_a_citation",
    ),
    _m(
        5,
        "a number that counts or measures something after a part is read as a second part",
        "        if _is_quantity(text, more.end()):\n            break\n",
        "",
        "counts_things",
    ),
)
