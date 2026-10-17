"""#664: a short plain-text API number TYPED in a chat question ("compare API 65
and API 650") is read as a standard; in document text it still is not.

The shared reader's long-standing rule (API needs 3-4 digits, or 1-2 with a
letter suffix) exists because in running document text a short number is
usually a quantity. A typed comparison question names standards on purpose,
so `chat_comparison` asks for the typed reading; datasheets and the standards
inventory keep the default, so no review verdict can change.
"""
from __future__ import annotations

import pytest

from app import chat_comparison, standard_ids


def labels(text: str, **kw) -> list[str]:
    return [label for label, _, _ in standard_ids.find_citations(text, **kw)]


@pytest.mark.parametrize("typed, expected", [
    ("compare API 65 and API 650", ["API 65", "API 650"]),
    ("compare API RP 65 with API 650", ["API RP 65", "API 650"]),
    ("compare api 65 and api 650", ["api 65", "api 650"]),
    ("compare API-65 and API 650", ["API-65", "API 650"]),
])
def test_a_typed_question_reads_a_short_api_number(typed, expected):
    assert labels(typed, typed_question=True) == expected


@pytest.mark.parametrize("typed, expected", [
    ("compare API 65 psi with API 650", ["API 650"]),      # a unit follows: a quantity
    ("oil of API 35 crude vs API 650 tank", ["API 650"]),  # API gravity of a crude
    ("is API 35 gravity in API 650", ["API 650"]),
    ("compare API 0 and API 650", ["API 650"]),            # never a standard number
    ("compare API 00 and API 650", ["API 650"]),
])
def test_a_short_api_quantity_is_not_a_standard_in_a_question(typed, expected):
    """cloud-2's review cases: each FITS the API shape, so the flag is what
    decides - a short number followed by a unit or API-gravity words is a
    quantity, and 0 / 00 are never standards."""
    assert labels(typed, typed_question=True) == expected


def test_a_long_api_number_before_a_unit_keeps_the_normal_rule():
    assert labels("compare API 650 m3 tanks", typed_question=True) == ["API 650"]


def test_document_text_keeps_the_old_rule():
    """Datasheets and the inventory call the default: a short API number in
    running text stays unread (the rule that keeps quantities out)."""
    assert labels("compare API 65 and API 650") == ["API 650"]


def test_api_65_is_never_the_held_api_650():
    assert not standard_ids.same_standard("API 65", "API 650")


def test_the_chat_comparison_names_both_sides():
    assert chat_comparison.typed_standards("compare API 65 and API 650") == ["API 65", "API 650"]
