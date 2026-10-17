"""ONE parser for a model's JSON reply (#455, C-H1).

Every model route used to strip Markdown code fences and parse JSON its own
way - eight copies, each a little different (one took a fence with no
closing line, one found the first `{`, one tolerated trailing spaces). This
is the one home for the two things they all do:

  `unfence(text)`      the reply without ONE enclosing code fence, tagged
                       (```json) or not; anything else is returned as it is;
  `parse(text)`        (value, error): the parsed JSON, or None and a NAMED
                       error - "empty" or "not_json" - never a silent None.

Removing the fence is not repairing the answer: what is inside must still be
the whole, valid JSON. A cut-off reply (no closing fence, half an object)
still fails the strict parse; the callers that walk a truncated array by
hand (`ai_engineering_check.parse_partial`, `claude_datasheet`) take the open
fence off with `unfence_open` and do their own careful walk.

The two review-path copies, `reader_api._unfenced` and `rule_eval`'s strip,
are named on #455 and left for the review-path owner.
"""
from __future__ import annotations

import json
import re
from typing import Any

#: A whole reply wrapped in one code fence, optionally tagged. Anchored at
#: both ends: a fence that does not enclose the entire reply is left alone.
_FENCE = re.compile(r"^\s*```[A-Za-z0-9_-]*[ \t]*\n(?P<body>.*?)\n?[ \t]*```\s*$", re.DOTALL)
#: A fence that was opened and never closed - a reply cut off by the cap.
_OPEN_FENCE = re.compile(r"^\s*```[A-Za-z0-9_-]*[ \t]*\n(?P<body>.*)$", re.DOTALL)

EMPTY, NOT_JSON = "empty", "not_json"


def unfence(text: Any) -> Any:
    """The reply without ONE enclosing Markdown code fence; else as it is."""
    if not isinstance(text, str):
        return text
    m = _FENCE.match(text)
    return m.group("body") if m else text


def unfence_open(text: Any) -> Any:
    """Like `unfence`, but also takes off a fence that was never closed
    (a reply the output cap cut). For the callers that walk a truncated
    reply by hand; a strict parse of the result still fails, as it should."""
    if not isinstance(text, str):
        return text
    m = _FENCE.match(text) or _OPEN_FENCE.match(text)
    return m.group("body") if m else text


def parse(text: Any) -> tuple[Any, str | None]:
    """(value, None) for a JSON reply, fenced or not; (None, error) otherwise,
    with the error NAMED: `empty` (nothing to read) or `not_json`."""
    body = unfence(text)
    if not isinstance(body, str) or not body.strip():
        return None, EMPTY
    try:
        return json.loads(body), None
    except (json.JSONDecodeError, TypeError, ValueError):
        return None, NOT_JSON
