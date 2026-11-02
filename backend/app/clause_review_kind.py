"""A procedure's requirement about equipment or hardware is not for this document kind: one line, not one row each.

A written procedure cannot meet "the casing shall be of this material", and a row for each such rule buries the rows an
engineer can act on. General for every procedure: nothing here names a standard, a field or a layout.

AI PROPOSES, IN THE SAME ASK. The answer gains two optional fields, so there is no second pass and a repeat is a stored
answer. Asked only when this applies; otherwise the prompt, the schema and the cache key are as they were.

CODE VERIFIES, AND ONLY THEN IS THE ROW LEFT OUT (`not_for_kind`), when all of these hold:
  * the switch is on and the kind is a CONFIRMED procedure (suggested, contested, unknown: today's behaviour);
  * the AI found no passage: a quote, verified or not, stays a row whatever its kind, and so does an unreadable answer;
  * it says `equipment_design`, not `procedure_content` or `unsure`;
  * its `about_quote` is words of this requirement, long enough to show something.
Anything else goes to a row, never to the line. Code checks that the AI's words are the requirement's; it cannot check the
judgement, so every rule id stays listed on the internal copy for an engineer to read.

"Not for this document kind" is not compliant and not "not mentioned", and never counts as checked, decided or a Pass.
"""

from __future__ import annotations

from .config import settings

NOT_FOR_KIND = "not_for_kind"
PROCEDURE = "procedure"
CONFIRMED = "confirmed"
EQUIPMENT = "equipment_design"
#: A shorter quote proves nothing: two words of a requirement can be about anything.
MIN_ABOUT_WORDS = 3
_VERSION = "content-only-v1"

_ASK = """

Also say what the requirement itself asks for, whatever the document says:
- "procedure_content": something a written procedure or method states, does or records.
- "equipment_design": only what a piece of equipment or hardware must be, be made of, or be designed or built to, so that no procedure could meet it.
- "unsure": anything else. When in doubt, "unsure".
With "equipment_design", copy into about_quote at least three words, word for word, of the requirement that show it; otherwise about_quote is null.
Add both to the JSON: "about": "procedure_content" | "equipment_design" | "unsure", "about_quote": string | null."""


def applies(kind: str | None, state: str | None) -> bool:
    return bool(
        settings.clause_review_content_only_enabled
        and kind == PROCEDURE
        and state == CONFIRMED
    )


def system(base: str, kind, state) -> str:
    return base + _ASK if applies(kind, state) else base


def schema(base: dict, kind, state) -> dict:
    """The two fields are optional: an answer without them is still an answer, and stays a row."""
    if not applies(kind, state):
        return base
    extra = {
        "about": {"type": ["string", "null"]},
        "about_quote": {"type": ["string", "null"]},
    }
    return {**base, "properties": {**base["properties"], **extra}}


def version(base: str, kind, state) -> str:
    return f"{base}+{_VERSION}" if applies(kind, state) else base


def ask_fields(
    system_base: str, schema_base: dict, version_base: str, kind, state
) -> dict:
    """The `rp.Packet` fields this module may change, on either lane."""
    return {
        "system": system(system_base, kind, state),
        "json_schema": schema(schema_base, kind, state),
        "prompt_version": version(version_base, kind, state),
    }


def cache_model(model: str, kind, state) -> str:
    """Part of the local answer's key: an answer stored without the fields would keep every requirement a row."""
    return f"{model}|{_VERSION}" if applies(kind, state) else model


def _fold(text) -> str:
    return " ".join(str(text or "").lower().split())


def not_for_kind(
    answer: dict | None, outcome: str, requirement: dict, kind, state
) -> bool:
    """True only when every check in this module's docstring holds. Pure."""
    if not applies(kind, state) or outcome != "no_evidence" or not answer:
        return False
    if answer.get("about") != EQUIPMENT:
        return False
    quote = _fold(answer.get("about_quote"))
    if len(quote.split()) < MIN_ABOUT_WORDS:
        return False
    return quote in _fold(requirement.get("requirement_text"))
