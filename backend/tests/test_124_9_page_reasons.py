"""Order 124 item 9 (engine side): a page's stored reason is plain words.

The page ledger's `facts_reason` is shown to engineers ("Page 3: ...").
It used to be an engine note ("33 label-value pairs were recovered and none
became a fact (12 by noise: revision table, ...)"). These tests hold the
stored sentence to plain words, keep the two failures apart, and keep the
counts available as the unparsed entry's "detail".
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import datasheets, page_reason_words, row_noise

ENGINE_WORDS = (
    "label-value",
    "noise:",
    "became a fact",
    " by ",
    "value gate",
    "create_fact",
)


def _plain(text: str) -> None:
    for word in ENGINE_WORDS:
        assert word not in text, (
            f"engine wording {word!r} reached the stored reason: {text}"
        )


def test_a_page_with_nothing_recovered_says_so_in_plain_words():
    reason = datasheets._unparsed_reason([], {})
    assert (
        reason
        == "No labelled values were found on this page (it may be a drawing or a scan)."
    )
    _plain(reason)


def test_a_page_whose_pairs_were_all_filtered_names_what_it_holds():
    dropped = {row_noise.REVISION: 12, row_noise.DOCUMENT_ID: 4}
    reason = datasheets._unparsed_reason([("a", "1")] * 33, dropped)
    assert reason == (
        "Nothing on this page was read as a datasheet value. "
        "What the reader found: a revision table and a title block."
    )
    # Review of #1155: what the reader SAW, never a claim about the page.
    assert "is a datasheet value" not in reason and "holds" not in reason
    _plain(reason)


def test_every_noise_rule_has_plain_words():
    """ONE table: every row_noise rule is mapped, and no mapping is the rule's
    own engine name."""
    for rule in row_noise.RULES:
        assert rule in page_reason_words.PLAIN, f"{rule!r} has no plain words"
        _plain(page_reason_words.PLAIN[rule])


def test_every_gate_reason_has_plain_words():
    for words in page_reason_words.PLAIN.values():
        _plain(words)


def test_an_unknown_reason_is_not_guessed_at():
    reason = datasheets._unparsed_reason([("a", "1")], {"some new gate": 1})
    assert reason.endswith("What the reader found: other text that is not a value.")


def test_no_recorded_reason_says_so():
    reason = datasheets._unparsed_reason([("a", "1")], {})
    assert "the reader did not record why" in reason
    assert "No labelled values were found" not in reason


def test_the_detail_keeps_the_counts():
    dropped = {row_noise.REVISION: 12, "value gate": 21}
    detail = page_reason_words.unparsed_detail(33, dropped)
    assert detail == (
        "33 label-value pairs were recovered and none became a fact "
        "(21 by value gate, 12 by noise: revision table)"
    )


def test_the_ai_note_is_a_plain_sentence():
    run = {"reasons": {2: "no text on this page"}}
    assert (
        datasheets._ai_page_note(run, 2)
        == "The AI reader added nothing here: no text on this page."
    )
    none = datasheets._ai_page_note(run, 3)
    assert none.startswith("The AI reader read the page") and "proved" not in none


@pytest.mark.parametrize(
    "why, words",
    [
        (None, "The picture reader was not used on this page."),
        ("VISION_BUDGET", "its page limit for this document was reached"),
        ("VISION_NO_TEXT_LAYER", "no text layer"),
        ("VISION_NOT_NEEDED", "a text reader had found labelled text"),
    ],
)
def test_the_vision_route_note_is_plain(why, words):
    note = page_reason_words.vision_route_note(
        getattr(datasheets, why) if why else None
    )
    assert words in note
    assert "routed" not in note and "OCR tier" not in note


def test_the_vision_note_is_plain_and_drops_the_false_not_counted_clause():
    """A vision-read page IS counted as read (honesty audit entry 68), so the
    old "not counted as the page read into fields" clause was false."""
    reading = SimpleNamespace(
        refused=None, asked=True, page_kind="table", proposed=3, kept=[1, 2]
    )
    note = datasheets._vision_ledger_note(reading, 1, None)
    assert note == (
        "The picture reader suggested 3 value(s); 2 matched the page text and 1 recorded. "
        "It called the page a 'table' (its own word, not checked)."
    )
    assert "not counted" not in note
