"""ONE way to take a model's JSON answer out of a code fence (#455).

A model asked for "JSON and nothing else" sometimes wraps the whole answer in a
Markdown fence (```json ... ```). Every reader of a model's JSON takes the fence
off here, by the one rule below, so the same reply is never used by one module
and thrown away by another (measured on #455: a reply with the closing fence on
the JSON's last line, a tag with a digit or an indented fence was read by the
datasheet readers and refused by four others).

`unfenced`: ONE fence that encloses the WHOLE answer is removed - an opening
line of backticks with an optional tag (letters, digits, "_" and "-"), the body,
and a closing fence that ends the answer (on its own line, or right after the
JSON, indented or not). Anything else is returned unchanged and parsed strictly
by the caller; nothing is repaired or guessed.

`opened`: for a reply the token cap CUT OFF, which has no closing fence: only
the opening fence is removed, and the caller walks what is complete.
"""

from __future__ import annotations

import re

_FENCE = re.compile(
    r"\A\s*```[A-Za-z0-9_-]*[ \t]*\r?\n(?P<body>.*?)\r?\n?[ \t]*```\s*\Z", re.DOTALL
)
_OPENING = re.compile(r"\A```[A-Za-z0-9_-]*\s*\n(.*)\Z", re.DOTALL)


def unfenced(body):
    """`body` without one enclosing code fence, else `body` unchanged. A value
    that is not text is returned as it is (the caller's parse then refuses it)."""
    if not isinstance(body, str):
        return body
    fence = _FENCE.match(body)
    return fence.group("body") if fence else body


def opened(text: str) -> str:
    """`text` without its OPENING fence only (a cut-off reply), else unchanged."""
    fence = _OPENING.match(text)
    return fence.group(1) if fence else text
