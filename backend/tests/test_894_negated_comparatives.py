"""#894 (PF2): "shall not be higher than X" is a ceiling, not a floor.

PF1's first run (#881): the invented clause "The minimum design metal
temperature shall not be higher than -10 °C" was stored as `> -10`, and a
sheet stating -20 °C was called "does not meet". The reader absorbed the
negation of less / more / greater only; "higher than" matched bare.

A REVERSED LIMIT IS THE WORST READING: a wrong Fail for a good value and a
false Meets for a bad one, each with a citation. On a copy of the library
(13 Oct 2026, counts only) 38 stored limits in 23 standards were reversed
this way. Invented sentences only.
"""
from __future__ import annotations

import pytest

from app import requirements_3b as r


def _operator(sentence: str):
    limit = r.parse_limit(sentence)
    return limit and (limit["operator"], limit["raw_value"])


@pytest.mark.parametrize("sentence, expected", [
    # the planted case of PF1
    ("The minimum design metal temperature shall not be higher than -10 °C.", ("<=", "-10")),
    # every comparative adjective the reader knows, negated
    ("The gap shall not be larger than 5 mm.", ("<=", "5")),
    ("The plate shall not be thicker than 5 mm.", ("<=", "5")),
    ("The run shall not be longer than 5 m.", ("<=", "5")),
    ("The slot shall not be wider than 5 mm.", ("<=", "5")),
    ("The level shall not be lower than 5 mm.", (">=", "5")),
    ("The bore shall not be smaller than 5 mm.", (">=", "5")),
    ("The wall shall not be thinner than 5 mm.", (">=", "5")),
    ("The spool shall not be shorter than 5 m.", (">=", "5")),
    ("The walkway shall not be narrower than 5 mm.", (">=", "5")),
    ("Supports shall not be closer than 5 m.", (">=", "5")),
    # the same with "no", "never", another modal, and no "be"
    ("The setting shall be no higher than 5 bar.", ("<=", "5")),
    ("The setting shall never be higher than 5 bar.", ("<=", "5")),
    ("The level must not be lower than 5 mm.", (">=", "5")),
    ("Supports are placed not closer than 5 m.", (">=", "5")),
    # above / below / over / under / beneath, negated
    ("The temperature shall not be above 5 °C.", ("<=", "5")),
    ("The temperature shall not be over 5 °C.", ("<=", "5")),
    ("The level shall not be below 5 mm.", (">=", "5")),
    ("The level shall not be under 5 mm.", (">=", "5")),
    ("The level shall not be beneath 5 mm.", (">=", "5")),
    # a word or two between the negation and the comparative
    ("The valve shall not be set higher than 5 bar.", ("<=", "5")),
    ("The level shall not fall below 5 mm.", (">=", "5")),
    ("The pressure shall not rise above 5 bar.", ("<=", "5")),
])
def test_a_negated_comparative_is_stored_the_way_the_sentence_means(sentence, expected):
    assert _operator(sentence) == expected


@pytest.mark.parametrize("sentence, expected", [
    ("The wall shall be thicker than 5 mm.", (">", "5")),
    ("The temperature shall be below 5 °C.", ("<", "5")),
    ("The temperature shall be above 5 °C.", (">", "5")),
    ("The level shall be higher than 5 mm.", (">", "5")),
    ("The gap shall be smaller than 5 mm.", ("<", "5")),
    # a "not" that belongs to something else, behind a comma
    ("The wall, not the lining, shall be thicker than 5 mm.", (">", "5")),
    # the negations the reader already knew
    ("The level shall not exceed 5 mm.", ("<=", "5")),
    ("The level shall not be less than 5 mm.", (">=", "5")),
    ("The level shall not be more than 5 mm.", ("<=", "5")),
    ("The level shall not be greater than 5 mm.", ("<=", "5")),
    ("In no case shall it be less than 5 mm.", (">=", "5")),
    ("The noise shall not be in excess of 85 dB(A).", ("<=", "85")),
    ("The thickness shall be at least 5 mm.", (">=", "5")),
])
def test_a_bare_comparative_and_the_known_negations_are_read_as_before(sentence, expected):
    assert _operator(sentence) == expected


def test_the_two_directions_never_meet():
    """The property behind every case above: negating a comparative turns
    the limit round and lets the limit value itself pass."""
    for word in r._LARGER_THAN + r._ABOVE:
        tail = f"{word} than" if word in r._LARGER_THAN else word
        assert _operator(f"The value shall be {tail} 5 mm.")[0] == ">"
        assert _operator(f"The value shall not be {tail} 5 mm.")[0] == "<="
    for word in r._SMALLER_THAN + r._BELOW:
        tail = f"{word} than" if word in r._SMALLER_THAN else word
        assert _operator(f"The value shall be {tail} 5 mm.")[0] == "<"
        assert _operator(f"The value shall not be {tail} 5 mm.")[0] == ">="
