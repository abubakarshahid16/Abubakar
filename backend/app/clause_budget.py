"""Who gets the clause-check budget (order 235.1).

`ai_clause_checks_max_per_run` caps how many clause sentences are put to the
local model. The sentences that can become a check on THIS sheet go first: one
that names a field the sheet states (its vocabulary, `field_naming.sheet_names`),
then one that prints a figure, then the rest in their stored order. Nothing here
reads a layout or a label spelling: a sentence is tied to a field when a whole
field name stands in it as whole words, any sheet.

Also the count per standard, so a run says where the budget went."""

from __future__ import annotations

import re

_WORDS = re.compile(r"[a-z0-9]+")
_FIGURE = re.compile(r"\d")


def _tokens(text: str) -> list[str]:
    return _WORDS.findall(str(text or "").lower())


def _names_a_field(sentence: str, names: list[list[str]]) -> bool:
    words = _tokens(sentence)
    for name in names:
        n = len(name)
        if n and any(words[i : i + n] == name for i in range(len(words) - n + 1)):
            return True
    return False


def sheet_names(facts: list[dict] | None) -> list[str]:
    """The sheet's stated fields' names (numbers and blanks it prints)."""
    from . import field_naming

    return field_naming.sheet_names(facts or [])


def order(
    requirements: list[dict], sentence_of, sheet_names: list[str] | None
) -> list[dict]:
    """Stable order: tied to a stated field, then prints a figure, then the rest."""
    names = [t for t in (_tokens(n) for n in sheet_names or []) if t]

    def key(r: dict) -> tuple[bool, bool]:
        text = sentence_of(r)
        return (not _names_a_field(text, names), not _FIGURE.search(text))

    return sorted(requirements, key=key)


def per_standard(requirements: list[dict], asked: int) -> dict[str, dict[str, int]]:
    """{standard: {asked, not_asked}} for requirements already in ask order; the
    first `asked` were put to the model."""
    out: dict[str, dict[str, int]] = {}
    for i, r in enumerate(requirements):
        name = str(r.get("standard_name") or r.get("standard_document_id") or "")
        row = out.setdefault(name, {"asked": 0, "not_asked": 0})
        row["asked" if i < asked else "not_asked"] += 1
    return out
