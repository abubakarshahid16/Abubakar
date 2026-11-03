"""#1607 (PR #1617): parse_value reads a Unicode hyphen before a number as a minus (numparse.py;
danger zone). Ids M1617-01.. (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_1607_numparse_hyphen_minus.py"
_TAG = ("pr1617", "numbers", "honesty")
_NUM = APP / "numparse.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1617-01",
        phase=1617,
        description="a Unicode hyphen before a number is a plus again",
        path=_NUM,
        anchor='    s = (value_str or "").strip().translate(_HYPHEN_AS_DASH)\n',
        replacement='    s = (value_str or "").strip()\n',
        target=_T,
        keyword="starting_a_value_is_a_minus",
        tags=_TAG,
    ),
    Mutation(
        id="M1617-02",
        phase=1617,
        description="a Unicode hyphen glued to a letter reads as a negative number",
        path=_NUM,
        # #1619 made the old mutant (the hyphens folded to ASCII) behave the same as the real code;
        # #1655 moved the guard to `_value_prefix`: a dash before the number leaves no prefix.
        anchor="    return prefix[:-1] if prefix[-1:] in DASHES else prefix\n",
        replacement='    return "" if prefix[-1:] in DASHES else prefix\n',
        target=_T,
        keyword="the_text_cannot_say",
        tags=_TAG,
    ),
    Mutation(
        id="M1617-03",
        phase=1617,
        description="only one of the two Unicode hyphens is read as a minus",
        path=_NUM,
        anchor=r'_HYPHEN_AS_DASH = str.maketrans("\u2010\u2011", "\u2013\u2013")',
        replacement=r'_HYPHEN_AS_DASH = str.maketrans("\u2010", "\u2013")',
        target=_T,
        keyword="agree_on_the_sign",
        tags=_TAG,
    ),
)
