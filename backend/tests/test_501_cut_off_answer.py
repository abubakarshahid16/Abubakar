"""#501: an AI reader answer cut off by the output limit keeps the facts it
had finished, and the run says the page was not read to its end.

Measured with the cloud reader on a real sheet (planner's run, 12 Oct 2026):
2 of 49 calls ended exactly at the output cap, half-way through a fact. Half
an object is not JSON, so both pages were reported "unusable" and every fact
the model HAD finished was thrown away. Planner decision (11:38 UTC): keep
the complete values of a cut-off answer and label it "cut off by the output
limit", as the AI engineering check already does.

Nothing is repaired or guessed: the unfinished fact is not returned, and
what is returned still passes the two-run agreement and the gate.
Invented page only.
"""
from __future__ import annotations

import json

import pytest

from app import absence, claude_datasheet as cd
from app import datasheets
from tests.test_claude_datasheet import PAGE, _answer, _fact, temp_storage  # noqa: F401 - autouse

SET = _fact("Set pressure", "340", "8 | Set pressure | 340 psig", unit="psig")
TEMP = _fact("Relieving temperature", "121", "9 | Relieving temperature | 121 C", unit="C")
CASING = _fact("Casing material", "Carbon steel", "12 | Casing material | Carbon steel")


def _cut(*finished, tail='{"field": "Hydrotest result", "value": "51", "un'):
    """A reply that is valid JSON up to and including `finished`, then cut
    off mid-way through one more fact - what an output cap leaves behind."""
    body = '{"facts": [' + ", ".join(json.dumps(f) for f in finished)
    return body + (", " if finished else "") + tail


def test_the_facts_finished_before_the_cut_are_returned_and_the_cut_one_is_not():
    finished = cd.facts_before_the_cut(_cut(SET, TEMP))
    assert [f["field"] for f in finished] == ["Set pressure", "Relieving temperature"]
    proposals, err, cut = cd.parse_or_cut(_cut(SET, TEMP))
    assert err is None and cut is True and [p["field"] for p in proposals] == ["Set pressure", "Relieving temperature"]


@pytest.mark.parametrize("raw", [
    _answer(SET, TEMP),                                   # a whole answer: not cut off
    "no",                                                 # not an answer at all
    '{"facts": [',                                        # cut before any fact was finished
    _cut(tail='{"field": "Set pres'),                     # the same
    '{"facts": [{"field": "Set pressure"}] trailing',     # the list closes: malformed some other way
    '{"facts": ["a string", ',                            # not a list of objects: do not guess
    '{"items": [' + json.dumps(SET) + ', {"fie',          # another shape
    None,
])
def test_anything_else_is_not_treated_as_a_cut_off_answer(raw):
    assert cd.facts_before_the_cut(raw) is None


def test_a_whole_answer_parses_exactly_as_before():
    assert cd.parse_or_cut(_answer(SET)) == (*cd.parse_response(_answer(SET)), False)
    assert cd.parse_or_cut("no") == ([], cd.Reason.MODEL_MALFORMED.value, False)


def test_a_brace_or_a_quote_inside_a_value_does_not_end_the_fact_early():
    odd = _fact("Casing material", 'Carbon steel {grade "B"}', "12 | Casing material | Carbon steel")
    assert [f["value"] for f in cd.facts_before_the_cut(_cut(odd))] == ['Carbon steel {grade "B"}']


def test_a_fenced_cut_off_answer_is_read_the_same_way():
    assert len(cd.facts_before_the_cut("```json\n" + _cut(SET, TEMP))) == 2


def test_a_page_whose_first_answer_was_cut_off_keeps_what_both_runs_agree_on():
    """Before: `error: model_malformed`, 0 values. The first run finished two
    facts before the cut; the second run is whole and agrees on both."""
    out = cd.read_page(PAGE, 1, [], lambda p: _cut(SET, TEMP), second_call=lambda p: _answer(SET, TEMP, CASING))
    assert "error" not in out and out["cut_off"] is True
    assert sorted(p["field"] for p in out["accepted"]) == ["Relieving temperature", "Set pressure"]


def test_a_cut_off_second_answer_makes_what_it_did_not_reach_unstable_not_accepted():
    """The two-run rule is not relaxed: a fact only the whole run produced is
    reported as unstable, exactly as if the second run had disagreed."""
    out = cd.read_page(PAGE, 1, [], lambda p: _answer(SET, TEMP), second_call=lambda p: _cut(SET))
    assert out["cut_off"] is True and [p["field"] for p in out["accepted"]] == ["Set pressure"]
    assert out["counts"] == {cd.Reason.MODEL_UNSTABLE.value: 1}


def test_the_gate_still_refuses_a_finished_fact_that_is_not_on_the_page():
    invented = _fact("Set pressure", "999", "8 | Set pressure | 999 psig", unit="psig")
    out = cd.read_page(PAGE, 1, [], lambda p: _cut(invented), second_call=lambda p: _cut(invented))
    assert out["accepted"] == [] and out["cut_off"] is True and sum(out["counts"].values()) == 1


def test_an_answer_cut_before_any_fact_is_still_an_error():
    out = cd.read_page(PAGE, 1, [], lambda p: '{"facts": [{"field": "Set pres')
    assert out["error"] == cd.Reason.MODEL_MALFORMED.value and "cut_off" not in out


def test_a_whole_page_is_not_marked_cut_off():
    out = cd.read_page(PAGE, 1, [], lambda p: _answer(SET))
    assert "cut_off" not in out and len(out["accepted"]) == 1


def test_the_run_names_the_pages_that_were_cut_off():
    ai_run = {"engine": "claude", "model": "m", "reasons": {3: "engine answer unusable (model_malformed)"},
              "pages": {1: {"accepted": [], "counts": {}}, 2: {"accepted": [], "counts": {}, "cut_off": True},
                        3: {"accepted": [], "counts": {}, "error": "engine answer unusable (model_malformed)",
                            "cut_off": True}}}
    summary = datasheets.reader_summary(ai_run, {}, pages=[1, 2, 3])
    assert summary["cut_off"] == [2] and summary["pages_read"] == 2
    line = absence.reader_summary_line(summary)
    assert "read 2 of 3 page(s)" in line
    assert "on page(s) 2 the AI's answer was cut off by the output limit" in line
    assert "only the values it had finished before the cut are used" in line
    whole = datasheets.reader_summary({**ai_run, "pages": {1: {"accepted": [], "counts": {}}}, "reasons": {}},
                                      {}, pages=[1])
    assert whole["cut_off"] == [] and "cut off" not in absence.reader_summary_line(whole)


# ------------------------------------------- #501: values typed on a fill line

FORM = """PUMP DATASHEET                                   Page 2 of 7
TEMP CLASS _____T3___
SERVICE: _________CONTINUOUS
RELATIVE HUMIDITY : MIN/MAX ___6 / __100_ %
MAX. SOUND LEVEL ______<85_________ (dBA)
PIPE GRADE ___A_106___
RATED SPEED ________________ rpm
"""


@pytest.mark.parametrize("text, reads", [
    ("TEMP CLASS _____T3___", "TEMP CLASS T3"),
    ("SERVICE: _________CONTINUOUS", "SERVICE: CONTINUOUS"),
    ("MIN/MAX ___6 / __100_ %", "MIN/MAX 6 / 100 %"),
    ("PIPE GRADE ___A_106___", "PIPE GRADE A_106"),          # an underscore inside a name stays
    ("no fill here", "no fill here"),
    ("________________", ""),
])
def test_a_forms_fill_lines_are_not_part_of_what_is_printed(text, reads):
    assert cd.without_fill(text) == reads


def test_a_value_typed_on_a_fill_line_is_found_in_its_quote():
    """Measured with the cloud reader on a real pump sheet (12 Oct 2026): 62
    readings were refused as "value not in the quote" although each stood in
    its quote, glued to the underscores of the line it was typed on."""
    facts = [_fact("Temp class", "T3", "TEMP CLASS _____T3___"),
             _fact("Service", "CONTINUOUS", "SERVICE: _________CONTINUOUS"),
             _fact("Pipe grade", "A_106", "PIPE GRADE ___A_106___"),
             _fact("Max. sound level", "<85", "MAX. SOUND LEVEL ______<85_________ (dBA)", unit="dBA")]
    out = cd.read_page(FORM, 2, [], lambda p: _answer(*facts))
    assert sorted(p["field"] for p in out["accepted"]) == ["Max. sound level", "Pipe grade", "Service", "Temp class"]
    assert out["counts"] == {}


def test_the_fill_line_does_not_make_a_value_that_is_not_there():
    """Taking the underscores out invents nothing: a value the line does not
    print, and a field the line does not name, are refused as before - and
    the quote must still be on the page as it was given."""
    wrong_value = _fact("Temp class", "T4", "TEMP CLASS _____T3___")
    wrong_field = _fact("Rated speed", "T3", "TEMP CLASS _____T3___")
    empty_line = _fact("Rated speed", "1480", "RATED SPEED ________________ rpm", unit="rpm")
    not_on_page = _fact("Temp class", "T3", "TEMP CLASS T3")            # the page prints it with its fill line
    out = cd.read_page(FORM, 2, [], lambda p: _answer(wrong_value, wrong_field, empty_line, not_on_page))
    assert out["accepted"] == []
    assert out["counts"] == {cd.Reason.VALUE_NOT_IN_QUOTE.value: 2, cd.Reason.FIELD_NOT_IN_QUOTE.value: 1,
                             cd.Reason.QUOTE_NOT_ON_PAGE.value: 1}
