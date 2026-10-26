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
