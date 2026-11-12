"""The equipment filter of the AI reviewer: it only ever REMOVES rules and checklist items (order 16.2 note 4).

The paper's equipment comes from the app's reader (`subject_scope.read_equipment`) mapped by DATA (`reference/equipment_mapping.json`)
onto the closed taxonomy (`reference/equipment_taxonomy.json`); a rule's equipment label is in `rule_equipment_label`. No
equipment word is written in code (rule 13). A rule is removed only when its label is `agreed` and NAMES a type or family that
is not the paper's; a rule that is general, whose label is not agreed, or that names nothing is asked. When the paper's
equipment is not usable (none named / named but not on the list / could not be read) only the rules that NAME an equipment are
removed, each with its own true reason. A missing equipment table or label is "equipment not known": asked as today."""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from . import rule_equipment

ANOTHER_EQUIPMENT = "another_equipment_type"
NO_EQUIPMENT = "paper_names_no_equipment"
NOT_IN_LIST = (
    "paper_equipment_not_in_list"  # the paper names equipment the mapping does not know
)
UNREADABLE = "paper_equipment_unreadable"  # the app's reader could not decide what the paper is about
PAPER_EQUIPMENT_REASONS = (NO_EQUIPMENT, NOT_IN_LIST, UNREADABLE)
#: a rule about a part (the label's `equip_part`) that the paper's own facts and pages show its equipment does not have
PART_ABSENT = "part_not_on_paper"
#: the two labelling readers disagreed with each other, and BOTH named equipment that is not the paper's
TWO_READERS_OTHER = "two_readers_other_equipment"

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
    #: related type id -> the approved label fields whose rules are kept (None: every rule of that type). Types that are
    #: the paper's own are never in it.
    related_fields: Mapping[str, frozenset[str] | None] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return bool(self.types)


@dataclass(frozen=True)
class PaperEvidence:
    """What code can read about one paper's parts: per part-stating role the stored facts (value, label and quote text), whether
    every such fact is complete and trusted, and the words on the paper's stored pages. Words only, never shown."""

    role_words: Mapping[str, frozenset[str]] = field(default_factory=dict)
    role_complete: Mapping[str, bool] = field(default_factory=dict)
    page_words: frozenset[str] = frozenset()
    pages_readable: bool = False


@dataclass(frozen=True)
class EquipmentCtx:
    """Everything the filter needs for one paper: its equipment, the taxonomy, the mapping and the mode. `evidence` (the
    paper's facts and page words) is optional: without it no rule is left out for a part."""

    eq: PaperEquipment
    tax: rule_equipment.Taxonomy
    mapping: Mapping
    mode: str = "type"
    evidence: PaperEvidence | None = None


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
    related: set[str] = set()
    only: dict[str, frozenset[str] | None] = {}
    core = tax.expand(types)
    for t in list(types):
        entry = related_map.get(t) or []
        # a list names types whose every rule counts; a {type: [fields]} object names the fields whose rules count
        wanted = dict.fromkeys(entry) if isinstance(entry, list) else dict(entry)
        for r, fields in wanted.items():
            if r not in tax.type_family:
                continue
            related.add(r)
            for stands_for in tax.expand({r}) - core:
                if only.get(stands_for, frozenset()) is None or fields is None:
                    only[stands_for] = None
                else:
                    only[stands_for] = only.get(stands_for, frozenset()) | frozenset(
                        fields
                    )
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
        frozenset(core),
        only,
    )


def _related_only_blocks(
    eq: PaperEquipment,
    tax: rule_equipment.Taxonomy,
    rtype: str | None,
    rfam: str | None,
    rule_field: str | None,
) -> bool:
    """True when the rule's type (or, with no type, its family) is in the paper's equipment ONLY through the `related` data and
    that data names fields the rule's approved label field is not among. A rule with no field is not named, so it is blocked
    too (the data line is an allow-list). The paper's own types and families are never gated."""
    if rtype:
        if rtype in eq.core_types or rtype not in eq.related_fields:
            return False
        allowed = eq.related_fields[rtype]
        return allowed is not None and rule_field not in allowed
    if not rfam or rfam in {tax.type_family.get(t) for t in eq.core_types}:
        return False
    ours = [v for t, v in eq.related_fields.items() if tax.type_family.get(t) == rfam]
    if not ours or any(v is None for v in ours):
        return False
    return rule_field not in frozenset().union(*ours)


def _both_readers_name_other_equipment(
    label: Mapping,
    eq: PaperEquipment,
    tax: rule_equipment.Taxonomy,
    mode: str,
    rule_field: str | None,
) -> str | None:
    """For a label the two readers did not agree on: the family left out when BOTH stored answers are valid, neither says
    "general", each names a type or a family, and the paper's own decision (`equipment_decision` on that answer alone) would
    leave each one out as another equipment type. Anything else (a missing, unparseable or invalid answer, "general", an
    answer that names nothing, one that names the paper's equipment or a related field the data line allows, a paper whose
    equipment is not usable): None, and the rule is asked."""
    if (
        str(label.get("equip_state") or "") != rule_equipment.NEEDS_HUMAN
        or not eq.usable
    ):
        return None
    families = []
    for which in ("a", "b"):
        ans = rule_equipment.answer_of(label, which)
        if ans is None or ans["general"] or not (ans["type"] or ans["family"]):
            return None
        keep, why, fam = equipment_decision(
            {
                "equip_state": rule_equipment.AGREED,
                "equip_type": ans["type"],
                "equip_family": ans["family"],
                "equip_general": 0,
            },
            eq,
            tax,
            mode,
            rule_field,
        )
        if keep or why != ANOTHER_EQUIPMENT:
            return None
        families.append(fam)
    return families[0] or families[1] or "unnamed"


def equipment_decision(
    label: Mapping,
    eq: PaperEquipment,
    tax: rule_equipment.Taxonomy,
    mode: str = "type",
    rule_field: str | None = None,
) -> tuple[bool, str, str | None]:
    """(keep, reason, family left out). A rule is left out ONLY when its equipment label is `agreed` and names another type
    (mode "family": another FAMILY; a sibling type of the paper's family is asked). Kept: general, same_equipment,
    equipment_not_known (the label is not agreed, or names nothing: no ground to remove it). Removed: another_equipment_type
    (also a related type's rule whose field the data line does not name); paper_names_no_equipment (the paper names no usable
    equipment: every rule that names a type or a family goes). `rule_field` is the rule's approved label field."""
    if str(label.get("equip_state") or "") != rule_equipment.AGREED:
        both = _both_readers_name_other_equipment(label, eq, tax, mode, rule_field)
        if both is not None:
            return False, TWO_READERS_OTHER, both
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
    fam_of_rule = rfam or tax.type_family.get(rtype or "")
    if mode == "family":
        if fam_of_rule is None:
            return True, "equipment_not_known", None
        if fam_of_rule not in eq.families:
            return False, ANOTHER_EQUIPMENT, fam_of_rule
        if _related_only_blocks(eq, tax, None, fam_of_rule, rule_field):
            return False, ANOTHER_EQUIPMENT, fam_of_rule
        return True, "same_equipment", None
    if rtype:
        if rtype not in eq.types or _related_only_blocks(
            eq, tax, rtype, None, rule_field
        ):
            return False, ANOTHER_EQUIPMENT, fam_of_rule
        return True, "same_equipment", None
    if rfam:
        if rfam not in eq.families or _related_only_blocks(
            eq, tax, None, rfam, rule_field
        ):
            return False, ANOTHER_EQUIPMENT, rfam
        return True, "same_equipment", None
    return True, "equipment_not_known", None


# ---- a part the paper's equipment does not have (only facts code can read; in doubt the rule is asked) ---------------------

_WORD = re.compile(r"[a-z0-9]+")


def _words(*texts: Any) -> frozenset[str]:
    return frozenset(w for t in texts for w in _WORD.findall(str(t or "").lower()))


def load_evidence(
    conn: sqlite3.Connection, document_id: str, mapping: Mapping
) -> PaperEvidence | None:
    """The paper's stored facts of the roles the data line `part_roles` names, and the words of its stored pages. None when
    the data names no role, a table is missing, or anything cannot be read (then no rule is left out for a part)."""
    roles = {str(r) for r in (mapping.get("part_roles") or [])}
    if not roles:
        return None
    from . import datasheet_checks
    from .datasheets import normalise_field_name

    rules = datasheet_checks.load_rules()
    words: dict[str, set[str]] = {r: set() for r in roles}
    complete: dict[str, bool] = dict.fromkeys(roles, True)
    seen: set[str] = set()
    try:
        facts = conn.execute(
            "SELECT field_name, field_label, field_value, source_text, is_blank "
            "FROM submittal_facts WHERE submittal_document_id = ? AND superseded_at IS NULL",
            (document_id,),
        ).fetchall()
        pages = conn.execute(
            "SELECT text FROM pages WHERE document_id = ? ORDER BY page_no",
            (document_id,),
        ).fetchall()
    except sqlite3.Error:
        return None
    for f in facts:
        role = datasheet_checks.role_of(normalise_field_name(f[1] or f[0] or ""), rules)
        if role not in roles:
            continue
        seen.add(role)
        words[role] |= _words(f[0], f[1], f[2], f[3])
        # a value code reads with a stored quote counts even when its geometry check disagrees: the NEGATIVE proof rests on the
        # words of the stored pages (below), which no reader's value can hide
        if f[4] or not str(f[2] or "").strip() or not str(f[3] or "").strip():
            complete[role] = False
    texts = [str(p[0] or "") for p in pages]
    return PaperEvidence(
        {r: frozenset(w) for r, w in words.items() if r in seen},
        {r: complete[r] for r in seen},
        _words(*texts),
        bool(texts) and all(t.strip() for t in texts),
    )


def part_absent(label: Mapping, rule_field: str | None, ctx: EquipmentCtx) -> bool:
    """True only when ALL hold: the rule's approved equipment label names a part; its approved field is one the data line
    `part_roles` says states a sheet's parts; the paper holds at least one stored fact of that field and every one is a
    non-blank value with a quote; every page of the paper has stored text; and no word of the part (or of an alias the data line
    `part_aliases` gives it) is in any such fact or on any page. Anything less is doubt: the rule is asked."""
    ev = ctx.evidence
    part = str(label.get("equip_part") or "")
    if ev is None or not part or not rule_field:
        return False
    if rule_field not in {str(r) for r in (ctx.mapping.get("part_roles") or [])}:
        return False
    if str(label.get("equip_state") or "") != rule_equipment.AGREED:
        return False
    if not ev.pages_readable or not ev.role_complete.get(rule_field):
        return False
    aliases = (ctx.mapping.get("part_aliases") or {}).get(part) or []
    wanted = _words(part.replace("_", " "), *aliases)
    return bool(wanted) and not (
        wanted & ev.role_words.get(rule_field, frozenset()) or wanted & ev.page_words
    )


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
        paper_equipment(conn, document_id, tax, mapping),
        tax,
        mapping,
        m,
        load_evidence(conn, document_id, mapping),
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
