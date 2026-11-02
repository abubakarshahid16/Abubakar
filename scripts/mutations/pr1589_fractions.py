"""PR 1589: a limit written as a fraction, in `numparse` (the one home of a number). Ids M1589-01 onwards, phase 1589."""

from __future__ import annotations

from ._base import APP, Mutation

_N = APP / "numparse.py"
_T = "tests/test_1584_standards_compiler.py"
_TAGS = ("numparse", "standards_compiler")


def _m(n, description, anchor, replacement, keyword):
    return Mutation(
        id=f"M1589-{n}",
        phase=1589,
        description=description,
        path=_N,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=_TAGS,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "a mixed fraction loses its whole part, so 2-3/8 inch reads as 0.375 inch",
        "value = int(m.group(1) or 0) + int(m.group(2)) / int(m.group(3))",
        "value = int(m.group(2)) / int(m.group(3))",
        "fraction_is_a_number",
    ),
    _m(
        "02",
        "one end of a date is read as a fraction",
        r"""(?<![\d./\u2044])(?:(\d+)[- ])?(\d+)\s*[/\u2044]\s*(\d+)(?![\d./\u2044])""",
        r"""(?:(\d+)[- ])?(\d+)\s*[/\u2044]\s*(\d+)""",
        "not_one_fraction",
    ),
    _m(
        "03",
        "a text limit with a fraction in it counts as one bare number",
        "    if len(found) == 1 and found[0].start == 0 and found[0].end == len(text.strip()):\n",
        "    if found:\n",
        "not_one_fraction",
    ),
)
