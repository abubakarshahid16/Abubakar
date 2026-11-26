"""Chat's answer gate lets a passage through when it holds the question's field label word for word (lead-4, 26 Nov 2026, G7 (3);
measured on 10 datasheet field questions before it was built: right 4 -> 7, wrong 2 -> 2, refused 4 -> 1). Without a question,
or with a label of one word, the gate is exactly as before. Invented passages only."""

from __future__ import annotations

import pytest

from app import answer
from app import answer_field_label as F

ROW = "| Set pressure |  | 123 psig (invented) |  | 49 | Adjusting screw |"


@pytest.mark.parametrize(
    "question, label",
    [
        ("What is the set pressure?", "set pressure"),
        ("what's the design temperature of the paper", "design temperature"),
        ("Give me the bonnet / yoke material", "bonnet yoke material"),
        ("What is the viscosity?", None),  # one word: too common to vouch
        ("What is it?", None),
    ],
)
def test_the_field_label_of_a_question(question, label):
    assert F.label_of(question) == label


def test_a_passage_holding_the_label_word_for_word_vouches():
    assert F.vouches({"text": ROW}, "What is the set pressure?")
    assert not F.vouches(
        {"text": ROW}, "What is the pressure set?"
    )  # the question's own order
    assert not F.vouches(
        {"text": ROW}, "What is the relief set pressure?"
    )  # every content word
    assert not F.vouches({"text": ROW}, None)


def test_the_gate_lets_a_low_scored_passage_with_the_label_through():
    hit = {"text": ROW, "rerank_score": answer.MIN_RERANK_SCORE - 2}
    assert not answer._is_semantically_credible(
        hit
    )  # without the question: exactly as before
    assert answer._is_semantically_credible(hit, "What is the set pressure?")
    assert not answer._is_semantically_credible(hit, "What is the design pressure?")


def test_a_high_scored_passage_passes_as_before():
    hit = {"text": "invented prose", "rerank_score": answer.MIN_RERANK_SCORE + 1}
    assert answer._is_semantically_credible(hit) and answer._is_semantically_credible(
        hit, "What is the set pressure?"
    )


NOTE = (
    "Relief capacity of each invented valve shall be calculated by the vendor (Note 4)."
)
VALUE_ROW = "| Relief capacity |  | 1234 kg/h (invented) |  | 44 | Cap type |"


def test_a_value_row_states_the_value_and_a_note_does_not():
    q = "What is the relief capacity?"
    assert F.states_value({"text": VALUE_ROW}, q)
    assert not F.states_value({"text": NOTE}, q)  # 'shall' comes before the only figure
    assert not F.states_value(
        {"text": "| Relief capacity |  |  | By vendor |"}, q
    )  # no figure


def test_a_field_question_quotes_the_row_that_states_the_value_not_a_note():
    q = "What is the relief capacity?"
    hits = [{"text": NOTE}, {"text": "invented prose"}, {"text": VALUE_ROW}]
    assert F.stated_first(q, hits, 0, lambda h: True, 5) == 2
    assert (
        F.stated_first(q, hits, 0, lambda h: False, 5) == 0
    )  # only a lexically plausible passage may take its place
    assert (
        F.stated_first(q, hits, 0, lambda h: True, 2) == 0
    )  # only within the gate's window
    assert (
        F.stated_first(
            "What is the relief capacity?",
            [{"text": VALUE_ROW}, {"text": NOTE}],
            0,
            lambda h: True,
            5,
        )
        == 0
    )
    assert (
        F.stated_first("What is it?", hits, 0, lambda h: True, 5) == 0
    )  # not a field question: the gate's own pick
