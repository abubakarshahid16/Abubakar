"""#455: ONE fence-stripper for model JSON answers, in `ai/json_reply`.

Every reader of a model's JSON (`ai_engineering_check.parse`, `field_naming._parse`,
`reasoning_provider.schema_errors`, `vision_reader.parse`, `reader_api.parse_response`,
`claude_datasheet.parse_response`, `form_reader.parse_answer`, and the answer judge) takes
the fence off with `json_reply.unfenced`. Measured on #455: a reply with the closing fence
on the JSON's last line, a tag with a digit, or an indented fence was used by the datasheet
readers and thrown away by the others. This is the acceptance table: the same reply shape
gives the same result at every site. Invented replies only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import (
    ai_engineering_check,
    claude_datasheet,
    field_naming,
    form_reader,
    reader_api,
    reasoning_provider,
    vision_reader,
)
from app.ai.json_reply import opened, unfenced

APP = Path(__file__).resolve().parents[1] / "app"

ITEMS = json.dumps({"items": [{"kind": "x"}]})
NAMES = json.dumps({"names": [{"item": 1, "field_name": None}]})
PAGE = json.dumps({"page_kind": "datasheet", "fields": [{"label": "a"}]})
FACTS = json.dumps({"facts": [{"field": "f"}]})
ROWS = json.dumps({"fields": [{"key": "k"}]})

#: (name, builder, is the JSON used?)
SHAPES = [
    ("bare", lambda p: p, True),
    ("fenced", lambda p: f"```json\n{p}\n```", True),
    ("fenced without tag", lambda p: f"```\n{p}\n```", True),
    ("fenced CRLF", lambda p: f"```json\r\n{p}\r\n```", True),
    ("tag then a space", lambda p: f"```json \n{p}\n```", True),
    ("closing fence on the JSON line", lambda p: f"```json\n{p}```", True),
    ("tag with a digit", lambda p: f"```json5\n{p}\n```", True),
    ("indented fence", lambda p: f"  ```json\n{p}\n  ```", True),
    ("cut off, no closing fence", lambda p: f"```json\n{p}", False),
    ("trailing text", lambda p: f"{p}\nDone.", False),
    ("leading text", lambda p: f"Here it is: {p}", False),
    ("text after the fence", lambda p: f"```json\n{p}\n```\nHope this helps", False),
    ("two fenced blocks", lambda p: f"```json\n{p}\n```\n```json\n{p}\n```", False),
    ("single backticks", lambda p: f"`{p}`", False),
    ("empty", lambda p: "", False),
    ("blank", lambda p: "   ", False),
]
IDS = [s[0] for s in SHAPES]


def _cases(payload):
    return [pytest.param(build(payload), used, id=name) for name, build, used in SHAPES]


@pytest.mark.parametrize("reply, used", _cases(ITEMS))
def test_the_one_rule_itself(reply, used):
    try:
        got = json.loads(unfenced(reply.strip()))
    except json.JSONDecodeError:
        got = None
    assert (got == json.loads(ITEMS)) is used


@pytest.mark.parametrize("reply, used", _cases(ITEMS))
def test_the_ai_check_reads_every_shape_alike(reply, used):
    assert (ai_engineering_check.parse(reply) is not None) is used


@pytest.mark.parametrize("reply, used", _cases(NAMES))
def test_field_naming_reads_every_shape_alike(reply, used):
    assert bool(field_naming._parse(reply)) is used


@pytest.mark.parametrize("reply, used", _cases(ITEMS))
def test_the_schema_gate_reads_every_shape_alike(reply, used):
    errors = reasoning_provider.schema_errors(reply, {"type": "object"})
    assert (errors == ()) is used


@pytest.mark.parametrize("reply, used", _cases(PAGE))
def test_the_vision_reader_reads_every_shape_alike(reply, used):
    kind, fields = vision_reader.parse(reply)
    assert (kind == "datasheet" and bool(fields)) is used


@pytest.mark.parametrize("reply, used", _cases(json.dumps({"proposals": []})))
def test_the_rule_reader_reads_every_shape_alike(reply, used):
    _proposals, reason = reader_api.parse_response(reply)
    assert (reason is None) is used


@pytest.mark.parametrize("reply, used", _cases(FACTS))
def test_the_datasheet_reader_reads_every_shape_alike(reply, used):
    _facts, reason = claude_datasheet.parse_response(reply)
    assert (reason is None) is used


@pytest.mark.parametrize("reply, used", _cases(ROWS))
def test_the_form_reader_reads_every_shape_alike(reply, used):
    _got, reason = form_reader.parse_answer(reply, {"k"})
    assert (reason is None) is used


def test_a_cut_off_reply_loses_only_its_opening_fence():
    assert opened('```json5\n{"items": [') == '{"items": ['
    assert opened('{"items": [') == '{"items": ['
    assert opened("text ```json\n{") == "text ```json\n{"


def test_no_module_carries_its_own_copy_of_the_fence_regex():
    copies = [
        p.name
        for p in APP.rglob("*.py")
        if p.name != "json_reply.py"
        and 're.compile(r"' in p.read_text(encoding="utf-8")
        and any(
            "```" in line and "re." in line
            for line in p.read_text(encoding="utf-8").splitlines()
        )
    ]
    assert copies == []
