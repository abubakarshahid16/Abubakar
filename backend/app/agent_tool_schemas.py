"""Model-facing JSON Schemas of the six agent tools, tolerant argument coercion and refusal hints (#1690). No document text."""

from __future__ import annotations

import json

_S = {"type": "string"}
_FIGURES = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"doc_quote": _S, "clause_quote": _S},
        "required": ["doc_quote", "clause_quote"],
    },
}
#: Real JSON Schemas (what the model is shown). `params` above stays for compatibility.
INPUT_SCHEMAS: dict[str, dict] = {
    "open_page": {
        "type": "object",
        "properties": {
            "doc": {
                "type": "string",
                "description": "document id; the run's own document when left out",
            },
            "page": {
                "type": "integer",
                "minimum": 1,
                "description": "page number, 1-based",
            },
        },
        "required": ["page"],
    },
    "search": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "words to look for"},
            "scope": {
                "type": "array",
                "items": _S,
                "description": "optional document ids; all allowed documents when left out",
            },
        },
        "required": ["query"],
    },
    "get_clause": {
        "type": "object",
        "properties": {"standard": _S, "clause": _S},
        "required": ["standard", "clause"],
    },
    "compare_number": {
        "type": "object",
        "properties": {
            "doc_quote": {
                "type": "string",
                "description": "the document's words holding the figure, with unit",
            },
            "clause_quote": {
                "type": "string",
                "description": "the clause's words holding the figure, with unit",
            },
        },
        "required": ["doc_quote", "clause_quote"],
    },
    "record_finding": {
        "type": "object",
        "properties": {
            "finding": {
                "type": "object",
                "properties": {
                    "item": _S,
                    "doc": _S,
                    "color": {"type": "string", "enum": ["GREEN", "YELLOW", "RED"]},
                    "page": {"type": "integer", "minimum": 1},
                    "doc_quote": _S,
                    "clause_quote": _S,
                    "standard": _S,
                    "clause": _S,
                    "action": _S,
                    "priority": {"type": "string", "enum": ["must", "should", "nice"]},
                    "figures": _FIGURES,
                    "reason": _S,
                },
                "required": ["color", "action", "priority", "reason"],
            }
        },
        "required": ["finding"],
    },
    "judge_row": {  # judge mode only (agent_judge_tools): ONE decision per row of system A's CRS
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": ["CONFIRM", "REMOVE", "UNSURE"]},
            "reason_code": {
                "type": "string",
                "enum": ["complies", "not_applicable", "already_stated"],
                "description": "REMOVE only: one of these three",
            },
            "page": {"type": "integer", "minimum": 1},
            "doc_quote": _S,
            "standard": _S,
            "clause": _S,
            "clause_quote": _S,
            "figures": _FIGURES,
            "reason": {
                "type": "string",
                "description": "at most 30 words, no document text",
            },
            "absent": {
                "type": "boolean",
                "description": "CONFIRM only: the row says something is missing and you found it nowhere",
            },
        },
        "required": ["decision"],
    },
    "ask_engineer": {
        "type": "object",
        "properties": {
            "item": {
                "type": "string",
                "description": "optional: the current item is used",
            },
            "why": {
                "type": "string",
                "description": "why the engineer must decide, at most 30 words",
            },
        },
        "required": ["why"],
    },
}


def coerce_page(value: object) -> tuple[int | None, str | None]:
    """(page, None) or (None, code). 1, 1.0, "1", "1.0" and " 1 " are page 1; 0, negatives and non-numbers are refused."""
    if isinstance(value, bool) or value is None:
        return None, "page_missing_or_not_a_number"
    number: float | None = None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            number = None
    if (
        number is None
        or number != number
        or number in (float("inf"), float("-inf"))
        or number != int(number)
    ):
        return None, "page_missing_or_not_a_number"
    if number < 1:
        return None, "page_must_be_1_or_more"
    return int(number), None


def coerce_scope(value: object) -> list[str] | None:
    """None (the default scope) for null, empty or unreadable; else a list of document ids from a list, a comma list or JSON text."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.startswith("["):
            try:
                value = json.loads(text)
            except ValueError:
                value = text.strip("[]").split(",")
        else:
            value = text.split(",")
    if isinstance(value, (list, tuple, set, frozenset)):
        ids = [
            str(v).strip().strip("\"'")
            for v in value
            if isinstance(v, (str, int)) and str(v).strip()
        ]
        return ids or None
    return None


def expect_of(name: str) -> dict:
    """The argument NAMES and types a tool expects (a hint for a retry; no text)."""
    schema = INPUT_SCHEMAS.get(name) or {}
    required = set(schema.get("required") or [])
    return {
        k: (v.get("type", "any") + ("" if k in required else "?"))
        for k, v in (schema.get("properties") or {}).items()
    }


#: Names a model may use for an argument; mapped to the real one.
ARG_ALIASES = {
    "document": "doc", "document_id": "doc", "doc_id": "doc", "page_no": "page", "page_number": "page",
    "q": "query", "question": "query", "search_query": "query", "documents": "scope", "doc_ids": "scope",
    "clause_number": "clause", "standard_id": "standard",
}  # fmt: skip
