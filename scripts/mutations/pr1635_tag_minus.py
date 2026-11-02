"""#1619 (PR #1635): a minus directly after a letter joins a tag or grade; it is not a sign
(numparse.py; danger zone). Ids M1635-01.. (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_1619_tag_minus.py"
_TAG = ("pr1635", "numbers", "honesty")
_NUM = APP / "numparse.py"
_PARSE = '    if m.group("num").startswith("-") and prefix[-1:].isalpha():\n'

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1635-01",
        phase=1635,
        description="parse_value reads a tag-shaped value as a negative number again",
        path=_NUM,
        anchor=_PARSE,
        replacement="    if False:\n",
        target=_T,
        keyword="directly_after_a_letter",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-02",
        phase=1635,
        description="parse_value refuses a real negative after a letter and a space",
        path=_NUM,
        anchor=_PARSE,
        replacement='    if m.group("num").startswith("-") and prefix.rstrip()[-1:].isalpha():\n',
        target=_T,
        keyword="real_negative_stays",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-05",
        phase=1635,
        description="a trailing limit restarts on a later digit of a joined number",
        path=APP / "requirements_3b.py",
        anchor=r"""(?<![\d.,]-)(?<![\d.,])(?P<value>""",
        replacement=r"""(?<![\d.,]-)(?P<value>""",
        target=_T,
        keyword="restarts_inside",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-06",
        phase=1635,
        description="a trailing limit reads the digits after a digit and a hyphen",
        path=APP / "requirements_3b.py",
        anchor=r"""(?<![^\W\d_]-)(?<![\d.,]-)(?<![\d.,])""",
        replacement=r"""(?<![^\W\d_]-)(?<![\d.,])""",
        target=_T,
        keyword="digit_then_hyphen",
        tags=_TAG,
    ),
)
