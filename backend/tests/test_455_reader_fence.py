"""#455: the datasheet readers' fence rule lives in `ai/json_reply`, moved unchanged.

`claude_datasheet` carried its own copy of the rule (`_unfenced`, and an inline
opening-fence regex in `facts_before_the_cut`), and `form_reader` borrowed it.
They now call `json_reply.unfenced_whole` / `opened_tagged`. This proves the move
is a refactor: every reply shape is read exactly as the old inline code read it,
and the old private copy is gone. The four strict sites are untouched (see
test_455_one_fence_parser.py). Invented replies only.
"""

from __future__ import annotations

import inspect
import json
import re

import pytest

from app import claude_datasheet, form_reader
from app.ai import json_reply

_OLD_FENCE = re.compile(
    r"^\s*```[A-Za-z0-9_-]*\s*\n(?P<body>.*?)\n?\s*```\s*$", re.DOTALL
)
_OLD_OPENING = r"^```[A-Za-z0-9_-]*\s*\n(.*)$"


def _old_unfenced(raw):
    if not isinstance(raw, str):
        return raw
    fenced = _OLD_FENCE.match(raw)
    return fenced.group("body") if fenced else raw


def _old_opened(body: str) -> str:
    fence = re.match(_OLD_OPENING, body, re.DOTALL)
    return fence.group(1) if fence else body


def _shapes(payload: str) -> list:
    return [
        payload,
        f"```json\n{payload}\n```",
        f"```\n{payload}\n```",
        f"```json\r\n{payload}\r\n```",
        f"```json\n{payload}```",
        f"```json5\n{payload}\n```",
        f"```json \n{payload}\n```",
        f"  ```json\n{payload}\n  ```",
        f"```json\n{payload}",
        f"{payload}\nDone.",
        f"Here it is: {payload}",
        f"```json\n{payload}\n```\nHope this helps",
        f"```json\n{payload}\n```\n```json\n{payload}\n```",
        f"`{payload}`",
        "",
        "   ",
        None,
        42,
    ]


FACTS = json.dumps({"facts": [{"field": "a", "value": "1", "quote": "a 1"}]})
FIELDS = json.dumps({"fields": [{"field_key": "k", "status": "found"}]})


@pytest.mark.parametrize("reply", _shapes(FACTS) + _shapes('{"a": "``` inside"}'))
def test_unfenced_whole_is_the_old_claude_datasheet_rule(reply):
    assert json_reply.unfenced_whole(reply) == _old_unfenced(reply)


@pytest.mark.parametrize("reply", [r for r in _shapes(FACTS) if isinstance(r, str)])
def test_opened_tagged_is_the_old_inline_opening_rule(reply):
    body = reply.strip()
    assert json_reply.opened_tagged(body) == _old_opened(body)


@pytest.mark.parametrize("reply", _shapes(FACTS))
def test_parse_response_reads_every_shape_as_before(reply):
    try:
        old = json.loads(_old_unfenced(reply))
    except (json.JSONDecodeError, TypeError):
        assert claude_datasheet.parse_response(reply)[1] == "model_malformed"
    else:
        assert old["facts"][0]["field"] == "a"
        assert claude_datasheet.parse_response(reply)[1] is None


@pytest.mark.parametrize("reply", _shapes(FIELDS))
def test_the_form_reader_reads_every_shape_as_before(reply):
    keys = {"k"}
    try:
        json.loads(_old_unfenced(reply))
    except (json.JSONDecodeError, TypeError):
        assert form_reader.parse_answer(reply, keys)[1] is not None
    else:
        assert form_reader.parse_answer(reply, keys)[1] is None


def test_the_private_copy_is_gone_from_claude_datasheet_and_form_reader():
    assert not hasattr(claude_datasheet, "_unfenced")
    assert not hasattr(claude_datasheet, "_FENCE")
    assert "claude_datasheet._unfenced" not in inspect.getsource(form_reader)
    assert claude_datasheet.unfenced_whole is json_reply.unfenced_whole
    assert form_reader.unfenced_whole is json_reply.unfenced_whole
    assert claude_datasheet.opened_tagged is json_reply.opened_tagged
