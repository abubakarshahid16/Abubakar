"""AI datasheet reading (#646): the model LOCATES each field, code READS its value.

Same rule as requirement extraction (#645, owner decision "AI locates, code
reads"), for the submittal's side. A datasheet page is read in passages of at
most `MAX_WORDS` words; for each field the model returns:

  label        the field's label exactly as printed ("Set pressure");
  value_text   the value exactly as printed next to it ("10 barg",
               "By Contractor", "Yes").

Code then:
  * checks BOTH are in the passage (whitespace and case aside), else the item
    is `could_not_read` with the reason - never kept;
  * READS the value from the verified `value_text`: a figure with a unit
    through the shared reader (`ai_requirements.read_figures`, #653's units,
    a bracketed conversion is one quantity); text with no figure ("Yes",
    "By Contractor", "N/A") is kept as text, never turned into a number;
  * merges duplicates (the same label and value read twice).

The model is the runner's setting (#683); nothing here names a datasheet,
an equipment type or a field. The result is CANDIDATE facts, with page and
quotes; this module writes nothing to the database.
"""
from __future__ import annotations

from . import ai_requirements, ai_task_runner

MAX_WORDS = ai_requirements.MAX_WORDS

SCHEMA = {
    "type": "object",
    "required": ["fields"],
    "properties": {
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["label", "value_text"],
                "properties": {
                    "label": {"type": "string"},
                    "value_text": {"type": "string"},
                },
            },
        },
    },
}

INSTRUCTION = """You read one passage of an equipment datasheet. List every field
that has a value: for each, the field's label exactly as printed, and the value
exactly as printed next to it (with its unit if one is printed). Copy both
character for character. Do not convert, round or explain. Leave out fields
with no value. If there are none, return an empty list."""

TASK = ai_task_runner.register(ai_task_runner.TaskSpec(
    name="datasheet_fields", version="v1", instruction=INSTRUCTION, schema=SCHEMA,
    num_predict=900))

LABEL_NOT_ON_PAGE = "the field label is not on the page"
VALUE_NOT_ON_PAGE = "the value is not on the page"


def _squash(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def _on_page(snippet: str, squashed_page: str) -> bool:
    """`snippet` is on the page as WHOLE words: "10 bar" is not found inside
    "10 barg" (gauge would be lost), "set" not inside "setting"."""
    import re

    s = _squash(snippet)
    return bool(s) and re.search(r"(?<!\w)" + re.escape(s) + r"(?!\w)", squashed_page) is not None


def read_value(value_text: str) -> dict:
    """{"figures": [...], "text": value as printed}. Figures only from a unit-
    bearing number in the verified text; anything else stays text."""
    return {"figures": ai_requirements.read_figures(value_text), "text": value_text.strip()}


def read_page(text: str, *, page: int | None = None, provider=None,
              use_cache: bool = True) -> dict:
    """Candidate fields of one page: {"fields": [{label, value_text, figures,
    page, passage}], "could_not_read": [{passage, reason}], "passages": n}."""
    fields: list[dict] = []
    seen: set[tuple] = set()
    unread: list[dict] = []
    passages = ai_requirements.split_passages(text)
    for index, passage in enumerate(passages):
        result = ai_task_runner.run_task(TASK, passage, provider=provider, use_cache=use_cache)
        if result.state != ai_task_runner.STATE_OK:
            unread.append({"passage": index, "reason": result.reason})
            continue
        squashed = _squash(passage)
        for item in result.data.get("fields") or []:
            label = (item.get("label") or "").strip()
            value = (item.get("value_text") or "").strip()
            if not label or not _on_page(label, squashed):
                unread.append({"passage": index, "reason": LABEL_NOT_ON_PAGE})
                continue
            if not value or not _on_page(value, squashed):
                unread.append({"passage": index, "reason": VALUE_NOT_ON_PAGE})
                continue
            key = (_squash(label), _squash(value))
            if key in seen:
                continue
            seen.add(key)
            fields.append({"label": label, "value_text": value, **read_value(value),
                           "page": page, "passage": index})
    return {"fields": fields, "could_not_read": unread, "passages": len(passages)}
