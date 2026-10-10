"""#618: the text-quality gate judges words against a real word list.

Before, `requirement_quality.text_quality` knew about 300 common words, so OCR
garbling that keeps its vowels ("Tbe vaive sball be tesled") passed. Now the
words are checked against the committed SCOWL list (the one `market_phrase`
already uses, British spellings included). Fewer than 60% known words in a
sentence long enough to judge flags it. Acronyms and unknown capitalised names
("Inconel") are neutral. Flagged text is kept and shown with its reason, as
before. INVENTED sentences only.

Mutations: M6401-M6405 (scripts/mutations/w2b_618_word_list.py).
"""
from __future__ import annotations

import pytest

from app import requirement_quality as rq

GARBLED = [
    "Tbe vaive sball be tesled at tbe set presure before shipment.",
    "Al1 weIds sbaII be radiograpbed and tbe fiIms retaimed by tbe vemdor.",
    "Tbe corrosiom aIIowance sbaII mot be Iess tban tbree miIIimetres.",
]
ENGINEERING = [
    "The relief valve shall be tested at the set pressure before shipment.",
    "Inconel Hastelloy Monel Stellite Superduplex weld overlay shall be applied to the seat.",
    "The UNS N06625 alloy shall have a maximum carbon content of 0.10 percent.",
    "Galvanised coatings shall be inspected for colour and uniformity on site.",
    "Bolting shall be ASTM A193 Gr B7 with A194 Gr 2H nuts and PTFE coated studs.",
    "Flange faces shall be RF with 125-250 AARH finish per ASME B16.5 unless noted.",
    "Hydrotest at 1.5 times MAWP with potable water, chloride under 50 ppm.",
    "10 % or less overpressure",
]


@pytest.mark.parametrize("text", GARBLED)
def test_garbled_text_that_keeps_its_vowels_is_flagged(text):
    """THE MUTATION TARGET: the short built-in list let these through."""
    assert rq.text_quality(text) == rq.TEXT_QUALITY


@pytest.mark.parametrize("text", ENGINEERING)
def test_ordinary_engineering_text_is_not_flagged(text):
    assert rq.text_quality(text) is None


def test_the_word_list_is_the_committed_dictionary_not_the_short_list():
    # Words the old ~300-word list never held, all ordinary English.
    for word in ("hydrostatic", "gasket", "nozzle", "flanges", "galvanised"):
        assert word not in rq._COMMON
        assert rq._known(word), word
    for nonsense in ("vaive", "sball", "tesled"):
        assert not rq._known(nonsense), nonsense


def test_a_run_of_trade_names_is_neutral_not_garbled():
    text = "Inconel Hastelloy Monel Stellite Superduplex Incoloy Sanicro Zeron"
    assert rq.text_quality(text) is None


def test_the_first_word_is_judged_even_when_capitalised():
    # Five of the eight other words are known (62.5%, above the bar); counting
    # the unknown capitalised first word makes it five of nine (56%).
    assert rq.text_quality("Tbe valve sball be tested at tbe set presure") == rq.TEXT_QUALITY


def test_exactly_half_known_is_below_the_bar():
    # Lower-case first word, five of ten known: 50% is not enough (bar 60%).
    assert rq.text_quality("the vaive sball be tesled at tbe set presure before") == rq.TEXT_QUALITY
