"""A full stop that belongs to an abbreviation is not a sentence end (seen on
the owner's screen 2026-10-01/02: a quote cut at "P-No." and the next line
starting "1 materials is not permitted").

Synthetic text only.
"""
from __future__ import annotations

import pytest

from app import answer, chat_stream, claims

TEXT = ("Code exemptions for post weld heat treatment of P-No. 4 and P-No. 5 "
        "materials are not permitted. Localized treatment per para. 7.1 is "
        "not permitted. See Fig. 3 and approx. 5 mm, e.g. the rest.")

WHOLE = [
    "Code exemptions for post weld heat treatment of P-No. 4 and P-No. 5 "
    "materials are not permitted.",
    "Localized treatment per para. 7.1 is not permitted.",
    "See Fig. 3 and approx. 5 mm, e.g. the rest.",
]

SPLITTERS = {
    "answer_sentence": lambda t: answer._SENTENCE.split(t),
    "answer_segment": lambda t: answer._SEGMENT.split(t),
    "claims": claims.split_sentences,
    "stream": lambda t: [p for p in chat_stream._BOUNDARY.split(t) if p],
}


@pytest.mark.parametrize("name", sorted(SPLITTERS))
def test_an_abbreviation_full_stop_does_not_cut_a_sentence(name):
    """THE MUTATION TARGET: no splitter may cut at "P-No." or "para."."""
    assert [p.strip() for p in SPLITTERS[name](TEXT)] == WHOLE


@pytest.mark.parametrize("name", sorted(SPLITTERS))
def test_a_real_sentence_end_still_splits(name):
    parts = [p.strip() for p in SPLITTERS[name]("PWHT is required. The record is kept. Done.")]
    assert parts == ["PWHT is required.", "The record is kept.", "Done."]
