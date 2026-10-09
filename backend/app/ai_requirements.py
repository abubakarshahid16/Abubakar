"""AI requirement extraction (#645): the model reads, code checks every field.

"AI reads, code checks" (owner decision 2026-10-08; rules on #644). One task
reads one passage of at most `MAX_WORDS` words of a standard and returns the
requirements it states, each with:

  quote     the exact words the requirement stands on;
  subject   what the requirement is about;
  operator  <=, <, >=, >, =, range, or none (a requirement with no figure);
  value     the figure as printed (for a range, its lower end);
  value_to  the upper end of a range, or null;
  unit      the unit as printed, or null;
  condition when it applies, or null;
  standard  a standard the requirement names, or null.

NOTHING THE MODEL SAYS IS KEPT ON ITS WORD. Each item is checked in code, and
an item that fails a check is `could_not_read` with the reason - never kept,
never repaired by guessing:

  * the quote must be in the passage (whitespace and case aside);
  * every figure the item states (value, value_to, with its unit) must be in
    THE QUOTE, number and unit together, through the one shared figure check
    (`answer.figure_check`, #653): 11 psi is not 11 %, psig is not psia;
  * a named standard must parse (`standard_ids`) and the quote must cite the
    same standard.

Duplicates (the same figures from the same words, met again in an
overlapping passage) are merged in code. The model is the runner's setting
(`settings.ai_task_model`, qwen3.5:2b by default). No rule here names a
document, a standard or a clause.
"""
from __future__ import annotations

import re

from . import ai_task_runner, numparse, standard_ids

#: Words per task. Under the runner's 300-word limit, so a passage split at a
#: sentence never crosses it (#644 decision b).
MAX_WORDS = 280

OPERATORS = ["<=", "<", ">=", ">", "=", "range", "none"]

SCHEMA = {
    "type": "object",
    "required": ["requirements"],
    "properties": {
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["quote", "subject", "operator", "value", "unit"],
                "properties": {
                    "quote": {"type": "string"},
                    "subject": {"type": "string"},
                    "operator": {"type": "string", "enum": OPERATORS},
                    "value": {"type": ["string", "null"]},
                    "value_to": {"type": ["string", "null"]},
                    "unit": {"type": ["string", "null"]},
                    "condition": {"type": ["string", "null"]},
                    "standard": {"type": ["string", "null"]},
                },
            },
        },
    },
}

INSTRUCTION = """You read one passage of an engineering standard. List every
requirement it states: a sentence with "shall", "must", "is required", "not
less than", "not more than", "maximum", "minimum", or a table row that sets a
limit. For each one give:
- quote: the exact words from the passage the requirement stands on, copied
  character for character (no paraphrase);
- subject: what it is about, in a few words;
- operator: one of <=, <, >=, >, =, range, none (none when it has no figure);
- value: the figure exactly as printed (for a range, the lower end), or null;
- value_to: the upper end of a range, or null;
- unit: the unit exactly as printed next to the figure, or null;
- condition: when it applies, or null;
- standard: a standard the requirement names, or null.
Worked examples, page numbers, clause numbers and document numbers are not
requirements. If the passage states none, return an empty list."""

TASK = ai_task_runner.register(ai_task_runner.TaskSpec(
    name="requirement_extraction",
    version="v1",
    instruction=INSTRUCTION,
    schema=SCHEMA,
    num_predict=900,
))

#: Why an item was not kept (plain words; shown to an engineer, never the text).
QUOTE_NOT_IN_SOURCE = "the quoted words are not in the passage"
FIGURE_NOT_IN_QUOTE = "a figure it states is not in its quote"
UNIT_NOT_IN_QUOTE = "the unit does not match the source"
STANDARD_NOT_READ = "the standard it names could not be read"
STANDARD_NOT_IN_QUOTE = "the standard it names is not in its quote"


def _squash(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def split_passages(text: str, max_words: int = MAX_WORDS) -> list[str]:
    """`text` cut at sentence ends into passages of at most `max_words`
    words. A single sentence longer than that is cut at the word limit."""
    sentences = re.split(r"(?<=[.;:!?])\s+|\n+", (text or "").strip())
    passages: list[str] = []
    current: list[str] = []
    count = 0
    for sentence in sentences:
        words = sentence.split()
        if not words:
            continue
        while len(words) > max_words:
            if current:
                passages.append(" ".join(current)); current, count = [], 0
            passages.append(" ".join(words[:max_words]))
            words = words[max_words:]
        if count + len(words) > max_words and current:
            passages.append(" ".join(current)); current, count = [], 0
        current.extend(words)
        count += len(words)
    if current:
        passages.append(" ".join(current))
    return passages


def check_item(item: dict, passage: str) -> str | None:
    """None when every field the item states is on the page, else the reason."""
    from . import answer

    quote = item.get("quote") or ""
    if not quote.strip() or _squash(quote) not in _squash(passage):
        return QUOTE_NOT_IN_SOURCE
    unit = (item.get("unit") or "").strip()
    for value in (item.get("value"), item.get("value_to")):
        value = (value or "").strip()
        if not value:
            continue
        stated = f"{value} {unit}".strip()
        claimed = {numparse.canonical(n) for n in numparse.find_numbers(stated)}
        if not claimed:
            return FIGURE_NOT_IN_QUOTE
        problem = answer.figure_check(stated, claimed, quote)
        if problem is not None:
            return UNIT_NOT_IN_QUOTE if problem[1] == answer.UNIT_MISMATCH else FIGURE_NOT_IN_QUOTE
    named = (item.get("standard") or "").strip()
    if named:
        if standard_ids.parse(named) is None:
            return STANDARD_NOT_READ
        if not any(standard_ids.same_standard(named, raw)
                   for raw, _s, _e in standard_ids.find_citations(quote)):
            return STANDARD_NOT_IN_QUOTE
    return None


def _key(item: dict) -> tuple:
    """Two items are one requirement when they state the same figures from the
    same words (an overlapping passage reads a sentence twice)."""
    def fig(v):
        found = numparse.find_numbers(v or "")
        return numparse.canonical(found[0]) if found else None
    return (_squash(item.get("quote")), fig(item.get("value")), fig(item.get("value_to")),
            _squash(item.get("unit")))


def extract(text: str, *, provider=None, use_cache: bool = True) -> dict:
    """Read `text` (any length) passage by passage. Returns
    {"requirements": [kept items, each with "passage"], "could_not_read":
    [{"passage", "reason"}], "passages": n, "merged": n}. A passage the model
    could not read, and an item a check rejected, are both listed with the
    reason - neither is guessed at."""
    kept: list[dict] = []
    seen: set[tuple] = set()
    unread: list[dict] = []
    merged = 0
    passages = split_passages(text)
    for index, passage in enumerate(passages):
        result = ai_task_runner.run_task(TASK, passage, provider=provider, use_cache=use_cache)
        if result.state != ai_task_runner.STATE_OK:
            unread.append({"passage": index, "reason": result.reason})
            continue
        for item in result.data.get("requirements") or []:
            reason = check_item(item, passage)
            if reason is not None:
                unread.append({"passage": index, "reason": reason})
                continue
            key = _key(item)
            if key in seen:
                merged += 1
                continue
            seen.add(key)
            kept.append({**item, "passage": index})
    return {"requirements": kept, "could_not_read": unread,
            "passages": len(passages), "merged": merged}
