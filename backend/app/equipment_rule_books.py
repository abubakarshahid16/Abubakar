"""Book selection by our own rule sorting (owner's item LPB, order 14, 17 Nov 2026).

A rule book is kept for a paper when it holds at least one AGREED rule that our rule sorting (`rule_equipment_label`) tagged for
the paper's own equipment. "Tagged for the paper's equipment" is decided by THE SAME function the AI reviewer's equipment filter
uses for each rule (`agent_review_equipment.equipment_decision`, mode "type", the paper's equipment read by
`agent_review_equipment.paper_equipment`): only a rule it would keep as "same_equipment" counts. A general rule, a rule whose label
is not agreed, a rule of another equipment type and a superseded rule never keep a book. Rule choice inside a kept book is not
touched: the AI reviewer's filters decide each rule exactly as before.

Hotfix 19c (17 Nov 2026): behind `equipment_rule_books_enabled`, OFF by default: the older field-name matcher matched single field
words to unrelated rules of the books this route kept. Off, `candidates` keeps nothing, so a paper keeps the books it kept before.

LPE (owner, 17 Nov 2026): with the switch ON, a rule is paired with a field of the paper ONLY when its equipment tag fits the
paper's equipment, decided by the same `equipment_decision` (`pairing_gate`): a rule it leaves out (an agreed tag naming another
equipment, both readers naming another, or a tagged rule on a paper whose equipment is not usable) is paired with no field in
any book. A book kept ONLY by this route pairs no rule at all with a field: it is kept for the AI reviewer, which reads each of
its rules against the paper with this same equipment filter. Measured on a copy (pump, valve, vessel of 17 Nov): pairing its
rules by tag alone still added two wrong rows to the pump (a pump-tagged plant-layout rule for flammable service, paired by the
AI matcher with the pumping temperature; a rotating-equipment vibration-plot rule, paired by one word with an inspection tick),
and its general and untagged rules were most of the 23 wrong rows. A general or untagged rule of a book chosen by a citation,
its scope or the governing table is paired as before. `unpairable` puts the code on the requirement (`NOT_PAIRED`); every
pairing tier of the comparison reads it. OFF: nothing is marked, nothing changes.

Read only. No equipment word is written here (rule 13): the paper's equipment and the taxonomy come from the data files. A
database without the label table, or a paper whose equipment is not usable, keeps nothing by this route.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Callable, Mapping

METHOD = "equipment_rules"
#: the stored reason (`review_applicable_standards.selection_reason`): counts and the app's own equipment names, never paper text
REASON = "holds {n} agreed rule(s) our rule sorting tagged for this equipment ({names})"

#: Every label of a stored rule, grouped; WHICH labels count is decided by `equipment_decision` alone (one decider: its state,
#: general flag, type and family), never by a second filter here.
_TAGGED_SQL = """SELECT sr.standard_document_id, l.equip_state, l.equip_general, l.equip_type, l.equip_family, COUNT(*)
    FROM rule_equipment_label l JOIN standard_requirements sr ON sr.id = l.rule_ref
    WHERE l.source = 'requirement'{superseded}
    GROUP BY sr.standard_document_id, l.equip_state, l.equip_general, l.equip_type, l.equip_family"""


def _has(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        is not None
    )


def tagged_counts(
    conn: sqlite3.Connection, document_id: str, book_ids
) -> tuple[dict[str, int], tuple[str, ...]]:
    """({book id: agreed rules tagged for this paper's equipment}, the paper's equipment names). Only books in `book_ids`."""
    from . import agent_review_equipment as are
    from . import rule_equipment

    if not (_has(conn, "rule_equipment_label") and _has(conn, "standard_requirements")):
        return {}, ()
    tax, mapping = rule_equipment.Taxonomy.load(), rule_equipment.load_mapping()
    eq = are.paper_equipment(conn, document_id, tax, mapping)
    if not eq.usable:
        return {}, ()
    columns = {r[1] for r in conn.execute("PRAGMA table_info(standard_requirements)")}
    superseded = " AND sr.superseded_at IS NULL" if "superseded_at" in columns else ""
    wanted = set(book_ids)
    counts: Counter = Counter()
    for book, state, general, rtype, rfam, n in conn.execute(
        _TAGGED_SQL.format(superseded=superseded)
    ):
        if book not in wanted:
            continue
        label = {
            "equip_state": state,
            "equip_general": general,
            "equip_type": rtype,
            "equip_family": rfam,
        }
        keep, why, _family = are.equipment_decision(label, eq, tax, "type", None)
        if keep and why == "same_equipment":
            counts[book] += int(n)
    return dict(counts), eq.app_names


def candidates(
    conn: sqlite3.Connection, document_id: str, library: list[dict]
) -> dict[str, dict]:
    """{standard id: selection row} for every library book holding agreed rules tagged for this paper's equipment. Nothing (and so
    nothing kept or ordered by this route) while `equipment_rule_books_enabled` is off (hotfix 19c, the default)."""
    from .config import settings

    if not settings.equipment_rule_books_enabled:
        return {}
    counts, names = tagged_counts(conn, document_id, {e["id"] for e in library})
    by_id = {e["id"]: e for e in library}
    said = ", ".join(names)
    return {
        book: {
            "method": METHOD,
            "identifier": by_id[book].get("document_number"),
            "reason": REASON.format(n=n, names=said),
            "tagged_rules": n,
        }
        for book, n in sorted(counts.items())
        if n > 0
    }


def tag_only_books(conn: sqlite3.Connection, run_id: str | None) -> frozenset[str]:
    """The books a run's selection INCLUDED only because they hold rules our rule sorting tagged for the equipment
    (`selection_method` = METHOD). They come LAST wherever a run has a limit (the AI reviewer's rule budget, the division-scope
    reads), so a book chosen by a citation, the governing table or its scope clause never loses a place to one of them."""
    if not run_id:
        return frozenset()
    try:
        rows = conn.execute(
            "SELECT standard_document_id FROM review_applicable_standards"
            " WHERE review_run_id = ? AND included = 1 AND selection_method = ?",
            (run_id, METHOD),
        ).fetchall()
    except sqlite3.Error:  # no selection table: no such book
        return frozenset()
    return frozenset(str(r[0]) for r in rows)


# ---- LPE: a rule is paired with a field only when its equipment tag fits the paper ------------------------------------------

#: The key `unpairable` puts on a requirement no pairing tier may pair with a field; its value is one of the codes below.
NOT_PAIRED = "equipment_not_paired"
OTHER_EQUIPMENT = "rule_for_other_equipment"
PAPER_EQUIPMENT_UNKNOWN = "paper_equipment_not_known"
BOOK_KEPT_BY_TAGS = "book_kept_by_rule_tags_only"
#: The words a finding gives for each code (`absence.pairing_not_checked`): what was decided, never a claim about the paper.
NOT_PAIRED_WORDS = {
    OTHER_EQUIPMENT: "the rule's agreed equipment tag names another kind of equipment than this paper's, so it was paired "
    "with no field of the paper",
    PAPER_EQUIPMENT_UNKNOWN: "the rule is tagged for a kind of equipment and this paper's equipment could not be read, so it "
    "was paired with no field of the paper",
    BOOK_KEPT_BY_TAGS: "its rule book was kept only because it holds rules tagged for this paper's equipment; the AI "
    "reviewer reads its rules against the paper, and no field of the paper was paired with them",
}


def pairing_gate(
    conn: sqlite3.Connection, document_id: str, run_id: str | None
) -> Callable[[Mapping], str | None] | None:
    """None while `equipment_rule_books_enabled` is off (nothing changes). On: a function giving, for one requirement, the code
    why no field of this paper may be paired with it, or None (it may be paired). The decision is the AI reviewer's own
    (`agent_review_equipment.equipment_decision`, mode "type", the rule's approved label field): left out there = paired with
    no field here, in any book. As in the AI reviewer, a paper of a kind with no main equipment (`kind_review_table`: a
    procedure, a contract, a transmittal) is not filtered by equipment. A book this run kept ONLY by this route
    (`tag_only_books`) pairs none of its rules."""
    from . import agent_review_equipment as are
    from . import kind_review_table, rule_equipment, rule_labels
    from .agent_review_kind import read_kind
    from .config import settings

    if not settings.equipment_rule_books_enabled:
        return None
    ctx = are.load_equipment(conn, document_id, "type")
    tag_only = tag_only_books(conn, run_id)
    kind = read_kind(conn, document_id)
    by_equipment = not (
        kind.get("known")
        and kind.get("kind") in kind_review_table.no_main_equipment_kinds()
    )

    def why_not(requirement: Mapping) -> str | None:
        rid = str(requirement.get("id") or "")
        label = rule_equipment.label_for(conn, "requirement", rid) or {}
        field = (rule_labels.label_for(conn, requirement_id=rid) or {}).get("field")
        keep, why, _family = are.equipment_decision(
            label, ctx.eq, ctx.tax, ctx.mode, field or None
        )
        if by_equipment and not keep:
            return (
                PAPER_EQUIPMENT_UNKNOWN
                if why in are.PAPER_EQUIPMENT_REASONS
                else OTHER_EQUIPMENT
            )
        return (
            BOOK_KEPT_BY_TAGS
            if requirement.get("standard_document_id") in tag_only
            else None
        )

    return why_not


def unpairable(
    conn: sqlite3.Connection,
    document_id: str,
    run_id: str | None,
    requirements: list[dict],
) -> list[dict]:
    """The run's requirements, each one no field may be paired with carrying `NOT_PAIRED` (its code). The same list, untouched,
    while the switch is off."""
    gate = pairing_gate(conn, document_id, run_id)
    if gate is None:
        return requirements
    return [{**r, NOT_PAIRED: why} if (why := gate(r)) else r for r in requirements]
