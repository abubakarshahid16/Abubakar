"""G2 (lead-4, 26 Nov 2026; audit of the 9 live reviews): a Question that asks to confirm, or raises a concern about, a value the
paper is said to state must show that value as a code-verified quote. With no verified quote at ANY of its places the claim is
unproven: the comment is open ("Missing information") and its ask starts with `VALUE_NOT_SHOWN`; it is never shown as if the
paper stated it. A comment with one verified place keeps its card. Invented values only."""

from __future__ import annotations

import re

import pytest

from app import aim_review_card as card_mod
from app import aim_review_contractor, aim_review_view


def _q(
    ask: str,
    quote: str = "",
    unverified: bool = False,
    field: str = "Design temperature",
) -> dict:
    return {
        "n": 1, "label": "Question", "shown_label": "Question", "ask": ask, "quote": quote, "quote_unverified": unverified,
        "field": field, "comment": "Confirm the invented value.", "code_note": "", "topic": "invented topic", "page": 3,
        "standard": "STD-X", "clause": "4.1", "source": "held standard",
    }  # fmt: skip


@pytest.mark.parametrize(
    "members, unshown",
    [
        ([_q("confirm")], True),  # no quote at all
        (
            [_q("concern", "Design temperature 150 C", unverified=True)],
            True,
        ),  # a quote code could not find
        (
            [_q("confirm", "Design temperature")],
            True,
        ),  # only the field's own label: no value
        ([_q("confirm", "Design temperature 150 C")], False),  # a verified value
        (
            [_q("concern", "Design temperature 150 C"), _q("concern", unverified=True)],
            False,
        ),  # one place verified
        ([_q("open")], False),  # already open: nothing claimed
    ],
)
def test_a_value_is_unshown_only_when_no_place_has_a_verified_quote(members, unshown):
    assert card_mod.value_not_shown(members) is unshown


def test_the_card_of_an_unshown_value_is_missing_information_and_says_so():
    members = [_q("confirm")]
    got = card_mod.card({"n": 1}, members)
    assert got["severity"] == card_mod.MISSING
    assert got["we_ask"].startswith(card_mod.VALUE_NOT_SHOWN)
    assert got["we_ask"].endswith(
        "Confirm the invented value."
    )  # the engineer still reads the AI's words after it


def test_a_verified_value_keeps_its_card_unchanged():
    members = [_q("concern", "Design temperature 150 C")]
    got = card_mod.card({"n": 1}, members)
    assert (
        got["severity"] == card_mod.CHECK
        and got["we_ask"] == "Confirm the invented value."
    )


def test_the_comment_asks_open_when_its_value_is_unshown():
    assert card_mod.card({"n": 1}, [_q("concern")])["ask"] == "open"
    assert "ask" not in card_mod.card(
        {"n": 1}, [_q("concern", "Design temperature 150 C")]
    )  # its own ask stands


def test_the_new_sentence_carries_no_internal_words_for_the_contractor_copy():
    for pattern, _what in aim_review_contractor.INTERNAL:
        assert not re.search(pattern, card_mod.VALUE_NOT_SHOWN)
