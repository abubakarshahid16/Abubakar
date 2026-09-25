"""Mutations of `backend/app/vision_reader.py` (#193 plan B4 item 1)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = 'tests/test_vision_reader.py'

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id='M630', phase=64,
        description='B4 vision: a value beside its label is never proved (reader keeps nothing)',
        path=APP / 'vision_reader.py',
        anchor='                    proof, value_box, label_box = "text layer, beside its label", vb, lb\n',
        replacement='                    pass\n',
        target=_T, keyword='beside_its_label_is_kept',
        tags=('honesty',),
    ),
    Mutation(
        id='M631', phase=64,
        description='B4 vision: an unproved value is kept anyway (the model\'s word stored)',
        path=APP / 'vision_reader.py',
        anchor=('    if proof is None:\n'
                '        return None, (VALUE_NOT_BESIDE_LABEL if quote_verified(value, text.text)\n'),
        replacement=('    if False:\n'
                     '        return None, (VALUE_NOT_BESIDE_LABEL if quote_verified(value, text.text)\n'),
        target=_T, keyword='not_on_the_page_is_dropped or elsewhere_is_not_beside',
        tags=('honesty', 'critical'),
    ),
    Mutation(
        id='M632', phase=64,
        description='B4 vision: a label that is not on the page is accepted',
        path=APP / 'vision_reader.py',
        anchor='    if not parts or not all(boxes.values()):\n',
        replacement='    if not parts:\n',
        target=_T, keyword='label_that_is_not_on_the_page',
        tags=('honesty', 'critical'),
    ),
    Mutation(
        id='M633', phase=64,
        description='B4 vision: any occurrence of the value counts as beside its label',
        path=APP / 'vision_reader.py',
        anchor=('    if same_line(label, value):\n'
                '        return value[0] >= label[0] and value[0] - label[2] <= 0.5 * page_width\n'),
        replacement='    return True\n',
        target=_T, keyword='elsewhere_is_not_beside',
        tags=('honesty', 'critical'),
    ),
    Mutation(
        id='M634', phase=64,
        description='B4 vision: a number is found inside another number ("2" in "250")',
        path=APP / 'vision_reader.py',
        anchor='    return word == token or word.strip(_WRAP) == token or (\n',
        replacement='    return token in word or (\n',
        target=_T, keyword='never_found_inside_another',
        tags=('honesty',),
    ),
    Mutation(
        id='M635', phase=64,
        description='B4 vision: an unproved unit no longer drops the reading',
        path=APP / 'vision_reader.py',
        anchor='        if not ok and not condition_cut:\n            return None, UNIT_NOT_PROVEN\n',
        replacement='        if False:\n            return None, UNIT_NOT_PROVEN\n',
        target=_T, keyword='unit_must_be_the_values',
        tags=('honesty', 'critical'),
    ),
    Mutation(
        id='M636', phase=64,
        description='B4 vision: the text layer\'s O-for-degree spelling is not tried',
        path=APP / 'vision_reader.py',
        anchor='        out += [unit.replace("°", glyph) for glyph in _DEGREE_SPELLINGS]\n',
        replacement='        pass\n',
        target=_T, keyword='degree_sign',
    ),
    Mutation(
        id='M637', phase=64,
        description='B4 vision: a condition after the value is kept as the value',
        path=APP / 'vision_reader.py',
        anchor='        value = value.split("@", 1)[0].strip()\n',
        replacement='        pass\n',
        target=_T, keyword='condition_is_cut or reduce_rules',
        tags=('honesty',),
    ),
    Mutation(
        id='M638', phase=64,
        description='B4 vision: a blank is recorded from an image',
        path=APP / 'vision_reader.py',
        anchor='    if _BLANKISH.match(value):\n        return None, BLANK\n',
        replacement='    if False:\n        return None, BLANK\n',
        target=_T, keyword='blank_is_never_recorded',
        tags=('honesty', 'critical'),
    ),
    Mutation(
        id='M639', phase=64,
        description='B4 vision: a duplicate proposal is kept twice',
        path=APP / 'vision_reader.py',
        anchor='        if key in seen:\n            reading.drop("duplicate")\n            continue\n',
        replacement='',
        target=_T, keyword='keeps_only_what_the_page_proves',
    ),
)
