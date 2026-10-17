"""#455 (C-H1): one shared fence-stripping JSON parser for a model's reply.

What must hold: a reply wrapped in one code fence, tagged or not, with or
without trailing whitespace, parses to the same value as the bare JSON; a
fence that does not enclose the whole reply is left alone; a cut-off reply
(no closing fence, half an object) is NOT repaired - it fails with a named
error; and every off-path model route reads through this one module, so a
second copy cannot grow back unnoticed (the two review-path copies are
named, not guarded here).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import ai_engineering_check, field_naming, model_json, vision_reader
from app.reasoning_provider import schema_errors

APP = Path(ai_engineering_check.__file__).parent
DOC = '{"items": [{"n": 1}], "page_kind": "datasheet", "fields": [{"a": 1}], "names": [{"i": 0}]}'


@pytest.mark.parametrize("wrapped", [
    DOC,
    "```json\n" + DOC + "\n```",
    "```\n" + DOC + "\n```",
    "  ```JSON \n" + DOC + "\n```  \n",
    "```json\n" + DOC + "```",          # the closing fence on the last line
])
def test_a_fenced_reply_parses_like_the_bare_json(wrapped):
    value, error = model_json.parse(wrapped)
    assert error is None and value["items"] == [{"n": 1}]
    assert model_json.unfence(wrapped).strip() == DOC


def test_a_fence_that_does_not_enclose_the_whole_reply_is_left_alone():
    text = "Here it is:\n```json\n" + DOC + "\n```"
    assert model_json.unfence(text) == text
    assert model_json.parse(text) == (None, model_json.NOT_JSON)


def test_a_cut_off_reply_is_named_not_repaired():
    cut = "```json\n" + DOC[:20]
    assert model_json.parse(cut) == (None, model_json.NOT_JSON)
    assert model_json.unfence(cut) == cut                      # strict: no closing fence
    assert model_json.unfence_open(cut) == DOC[:20]            # for the hand-walkers only
    assert model_json.parse("") == (None, model_json.EMPTY)
    assert model_json.parse("```json\n\n```") == (None, model_json.EMPTY)
    assert model_json.parse(None) == (None, model_json.EMPTY)


def test_every_off_path_route_reads_a_fenced_reply_the_same_way():
    fenced = "```json\n" + DOC + "\n```"
    assert ai_engineering_check.parse(fenced) == [{"n": 1}]
    assert ai_engineering_check.parse("```json\n" + DOC[:30]) is None
    assert field_naming._parse(fenced) == [{"i": 0}]
    assert vision_reader.parse(fenced) == ("datasheet", [{"a": 1}])
    assert schema_errors(fenced, {"type": "object", "required": ["items"]}) == ()
    assert schema_errors("```json\n" + DOC[:30], {"type": "object"}) == ("not valid JSON",)
    # a cut-off items array: the complete items before the cut, through the open fence
    assert ai_engineering_check.parse_partial('```json\n{"items": [{"n": 1}, {"n": 2') == [{"n": 1}]


def test_no_second_fence_stripping_parser_grows_back():
    """Source-level guard: the fence regex lives in `model_json` only. The two
    review-path copies (#455, for the review-path owner) are named here so
    the guard fails the day a third one appears."""
    allowed = {"model_json.py", "reader_api.py", "rule_eval.py"}
    copies = sorted(p.name for p in APP.glob("*.py")
                    if p.name not in allowed and re.search(r"```", p.read_text(encoding="utf-8"))
                    and re.search(r"re\.(match|compile)\(r?\"[^\"]*```", p.read_text(encoding="utf-8")))
    assert copies == []
    stripped = sorted(p.name for p in APP.glob("*.py")
                      if p.name not in allowed and '.strip("`")' in p.read_text(encoding="utf-8"))
    assert stripped == []
