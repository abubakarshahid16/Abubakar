"""#1584: the rules still readable in a paid answer that does not parse as a whole. Pure: no database, no model.

An answer may open with words before its JSON, or one rule may be broken. Each rule that reads whole on its own and fits
the schema is kept for the usual proof, which decides as it does for any other. Nothing is repaired or completed: a rule
cut off at the end is dropped.

`whole` says nothing was lost: one rule list, closed, every object in it read. Only that may count as answered.
"""

from __future__ import annotations

import json
import re

from .compiled_rule_proof import ANSWER_SCHEMA
from .reasoning_provider import schema_errors

_RULES = re.compile(r'"rules"\s*:\s*\[')
_DECODER = json.JSONDecoder()


def _fits(rule: object) -> bool:
    return isinstance(rule, dict) and not schema_errors(
        json.dumps({"rules": [rule]}), ANSWER_SCHEMA
    )


def rescued(text: str) -> tuple[list[dict], bool]:
    """(the rules readable in `text`, whether nothing was lost)."""
    lists = list(_RULES.finditer(text))
    if not lists:
        return [], False
    rules: list[dict] = []
    # A draft and a final list: the last is read, and which was meant is not proven.
    whole = len(lists) == 1
    at = lists[-1].end()
    while True:
        separator = re.compile(r"[\s,]*").match(text, at)
        at = separator.end()
        if at >= len(text):
            return rules, False  # never closed
        if text[at] == "]":
            return rules, whole and bool(re.compile(r"\s*\}").match(text, at + 1))
        if text[at] != "{":
            whole = False
            at = text.find("{", at)
            if at < 0:
                return rules, False
            continue
        try:
            rule, at = _DECODER.raw_decode(text, at)
        except ValueError:
            whole = False
            at = text.find("{", at + 1)
            if at < 0:
                return rules, False
            continue
        if _fits(rule):
            rules.append(rule)
        else:
            whole = False
