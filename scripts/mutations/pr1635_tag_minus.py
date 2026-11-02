"""#1619 (PR #1635): a minus directly after a letter joins a tag or grade; it is not a sign
(numparse.py; danger zone). Ids M1635-01.. (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_1619_tag_minus.py"
_TAG = ("pr1635", "numbers", "honesty")
_NUM = APP / "numparse.py"
_R3B = APP / "requirements_3b.py"
_OWN = APP / "own_value_limit.py"
_SIGN = APP / "impossible_sign.py"
_JOINED = "    return prefix[-1] not in _SIGN_LEAD\n"
_MAY = '    return not lead or lead.isspace() or (lead in _SIGN_LEAD and lead != ",")\n'
_FIRST = "        if direction is not None and raw_unit:\n"
_RANGE = "    if limit is None and own_value_limit.trailing_refused(sentence):\n"
_CROSS = "        return own_value_limit.trailing_refused(text)\n"
_GENERAL = "    if own_value_limit.trailing_refused(sentence):\n"
_APPEND = "        starts.append(fraction.start if fraction else match.start())\n"
_SLASH = '    if sentence[match.start() - 1 : match.start()] not in ("/", "\\u2044"):\n'
_PROPER = '        if fraction.end == match.end("value") and int(top) < int(bottom):\n'
_HELD = "        if not (is_negative(fact) or _glued_number(fact)):\n"
_LIBRARY = '    if verdict.get("status") != _PASS or not (is_negative(fact) or _glued_number(fact)):\n'
_DOUBT = "    if not _glued_number(fact):\n        return None\n    from .datasheet_checks import _label, _said\n"

MUTATIONS: tuple[Mutation, ...] = (
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
    Mutation(
        id="M1635-21",
        phase=1635,
        description="a general limit is read past an unreadable exception",
        path=_R3B,
        anchor=_GENERAL,
        replacement="    if False:\n",
        target=_T,
        keyword="unreadable_exception",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-23",
        phase=1635,
        description="parse_value reads a joining hyphen as a minus",
        path=_NUM,
        anchor=_JOINED,
        replacement="    return False\n",
        target=_T,
        keyword="no_sign_outside",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-24",
        phase=1635,
        description="parse_value refuses every minus not at the start",
        path=_NUM,
        anchor=_JOINED,
        replacement="    return True\n",
        target=_T,
        keyword="real_negative_stays",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-25",
        phase=1635,
        description="a fraction start is not checked, so a glued one is read",
        path=_OWN,
        anchor=_APPEND,
        replacement="        starts.append(0 if fraction else match.start())\n",
        target=_T,
        keyword="glued_fraction",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-26",
        phase=1635,
        description="a plain fraction is refused",
        path=_OWN,
        anchor=_SLASH,
        replacement="    if True:\n",
        target=_T,
        keyword="plain_fraction_is_read",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-27",
        phase=1635,
        description="an improper fraction is read as a size",
        path=_OWN,
        anchor=_PROPER,
        replacement='        if fraction.end == match.end("value"):\n',
        target=_T,
        keyword="improper_fraction",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-28",
        phase=1635,
        description="a glued number passes a required item",
        path=_SIGN,
        anchor=_HELD,
        replacement="        if not is_negative(fact):\n",
        target=_T,
        keyword="glued_number_required",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-29",
        phase=1635,
        description="a glued number passes a library rule",
        path=_SIGN,
        anchor=_LIBRARY,
        replacement='    if verdict.get("status") != _PASS or not is_negative(fact):\n',
        target=_T,
        keyword="glued_number_is_held",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-30",
        phase=1635,
        description="a glued number is not implausible",
        path=_SIGN,
        anchor=_DOUBT,
        replacement="    return None\n    from .datasheet_checks import _label, _said\n",
        target=_T,
        keyword="implausible_flags",
        tags=_TAG,
    ),
    Mutation(
        id="M1635-31",
        phase=1635,
        description="any later limit no longer refuses a sentence",
        path=_OWN,
        anchor=_APPEND,
        replacement="        starts.append(fraction.start if fraction else match.start())\n        break\n",
        target=_T,
        keyword="later_unreadable",
        tags=_TAG,
    ),
)
