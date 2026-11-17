"""Book selection by our own rule sorting (owner's item LPB, order 14, 17 Nov 2026).

A rule book is kept for a paper when it holds at least one AGREED rule that our rule sorting (`rule_equipment_label`) tagged for
the paper's own equipment. "Tagged for the paper's equipment" is decided by THE SAME function the AI reviewer's equipment filter
uses for each rule (`agent_review_equipment.equipment_decision`, mode "type", the paper's equipment read by
`agent_review_equipment.paper_equipment`): only a rule it would keep as "same_equipment" counts. A general rule, a rule whose label
is not agreed, a rule of another equipment type and a superseded rule never keep a book. Rule choice inside a kept book is not
touched: the AI reviewer's filters decide each rule exactly as before.

Read only. No equipment word is written here (rule 13): the paper's equipment and the taxonomy come from the data files. A
database without the label table, or a paper whose equipment is not usable, keeps nothing by this route.
"""

from __future__ import annotations

import sqlite3
from collections import Counter

METHOD = "equipment_rules"
#: the stored reason (`review_applicable_standards.selection_reason`): counts and the app's own equipment names, never paper text
REASON = "holds {n} agreed rule(s) our rule sorting tagged for this equipment ({names})"

_TAGGED_SQL = """SELECT sr.standard_document_id, l.equip_type, l.equip_family, COUNT(*)
    FROM rule_equipment_label l JOIN standard_requirements sr ON sr.id = l.rule_ref
    WHERE l.source = 'requirement' AND l.equip_state = 'agreed' AND l.equip_general = 0{superseded}
    GROUP BY sr.standard_document_id, l.equip_type, l.equip_family"""


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
    for book, rtype, rfam, n in conn.execute(_TAGGED_SQL.format(superseded=superseded)):
        if book not in wanted:
            continue
        label = {
            "equip_state": rule_equipment.AGREED,
            "equip_general": 0,
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
    """{standard id: selection row} for every library book holding agreed rules tagged for this paper's equipment."""
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
