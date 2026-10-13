"""#921 (PF2): a cell that points elsewhere ("see note 3", "refer to drawing",
"as per datasheet", "N/A") or says nothing ("TBD", "by vendor") is not a stated
value: it may not make a "state it" clause or a "one of these values" clause
COMPLIANT. Invented data only."""
from __future__ import annotations

import pytest

from app import comparison, field_links
from tests.test_893_named_values import BODY, STATED, _judge, _fact, fresh  # noqa: F401 - autouse

POINTERS = ["See note 3", "refer to drawing 12", "As per datasheet", "N/A", "Not applicable", "to follow",
            "By others", "Various", "TBD", "By vendor", "-"]


@pytest.mark.parametrize("value", POINTERS)
def test_a_pointer_does_not_satisfy_a_state_it_clause(value):
    _match, verdict = _judge(STATED, "impeller material", [_fact("impeller material", value)])
    assert verdict["status"] != comparison.COMPLIANT, verdict


@pytest.mark.parametrize("value", ["See note 3", "As per datasheet", "N/A", "Various"])
def test_a_pointer_does_not_satisfy_a_named_values_clause(value):
    _match, verdict = _judge(BODY, "body material", [_fact("body material", value)])
    assert verdict["status"] != comparison.COMPLIANT, verdict


@pytest.mark.parametrize("value", ["Stainless steel 316", "Natural rubber", "Performance grade A", "Nitrile"])
def test_a_real_value_is_still_a_value(value):
    assert field_links.states_a_value(value)
    _match, verdict = _judge(STATED, "impeller material", [_fact("impeller material", value)])
    assert verdict["status"] == comparison.COMPLIANT and verdict["rationale"].startswith(comparison.STATED_AS_ASKED)
