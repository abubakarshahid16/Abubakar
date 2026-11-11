"""Rule choice for the AI reviewer: ask only the rules that fit the paper (order 12, ported from exp12/rule_labels.py).

A stored rule carries a label (`rule_label`, #1744): paper kind, field, a state. A rule is ASKED only when (a) its label paper
kind equals the paper's kind and (b) its tier is usable: `rule_labels.usable_tier` says owner, engineer or AI approved. The
experiment's extra mode (`ask_unapproved="both"`) also asks a rule the two models did not fully agree on, only when BOTH
models' kind is the paper's kind (the stored agreed kind), the label state is `needs_human` (so the quote was found), the
quote is not an OCR or unreadable one, and no person declined it. Such a rule is tier "not AI approved": the verdict cap
(`agent_review_verdict.cap_unapproved`, `agent_review_wording.final_cap`) keeps its lines from ever being Pass or Fail and no
paid call beyond the lead's own answer is bought for it (`calls_allowed`).

Every other rule is NOT asked and counted under ONE reason: needs another paper (by kind), needs a human, quote not found,
not labelled yet, or paper kind unknown. Nothing is dropped silently. The quote bridge is OFF: a label is found by the
requirement id (or the rule-book version id), never through a sibling rule that quotes the same sentence. Rule books
the library does not hold are listed, never counted against the system. Engineer and owner approvals are only READ.
General code: no equipment name, tag or layout (rule 13). Read only; no model call; no network.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from . import rule_equipment, rule_labels
from .agent_review_verdict import RULE_NOT_APPROVED, TIER_NOT_APPROVED

ANOTHER_PAPER = "needs_another_paper"
NEEDS_HUMAN = "needs_a_human"
QUOTE_NOT_FOUND = "quote_not_found"
NOT_LABELLED = "not_labelled_yet"
KIND_UNKNOWN = "paper_kind_unknown"
ANOTHER_EQUIPMENT = "another_equipment_type"
NO_EQUIPMENT = "paper_names_no_equipment"
REASONS = (
    ANOTHER_PAPER,
    NEEDS_HUMAN,
    QUOTE_NOT_FOUND,
    NOT_LABELLED,
    KIND_UNKNOWN,
    ANOTHER_EQUIPMENT,
    NO_EQUIPMENT,
)
REASON_WORDS = {
    ANOTHER_PAPER: "needs another paper",
    NEEDS_HUMAN: "needs a human",
    QUOTE_NOT_FOUND: "quote not found",
    NOT_LABELLED: "not labelled yet",
    KIND_UNKNOWN: "paper kind unknown",
    ANOTHER_EQUIPMENT: "another equipment type",
    NO_EQUIPMENT: "the paper names no equipment",
}
LABEL_KINDS = rule_labels.PAPER_KINDS
ASK_UNAPPROVED_MODES = ("off", "both")
#: A rule we cannot quote cleanly is not shown to an engineer as a rule, so these disagreement parts exclude it.
UNQUOTABLE_PARTS = frozenset({"ocr_low_confidence", "unreadable_quote"})
#: `usable_tier` reason word -> the left-out reason of this module
_REASON_OF = {
    rule_labels.NOT_LABELLED: NOT_LABELLED,
    rule_labels.NO_LABEL_TABLE: NOT_LABELLED,
    rule_labels.ONE_PASS_ONLY: NOT_LABELLED,
    rule_labels.NEEDS_A_HUMAN: NEEDS_HUMAN,
    rule_labels.QUOTE_NOT_ON_PAGE: QUOTE_NOT_FOUND,
    rule_labels.PERSON_DECLINED: NEEDS_HUMAN,
    rule_labels.LABEL_REFUSED: NEEDS_HUMAN,
}


def norm_kind(kind: Any) -> str | None:
    """A paper kind in the label's spelling (lower case, underscores); None when empty."""
    k = str(kind or "").strip().lower().replace(" ", "_")
    return k or None


def _parts(disagreement: Any) -> set[str]:
    return {p.strip() for p in str(disagreement or "").split(",") if p.strip()}


def _blank_decision() -> dict[str, Any]:
    return {
        "ask": False,
        "reason": None,
        "tier": None,
        "label_paper_kind": None,
        "field": None,
        "state": None,
        "label_key": None,
        "needs_kind": None,
        "disagreement": None,
        "unapproved_why": None,
    }


def _decide_label(
    conn: sqlite3.Connection,
    requirement_id: str,
    paper_kind: str | None,
    kind_known: bool = True,
    *,
    equipment_type: str | None = None,
    ask_unapproved: str = "off",
) -> dict:
    """{'ask', 'reason', 'tier', 'label_paper_kind', 'field', 'state', 'label_key', 'needs_kind', 'disagreement',
    'unapproved_why'} for one rule (a `standard_requirements` id). Read only.

    An unknown paper kind asks NOTHING (reason paper_kind_unknown). A rule of another kind is never asked (needs another
    paper). `tier` is "owner", "engineer", "AI approved" or "not AI approved"."""
    if ask_unapproved not in ASK_UNAPPROVED_MODES:
        raise ValueError(f"ask_unapproved is one of {ASK_UNAPPROVED_MODES}")
    out = _blank_decision()
    want = norm_kind(paper_kind)
    if not kind_known or not want:
        out["reason"] = KIND_UNKNOWN
        return out
    got = rule_labels.usable_tier(
        conn, requirement_id=str(requirement_id), equipment_type=equipment_type
    )
    label = got.label
    if label is None:
        out["reason"] = NOT_LABELLED
        return out
    state, kind = str(label.get("state") or ""), norm_kind(label.get("paper_kind"))
    out.update(
        state=state,
        label_paper_kind=kind,
        field=label.get("field") or None,
        disagreement=label.get("disagreement") or None,
        label_key=str(label.get("rule_ref") or label.get("rule_version_id")),
    )
    if kind is None:  # the two models did not agree on a kind
        out["reason"] = (
            QUOTE_NOT_FOUND
            if state == rule_labels.QUOTE_NOT_FOUND
            else _REASON_OF.get(got.reason, NEEDS_HUMAN)
        )
        if state in ("labelled_a", ""):
            out["reason"] = NOT_LABELLED
        return out
    if kind != want:
        out["reason"], out["needs_kind"] = ANOTHER_PAPER, kind
        return out
    if got.tier and not (label.get("disagreement") and got.tier == rule_labels.AI_TIER):
        out.update(ask=True, tier=got.tier)
        return out
    if got.tier:  # labelled ai_approved but its readings disagree somewhere: a human decides (never asked as approved)
        out["reason"] = NEEDS_HUMAN
        return out
    parts = _parts(label.get("disagreement"))
    page = label.get("quote_page")
    if (
        ask_unapproved == "both"
        and got.reason == rule_labels.NEEDS_A_HUMAN
        and state == rule_labels.NEEDS_HUMAN
        and isinstance(page, int)
        and not isinstance(page, bool)
        and not (parts & UNQUOTABLE_PARTS)
    ):  # both models' kind (the stored agreed kind) is the paper's kind, the quote was found, no person declined it
        out.update(
            ask=True,
            tier=TIER_NOT_APPROVED,
            unapproved_why=", ".join(sorted(parts)) or "not agreed",
        )
        return out
    out["reason"] = _REASON_OF.get(got.reason, NOT_LABELLED)
    return out


def decide_rule(
    conn: sqlite3.Connection,
    requirement_id: str,
    paper_kind: str | None,
    kind_known: bool = True,
    *,
    equipment_type: str | None = None,
    ask_unapproved: str = "off",
    equipment: EquipmentCtx | None = None,
) -> dict:
    """The label decision (`_decide_label`), then, only with an `equipment` context, the equipment filter, which can only
    REMOVE a rule that would be asked (reason another_equipment_type / paper_names_no_equipment). A rule whose equipment label is
    not agreed stays asked and is counted apart (`equipment_why` = equipment_not_known)."""
    out = _decide_label(
        conn,
        requirement_id,
        paper_kind,
        kind_known,
        equipment_type=equipment_type,
        ask_unapproved=ask_unapproved,
    )
    if equipment is None or not out["ask"]:
        return out
    label = rule_equipment.label_for(conn, "requirement", str(requirement_id)) or {}
    out["equipment"] = {
        k: label.get(k)
        for k in ("equip_family", "equip_type", "equip_state", "equip_general")
    }
    keep, why, family = equipment_decision(
        label, equipment.eq, equipment.tax, equipment.mode
    )
    out["equipment_why"] = why
    if not keep:
        out.update(ask=False, reason=why, tier=None, equipment_family=family)
    return out


def tier_lookup(
    conn: sqlite3.Connection,
    paper_kind: str | None,
    kind_known: bool = True,
    *,
    equipment_type: str | None = None,
    ask_unapproved: str = "off",
):
    """A `lookup(item)` for `agent_review_verdict.item_tier` / `agent_review_wording.final_cap`: the CURRENT tier of a rule item
    from the label table now ("owner", "engineer", "AI approved", or the not-approved word / None). A rule the table would not
    ask of this paper is None, so a stored Pass or Fail of it can never stand."""

    def lookup(item: Mapping) -> str | None:
        got = decide_rule(
            conn,
            str(item.get("rule_version_id")),
            paper_kind,
            kind_known,
            equipment_type=equipment_type,
            ask_unapproved=ask_unapproved,
        )
        return got["tier"] if got["ask"] else None

    return lookup


# ---- the equipment filter: only ever REMOVES rules ------------------------------------------------------------------------

EQUIPMENT_MODES = ("off", "on", "type", "family")  # "on" is an alias of "type"


class EquipmentLabelsMissing(ValueError):
    """The equipment filter is on but the database holds no equipment labels table."""


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
    found, _source, _doubt = subject_scope.read_equipment(
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
    return PaperEquipment(
        frozenset(tax.expand(every)) if every else frozenset(),
        frozenset(tax.type_family[t] for t in every if t in tax.type_family),
        bool(found),
        tuple(sorted(found)),
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
    if not eq.usable:
        return False, NO_EQUIPMENT, rfam or tax.type_family.get(rtype or "")
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
    """The equipment context of one paper, or None when the filter is off. Refuses (EquipmentLabelsMissing) when the filter is
    on and the database holds no equipment labels table: a filter on nothing is not a filter."""
    m = norm_mode(mode)
    if m is None:
        return None
    if not rule_equipment.has_tables(conn):
        raise EquipmentLabelsMissing(
            "the equipment filter needs the rule_equipment_label table"
        )
    tax, mapping = rule_equipment.Taxonomy.load(), rule_equipment.load_mapping()
    return EquipmentCtx(
        paper_equipment(conn, document_id, tax, mapping), tax, mapping, m
    )


def equipment_skill_fits(types_app: set[str], ctx: EquipmentCtx) -> bool:
    """The same notion of "same equipment" for a checklist item: its app equipment names, mapped, meet the paper's types."""
    names = ctx.mapping.get("map") or {}
    return (
        bool({names[n] for n in types_app if n in names} & ctx.eq.types)
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
        "asked_by_equipment": dict(kept),
    }


# ---- filtering ----------------------------------------------------------------------------------------------------------


def left_out_record(row: Mapping, why: Mapping, key: str) -> dict:
    return {
        "rule_version_id": row.get(key),
        "item_id": row.get("item_id"),
        "rule_book": row.get("standard"),
        "standard_document_id": row.get("standard_document_id"),
        "clause": row.get("clause"),
        "page": row.get("page"),
        "reason": why["reason"],
        "disagreement": why.get("disagreement"),
        "equipment_family": why.get("equipment_family"),
        "needs_paper_kind": why.get("needs_kind"),
        "label_state": why.get("state"),
    }


def filter_rows(
    conn: sqlite3.Connection,
    rows: Iterable[Mapping],
    paper_kind: str | None,
    kind_known: bool = True,
    id_key: str = "id",
    *,
    equipment_type: str | None = None,
    ask_unapproved: str = "off",
    equipment: EquipmentCtx | None = None,
) -> tuple[list[dict], list[dict], dict[str, dict]]:
    """(kept rows, left-out records, decision of each kept row by its id). A row with no id is never lost: it is left out
    as not labelled."""
    kept, left, why_kept = [], [], {}
    for row in rows:
        rid = str(row.get(id_key))
        why = decide_rule(
            conn,
            rid,
            paper_kind,
            kind_known,
            equipment_type=equipment_type,
            ask_unapproved=ask_unapproved,
            equipment=equipment,
        )
        if why["ask"]:
            kept.append(dict(row))
            why_kept[rid] = why
        else:
            left.append(left_out_record(row, why, id_key))
    return kept, left, why_kept


def count_left_out(left: Iterable[Mapping]) -> dict:
    """Counts only: {'needs_another_paper': {'total': n, 'by_kind': {...}}, 'needs_a_human': n, ...}."""
    left = list(left)
    c = Counter(r["reason"] for r in left)
    by_kind = Counter(
        r.get("needs_paper_kind") or "unlabelled"
        for r in left
        if r["reason"] == ANOTHER_PAPER
    )
    out: dict[str, Any] = {
        r: c.get(r, 0) for r in REASONS if r not in (ANOTHER_PAPER, ANOTHER_EQUIPMENT)
    }
    parts: Counter = (
        Counter()
    )  # a needs-a-human rule counts once under each disagreement part it carries
    for r in left:
        if r["reason"] == NEEDS_HUMAN:
            for part in str(r.get("disagreement") or "unstated").split(","):
                parts[part.strip() or "unstated"] += 1
    out["needs_a_human_by_disagreement"] = dict(sorted(parts.items()))
    out[ANOTHER_PAPER] = {
        "total": c.get(ANOTHER_PAPER, 0),
        "by_kind": dict(sorted(by_kind.items())),
    }
    by_family = Counter(
        r.get("equipment_family") or "unnamed"
        for r in left
        if r["reason"] == ANOTHER_EQUIPMENT
    )
    out[ANOTHER_EQUIPMENT] = {
        "total": c.get(ANOTHER_EQUIPMENT, 0),
        "by_family": dict(sorted(by_family.items())),
    }
    return out


def summary_lines(
    counts: Mapping,
    paper_kind: str | None,  # noqa: ARG001 - kept for the callers' signature
    kind_known: bool = True,
) -> list[str]:
    """The CRS summary lines: ONE line for rules that need another paper; one line for the rest. Counts only."""
    lines = []
    other = counts.get(ANOTHER_PAPER) or {}
    if other.get("total"):
        parts = ", ".join(
            f"{k} {n}" for k, n in sorted(other.get("by_kind", {}).items())
        )
        lines.append(f"needs another paper: {other['total']} rules ({parts})")
    eq_other = counts.get(ANOTHER_EQUIPMENT) or {}
    if eq_other.get("total"):
        parts = ", ".join(
            f"{k} {n}" for k, n in sorted(eq_other.get("by_family", {}).items())
        )
        lines.append(
            f"another equipment type: {eq_other['total']} rules not asked ({parts})"
        )
    if counts.get(NO_EQUIPMENT):
        lines.append(
            f"the paper names no equipment: {counts[NO_EQUIPMENT]} rules about a named equipment not asked; "
            "only general rules and rules of unknown equipment are asked"
        )
    rest = [
        f"{REASON_WORDS[r]} {counts[r]}"
        for r in (NEEDS_HUMAN, QUOTE_NOT_FOUND, NOT_LABELLED)
        if counts.get(r)
    ]
    if rest:
        lines.append("rules not asked: " + ", ".join(rest))
    if not kind_known:
        lines.insert(
            0,
            f"paper kind unknown: {counts.get(KIND_UNKNOWN, 0)} rules NOT asked; no rule was decided "
            "for this paper. The engineer names the paper kind and the review runs again",
        )
    return lines


# ---- the rule books the library does not hold -----------------------------------------------------------------------------


def library_of(conn: sqlite3.Connection) -> list[dict]:
    """The standards the library holds: every document that holds stored rules (the rule books)."""
    from . import applicability

    rows = conn.execute(
        "SELECT d.id AS id, d.filename AS filename FROM documents d WHERE d.id IN"
        " (SELECT DISTINCT standard_document_id FROM standard_requirements)"
    ).fetchall()
    return [
        {
            "id": r[0],
            "filename": r[1],
            "document_number": applicability.library_identifier(r[1] or ""),
        }
        for r in rows
    ]


def missing_rule_books(
    conn: sqlite3.Connection,
    document_id: str,
    equipment_type: str | None = None,
    governing: Mapping | None = None,
) -> list[dict]:
    """The rule books the paper CITES (its own pages) or its equipment type needs (`reference/governing_standards.json`)
    that the library does not hold. Never counted against any score. Names of standards only, no paper text."""
    from . import applicability, standard_ids

    text = "\n".join(
        r[0] or ""
        for r in conn.execute(
            "SELECT text FROM pages WHERE document_id = ? ORDER BY page_no",
            (document_id,),
        )
    )
    library = library_of(conn)
    out: list[dict] = []
    seen: set[str] = set()
    for name in applicability.missing_references(
        library, standard_ids.cited_standards(text)
    ):
        seen.add(standard_ids.key(name))
        out.append({"rule_book": name, "why": "cited by the paper"})
    table = governing if governing is not None else applicability.governing_table()
    for name in (table.get("equipment_types") or {}).get(equipment_type or "", []):
        key = standard_ids.key(name)
        if key in seen:
            continue
        seen.add(key)
        if applicability.find_standard(library, name) is None:
            out.append(
                {
                    "rule_book": name,
                    "why": f"needed by the paper kind or type ({equipment_type})",
                }
            )
    return out


# ---- the label block and the RULES USED record -----------------------------------------------------------------------------


def label_block(
    counts: Mapping,
    left: list[dict],
    kind: Mapping,
    missing: list[dict],
    unapproved: int = 0,
    equipment: Mapping | None = None,
) -> dict:
    """What the Rules used page and the CRS summary need: counts, left-out records, missing books. No text."""
    return {
        "on": True,
        "paper_kind": kind.get("kind"),
        "paper_kind_known": bool(kind.get("known")),
        "paper_kind_method": kind.get("method"),
        "paper_kind_guess": kind.get("guess"),
        "counts": dict(counts),
        "unapproved_asked": unapproved,
        "equipment": equipment,
        "summary_lines": summary_lines(
            counts, kind.get("kind"), bool(kind.get("known"))
        )
        + (
            [
                f"rules asked though not AI approved: {unapproved} (shown as AI opinion, rule not yet approved)"
            ]
            if unapproved
            else []
        ),
        "left_out": left,
        "missing_rule_books": missing,
    }


def rule_label_of(why: Mapping) -> dict:
    return {
        "paper_kind": why.get("label_paper_kind"),
        "field": why.get("field"),
        "tier": why.get("tier"),
        "state": why.get("state"),
        "label_key": why.get("label_key"),
        "equipment": why.get("equipment"),
        "unapproved_why": why.get("unapproved_why"),
    }


def tier_fields(why: Mapping) -> dict:
    """The item fields of an asked-though-unapproved rule (every cap is keyed on `rule_tier`)."""
    if why.get("tier") == TIER_NOT_APPROVED:
        return {
            "rule_tier": RULE_NOT_APPROVED,
            "rule_unapproved_why": why.get("unapproved_why"),
        }
    return {}


def rules_used(items: Iterable[Mapping], block: Mapping | None) -> dict:
    """The RULES USED record of one review (no text): every rule asked, every rule left out with its reason, and the rule
    books not held. `quote_ref` is the id of the quote in the clause cache, never the quote."""
    block = block or {}
    asked = []
    for it in items:
        if it.get("source") != "rule":
            continue
        lab = it.get("rule_label") or {}
        asked.append(
            {
                "rule_id": it.get("rule_version_id"),
                "rule_book": it.get("standard"),
                "clause": it.get("clause"),
                "page": it.get("clause_page"),
                "quote_ref": it.get("rule_quote_ref") or it.get("clause_quote_ref"),
                "paper_kind": lab.get("paper_kind"),
                "field": lab.get("field"),
                "tier": lab.get("tier"),
                "equipment": lab.get("equipment"),
                "recommendation": it.get("rule_kind") == "advice",
                "not_approved_why": it.get("rule_unapproved_why")
                if it.get("rule_tier") == RULE_NOT_APPROVED
                else None,
            }
        )
    return {
        "paper_kind": block.get("paper_kind"),
        "paper_kind_known": block.get("paper_kind_known"),
        "equipment": block.get("equipment"),
        "asked_by_tier": dict(Counter(a["tier"] for a in asked)),
        "asked": asked,
        "left_out": block.get("left_out") or [],
        "left_out_counts": block.get("counts") or {},
        "rule_books_not_held": block.get("missing_rule_books") or [],
    }


# ---- checklist items: skill_fits and F2 (the paper's own equipment type) --------------------------------------------------------

ANOTHER_TYPE, TYPE_UNKNOWN = "another_equipment_type", "equipment_type_unknown"


def skill_fits(skill_kind: Any, paper_kind: str | None) -> bool:
    """A checklist item is asked only for a paper of its own kind: its kind is "<subject>_<paper kind>"."""
    tail = norm_kind(paper_kind) or ""
    k = str(skill_kind or "")
    return bool(tail) and (k == tail or k.endswith("_" + tail))


def paper_equipment_types(conn: sqlite3.Connection, document_id: str) -> set[str]:
    """The equipment types of a paper as the app reads them (`subject_scope.read_equipment`: the stored classification, then
    the title), in the app's own vocabulary. Empty when unknown (or when the datasheet itself disagrees)."""
    from . import subject_scope

    try:
        row = conn.execute(
            "SELECT equipment_type, title FROM document_classification WHERE document_id = ?",
            (document_id,),
        ).fetchone()
    except sqlite3.Error:
        row = None
    record = {"equipment_type": row[0], "title": row[1]} if row else {}
    found, _source, _doubt = subject_scope.read_equipment(
        record, [], subject_scope.vocabulary()
    )
    return set(found)


def skill_types(
    conn: sqlite3.Connection, item: Mapping, governing: Mapping | None = None
) -> set[str]:
    """The equipment types a checklist item is about, read from DATA only: the types whose governing standards (reference
    table) the item cites, and the types named in the cited standard's own classification. No equipment name in code."""
    from . import applicability, standard_ids, subject_scope

    table = governing if governing is not None else applicability.governing_table()
    vocab = subject_scope.vocabulary()
    types: set[str] = set()
    for ref in item.get("clause_refs") or []:
        name = ref.get("standard")
        for kind, ids in (table.get("equipment_types") or {}).items():
            if name and any(standard_ids.same_standard(name, i) for i in ids):
                types.add(kind)
        doc = ref.get("standard_document_id")
        if doc:
            try:
                row = conn.execute(
                    "SELECT equipment_type, title, discipline FROM document_classification WHERE document_id = ?",
                    (doc,),
                ).fetchone()
            except sqlite3.Error:
                row = None
            for text in row or ():
                types |= set(vocab.equipment_in(str(text or "")))
    return types


def filter_skill_items(
    conn: sqlite3.Connection,
    items: list[dict],
    paper_types: set[str],
    governing: Mapping | None = None,
    equipment: EquipmentCtx | None = None,
) -> tuple[list[dict], list[dict]]:
    """F2: (kept, dropped records). With an `equipment` context the ONE notion of "same equipment" is the taxonomy mapping. A checklist item about equipment types is kept only when the paper's type is among them;
    a paper of unknown type gets no type-specific checklist item. An item about no type stays (it is general)."""
    kept, dropped = [], []
    for it in items:
        types = skill_types(conn, it, governing)
        if equipment is not None:
            if not types or equipment_skill_fits(types, equipment):
                kept.append(it)
            else:
                reason = ANOTHER_TYPE if equipment.eq.usable else TYPE_UNKNOWN
                dropped.append({"item_id": it.get("item_id"), "reason": reason})
            continue
        if not types or (paper_types and types & paper_types):
            kept.append(it)
        else:
            dropped.append(
                {
                    "item_id": it.get("item_id"),
                    "reason": ANOTHER_TYPE if paper_types else TYPE_UNKNOWN,
                }
            )
    return kept, dropped


def add_skill_block(block: dict, dropped: list[dict]) -> None:
    """Record the dropped checklist items on the label block and say so on the CRS (counts only)."""
    n = Counter(d["reason"] for d in dropped)
    block["skills_left_out"] = {
        ANOTHER_TYPE: n.get(ANOTHER_TYPE, 0),
        TYPE_UNKNOWN: n.get(TYPE_UNKNOWN, 0),
        "item_ids": [d["item_id"] for d in dropped],
    }
    if n.get(TYPE_UNKNOWN):
        block.setdefault("summary_lines", []).append(
            f"equipment type unknown: {n[TYPE_UNKNOWN]} type-specific checklist items NOT asked"
        )
    if n.get(ANOTHER_TYPE):
        block.setdefault("summary_lines", []).append(
            f"checklist items for another equipment type: {n[ANOTHER_TYPE]} not asked"
        )
