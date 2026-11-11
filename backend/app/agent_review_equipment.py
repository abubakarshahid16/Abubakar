"""The equipment filter of the AI reviewer: it only ever REMOVES rules and checklist items (order 16.2 note 4).

The paper's equipment comes from the app's reader (`subject_scope.read_equipment`) mapped by DATA (`reference/equipment_mapping.json`)
onto the closed taxonomy (`reference/equipment_taxonomy.json`); a rule's equipment label is in `rule_equipment_label`. No
equipment word is written in code (rule 13). A rule is removed only when its label is `agreed` and NAMES a type or family that
is not the paper's; a rule that is general, whose label is not agreed, or that names nothing is asked. When the paper's
equipment is not usable (none named / named but not on the list / could not be read) only the rules that NAME an equipment are
removed, each with its own true reason. A missing equipment table or label is "equipment not known": asked as today."""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from . import rule_equipment

ANOTHER_EQUIPMENT = "another_equipment_type"
NO_EQUIPMENT = "paper_names_no_equipment"
NOT_IN_LIST = (
    "paper_equipment_not_in_list"  # the paper names equipment the mapping does not know
)
UNREADABLE = "paper_equipment_unreadable"  # the app's reader could not decide what the paper is about
PAPER_EQUIPMENT_REASONS = (NO_EQUIPMENT, NOT_IN_LIST, UNREADABLE)

# ---- the equipment filter: only ever REMOVES rules ------------------------------------------------------------------------

EQUIPMENT_MODES = ("off", "on", "type", "family")  # "on" is an alias of "type"


def norm_mode(mode: Any) -> str | None:
    """None (filter off), "type" ("on" or "type") or "family"."""
    m = str(mode or "off").strip().lower()
    if m not in EQUIPMENT_MODES:
        raise ValueError(f"the equipment filter is one of {EQUIPMENT_MODES}")
    return None if m == "off" else ("type" if m == "on" else m)


@dataclass(frozen=True)
class PaperEquipment:
    """What the paper is about, in taxonomy ids. `named`: the reader found equipment; `types` is empty when it found some the
    mapping does not know (then the paper's equipment is not usable)."""

    types: frozenset[str] = frozenset()
    families: frozenset[str] = frozenset()
    named: bool = False
    app_names: tuple[str, ...] = ()
    state: str = "none"  # read | none | unmapped | unreadable
    core_types: frozenset[str] = (
        frozenset()
    )  # the paper's own types WITHOUT the `related` data (rules only use `related`)

    @property
    def usable(self) -> bool:
        return bool(self.types)


@dataclass(frozen=True)
class EquipmentCtx:
    """Everything the filter needs for one paper: its equipment, the taxonomy, the mapping and the mode."""

    eq: PaperEquipment
    tax: rule_equipment.Taxonomy
    mapping: Mapping
    mode: str = "type"


def paper_equipment(
    conn: sqlite3.Connection,
    document_id: str,
    tax: rule_equipment.Taxonomy,
    mapping: Mapping,
) -> PaperEquipment:
    """The paper's equipment: the app's reader (`subject_scope.read_equipment`: stored classification, then title) gives app
    names; the mapping data turns them into taxonomy type ids; a more specific taxonomy type named by the classification text
    whose `also_applies` lists a mapped type is added; optional `related` data adds equipment a type is also read against. A type
    also stands for everything it lists under `also_applies`."""
    from . import subject_scope

    names = mapping.get("map") or {}
    try:
        row = conn.execute(
            "SELECT equipment_type, title FROM document_classification WHERE document_id = ?",
            (document_id,),
        ).fetchone()
    except sqlite3.Error:
        row = None
    record = {"equipment_type": row[0], "title": row[1]} if row else {}
    found, _source, doubt = subject_scope.read_equipment(
        record, [], subject_scope.vocabulary()
    )
    types = {names[n] for n in found if n in names}
    text = rule_equipment._norm(record.get("equipment_type"))
    if text and types:
        for label, tid in tax.names.items():
            if (
                label
                and f"_{label}_" in f"_{text}_"
                and set(tax.also.get(tid, ())) & tax.expand(types)
            ):
                types.add(tid)
    related_map = mapping.get("related") or {}
    related = {
        r for t in list(types) for r in related_map.get(t, []) if r in tax.type_family
    }
    every = types | related
    state = (
        "read"
        if types
        else ("unmapped" if found else ("unreadable" if doubt is not None else "none"))
    )
    return PaperEquipment(
        frozenset(tax.expand(every)) if every else frozenset(),
        frozenset(tax.type_family[t] for t in every if t in tax.type_family),
        bool(found),
        tuple(sorted(found)),
        state,
        frozenset(tax.expand(types)),
    )


def equipment_decision(
    label: Mapping, eq: PaperEquipment, tax: rule_equipment.Taxonomy, mode: str = "type"
) -> tuple[bool, str, str | None]:
    """(keep, reason, family left out). A rule is left out ONLY when its equipment label is `agreed` and names another type
    (mode "family": another FAMILY; a sibling type of the paper's family is asked). Kept: general, same_equipment,
    equipment_not_known (the label is not agreed, or names nothing: no ground to remove it). Removed: another_equipment_type;
    paper_names_no_equipment (the paper names no usable equipment: every rule that names a type or a family goes)."""
    if str(label.get("equip_state") or "") != rule_equipment.AGREED:
        return True, "equipment_not_known", None
    if int(label.get("equip_general") or 0) == 1:
        return True, "general", None
    rtype, rfam = label.get("equip_type") or None, label.get("equip_family") or None
    if not (
        rtype or rfam
    ):  # agreed but names nothing: no ground to remove it, whatever the paper's equipment
        return True, "equipment_not_known", None
    if not eq.usable:  # the paper's equipment is not usable: only a rule that NAMES an equipment is removed
        reason = {"unmapped": NOT_IN_LIST, "unreadable": UNREADABLE}.get(
            eq.state, NO_EQUIPMENT
        )
        return False, reason, rfam or tax.type_family.get(rtype or "")
    if mode == "family":
        fam = rfam or tax.type_family.get(rtype or "")
        if fam is None:
            return True, "equipment_not_known", None
        return (
            (True, "same_equipment", None)
            if fam in eq.families
            else (False, ANOTHER_EQUIPMENT, fam)
        )
    if rtype:
        if rtype in eq.types:
            return True, "same_equipment", None
        return False, ANOTHER_EQUIPMENT, rfam or tax.type_family.get(rtype)
    if rfam:
        return (
            (True, "same_equipment", None)
            if rfam in eq.families
            else (False, ANOTHER_EQUIPMENT, rfam)
        )
    return True, "equipment_not_known", None


def load_equipment(
    conn: sqlite3.Connection, document_id: str, mode: Any = "type"
) -> EquipmentCtx | None:
    """The equipment context of one paper, or None when the filter is off. A database without the equipment labels table is
    NOT an error: every rule then has no label, which is "equipment not known" (asked as today, counted)."""
    m = norm_mode(mode)
    if m is None:
        return None
    tax, mapping = rule_equipment.Taxonomy.load(), rule_equipment.load_mapping()
    return EquipmentCtx(
        paper_equipment(conn, document_id, tax, mapping), tax, mapping, m
    )


def equipment_skill_fits(types_app: set[str], ctx: EquipmentCtx) -> bool:
    """The same notion of "same equipment" for a checklist item: its app equipment names, mapped, meet the paper's types."""
    names = ctx.mapping.get("map") or {}
    return (
        bool({names[n] for n in types_app if n in names} & ctx.eq.core_types)
        if ctx.eq.usable
        else False
    )


def equipment_block(ctx: EquipmentCtx, why_kept: Mapping[str, Mapping]) -> dict:
    """The equipment facts of one list for the Rules used record and the CRS: the paper's equipment and how the asked rules
    matched (counts only)."""
    kept = Counter(
        w.get("equipment_why") for w in why_kept.values() if w.get("equipment_why")
    )
    return {
        "paper_types": sorted(ctx.eq.types),
        "paper_families": sorted(ctx.eq.families),
        "paper_named_equipment": ctx.eq.named,
        "paper_usable": ctx.eq.usable,
        "paper_equipment_state": ctx.eq.state,
        "asked_by_equipment": dict(kept),
    }
