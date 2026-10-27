"""#618: the text-quality gate judges words against a real dictionary.

`requirement_quality.text_quality` used to judge words against a list of about 300. Now a word
counts as English when that list OR the committed dictionary (`market_phrase.vouched_for`) knows
it: a technical word the short list lacks no longer counts against a sentence, noise that keeps its
vowels is caught (most words in no dictionary), and a reversed THREE-letter word proves nothing
("net"/"ten", "ton"/"not"). Flagged text is still kept, shown with its reason and kept out of
reviews: this changes only what is flagged. Invented sentences only.
"""

from __future__ import annotations

import pytest

from app import requirement_quality as rq

TECHNICAL = [
    "The relief valve shall be sized for the maximum credible overpressure scenario at the relieving temperature.",
    "Compressor discharge pipework shall be pressure tested in accordance with the applicable piping code before commissioning.",
    "Stainless steel impellers shall be supplied with certified mill test reports traceable to the heat number.",
    "All flanges shall conform to ASME B16.5 class 300 raised face unless otherwise stated by the purchaser.",
    "The mechanical seal shall be a cartridge type with a dual pressurised barrier fluid system per API Plan 53B.",
    "Bearing housings shall have constant level oilers and shall be provided with vibration probe connections.",
    "Nozzle loads shall not exceed twice the allowable values given in the table for casing materials.",
    "The vendor shall submit hydrostatic test certificates, NDE procedures and welding procedure qualification records.",
]


@pytest.mark.parametrize("text", TECHNICAL)
def test_ordinary_technical_sentences_are_not_flagged(text):
    assert rq.text_quality(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "ecnalpmoc eht ot gnidrocca dellatsni eb llahs tnemerrub eulav efilel",  # reversed
        "kelmop baranit divosk tarelun vishop ganeru bolika lemtos arpine donuva",  # noise with vowels
        "zxcv qwrt plkj mnbv hgfd sdfg rtyu bnmk",  # no vowels
    ],
)
def test_reversed_and_noise_text_is_flagged(text):
    assert rq.text_quality(text) == rq.TEXT_QUALITY


def test_noise_that_keeps_its_vowels_is_caught_by_the_dictionary_not_the_short_list():
    noise = "kelmop baranit divosk tarelun vishop ganeru bolika lemtos arpine donuva"
    assert not rq._is_word("kelmop") and rq._is_word("compressor")
    assert rq.text_quality(noise) == rq.TEXT_QUALITY


def test_a_word_the_short_list_lacks_counts_as_english_through_the_dictionary():
    assert "impellers" not in rq._COMMON and rq._is_word("impellers")
    assert "pressurised" not in rq._COMMON and rq._is_word(
        "pressurised"
    )  # British spelling


def test_three_letter_words_that_read_as_words_both_ways_do_not_prove_reversed_text():
    """net/ten, ton/not, era/are are all words: this is English, not a mirrored scan."""
    assert rq.text_quality("Net ton era net ton era net ton era") is None


def test_a_short_line_is_never_judged_by_its_words():
    assert rq.text_quality("kelmop baranit divosk") is None
    assert rq.text_quality("10 % or less overpressure") is None


def test_the_unknown_share_has_a_line_and_it_is_not_crossed_by_technical_wording():
    # 8 words, 5 in no dictionary (62%): flagged; 4 of 8 (50%): not
    five = "zorbat kelmop shall lemtos arpine donuva be fitted"
    four = "zorbat kelmop shall lemtos arpine be fitted on"
    assert rq.text_quality(five) == rq.TEXT_QUALITY
    assert rq.text_quality(four) is None
