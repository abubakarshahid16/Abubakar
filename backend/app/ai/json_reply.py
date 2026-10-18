"""ONE way to take a model's JSON answer out of a code fence (#455).

A model asked for "JSON and nothing else" sometimes wraps the whole answer
in a Markdown fence (```json ... ```). Four modules each carried their own
copy of the same fence regex: `ai_engineering_check.parse`,
`field_naming._parse`, `reasoning_provider.schema_errors` and
`vision_reader.parse`. They now call `unfenced`, character for character
the same rule, so no reply is read differently than before.

The rule: after the caller's own strip, ONE fence that encloses the whole
answer is removed - an opening line of backticks with an optional
letters-only tag, the body, and a closing fence on its own line at the very
end. Anything else is returned unchanged and is parsed strictly by the
caller; nothing is repaired or guessed.

Three other readers differ ON PURPOSE or have not been aligned yet, and keep
their own behaviour (measured on #455):
  * `ai_engineering_check.parse_partial` removes only the OPENING fence: it
    walks a reply the token cap cut off, which has no closing fence;
  * `reader_api._unfenced` and `claude_datasheet._unfenced` also accept a
    closing fence on the JSON's last line, a tag with digits (```json5) and
    an indented fence. Aligning these four sites with them changes which
    replies count, so it needs the review proof (order 64), not a refactor.
"""
from __future__ import annotations

import re

_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n(.*)\n```$", re.DOTALL)


def unfenced(body: str) -> str:
    """`body` without one enclosing code fence, else `body` unchanged.
    The caller strips first, as each of the four sites always did."""
    fence = _FENCE.match(body)
    return fence.group(1) if fence else body
