"""Order 305.4: a converter row the first pass verified is asked a second, differently worded question; it stays
verified only if the two answers agree. Invented sentences; the scripted provider plays both questions."""

from __future__ import annotations

import json

import pytest

from app import converter_review, converter_second, standards_converter
from app.db import connect
from app.reasoning_provider import ProviderRefused, Response
from tests.test_270_standards_converter import (  # noqa: F401 - fixtures and helpers
    DICT,
    GOOD,
    PUMP,
    _standard,
    temp_db,
)

PLAIN = "The casing design pressure shall not exceed 25 bar."
HIDDEN = (
    "For pumps in sour service, the casing design pressure shall not exceed 25 bar."
)
IN_SOUR = "for pumps in sour service"


class Scripted:
    """Answers the first question with GOOD for every sentence, and the second with `second_for(text)`."""

    requested_model = "local-35b"
    name = "ollama"

    def __init__(self, second_for, first_for=lambda text: GOOD, refuse_second=False):
        self.second_for, self.first_for, self.refuse_second = (
            second_for,
            first_for,
            refuse_second,
        )
        self.packets = []

    def reason(self, packet):
        self.packets.append(packet)
        second = packet.prompt_version == converter_second.PROMPT_VERSION
        if second and self.refuse_second:
            raise ProviderRefused("no")
        checks = []
        for item in json.loads(packet.prompt)["items"]:
            got = (self.second_for if second else self.first_for)(item["text"])
            checks.append({"i": item["i"], **(got or {"field": None})})
        return Response(
            text=json.dumps({"checks": checks}),
            provider="ollama",
            model_tag="local-35b",
            digest="d",
            finish_reason="stop",
            prompt_sha256=packet.sha256,
        )


def _run(texts, provider):
    doc = _standard("SAES-G-005", tuple(texts))
    with connect() as conn:
        return standards_converter.convert(
            conn, doc, "SAES-G-005", PUMP, provider, lane="local", ask_twice=True
        )


def second(always, only_when=None, quote=None):
    """The second question's scripted answer for every sentence."""
    return lambda text: {"always": always, "only_when": only_when, "quote": quote}


def first(condition=None):
    """The first question's scripted answer: GOOD, with the model's condition."""
    return lambda text: {**GOOD, "condition": condition}


ALWAYS = second(True)
SAW_SOUR = second(False, IN_SOUR, IN_SOUR)


def test_two_agreeing_answers_keep_the_row_verified_and_record_both():
    fake = Scripted(ALWAYS)
    result = _run([PLAIN], fake)
    row = result.rows[0]
    assert row["status"] == "verified" and row["asked_twice"] is True
    assert row["second"] == {"always": True, "only_when": None, "quote": None}
    assert len(fake.packets) == 2 and result.calls == 2


def test_a_hidden_only_if_the_first_answer_missed_makes_the_row_unproven():
    """The first pass saw no condition (it missed 'in sour service'); the second sees it: they disagree."""
    row = _run([HIDDEN], Scripted(SAW_SOUR, first_for=first(None))).rows[0]
    assert (row["status"], row["reason"]) == ("unproven", converter_second.DISAGREES)
    assert row["limit"] is None and row["field"] is None
    assert row["note"] == standards_converter.ENGINEER and "asked_twice" not in row


def test_both_answers_naming_the_same_condition_keep_the_row():
    row = _run([HIDDEN], Scripted(SAW_SOUR, first_for=first(IN_SOUR))).rows[0]
    assert row["status"] == "verified" and row["asked_twice"] is True
    assert row["condition"] == IN_SOUR


def test_a_first_condition_the_second_answer_denies_is_a_disagreement():
    row = _run([HIDDEN], Scripted(ALWAYS, first_for=first(IN_SOUR))).rows[0]
    assert (row["status"], row["reason"]) == ("unproven", converter_second.DISAGREES)


def test_a_condition_the_clause_does_not_say_is_not_accepted():
    invented = second(False, "for offshore pumps", "for offshore pumps")
    row = _run([HIDDEN], Scripted(invented, first_for=first(IN_SOUR))).rows[0]
    assert (row["status"], row["reason"]) == ("unproven", converter_second.NOT_QUOTED)


def test_a_condition_whose_quote_is_real_but_whose_words_are_invented_is_not_accepted():
    invented = second(
        False, "for offshore pumps", IN_SOUR
    )  # the quote is in the clause, the condition is not
    row = _run([HIDDEN], Scripted(invented, first_for=first(IN_SOUR))).rows[0]
    assert (row["status"], row["reason"]) == ("unproven", converter_second.NOT_QUOTED)


def test_a_second_condition_that_overlaps_the_first_agrees():
    inside = second(False, "pumps in sour service", "pumps in sour service")
    row = _run([HIDDEN], Scripted(inside, first_for=first(IN_SOUR))).rows[0]
    assert row["status"] == "verified"


def test_two_different_conditions_are_a_disagreement():
    other = second(False, "design pressure", "design pressure")
    row = _run([HIDDEN], Scripted(other, first_for=first(IN_SOUR))).rows[0]
    assert (row["status"], row["reason"]) == ("unproven", converter_second.DISAGREES)


@pytest.mark.parametrize("reply", [None, {"always": None}, {"always": "yes"}])
def test_an_unreadable_second_answer_is_unproven(reply):
    row = _run([PLAIN], Scripted(lambda text: reply)).rows[0]
    assert (row["status"], row["reason"]) == ("unproven", converter_second.UNREADABLE)


def test_a_refused_second_call_never_leaves_a_row_verified():
    result = _run([PLAIN], Scripted(ALWAYS, refuse_second=True))
    assert result.rows[0]["status"] == "unproven"
    assert result.rows[0]["reason"] == converter_second.UNREADABLE


def test_only_the_rows_the_first_pass_verified_are_asked_again():
    only_plain = lambda text: GOOD if text == PLAIN else {"field": None}  # noqa: E731
    fake = Scripted(ALWAYS, first_for=only_plain)
    _run([PLAIN, "Pumps shall be painted."], fake)
    asked = [
        p for p in fake.packets if p.prompt_version == converter_second.PROMPT_VERSION
    ]
    assert len(asked) == 1 and len(json.loads(asked[0].prompt)["items"]) == 1


def test_the_second_question_is_standards_text_only():
    fake = Scripted(ALWAYS)
    _run([PLAIN], fake)
    asked = next(
        p for p in fake.packets if p.prompt_version == converter_second.PROMPT_VERSION
    )
    item = json.loads(asked.prompt)["items"][0]
    assert set(item) == {"i", "clause", "text", "limit"} and item["text"] == PLAIN


def test_with_ask_twice_off_the_first_answer_alone_verifies():
    doc = _standard("SAES-G-005", (PLAIN,))
    with connect() as conn:
        result = standards_converter.convert(
            conn,
            doc,
            "SAES-G-005",
            PUMP,
            Scripted(ALWAYS),
            lane="local",
            ask_twice=False,
        )
    assert (
        result.rows[0]["status"] == "verified" and "asked_twice" not in result.rows[0]
    )
    assert result.asked_twice is False


def test_the_shipped_default_is_to_ask_twice(monkeypatch):
    """The first-pass test files switch it off with a fixture; the code's own default is on."""
    import inspect

    assert "\nASK_TWICE = True" in inspect.getsource(standards_converter)
    monkeypatch.setattr(standards_converter, "ASK_TWICE", True)
    doc = _standard("SAES-G-005", (PLAIN,))
    fake = Scripted(ALWAYS)
    with connect() as conn:
        standards_converter.convert(conn, doc, "SAES-G-005", PUMP, fake, lane="local")
    assert len(fake.packets) == 2


def _file(tmp_path, asked, entry):
    body = {
        "converter": True,
        "status": standards_converter.STATUS,
        "equipment_type": PUMP,
        "standard": "SAES-G-005",
        "ask_twice": converter_second.PROMPT_VERSION if asked else None,
        "entries": [entry],
    }
    path = tmp_path / "x.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


VERIFIED = {
    "status": "verified",
    "applies": None,
    "field": "design_pressure",
    "text_sha256": "abc",
}


def test_the_review_refuses_a_verified_row_of_a_twice_asked_file_that_was_not_asked_twice(
    tmp_path,
):
    """A hand-edited or old row cannot slip a one-answer row through a file that says it asked twice."""
    assert converter_review.reviewed_entries([_file(tmp_path, True, VERIFIED)]) == []
    kept = converter_review.reviewed_entries(
        [_file(tmp_path, True, {**VERIFIED, "asked_twice": True})]
    )
    assert len(kept) == 1


def test_a_file_made_before_the_second_question_is_read_as_before(tmp_path):
    assert (
        len(converter_review.reviewed_entries([_file(tmp_path, False, VERIFIED)])) == 1
    )


def test_the_file_says_the_second_question_was_asked(tmp_path):
    result = _run([PLAIN], Scripted(ALWAYS))
    paths = standards_converter.write(result, tmp_path, form_sha="abcdef1")
    body = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert body["ask_twice"] == converter_second.PROMPT_VERSION
    assert body["entries"][0]["asked_twice"] is True
