"""#1619 (PR #1635): a minus directly after a letter joins a tag or grade; it is not a sign
(numparse.py; danger zone). Ids M1635-01.. (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_1619_tag_minus.py"
_TAG = ("pr1635", "numbers", "honesty")
_NUM = APP / "numparse.py"
_R3B = APP / "requirements_3b.py"
_PARSE = '    if m.group("num").startswith("-") and prefix and prefix[-1] not in _SIGN_LEAD:\n'
_LEAD = r"""(?<![^\s<>=:;~(\[{≤≥])(?P<value>"""

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1635-07",
        phase=1635,
        description="parse_value reads a joining hyphen as a minus",
        path=_NUM,
        anchor=_PARSE,
        replacement="    if False:\n",
        target=_T,
        keyword="no_sign_outside",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-08",
        phase=1635,
        description="parse_value refuses every minus not at the start",
        path=_NUM,
        anchor=_PARSE,
        replacement='    if m.group("num").startswith("-") and prefix:\n',
        target=_T,
        keyword="real_negative_stays",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-09",
        phase=1635,
        description="a trailing limit may start anywhere",
        path=_R3B,
        anchor=_LEAD,
        replacement="(?P<value>",
        target=_T,
        keyword="joined_number_gives_no",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-10",
        phase=1635,
        description="a trailing limit may start after a hyphen",
        path=_R3B,
        anchor=_LEAD,
        replacement=r"""(?<![^\s<>=:;~(\[{≤≥-])(?P<value>""",
        target=_T,
        keyword="joined_number_gives_no",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-11",
        phase=1635,
        description="a trailing limit may start after a comma",
        path=_R3B,
        anchor=_LEAD,
        replacement=r"""(?<![^\s<>=:;,~(\[{≤≥])(?P<value>""",
        target=_T,
        keyword="joined_number_gives_no",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-12",
        phase=1635,
        description="a trailing limit starts only after whitespace",
        path=_R3B,
        anchor=_LEAD,
        replacement=r"""(?<!\S)(?P<value>""",
        target=_T,
        keyword="real_limits_keep",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-13",
        phase=1635,
        description="a joined number decides a verdict",
        path=_R3B,
        anchor=_LEAD,
        replacement="(?P<value>",
        target=_T,
        keyword="joined_number_goes_to_review",
        tags=_TAG,
    ),
)
