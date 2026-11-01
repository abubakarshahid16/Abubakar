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
    return next((r for r in found if r in prefer), found[0] if found else None)


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
    found: list[str] = []
    for part in parts:
        if roles_of(part, rules):
            continue
        words = part.split()
        ends = [r for r in text_roles if r.split("_")[-len(words) :] == words]
        if len(ends) == 1 and ends[0] not in found:
            found.append(ends[0])
    return found
