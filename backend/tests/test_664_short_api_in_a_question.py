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


@pytest.mark.parametrize("typed", ["the pump runs at 65 psi", "API gravity 65 at 15 C"])
def test_a_quantity_is_still_not_a_standard_in_a_question(typed):
    assert labels(typed, typed_question=True) == []


def test_document_text_keeps_the_old_rule():
    """Datasheets and the inventory call the default: a short API number in
    running text stays unread (the rule that keeps quantities out)."""
    assert labels("compare API 65 and API 650") == ["API 650"]


def test_api_65_is_never_the_held_api_650():
    assert not standard_ids.same_standard("API 65", "API 650")


def test_the_chat_comparison_names_both_sides():
    assert chat_comparison.typed_standards("compare API 65 and API 650") == ["API 65", "API 650"]
