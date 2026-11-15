"""Rule choice v2 of the AI reviewer (owner order 15 Nov 2026), behind `AGENT_REVIEW_RULE_CHOICE_V2_ENABLED` (default off).

OFF: nothing here runs; the plan and every request are byte-for-byte what they were. ON, four things, all general (rule 13):
  1. the partial-standard gate (`governing_standards.json`, `subject_scope.partial_gate`): a rule of a book that governs this
     equipment only through the parts it names, and whose own words name none of them, is left out ("this part of the book does
     not govern this equipment");
  2. a rule left out only as "needs a human" whose paper kind AND field the two labelling readers agree on is ASKED, marked in
     plain words "rule not yet approved by an engineer"; it can only be an AI opinion or a Query (the one exit cap, tested over
     the whole line table), never a decision, never on the contractor copy;
  3. rank and budget: score = +3 governing or cited book, +2 field on the equipment type's approved list, +1 mandatory wording,
     +1 a parsed limit, +1 approved, -2 not approved; at most `budget` rules are asked (Claude 150, local 40, settings); the rest
     are LISTED as left out below the limit, never silently;
  4. "needs a human" that is not asked: one grouped Query point per rule book, with its count and its boundary.
Reads only; no model call; no network."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

PART_OUTSIDE = "outside_governed_part"
BELOW_LIMIT = "below_review_limit"
WORDS = {
    PART_OUTSIDE: "this part of the book does not govern this equipment",
    BELOW_LIMIT: "below the limit for one review",
}
GOVERNING_METHODS = (
    "governing_standard",
    "referenced",
)  # `review_applicable_standards.selection_method`

#: What a label guard that held a rule means, in words an engineer reads (one table; no code word reaches the page).
CAUSE_WORDS = {
    "numbers_unread": "a number in its quote was not read by the two readers",
    "invalid_reading": "a number or unit a reader gave is not in its quote",
    "comparator": "the two readers read its comparison differently",
    "values": "the two readers read its numbers differently",
    "unit": "the two readers read its unit differently",
    "strength": "the two readers read its strength (shall, should) differently",
}
UNAPPROVED_PREFIX = "rule not yet approved by an engineer"


def enabled() -> bool:
    from .config import settings

    return bool(getattr(settings, "agent_review_rule_choice_v2_enabled", False))


def budget_for(local: bool) -> int:
    from .config import settings

    return int(
        settings.agent_review_budget_local
        if local
        else settings.agent_review_budget_claude
    )


def unapproved_sentence(parts: Iterable[str]) -> str:
    """The plain words that mark an asked rule no engineer or pair of models approved."""
    said = [CAUSE_WORDS[p] for p in sorted(set(parts)) if p in CAUSE_WORDS]
    return f"{UNAPPROVED_PREFIX} ({'; '.join(said)})" if said else UNAPPROVED_PREFIX


# ---- 1. the partial-standard gate -------------------------------------------------------------------------------------------


def partial_gate_rows(
    conn,
    rows: list[dict],
    equipment_names: set[str],
    standard_labels: Mapping[str, str],
) -> tuple[list[dict], list[dict]]:
    """(kept rows, left-out records). A book the equipment takes only in part keeps the rules whose own words name the part,
    and also a rule whose label says a datasheet field is its subject (the two readers agreed on kind AND field): what a
    datasheet states can be checked whichever clause of the book it stands in. The equipment filter that follows still drops
    such a rule when it is about another equipment."""
    from . import subject_scope

    table = json.loads(
        (Path(__file__).parent / "reference" / "governing_standards.json").read_text(
            encoding="utf-8"
        )
    )
    got = subject_scope.partial_gate(
        rows,
        equipment=set(equipment_names),
        standard_labels=dict(standard_labels),
        partial_standards=table.get("partial_standards") or {},
    )
    rescued = _rescued_ids(conn, [it["requirement"].get("id") for it in got["items"]])
    kept = got["kept"] + [
        it["requirement"]
        for it in got["items"]
        if str(it["requirement"].get("id")) in rescued
    ]
    got = {
        "kept": kept,
        "items": [
            it for it in got["items"] if str(it["requirement"].get("id")) not in rescued
        ],
    }
    left = [
        {
            "rule_version_id": it["requirement"].get("id"),
            "item_id": it["requirement"].get("item_id"),
            "rule_book": it["requirement"].get("standard"),
            "standard_document_id": it["requirement"].get("standard_document_id"),
            "clause": it["requirement"].get("clause"),
            "page": it["requirement"].get("page"),
            "reason": PART_OUTSIDE,
            "disagreement": None,
            "equipment_family": None,
            "needs_paper_kind": None,
            "label_state": None,
            "part_note": None,
        }
        for it in got["items"]
    ]
    return got["kept"], left


def _rescued_ids(conn, ids: list) -> set[str]:
    """The rules among `ids` whose label names a datasheet field (kind datasheet, field agreed and on the list)."""
    out: set[str] = set()
    ids = [str(i) for i in ids if i]
    for start in range(0, len(ids), 500):
        part = ids[start : start + 500]
        try:
            for r in conn.execute(
                "SELECT rule_ref FROM rule_label WHERE source = 'requirement' AND paper_kind = 'datasheet' AND field IS NOT NULL"
                f" AND rule_ref IN ({','.join('?' * len(part))})",
                part,
            ):
                out.add(str(r[0]))
        except sqlite3.Error:  # no label table: nothing is rescued
            return set()
    return out


# ---- 3. rank and budget -----------------------------------------------------------------------------------------------------

_MANDATORY = re.compile(r"\b(shall|must)\b", re.I)


def score(
    row: Mapping, why: Mapping, governing_ids: set[str], approved_fields: set[str]
) -> int:
    """The rank of one asked rule (higher is asked first)."""
    s = 0
    if str(row.get("standard_document_id")) in governing_ids:
        s += 3
    if why.get("field") and why["field"] in approved_fields:
        s += 2
    if _MANDATORY.search(
        str(row.get("requirement_text") or row.get("source_text") or "")
    ):
        s += 1
    if row.get("operator") and row.get("value") is not None:
        s += 1
    s += -2 if why.get("tier") == "Not AI approved" else 1
    return s


def rank_and_cut(
    kept: list[dict],
    why_kept: Mapping[str, Mapping],
    id_key: str,
    limit: int,
    governing_ids: set[str],
    approved_fields: set[str],
    first_ids: set[str] | frozenset[str] = frozenset(),
) -> tuple[list[dict], list[dict], dict]:
    """(rows asked, left-out records below the limit, facts). Order among equal scores: books that govern this equipment by
    `governing_standards.json` (`first_ids`) before books only cited, then book, page, id (stable, no randomness)."""
    scored = [
        (
            -score(
                r,
                why_kept.get(str(r.get(id_key))) or {},
                governing_ids,
                approved_fields,
            ),
            str(r.get("standard_document_id")) not in first_ids,
            str(r.get("standard_document_id")),
            r.get("page") or 0,
            str(r.get(id_key)),
            r,
        )
        for r in kept
    ]
    scored.sort(key=lambda t: t[:5])
    top = [t[5] for t in scored[: max(0, int(limit))]]
    cut = [t[5] for t in scored[max(0, int(limit)) :]]
    left = [
        {
            "rule_version_id": r.get(id_key),
            "item_id": r.get("item_id"),
            "rule_book": r.get("standard"),
            "standard_document_id": r.get("standard_document_id"),
            "clause": r.get("clause"),
            "page": r.get("page"),
            "reason": BELOW_LIMIT,
            "disagreement": None,
            "equipment_family": None,
            "needs_paper_kind": None,
            "label_state": None,
            "part_note": None,
        }
        for r in cut
    ]
    return (
        top,
        left,
        {
            "limit": int(limit),
            "applicable": len(kept),
            "asked": len(top),
            "below": len(cut),
        },
    )


def below_line_sentence(facts: Mapping) -> str | None:
    if not facts.get("below"):
        return None
    return (
        f"{facts['below']} more rules apply but were not asked: the limit for one review is {facts['limit']}; "
        "they are listed under Rules used"
    )


def governing_book_ids(
    conn,
    scope_run: str | None,
    equipment_names: Iterable[str] = (),
    standard_labels: Mapping[str, str] | None = None,
) -> set[str]:
    """The books that GOVERN the equipment (`governing_standards.json`, by the one identifier matcher) or that the run's selection
    marked as governing or cited by the paper."""
    out: set[str] = set()
    if scope_run:
        try:
            marks = ",".join("?" * len(GOVERNING_METHODS))
            out |= {
                str(r[0])
                for r in conn.execute(
                    "SELECT standard_document_id FROM review_applicable_standards WHERE review_run_id = ? AND included = 1"
                    f" AND selection_method IN ({marks})",
                    (scope_run, *GOVERNING_METHODS),
                )
            }
        except sqlite3.Error:  # no table: nothing is marked by the selection
            pass
    if standard_labels and equipment_names:
        from . import standard_ids

        table = json.loads(
            (
                Path(__file__).parent / "reference" / "governing_standards.json"
            ).read_text(encoding="utf-8")
        )
        named = [
            e
            for name in equipment_names
            for e in (table.get("equipment_types") or {}).get(name, [])
        ]
        for doc_id, label in standard_labels.items():
            if label and any(standard_ids.same_standard(label, e) for e in named):
                out.add(str(doc_id))
    return out


def equipment_governing_ids(
    equipment_names: Iterable[str], standard_labels: Mapping[str, str]
) -> set[str]:
    """Only the books `governing_standards.json` names for this equipment (not the books merely cited)."""
    return governing_book_ids(None, None, equipment_names, standard_labels)


def approved_field_names(equipment_type: str | None) -> set[str]:
    from . import datasheet_checks, datasheet_roles

    try:
        return set(
            datasheet_roles.wanted_roles(equipment_type, datasheet_checks.load_rules())
        )
    except (KeyError, ValueError, OSError):
        return set()


# ---- 4. the grouped point per rule book -------------------------------------------------------------------------------------


def group_points(left: Iterable[Mapping], needs_human_reason: str) -> list[dict]:
    """Counts only: one entry per rule book with the rules still left out as "needs a human"."""
    by_book: Counter = Counter()
    ids: dict[str, str] = {}
    for r in left:
        if r.get("reason") == needs_human_reason:
            book = str(r.get("rule_book") or "a rule book")
            by_book[book] += 1
            ids.setdefault(book, str(r.get("standard_document_id") or book))
    return [
        {"rule_book": b, "count": n, "book_id": ids[b]}
        for b, n in sorted(by_book.items())
    ]


def group_line(point: Mapping) -> dict:
    """The stored line of one grouped point: a Query for the engineer, internal copy only, no model call."""
    n, book = int(point["count"]), point["rule_book"]
    words = (
        f"{n} rules of {book} could not be matched to a field of this paper: an engineer checks them "
        "(counted over the rules of the books this review selected that govern this equipment)"
    )
    key = hashlib.sha256(str(point["book_id"]).encode()).hexdigest()[:8]
    return {
        "item_id": f"G-{key}",
        "source": "group",
        "standard": book,
        "clause": "",
        "verdict": "Query",
        "decided_by": "engineer",
        "why": words,
        "comment": words,
        "reasoning": words,
        "rule_tier": None,
        "tier": None,
        "checklist": False,
        "group_count": n,
    }


def is_group_line(line: Mapping) -> bool:
    return line.get("source") == "group"


def plan_args(local: bool, default_ask: str) -> dict:
    """The two arguments of `build_items_for_run` that rule choice v2 sets (off: the default ask mode and no budget)."""
    if not enabled():
        return {"ask_unapproved": default_ask}
    return {"ask_unapproved": "agreed_field", "rule_budget": budget_for(local)}


def plan_extra(doc: Mapping) -> dict:
    """The group points of the plan, only when v2 made them (off: nothing is added to the plan)."""
    return {"group_points": doc["group_points"]} if "group_points" in doc else {}


def store_group_lines(run_id: str, plan: Mapping, store_line) -> list[dict]:
    """Store and return one Query line per grouped point (no model call; internal copy only). [] when there is none."""
    from . import agent_review_wording as wording

    out = []
    for point in plan.get("group_points") or []:
        line = wording.apply(group_line(point))
        store_line(run_id, line, None)
        out.append(line)
    return out


__all__: list[Any] = [
    "BELOW_LIMIT",
    "PART_OUTSIDE",
    "WORDS",
    "approved_field_names",
    "below_line_sentence",
    "budget_for",
    "enabled",
    "governing_book_ids",
    "group_line",
    "group_points",
    "is_group_line",
    "partial_gate_rows",
    "plan_args",
    "plan_extra",
    "store_group_lines",
    "rank_and_cut",
    "score",
    "unapproved_sentence",
]
