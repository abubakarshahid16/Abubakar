"""#1619 (PR #1635): a minus directly after a letter joins a tag or grade; it is not a sign
(numparse.py; danger zone). Ids M1635-01.. (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_1619_tag_minus.py"
_TAG = ("pr1635", "numbers", "honesty")
_NUM = APP / "numparse.py"
_R3B = APP / "requirements_3b.py"
_OWN = APP / "own_value_limit.py"
_PARSE = '    if m.group("num").startswith("-") and prefix and prefix[-1] not in _SIGN_LEAD:\n'
_MAY = '    return not lead or lead.isspace() or (lead in _SIGN_LEAD and lead != ",")\n'
_FIRST = "        if direction is not None and raw_unit:\n"
_RANGE = "    if limit is None and own_value_limit.trailing_refused(sentence):\n"
_CROSS = "        return own_value_limit.trailing_refused(text)\n"

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
        id="M1635-14",
        phase=1635,
        description="a value may start anywhere",
        path=_NUM,
        anchor=_MAY,
        replacement="    return True\n",
        target=_T,
        keyword="joined_number_gives_no",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-15",
        phase=1635,
        description="a value may start after a comma",
        path=_NUM,
        anchor=_MAY,
        replacement="    return not lead or lead.isspace() or lead in _SIGN_LEAD\n",
        target=_T,
        keyword="joined_number_gives_no",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-16",
        phase=1635,
        description="a value starts only after whitespace",
        path=_NUM,
        anchor=_MAY,
        replacement="    return not lead or lead.isspace()\n",
        target=_T,
        keyword="real_limits_keep",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-17",
        phase=1635,
        description="a refused first value moves on to a later one",
        path=_OWN,
        anchor=_FIRST,
        replacement="        if direction is not None and raw_unit and numparse.value_may_start(sentence, match.start()):\n",
        target=_T,
        keyword="two_limits",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-18",
        phase=1635,
        description="a candidate with no direction refuses the sentence",
        path=_OWN,
        anchor=_FIRST,
        replacement="        if True:\n",
        target=_T,
        keyword="no_direction",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-19",
        phase=1635,
        description="a range or nominal is read past a refused limit",
        path=_R3B,
        anchor=_RANGE,
        replacement="    if False:\n",
        target=_T,
        keyword="two_limits",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-20",
        phase=1635,
        description="a refused limit becomes a field comparison",
        path=_R3B,
        anchor=_CROSS,
        replacement="        return False\n",
        target=_T,
        keyword="no_field_comparison",
        tags=_TAG,
    ),
)
