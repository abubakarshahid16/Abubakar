"""#1619 (PR #1635): a minus directly after a letter joins a tag or grade; it is not a sign
(numparse.py; danger zone). Ids M1635-01.. (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_1619_tag_minus.py"
_TAG = ("pr1635", "numbers", "honesty")
_NUM = APP / "numparse.py"
_PARSE = '    if m.group("num").startswith("-") and prefix[-1:].isalpha():\n'
_SIGN = '        if lead and (lead.isdigit() or lead.isalpha() or lead in ")]"):\n'

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
        id="M1635-03",
        phase=1635,
        description="find_numbers reads U+2212 after a letter as a minus again",
        path=_NUM,
        anchor=_SIGN,
        replacement='        if lead and (lead.isdigit() or lead in ")]"):\n',
        target=_T,
        keyword="find_numbers_reads_no_sign",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-04",
        phase=1635,
        description="find_numbers drops the minus of a real negative after a comparator",
        path=_NUM,
        anchor=_SIGN,
        replacement="        if lead and not lead.isspace():\n",
        target=_T,
        keyword="keeps_the_other_readings",
        tags=_TAG,
    ),
)
