"""Which requirements a review may check (#598).

A standards table has one requirement per cell. A review used to turn every
one of them into a check, so a single datasheet got thousands of "value not
found by the page reader" findings about grades, sizes and materials it never
mentioned. A table cell (`table_value`) is now CHECKED only when the submittal has a field that
answers it, and the cells that are not checked are COUNTED, in one grouped line
per standard, never dropped silently.

MATCHING IS GENERIC. It compares normalised words, never a list of standards
or materials:

  * ROW KEY: the cell's row label ("UNS S31600", "DN 50", "Grade B") is
    matched against the submittal's field VALUES and field names. The
    submittal says "Material: S31600" and the row "UNS S31600" is checked; the
    row for another grade is not.
  * COLUMN FIELD: the cell's column ("Max. clearance") is matched against the
    submittal's field names. It is the handle only for a table whose rows the
    submittal cannot select at all: once any row of a table matches by its key,
    only the matching rows are checked, otherwise every row of a table with a
    matching column would come back.

Also here: a `definition` (#596) and a requirement whose text failed the
quality gate and has not been confirmed (#597) are never checks. Both are read
defensively (`.get`), so this works whether or not those fields exist yet.

Pure functions over dicts. No database, no network.
"""
from __future__ import annotations

import re
from collections import defaultdict

from . import numparse

DEFINITION = "definition"
TEXT_QUALITY = "text_quality"

#: Words that say HOW a column limits a value, not WHAT it limits.
_COLUMN_FILLER = frozenset({
    "max", "maximum", "min", "minimum", "value", "values", "limit", "limits",
    "allowable", "allowed", "permissible", "the", "of", "and", "for", "in"})

_TOKEN = re.compile(r"[a-z0-9]+")


def tokens(text: object) -> tuple[str, ...]:
    """Normalised words: case, spacing and punctuation do not matter."""
    return tuple(_TOKEN.findall(numparse.fold(text or "")))


def _usable(words: tuple[str, ...]) -> bool:
    """Enough to identify something: a word with a digit, or 3+ characters."""
    return bool(words) and (any(any(c.isdigit() for c in w) for w in words)
                            or sum(len(w) for w in words) >= 3)


def _contains(big: tuple[str, ...], small: tuple[str, ...]) -> bool:
    """`small` appears in `big` as a run of whole words."""
    n = len(small)
    return n > 0 and any(big[i:i + n] == small for i in range(len(big) - n + 1))


def _same_thing(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    if not (_usable(a) and _usable(b)):
        return False
    return _contains(a, b) or _contains(b, a)


def excluded_reason(requirement: dict) -> str | None:
    """Why a requirement is never a check, or None.

    A human's confirmation outranks the quality gate (the text was read and
    accepted); nothing outranks a definition.
    """
    if requirement.get("requirement_type") == DEFINITION:
        return DEFINITION
    held = (requirement.get("quality_reason")
            or requirement.get("needs_verification_reason")) == TEXT_QUALITY
    if held and not requirement.get("confirmed_by"):
        return TEXT_QUALITY
    return None


def _is_table_cell(requirement: dict) -> bool:
    # `table_row` is NOT here. It is a sentence that defers to a table, about a
    # named subject ("the maximum allowable working pressure"), and the matcher
    # pairs it by that subject, the model tier included. It is 271 of the
    # 106,832 live requirements, not the flood, and a gate that cannot see the
    # model's pairing would drop rows the matcher would have paired. Table and
    # formula rules (owner order 2a/2b) ride on these rows.
    return requirement.get("requirement_type") == "table_value"


def _fact_words(facts: list[dict]) -> tuple[list[tuple[str, ...]], list[tuple[str, ...]]]:
    """(value words, label words) for every non-blank fact of the submittal."""
    values: list[tuple[str, ...]] = []
    labels: list[tuple[str, ...]] = []
    for fact in facts:
        if fact.get("is_blank"):
            continue
        label = tokens(fact.get("field_label") or fact.get("field_name"))
        if label:
            labels.append(label)
        value = tokens(fact.get("field_value") if fact.get("field_value") not in (None, "")
                       else fact.get("raw_value"))
        if value:
            values.append(value)
    return values, labels


def _row_key(requirement: dict) -> tuple[str, ...]:
    return tokens(requirement.get("condition") or requirement.get("subject"))


def _column_words(requirement: dict) -> tuple[str, ...]:
    return tuple(w for w in tokens(requirement.get("field"))
                 if w not in _COLUMN_FILLER)


def _matches_row(key: tuple[str, ...], values, labels) -> bool:
    return any(_same_thing(key, other) for other in (*values, *labels))


def _matches_column(column: tuple[str, ...], labels) -> bool:
    return any(_same_thing(column, tuple(w for w in label if w not in _COLUMN_FILLER))
               for label in labels)


def gate(requirements: list[dict], facts: list[dict], *,
         standard_names: dict[str, str] | None = None) -> dict:
    """Split `requirements` into what a review checks and what it does not.

    Returns {"kept": [...], "excluded": {"definition": n, "text_quality": n},
    "not_compared": [one grouped line per standard]}. Order of `kept` is the
    order given. Non-table requirements always stay.
    """
    values, labels = _fact_words(facts)
    kept_flags: dict[int, bool] = {}
    excluded: dict[str, int] = defaultdict(int)

    # Rows that match by their key, and which tables have any such row.
    row_matched: dict[int, bool] = {}
    table_selectable: dict[tuple, bool] = defaultdict(bool)
    for index, requirement in enumerate(requirements):
        if excluded_reason(requirement) or not _is_table_cell(requirement):
            continue
        key = _row_key(requirement)
        hit = bool(key) and _matches_row(key, values, labels)
        row_matched[index] = hit
        if hit:
            table_selectable[_table_of(requirement)] = True

    not_compared: dict[str, dict] = {}
    for index, requirement in enumerate(requirements):
        reason = excluded_reason(requirement)
        if reason:
            excluded[reason] += 1
            continue
        if not _is_table_cell(requirement):
            kept_flags[index] = True
            continue
        table = _table_of(requirement)
        checked = row_matched.get(index, False)
        if not checked and not table_selectable[table]:
            column = _column_words(requirement)
            checked = bool(column) and _matches_column(column, labels)
        if checked:
            kept_flags[index] = True
            continue
        standard_id = requirement.get("standard_document_id") or ""
        entry = not_compared.setdefault(standard_id, {
            "standard_document_id": standard_id, "count": 0, "tables": {}})
        entry["count"] += 1
        page = requirement.get("page")
        table_entry = entry["tables"].setdefault(
            table[1], {"page": page, "count": 0, "examples": []})
        table_entry["count"] += 1
        label = (requirement.get("condition") or "").strip()
        if label and label not in table_entry["examples"] and len(table_entry["examples"]) < 5:
            table_entry["examples"].append(label)

    lines = []
    for standard_id, entry in not_compared.items():
        name = (standard_names or {}).get(standard_id) or standard_id
        tables = sorted(entry["tables"].values(), key=lambda t: (t["page"] or 0))
        lines.append({
            "standard_document_id": standard_id,
            "standard_name": name,
            "count": entry["count"],
            "table_count": len(tables),
            "line": (f"{entry['count']} table values in {len(tables)} "
                     f"table{'s' if len(tables) != 1 else ''} of {name} not compared: "
                     "no matching field on this submittal"),
            "tables": tables,
        })
    lines.sort(key=lambda l: (-l["count"], l["standard_name"]))
    return {
        "kept": [r for i, r in enumerate(requirements) if kept_flags.get(i)],
        "excluded": dict(excluded),
        "not_compared": lines,
    }


def _table_of(requirement: dict) -> tuple[str, str]:
    """The table a cell belongs to: the chunk its page was read from."""
    return (requirement.get("standard_document_id") or "",
            requirement.get("chunk_id") or f"page-{requirement.get('page')}")
