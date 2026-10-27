"""#455: one fence-stripper for model JSON answers, in `ai/json_reply`.

The four copies of the same regex (`ai_engineering_check.parse`,
`field_naming._parse`, `reasoning_provider.schema_errors`,
`vision_reader.parse`) now call `unfenced`. This proves (1) no copy is left,
and (2) every site reads every reply shape exactly as the old inline code
did - a refactor, not a change to which replies count. Invented replies only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app import ai_engineering_check, field_naming, reasoning_provider, vision_reader
from app.ai.json_reply import unfenced

APP = Path(__file__).resolve().parents[1] / "app"
_OLD = re.compile(r"^```[a-zA-Z]*\s*\n(.*)\n```$", re.DOTALL)  # the copy each site carried


def _old_unfenced(body: str) -> str:
    fence = re.match(_OLD.pattern, body, re.DOTALL)
    return fence.group(1) if fence else body


def _wrap(payload: str) -> list[str]:
    return [
        payload,
        f"```json\n{payload}\n```",
        f"```\n{payload}\n```",
        f"```json\r\n{payload}\r\n```",
        f"```json\n{payload}```",          # closing fence on the JSON line: refused, as before
        f"```json5\n{payload}\n```",       # tag with a digit: refused, as before
        f"```json \n{payload}\n```",
        f"  ```json\n{payload}\n  ```",    # indented fence: refused, as before
        f"```json\n{payload}",             # cut off
        f"{payload}\nDone.",
        f"Here it is: {payload}",
        f"```json\n{payload}\n```\nHope this helps",
        f"```json\n{payload}\n```\n```json\n{payload}\n```",
        f"`{payload}`",
        "",
        "   ",
    ]


ITEMS = json.dumps({"items": [{"kind": "x"}]})
NAMES = json.dumps({"names": [{"item": 1, "field_name": None}]})
PAGE = json.dumps({"page_kind": "datasheet", "fields": [{"label": "a"}]})


@pytest.mark.parametrize("reply", _wrap(ITEMS) + _wrap('{"a": "``` inside"}'))
def test_unfenced_is_the_old_rule_character_for_character(reply):
    assert unfenced(reply.strip()) == _old_unfenced(reply.strip())


def _old_items(text):
    body = _old_unfenced((text or "").strip())
    try:
        value = json.loads(body)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    items = value.get("items") if isinstance(value, dict) else None
    return items if isinstance(items, list) else None


def _old_names(text):
    body = _old_unfenced(text.strip())
    try:
        value = json.loads(body)
    except json.JSONDecodeError:
        return []
    names = value.get("names") if isinstance(value, dict) else None
    return names if isinstance(names, list) else []


def _old_schema(text):
    body = _old_unfenced(text.strip())
    try:
        json.loads(body)
    except json.JSONDecodeError:
        return ("not valid JSON",)
    return ()


@pytest.mark.parametrize("reply", _wrap(ITEMS))
def test_the_ai_check_reads_every_shape_as_before(reply):
    assert ai_engineering_check.parse(reply) == _old_items(reply)


@pytest.mark.parametrize("reply", _wrap(NAMES))
def test_field_naming_reads_every_shape_as_before(reply):
    assert field_naming._parse(reply) == _old_names(reply)


@pytest.mark.parametrize("reply", _wrap(ITEMS))
def test_the_schema_gate_reads_every_shape_as_before(reply):
    # every payload is an object, so a parsed reply has no schema error
    assert reasoning_provider.schema_errors(reply, {"type": "object"}) == _old_schema(reply)


@pytest.mark.parametrize("reply", _wrap(PAGE))
def test_the_vision_reader_reads_every_shape_as_before(reply):
    kind, fields = vision_reader.parse(reply)
    old = _old_unfenced((reply or "").strip())
    try:
        value = json.loads(old)
    except json.JSONDecodeError:
        assert (kind, fields) == (None, [])
        return
    assert kind == value.get("page_kind") and fields == value.get("fields")


def test_no_module_carries_its_own_copy_of_the_fence_regex():
    copies = [p.name for p in APP.rglob("*.py")
              if p.name != "json_reply.py" and _OLD.pattern in p.read_text(encoding="utf-8")]
    assert copies == []
    for module in (ai_engineering_check, field_naming, reasoning_provider, vision_reader):
        assert module.unfenced is unfenced, module.__name__
