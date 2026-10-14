"""#915 (PF2): ONE vocabulary of limit-direction words.

`reader_api` kept its own ceiling / floor lists. They lacked "less than",
"greater than", "more than", "below", "above", "under", "over", "up to",
"or less", "or more" and the symbols; a quote worded that way had NO
direction and rule 4 (a model's operator against the sentence) never fired,
so a parsed limit with the wrong operator was accepted once two runs agreed
with each other. The direction words now live in `comparators`, built on the
words `claims` already has; a drift test keeps `claims` and
`requirements_3b` from disagreeing with it.

Invented sentences only; no model, no socket.
"""
from __future__ import annotations

import pytest

from app import claims, comparators, reader_api, requirements_3b

CEILING_SENTENCES = [
    "The level shall not exceed 5 mm.", "The level shall be less than 5 mm.", "The level shall be below 5 mm.",
    "The level shall be under 5 mm.", "The level shall be at most 5 mm.", "The level shall be up to 5 mm.",
    "The level shall be 5 mm or less.", "The level shall be 5 mm or fewer.", "The level shall be 5 mm or lower.",
    "The level shall be no more than 5 mm.", "The level shall be not more than 5 mm.", "The level shall be not greater than 5 mm.",
    "The level shall not be higher than 5 mm.", "The level shall not be larger than 5 mm.", "The level shall not rise above 5 mm.",
    "The level shall not be over 5 mm.", "The level shall be not to exceed 5 mm.", "The limit shall not be exceeded: 5 mm.",
    "The level shall be maximum 5 mm.", "The level shall be max. 5 mm.", "The level shall be ≤ 5 mm.",
    "The level shall be <= 5 mm.", "The level shall be < 5 mm.", "In no case shall it be greater than 5 mm.",
    "The level shall not be set higher than 5 mm.", "The level shall be less than or equal to 5 mm.",
]
FLOOR_SENTENCES = [
    "The level shall be at least 5 mm.", "The level shall be greater than 5 mm.", "The level shall be more than 5 mm.",
    "The level shall be above 5 mm.", "The level shall be over 5 mm.", "The level shall be 5 mm or more.",
    "The level shall be 5 mm or greater.", "The level shall be 5 mm or higher.", "The level shall be 5 mm or above.",
    "The level shall be no less than 5 mm.", "The level shall be not less than 5 mm.", "The level shall not be less than 5 mm.",
    "The level shall not be lower than 5 mm.", "The level shall not be smaller than 5 mm.", "The level shall not fall below 5 mm.",
    "The level shall not be under 5 mm.", "The level shall be minimum 5 mm.", "The level shall be min. 5 mm.",
    "The level shall be ≥ 5 mm.", "The level shall be >= 5 mm.", "The level shall be > 5 mm.",
    "In no case shall it be less than 5 mm.", "The level shall be greater than or equal to 5 mm.",
]


@pytest.mark.parametrize("sentence", CEILING_SENTENCES)
def test_every_ceiling_phrase_is_a_ceiling(sentence):
    assert comparators.direction_of(sentence) == comparators.CEILING
    assert reader_api.direction_of_quote(sentence) == "<="


@pytest.mark.parametrize("sentence", FLOOR_SENTENCES)
def test_every_floor_phrase_is_a_floor(sentence):
    assert comparators.direction_of(sentence) == comparators.FLOOR
    assert reader_api.direction_of_quote(sentence) == ">="


@pytest.mark.parametrize("sentence", [
    "The minimum cover shall not exceed 50 mm.",                      # both families
    "The cover shall be at least 5 mm and at most 10 mm.",
    "The level shall be above 5 mm and below 9 mm.",
    "The level shall not be the thing higher than 5 mm.",             # a negation that is not absorbed
    "The level shall be 5 mm.",                                        # no comparator
    "The level shall be between 5 mm and 10 mm.",                      # a range has no single direction
    "Equipment generating noise in excess of 85 dB(A) shall submit Form 7305-ENG.",   # a trigger
    "", None,
])
def test_a_sentence_with_both_families_or_none_has_no_direction(sentence):
    assert comparators.direction_of(sentence) is None


@pytest.mark.parametrize("sentence", [
    "Over time the level rises.", "Under normal conditions the pump runs.", "The pump runs up to speed quickly.",
    "Nominal pressure shall be stated.",
])
def test_a_weak_word_counts_only_in_front_of_a_number(sentence):
    """"over", "under", "up to" are ordinary prose as often as comparators;
    "nominal" contains "min"."""
    assert comparators.direction_of(sentence) is None


def test_a_negation_in_an_earlier_clause_does_not_hold_a_later_one():
    assert comparators.direction_of("The vendor shall not substitute; the level shall be below 5 mm.") == comparators.CEILING


def test_nominal_is_not_a_minimum():
    assert comparators.directions_in("Nominal pressure shall be above 5 bar.") == [comparators.FLOOR]


# --------------------------------------------------- what rule 4 now catches
def _proposal(sentence: str, operator: str) -> dict:
    return {"kind": "limit", "operator": operator, "value": "5", "unit": "mm", "subject": "the level",
            "quote": sentence}


@pytest.mark.parametrize("sentence, wrong, right", [
    ("The level shall be less than 5 mm.", ">=", "<="),
    ("The level shall be below 5 mm.", ">", "<"),
    ("The level shall be up to 5 mm.", ">=", "<="),
    ("The level shall be 5 mm or less.", ">=", "<="),
    ("The level shall be greater than 5 mm.", "<=", ">="),
    ("The level shall be above 5 mm.", "<", ">"),
    ("The level shall be 5 mm or more.", "<=", ">="),
    ("The level shall be \u2264 5 mm.", ">=", "<="),
])
def test_a_proposal_whose_operator_contradicts_the_sentence_is_dropped_whatever_the_words(sentence, wrong, right):
    """THE CASE of #915: before, each of these quotes had no direction, and the
    wrong operator was accepted."""
    dropped = reader_api.accept([_proposal(sentence, wrong)], sentence)
    assert dropped["accepted"] == [] and dropped["counts"] == {reader_api.Reason.OPERATOR_CONTRADICTS_QUOTE.value: 1}
    kept = reader_api.accept([_proposal(sentence, right)], sentence)
    assert len(kept["accepted"]) == 1, kept["rejected"]


# ---------------------------------------------------------------- one vocabulary
@pytest.mark.parametrize("phrase, symbol", [(p, s) for p, s in claims._COMPARATOR_WORDS if s in (">=", ">", "<=", "<")
                                            and p.replace("\\s+", " ").replace("(?:", "").replace(")?", "")
                                            .replace(r"\.?", "") and "(" not in p and "\\" not in p.replace("\\s+", " ")])
def test_every_plain_phrase_of_claims_reads_the_same_here(phrase, symbol):
    expected = comparators.CEILING if symbol in ("<=", "<") else comparators.FLOOR
    assert comparators.direction_of(phrase.replace("\\s+", " ") + " 5") == expected


@pytest.mark.parametrize("sentence", [t for t in CEILING_SENTENCES + FLOOR_SENTENCES
                                      if requirements_3b.parse_limit(t) is not None])
def test_the_stored_operator_of_the_requirement_reader_agrees_with_the_vocabulary(sentence):
    """The two readers of a sentence may never read it in opposite directions."""
    limit = requirements_3b.parse_limit(sentence)
    side = comparators.CEILING if limit["operator"] in ("<=", "<") else comparators.FLOOR
    assert side == comparators.direction_of(sentence), (sentence, limit["operator"])


def test_the_requirement_reader_reads_most_of_the_phrases_so_the_agreement_test_means_something():
    read = [t for t in CEILING_SENTENCES + FLOOR_SENTENCES if requirements_3b.parse_limit(t) is not None]
    assert len(read) >= 25, len(read)
