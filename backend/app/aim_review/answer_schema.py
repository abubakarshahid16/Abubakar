"""The answer shape of each model step as a JSON schema, for an engine that can force it (the local engine's `format`; planner
note 25 Nov 2026 23:05: forced output lifts a small model's structural validity, it does not lift its understanding).

The schema says what the step's prompt already asks; code checks every answer the same way afterwards (`prompts.parse_json`
and each step's own checks), so a schema never decides anything. The judge's schema lists "numbers" among the fields every
judgment carries (an object, or null when there is no limit), so a small model is asked for it on every item. A step with no
full schema of its own gets none (plain JSON). Shapes only; no text."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_LABELS = ["Met", "Not met", "Question", "Does not apply", "AI opinion"]
_STR, _INT, _BOOL = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}


def _text(most: int) -> dict:
    """A string of at most `most` characters: the forced shape always closes (26 Nov 2026: the 14B wrote checklist answers that
    never ended, 8,192 tokens out of 1,500 in)."""
    return {"type": "string", "maxLength": most}


#: At most this many checklist items per call (a 9,000-character batch holds about 12 rules) and judgments per call.
MAX_ITEMS, MAX_JUDGMENTS = 24, 24
_PAGE = {"anyOf": [_INT, {"type": "null"}]}
_NUMBERS = {
    "anyOf": [
        {
            "type": "object",
            "properties": {
                "paper_value": _STR,
                "paper_unit": _STR,
                "operator": {"enum": ["<=", ">=", "<", ">", "==", "!="]},
                "rule_value": _STR,
                "rule_unit": _STR,
                "limit_quote": _STR,
                "limit_page": _PAGE,
            },
            "required": [
                "paper_value",
                "paper_unit",
                "operator",
                "rule_value",
                "rule_unit",
            ],
        },
        {"type": "null"},
    ]
}
_JUDGMENT = {
    "type": "object",
    "properties": {
        "id": _STR,
        "label": {"enum": _LABELS},
        "field": _text(120),
        "page": _PAGE,
        "quote": _text(400),
        "deferred": _BOOL,
        "ask": {"enum": ["concern", "confirm", ""]},
        "numbers": _NUMBERS,
        "comment": _text(600),
        "not_here": _BOOL,
        "other": {"type": "object", "properties": {"page": _PAGE, "quote": _text(400)}},
        "items": {"type": "array", "items": _text(120), "maxItems": 4},
    },
    "required": ["id", "label", "field", "page", "quote", "numbers", "comment"],
}
_ITEM = {
    "type": "object",
    "properties": {
        "topic": _text(80),
        "what_to_check": _text(300),
        "book": _text(20),
        "clause": _text(40),
        "page": _PAGE,
        "rule_quote": _text(400),
        "applies_when": _text(200),
        "paper_fields": {"type": "array", "items": _text(80), "maxItems": 6},
        "paper_pages": {"type": "array", "items": _INT, "maxItems": 10},
        "kind": _text(20),
        "source": _text(40),
        "stands_in_for": _text(120),
        "carried_by": _text(120),
    },
    # book, clause, page, rule_quote and source are required too (F's 9B run on update 10, 91f40e4f: with them optional the
    # model left them out, an item with no source counts as a held standard, and about 190 such items had no book and no
    # quote to find: 117 were set aside unasked). A knowledge item gives them empty, as the task says.
    "required": [
        "topic",
        "what_to_check",
        "book",
        "clause",
        "page",
        "rule_quote",
        "applies_when",
        "paper_fields",
        "kind",
        "source",
    ],
}
_ITEMS = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": _ITEM, "maxItems": MAX_ITEMS}},
    "required": ["items"],
}

#: The local attack's answer (`attack_local`): one short fixed verdict per item, each bounded.
_VERDICT = {
    "type": "object",
    "properties": {
        "id": _text(12),
        "verdict": {"enum": ["keep", "remove", "fix"]},
        "why": _text(160),
        "what_to_check": _text(300),
    },
    "required": ["id", "verdict", "why", "what_to_check"],
}

SCHEMAS: dict[str, dict] = {
    "aim_attack_items": {
        "type": "object",
        "properties": {
            "verdicts": {"type": "array", "items": _VERDICT, "maxItems": 12}
        },
        "required": ["verdicts"],
    },
    "aim_judge": {
        "type": "object",
        "properties": {
            "judgments": {
                "type": "array",
                "items": _JUDGMENT,
                "maxItems": MAX_JUDGMENTS,
            }
        },
        "required": ["judgments"],
    },
    "aim_second_read": {
        "type": "object",
        "properties": {
            "reads": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "n": _INT,
                        "label": {"enum": _LABELS},
                        "page": _PAGE,
                        "quote": _STR,
                        "reason": _STR,
                    },
                    "required": ["n", "label", "page", "quote", "reason"],
                },
            }
        },
        "required": ["reads"],
    },
    "aim_checklist": _ITEMS,
    "aim_checklist_retry": _ITEMS,
    "aim_checklist_knowledge": _ITEMS,
}
#: Role 5 of the nine roles (`missed.STEP`) asks the judge's own question again: the judge's answer shape.
SCHEMAS["aim_checklist_missed"] = SCHEMAS["aim_judge"]


#: The checklist call in force may hold at most this many items (`items_at_most`, set by the caller per batch); None: MAX_ITEMS.
_ITEMS_HINT: ContextVar[int | None] = ContextVar("aim_answer_items_hint", default=None)
_ITEM_STEPS = ("aim_checklist", "aim_checklist_retry", "aim_checklist_knowledge")


@contextmanager
def items_at_most(n: int | None) -> Iterator[None]:
    """The items one checklist call may hold, from its batch's size (lead-4, 26 Nov 2026: a fixed cap let a small batch loop)."""
    token = _ITEMS_HINT.set(n)
    try:
        yield
    finally:
        _ITEMS_HINT.reset(token)


def for_step(step: str) -> dict | None:
    """The step's own schema, or None (the engine's plain JSON mode). A step without a full shape of its own gets NO schema: a
    schema naming only its answer keys let the local model write those keys alone (26 Nov 2026: the paper's identity came back
    as the kind only, 30 tokens against 741, and the review lost its equipment type and subject). A checklist step's item cap
    follows the batch in force (`items_at_most`)."""
    shape, n = SCHEMAS.get(step), _ITEMS_HINT.get()
    if shape is None or not n or step not in _ITEM_STEPS:
        return shape
    items = {**shape["properties"]["items"], "maxItems": min(MAX_ITEMS, int(n))}
    return {**shape, "properties": {**shape["properties"], "items": items}}
