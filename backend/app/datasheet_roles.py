"""Which role a datasheet field name states (#900).

A name can fit more than one role: "rated capacity" is a pump's rated flow and
a relief valve's rated relieving capacity. The roles table lists the pump role
first, so the first match alone read a valve's rated capacity as a pump flow
and the valve's own checks found no rated capacity (PF1, #881).

RULE, GENERIC: when a name fits several roles, the role the sheet's own
equipment type checks wins; no role of that type, or no type, keeps the first
in table order exactly as before. The roles a type checks are read from the
table's own mandatory list and checklist, never from a list written here, and
no label or type is named in this file.
"""

from __future__ import annotations

import re


def roles_of(field_name: str, rules: dict) -> list[str]:
    """Every role whose name patterns match the field name, in table order."""
    from .datasheet_checks import _fold

    name = _fold(field_name)
    return [
        role
        for role, spec in rules["roles"].items()
        if any(re.search(p, name) for p in spec["names"])
    ]


def role_of(
    field_name: str, rules: dict, prefer: frozenset = frozenset()
) -> str | None:
    """The first matching role, or the first one in `prefer` when several match."""
    found = roles_of(field_name, rules)
    # switch `datasheet_label_join_enabled`: a split abbreviation ("tube o d")
    if not found:
        found = _joined_roles(field_name, rules)
    return next((r for r in found if r in prefer), found[0] if found else None)


def _joined_roles(field_name: str, rules: dict) -> list[str]:
    """The roles a name states once its split abbreviation is joined; [] with the switch off."""
    from .config import settings

    if not settings.datasheet_label_join_enabled:
        return []
    from .datasheet_checks import _fold
    from .label_match import joined_letters

    joined = joined_letters(_fold(field_name))
    return roles_of(joined, rules) if joined != _fold(field_name) else []


def wanted_roles(equipment_type: str | None, rules: dict) -> frozenset:
    """The roles this equipment type's mandatory list and checklist use: every
    string in them that names a role."""
    from . import datasheet_checks

    roles = rules["roles"]
    found = set(
        rules["mandatory"].get(
            datasheet_checks.mandatory_list_key(equipment_type, rules), []
        )
    )
    items = (datasheet_checks.checklist_for(equipment_type, rules) or {}).get(
        "items", []
    )

    def walk(node) -> None:
        if isinstance(node, str):
            found.add(node)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk([[i.get("rule"), i.get("condition")] for i in items])
    return frozenset(found & set(roles))


_JOINERS = re.compile(r"\s*(?:/|,|&|;|\band\b)\s*")


def combined_roles(label: str, rules: dict, wanted: frozenset) -> list[str]:
    """#1472: the TEXT roles a combined label names ("a / b, c" lists three attributes).

    A part answers a role when its words are the tail of the role's own name
    ("rating" ends "inlet rating") AND it ends exactly one wanted text role - a part
    that ends several ("type", "size", "material") answers none, and a part that is a
    complete field name on its own is not an attribute of a longer line. Only text
    roles: a numeric field ("design / operating pressure") is never answered by a line
    that holds two numbers. The caller decides what such a line may say.
    """
    from .datasheet_checks import _fold

    parts = [_fold(p) for p in _JOINERS.split(label or "")]
    parts = [p for p in parts if p]
    if len(parts) < 2:
        return []
    text_roles = [
        r
        for r, spec in rules["roles"].items()
        if spec.get("kind") == "text" and r in wanted
    ]
    pair_words = _pair_words(rules)
    found: list[str] = []
    for part in parts:
        if roles_of(part, rules):
            continue
        words = part.split()
        ends = [r for r in text_roles if r.split("_")[-len(words) :] == words]
        if len(ends) != 1 or ends[0] in found:
            continue
        qualifier = set(ends[0].split("_")[: -len(words)])
        others = [r for p in parts if p != part for r in roles_of(p, rules)]
        if qualifier and not _agrees(qualifier, others, pair_words):
            continue
        found.append(ends[0])
    return found


def _pair_words(rules: dict) -> frozenset:
    """Qualifier words the roles table itself sets against each other (inlet / outlet):
    the first words of two role names that differ only there."""
    tails: dict[tuple, set] = {}
    for role in rules["roles"]:
        head, *rest = role.split("_")
        tails.setdefault(tuple(rest), set()).add(head)
    return frozenset(w for heads in tails.values() if len(heads) > 1 for w in heads)


def _agrees(qualifier: set, others: list[str], pair_words: frozenset) -> bool:
    """An unqualified part ("rating") answers a qualified role ("inlet rating") only when
    another part of the label names a role of that same qualifier ("valve size" is an
    inlet size) and none names the opposite one ("outlet size")."""
    named = [set(r.split("_")) for r in others]
    if any((w & pair_words) - qualifier for w in named):
        return False
    return any(qualifier <= w for w in named)


def add_combined(facts: list[dict], by_tag: dict, rules: dict, wanted) -> None:
    """#1472 (switch `datasheet_one_value_enabled`): a combined label ("a / rating / c")
    answers the text attribute it names, for a tag with no value of its own under that
    role. The copy carries `combined_label`; `combined_result` never decides on it."""
    from .config import settings

    if not settings.datasheet_one_value_enabled:
        return
    shared = by_tag.get(None, {})
    for fact in facts:
        label = str(fact.get("field_label") or fact.get("field_name") or "")
        for role in combined_roles(label, rules, wanted):
            mine = by_tag.setdefault(fact.get("equipment_tag"), {})
            if not mine.get(role) and not shared.get(role):
                mine.setdefault(role, []).append({**fact, "combined_label": label})


def combined_result(fact: dict, field: str, res):
    """The row for a value that sits inside a combined line: code cannot say which part
    is this field's, so it is an engineer's question (a blank line is judged before this)."""
    from .datasheet_checks import (
        NEEDS_ENGINEER_REVIEW,
        _label,
        _pretty,
        _said,
        _sentence,
    )

    return res(
        NEEDS_ENGINEER_REVIEW,
        _sentence(
            f"the {_pretty(field).lower()} is given inside the combined line "
            f"'{_label(fact, field)}' (page {fact.get('page')}): '{_said(fact)}'; "
            "engineer to check that part"
        ),
        fact,
    )


def with_roles(facts: list[dict], rules: dict, wanted) -> list[dict]:
    """The facts, each bare part-name fact that strictly satisfies `part_name_roles` renamed to its role (switch off:
    as given)."""
    from .part_name_roles import with_roles as renamed

    return renamed(facts, rules, wanted)
