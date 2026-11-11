# -*- coding: utf-8 -*-
"""#947: `verify_proposal` refused a correct temperature limit ("shall not
exceed 60 C" -> "model value disagreed"): `read_figures` lower-cases a unit and
`_hints_agree` wrote it out and read it again, where a lone lower-case letter is
a word, so "60 c" had no unit. Pressure units passed by luck. Invented
sentences only."""
from __future__ import annotations

import pytest

from app import ai_requirements as ar

DEG = "°"


def _proposal(sentence, value, unit):
    return {"has_limit": True, "field": "temperature", "operator": "<=", "value": value, "unit": unit,
            "quote": sentence.rstrip("."), "condition": None}


@pytest.mark.parametrize("sentence, value, unit", [
    ("The temperature shall not exceed 60 C.", "60", "C"),
    ("The temperature shall not exceed 60 " + DEG + "C.", "60", DEG + "C"),
    ("The temperature shall not exceed 140 F.", "140", "F"),
    ("The temperature shall not exceed 140 " + DEG + "F.", "140", DEG + "F"),
    ("The temperature shall not exceed 60 degC.", "60", "degC"),
    ("The pressure shall not exceed 60 bar.", "60", "bar"),
    ("The thickness shall not exceed 2.5 mm.", "2.5", "mm"),
])
def test_a_correct_proposal_is_accepted_whatever_the_unit(sentence, value, unit):
    check, why = ar.verify_proposal(_proposal(sentence, value, unit), sentence)
    assert why is None and check["value"] == value, why


@pytest.mark.parametrize("sentence, value, unit", [
    ("The temperature shall not exceed 60 C.", "65", "C"),              # another number
    ("The temperature shall not exceed 60 C.", "60", "F"),              # another unit
    ("The temperature shall not exceed 140 F.", "60", "C"),
])
def test_a_wrong_proposal_is_still_refused(sentence, value, unit):
    check, why = ar.verify_proposal(_proposal(sentence, value, unit), sentence)
    assert check is None and why in (ar.MODEL_VALUE_DISAGREED, ar.VALUE_NOT_IN_QUOTE, ar.UNIT_NOT_IN_QUOTE), why
