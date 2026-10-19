"""Order 139 (#882): every page is read, or ends with a named reason.

On the local model a dense datasheet page's answer - a long, VALID list of
facts - reached the output limit, and the whole page was thrown away as
"engine failed (EngineFailed)": three pages of seven, every reading lost.
In form mode the same failure of the whole-page pass vanished from the run.

Proved here, with made-up page text and fake model calls only:
  * a cut-off page is read again in parts; every part's readings are kept,
    each checked against the WHOLE page (`gate_text`);
  * a part still cut off at the last split keeps the facts it finished,
    and the page says `cut_off` - never a clean page;
  * the number of calls is bounded, and the time budget is respected;
  * a part not read is named (`partial`), and a page with no part read is
    an `error`;
  * the local engine raises the cut-off WITH its text (`AnswerCutOff`);
  * the form reader names a cut-off batch `model_cut_off`;
  * in form mode, the whole-page pass's gaps (failed, partial, out of time,
    cut off, timed out) stay on the run.
"""

from __future__ import annotations

import json
import time

from app import (
    claude_datasheet,
    datasheet_ai,
    form_reader,
    form_reader_run,
    model_transport,
)
from app.config import settings
from app.datasheet_ai import AnswerCutOff

ROWS = [
    ("Design pressure", "23.5", "barg"),
    ("Design temperature", "120", "degC"),
    ("Rated flow", "42", "m3/h"),
    ("Rated head", "55", "m"),
    ("Motor power", "75", "kW"),
    ("Impeller diameter", "260", "mm"),
    ("Suction pressure", "2.5", "barg"),
    ("Minimum flow", "12", "m3/h"),
]
PAGE = "\n".join(f"{label} {value} {unit}" for label, value, unit in ROWS)


def _page_of(prompt: str) -> str:
    """The page text `claude_datasheet.build_prompt` put after "PAGE n:"."""
    return prompt.rsplit("\nPAGE ", 1)[1].split("\n", 1)[1]


def _facts(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        label, value, unit = line.rsplit(" ", 2)
        out.append(
            {
                "field": label,
                "value": value,
                "unit": unit,
                "quote": line,
                "kind": "offered",
            }
        )
    return out


def _cut(facts: list[dict]) -> str:
    """The first fact finished, the second cut half-way: what Ollama returns."""
    return (
        '{"facts": [' + json.dumps(facts[0]) + ', {"field": "' + facts[1]["field"][:4]
    )


class CutsLongAnswers:
    """A local engine whose answer is cut off when the text holds more than
    `max_lines` rows, and that fails on a short text holding `fails_on`.
    Records each prompt's row count."""

    engine = "fake-local"

    def __init__(self, max_lines: int, fails_on: str | None = None):
        self.max_lines = max_lines
        self.fails_on = fails_on
        self.rows: list[int] = []

    def __call__(self, prompt: str) -> str:
        text = _page_of(prompt)
        facts = _facts(text)
        self.rows.append(len(facts))
        if len(facts) > self.max_lines:
            raise AnswerCutOff(_cut(facts))
        if self.fails_on and self.fails_on in text:
            raise RuntimeError("engine down")
        return json.dumps({"facts": facts})


def _read(model, **kw):
    return datasheet_ai._read(PAGE, 1, model, "fake-local", **kw)


# ============================================================ the merge pass


def test_a_cut_off_page_is_read_again_in_parts_and_every_value_is_kept():
    model = CutsLongAnswers(max_lines=4)
    out = _read(model)
    assert "error" not in out and "partial" not in out and "cut_off" not in out
    assert sorted(f["field"] for f in out["accepted"]) == sorted(r[0] for r in ROWS)
    assert {f["page"] for f in out["accepted"]} == {1}
    # one cut-off call on the page, then two halves read twice each
    assert model.rows == [8, 4, 4, 4, 4]
    assert out["parts"] == {"read": 2, "not_read": 0, "cut_again": 0}


def test_a_part_still_cut_off_at_the_last_split_keeps_its_finished_facts_marked():
    model = CutsLongAnswers(max_lines=1)
    out = _read(model)
    # halves cut again, quarters (2 rows) are the last split: one finished fact each
    assert "error" not in out and out["cut_off"] is True
    assert len(out["accepted"]) == 4
    assert out["parts"]["read"] == 2**datasheet_ai.MAX_SPLITS
    # bounded: 1 page call + 2 cut halves + 4 quarters x 2 runs
    assert len(model.rows) == 1 + 2 + 4 * 2


def test_the_parts_are_checked_against_the_whole_page(monkeypatch):
    """A quote the gate would refuse as most of a PART is a few cells of
    the page it is cited to: the share is measured on the page."""
    seen = []
    real = claude_datasheet.accept

    def spy(proposals, page_text, known_fields=None):
        seen.append(page_text)
        return real(proposals, page_text, known_fields)

    monkeypatch.setattr(claude_datasheet, "accept", spy)
    _read(CutsLongAnswers(max_lines=4))
    assert seen == [PAGE, PAGE]


def test_a_part_that_fails_is_named_and_the_rest_of_the_page_is_kept():
    model = CutsLongAnswers(max_lines=4, fails_on="Minimum flow")
    out = _read(model)
    assert "error" not in out
    assert len(out["accepted"]) == 4
    assert "1 part(s) not read" in out["partial"] and "RuntimeError" in out["partial"]


def test_read_pages_records_a_partly_read_page_as_read_with_its_reason():
    model = CutsLongAnswers(max_lines=4, fails_on="Minimum flow")
    run = datasheet_ai.read_pages({1: PAGE, 2: "Rated speed 2950 rpm"}, model)
    assert 1 in run["pages"] and "error" not in run["pages"][1]
    assert "part(s) not read" in run["reasons"][1]
    assert 2 not in run["reasons"]


def test_the_time_budget_stops_the_parts_and_says_so():
    model = CutsLongAnswers(max_lines=4)
    out = _read(model, deadline=time.monotonic() - 1)
    assert model.rows == [8]  # the page call only; no part was sent
    assert out["accepted"] == []
    assert "no part of the page was read" in out["error"]
    assert "time budget" in out["error"]


def test_read_pages_gives_the_parts_the_pass_s_time_budget(monkeypatch):
    monkeypatch.setattr(settings, "datasheet_ai_max_seconds", 0.0)
    model = CutsLongAnswers(max_lines=4)
    run = datasheet_ai.read_pages({1: PAGE}, model)
    assert model.rows == []  # the budget was spent before the page
    assert run["stopped"] == "time_budget" and 1 in run["reasons"]


def test_the_local_engine_raises_the_cut_off_with_its_text(monkeypatch):
    """Through `_ollama_call` and `model_transport`: "length" is a cut-off
    that carries the text, and the page is then read in parts."""
    posted = []

    def post_json(path, body, *, timeout):
        facts = _facts(_page_of(body["prompt"]))
        posted.append(len(facts))
        if len(facts) > 4:
            return {
                "response": _cut(facts),
                "model": "local-0001",
                "done_reason": "length",
            }
        return {
            "response": json.dumps({"facts": facts}),
            "model": "local-0001",
            "done_reason": "stop",
        }

    monkeypatch.setattr(model_transport, "post_json", post_json)
    monkeypatch.setattr(settings, "datasheet_ai_ollama_model", "local-0001")
    out = datasheet_ai.read_page_text_with_ai(PAGE, 1, "ollama")
    assert "error" not in out and len(out["accepted"]) == len(ROWS)
    assert posted == [8, 4, 4, 4, 4]


# ============================================================ the form pass


def test_the_form_reader_names_a_cut_off_answer():
    def cut(prompt):
        raise AnswerCutOff('{"fields": [{"field_key": "design_pr')

    reading = form_reader.read_form({1: PAGE}, "Centrifugal Pump", cut)
    assert reading.facts == []
    assert set(reading.counts()["rejected_by_reason"]) == {"model_cut_off"}
    assert "model_cut_off" in reading.errors[1]


def _page(accepted, **extra):
    return {
        "page": 1,
        "engine": "fake",
        "accepted": accepted,
        "rejected": [],
        "counts": {},
        **extra,
    }


def _fact(name, value):
    return {
        "field_name": name,
        "field": name,
        "value": value,
        "quote": f"{name} {value}",
        "page": 1,
    }


def _form(pages):
    return {
        "pages": pages,
        "reasons": {},
        "stopped": None,
        "timed_out": [],
        "seconds": 1,
    }


def test_a_whole_page_pass_failure_on_a_page_the_form_read_stays_on_the_run():
    form = _form(
        {
            1: _page([_fact("design pressure", "10")]),
            2: _page([_fact("rated flow", "42")]),
            3: _page([_fact("rated head", "55")]),
        }
    )
    merge = {
        "pages": {
            1: _page([], error="engine failed (AnswerCutOff)"),
            2: _page([_fact("motor power", "75")], partial="1 part(s) not read"),
            3: _page([_fact("speed", "2950")], cut_off=True),
        },
        "reasons": {
            1: "engine failed (AnswerCutOff)",
            2: "1 part(s) not read",
            4: "not read: the AI reader's time budget ran out",
        },
        "stopped": None,
        "timed_out": [4],
        "seconds": 1,
    }
    out = form_reader_run.add_merge_reading(form, merge)
    assert "AnswerCutOff" in out["reasons"][1]
    assert "part(s) not read" in out["reasons"][2]
    assert "time budget" in out["reasons"][4]
    assert 3 not in out["reasons"] and out["pages"][3]["cut_off"] is True
    assert out["timed_out"] == [4]
    # the form's readings are untouched; the page the form read stays read
    assert "error" not in out["pages"][1]
    assert [f["value"] for f in out["pages"][1]["accepted"]] == ["10"]


def test_a_page_only_the_whole_page_pass_read_in_part_keeps_its_reason():
    form = _form({1: _page([], error="form reader could not read this page")})
    form["reasons"] = {1: "form reader could not read this page"}
    merge = {
        "pages": {1: _page([_fact("motor power", "75")], partial="1 part(s) not read")},
        "reasons": {1: "1 part(s) not read"},
        "stopped": None,
        "seconds": 1,
    }
    out = form_reader_run.add_merge_reading(form, merge)
    assert out["pages"][1]["accepted"][0]["value"] == "75"
    assert "part(s) not read" in out["reasons"][1]


def test_the_cut_off_text_is_kept_on_the_exception():
    exc = AnswerCutOff('{"facts": [')
    assert isinstance(exc, datasheet_ai.EngineFailed) and exc.text == '{"facts": ['
    assert AnswerCutOff(None).text == ""


def test_split_text_cuts_at_the_line_nearest_the_middle_and_loses_nothing():
    head, tail = datasheet_ai.split_text(PAGE)
    assert head.count("\n") == 3 and tail.count("\n") == 3
    assert head + "\n" + tail == PAGE
    assert datasheet_ai.split_text("one two") == ["one", "two"]
    assert datasheet_ai.split_text("single") == []
