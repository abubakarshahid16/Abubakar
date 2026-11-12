"""The item list for one paper (ported from the experiment's exp11/items.py; read only, no sys.path hack).

Items = the checklist items for the paper kind and equipment type + every held rule that fits this paper (its label paper kind
is the paper's kind and its tier is usable), one item per rule. General code: no equipment name, tag or layout (rule 13).
A checklist item whose every clause is already a rule's is folded into the rule, except into a rule not AI approved.
Clause text goes ONLY to the caller's cache dict, keyed by `clause_quote_ref`.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from typing import Any

from . import agent_review_rules as rules_mod
from . import agent_review_text, requirement_split, rule_labels, table_gate
from .agent_review_standards import (
    _norm_clause,
    _paper_pages,
    _Standards,
)
from .agent_review_verdict import RULE_NOT_APPROVED

PAPER_KINDS = (*rule_labels.PAPER_KINDS, "test record")
IN_STATES = (
    "checked",
    "applies_not_checked",
)  # the run states these apply (requirement_split)
QUERY_CODE = "recommendation_query"  # advice raised as a query: not a requirement
#: Paper kinds that have no main equipment type (step 2, paper kind first): the old run's
#: "another equipment type" exclusion does not hold for them, so those rules are back in.
NO_EQUIPMENT_KINDS = ("procedure", "contract")
EQUIPMENT_CODE = "other_equipment"
#: The clause label of a rule whose sentence sits before the standard's first heading.
BEFORE_FIRST_HEADING = "before first heading"
MAX_CLAUSE_CHARS = 8000
MAX_BATCH = 12

ITEM_KEYS = (
    "item_id", "source", "rule_version_id", "standard", "clause", "clause_page", "rule_kind",
    "comparator", "value", "unit", "field_roles", "question", "page_hint", "clause_quote_ref",
)  # fmt: skip
RULE_KINDS = ("limit", "range", "no_figure", "advice", None)


# ---- small helpers -----------------------------------------------------------------------------


class _RowConn:
    """Gives the caller's connection dict-like rows for this module's queries without changing its `row_factory`."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        cursor = self._conn.cursor()
        cursor.row_factory = sqlite3.Row
        return cursor.execute(sql, params)


def _key(*parts: object) -> str:
    return hashlib.sha256("\x00".join(str(p) for p in parts).encode()).hexdigest()[:16]


# ---- the old engine's checklist ---------------------------------------------------------------


def old_engine_run(conn: sqlite3.Connection, document_id: str) -> str | None:
    """The latest completed old-engine run on the paper that stored its scope decisions."""
    row = conn.execute(
        "SELECT r.id FROM review_runs r WHERE r.submittal_document_id = ? AND r.status = 'completed'"
        " AND EXISTS (SELECT 1 FROM review_scope_decisions s WHERE s.review_run_id = r.id)"
        " ORDER BY r.created_at DESC, r.id DESC LIMIT 1",
        (document_id,),
    ).fetchone()
    return row["id"] if row else None


def has_scope_decisions(conn: sqlite3.Connection, run_id: str | None) -> bool:
    """True when the run stored per-rule scope decisions (only a full classic review writes them)."""
    if not run_id:
        return False
    try:
        return (
            conn.execute(
                "SELECT 1 FROM review_scope_decisions WHERE review_run_id = ? LIMIT 1",
                (run_id,),
            ).fetchone()
            is not None
        )
    except sqlite3.OperationalError:  # no ledger table at all: no decisions
        return False


def selected_book_rows(
    conn: sqlite3.Connection, run_id: str, allowed: frozenset[str] | set[str]
) -> list[dict]:
    """Every stored rule of the rule books the run's selection INCLUDED (`review_applicable_standards`, `included = 1`),
    limited to books the caller may read (rule 5: an intersection). Used when the run has no per-rule scope decisions: the
    candidates are then the rules of the selected books, and the label filter (paper kind, tier, equipment) narrows them."""
    try:
        cur = conn.execute(
            "SELECT sr.* FROM standard_requirements sr JOIN review_applicable_standards a"
            " ON a.standard_document_id = sr.standard_document_id"
            " WHERE a.review_run_id = ? AND a.included = 1",
            (run_id,),
        )
    except sqlite3.OperationalError:  # no selection table: no selected book
        return []
    names = [c[0] for c in cur.description]
    rows = [dict(zip(names, r, strict=True)) for r in cur.fetchall()]
    return [r for r in rows if r["standard_document_id"] in allowed]


def books_not_selected(
    conn: sqlite3.Connection,
    run_id: str,
    paper_kind: str | None,
    allowed: frozenset[str] | set[str],
) -> dict:
    """Counts only: how many AI-approved rules of this paper kind sit in rule books the selection did NOT include."""
    if not paper_kind:
        return {"books": 0, "ai_approved_of_this_kind": 0}
    try:
        chosen = {
            r[0]
            for r in conn.execute(
                "SELECT standard_document_id FROM review_applicable_standards WHERE review_run_id = ? AND included = 1",
                (run_id,),
            )
        }
        per_book: dict[str, int] = {}
        for (d,) in conn.execute(
            "SELECT sr.standard_document_id FROM rule_label l JOIN standard_requirements sr ON sr.id = l.rule_ref"
            " WHERE l.source = 'requirement' AND l.state = 'ai_approved' AND l.paper_kind = ?",
            (paper_kind,),
        ):
            if d in allowed and d not in chosen:
                per_book[d] = per_book.get(d, 0) + 1
    except sqlite3.OperationalError:  # no selection or label table: nothing to count
        return {"books": 0, "ai_approved_of_this_kind": 0}
    return {"books": len(per_book), "ai_approved_of_this_kind": sum(per_book.values())}


def applicable_rules(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    no_equipment_filter: bool = False,
) -> tuple[list[dict], dict]:
    """(one requirement row per applicable rule, the left-out counts by stored state/reason).

    Same grouping as `requirement_split.build`: a rule key is applicable when ANY of its rows is
    checked or applies-not-checked (a better group wins); advice queries are not requirements.
    `no_equipment_filter`: a row the run left out ONLY as "another equipment type" applies."""
    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT d.state, d.reason_code, sr.* FROM review_scope_decisions d"
            " JOIN standard_requirements sr ON sr.id = d.requirement_id"
            " WHERE d.review_run_id = ?",
            (run_id,),
        )
    ]
    order = {"checked": 0, "applies_not_checked": 1, "does_not_apply": 2, "not_used": 3}
    best: dict[str, dict] = {}
    left: dict[str, int] = {}
    for r in rows:
        if (
            no_equipment_filter
            and r["state"] == "does_not_apply"
            and r["reason_code"] == EQUIPMENT_CODE
        ):
            r = {
                **r,
                "state": "applies_not_checked",
                "reason_code": "equipment_filter_not_used",
            }
        if r["state"] == "applies_not_checked" and r["reason_code"] == QUERY_CODE:
            left[f"{r['state']}:{QUERY_CODE}"] = (
                left.get(f"{r['state']}:{QUERY_CODE}", 0) + 1
            )
            continue
        k = requirement_split.requirement_key(r)
        cur = best.get(k)
        rank = (
            order.get(r["state"], 9),
            not r.get("clause"),
            r.get("page") or 0,
            r["id"],
        )
        if cur is None or rank < cur["_rank"]:
            if cur is not None:
                left["stored_repeat"] = left.get("stored_repeat", 0) + 1
            best[k] = {**r, "_rank": rank}
        else:
            left["stored_repeat"] = left.get("stored_repeat", 0) + 1
    keep = []
    for r in best.values():
        if r["state"] in IN_STATES:
            keep.append(r)
        else:
            tag = f"{r['state']}:{r['reason_code']}"
            left[tag] = left.get(tag, 0) + 1
    keep.sort(key=lambda r: (r["standard_document_id"], r.get("page") or 0, r["id"]))
    return keep, left


# ---- skills ------------------------------------------------------------------------------------


def skill_kinds_for(paper_kind: str, kinds: tuple[str, ...] | None = None) -> list[str]:
    """Skill kinds whose name ends in the paper kind ("<subject>_datasheet" for a datasheet)."""
    if kinds is None:
        from app import agent_skills

        kinds = agent_skills.KINDS
    tail = paper_kind.replace(" ", "_")
    return [k for k in kinds if k == tail or k.endswith("_" + tail)]


def load_skills(paper_kind: str, skills: list[dict] | None = None) -> list[dict]:
    if skills is not None:
        return skills
    from app import agent_skills

    out = []
    for kind in skill_kinds_for(paper_kind):
        try:
            out.append(agent_skills.load_skill(kind))
        except agent_skills.SkillError:
            continue
    return out


# ---- items -------------------------------------------------------------------------------------


def _page_hint(words: str | None, pages: list[tuple[int, str]]) -> list[int]:
    """Pages of the paper where every word of the field role appears; [] when none or all do."""
    toks = [t for t in table_gate.tokens(words or "") if len(t) > 1]
    if not toks or not pages:
        return []
    hit = []
    for page, text in pages:
        have = set(table_gate.tokens(text))
        if all(t in have for t in toks):
            hit.append(page)
    return [] if len(hit) == len(pages) and len(pages) > 1 else hit


def _rule_kind(r: dict) -> str:
    if (r.get("requirement_type") or "") == "recommendation":
        return "advice"
    if r.get("operator") and r.get("value") is not None:
        return "limit"
    if r.get("value_low") is not None and r.get("value_high") is not None:
        return "range"
    return "no_figure"


def _put(cache: dict, key: str, entry: dict) -> str:
    cache[key] = entry
    return key


def _clause_entry(
    stds: _Standards, cache: dict, doc: str, std: str | None, clause: str | None
) -> tuple[str | None, int | None]:
    """(cache key, clause page) for a held clause, or (None, None) when the clause is not found."""
    if not clause:
        return None, None
    key = "C-" + _key(doc, _norm_clause(clause))
    if key in cache and cache[key].get("text"):
        return key, cache[key].get("page")
    body, page = stds.clause(doc, clause)
    if not body:
        return None, None
    _put(
        cache,
        key,
        {
            "standard_document_id": doc,
            "standard": std,
            "clause": clause,
            "page": page,
            "source": "clause_span",
            "text": body[:MAX_CLAUSE_CHARS],
            "truncated": len(body) > MAX_CLAUSE_CHARS,
        },
    )
    return key, page


def _quote_entry(
    cache: dict, r: dict, doc: Any, label: str | None, clause: str | None
) -> str | None:
    """The cache key of the rule's own verbatim quote (None when the rule stores none)."""
    text = (r.get("source_text") or "").strip()
    if not text:
        return None
    return _put(
        cache,
        "Q-" + _key(r["id"]),
        {
            "standard_document_id": doc,
            "standard": label,
            "clause": clause,
            "page": r.get("page"),
            "source": "rule_quote",
            "text": text[:MAX_CLAUSE_CHARS],
            "truncated": len(text) > MAX_CLAUSE_CHARS,
        },
    )


def _question_of(
    r: dict, label: str | None, clause: str | None, cpage: int | None
) -> str:
    figure = ""
    if r.get("operator") and r.get("value") is not None:
        rule = f" Rule: {r.get('field') or 'value'} {r['operator']} {r['value']:g} {r.get('unit') or ''}"
        figure = rule.rstrip() + "."
    return (
        f"Does the paper meet {label} clause {clause or '(no clause number)'}"
        f" (standard page {cpage if cpage is not None else r.get('page')})? Requirement: "
        f"{(r.get('requirement_text') or '').strip()}{figure}"
    )


def rule_item(
    r: dict, stds: _Standards, cache: dict, label: str | None, pages: list
) -> dict:
    doc = r["standard_document_id"]
    clause = (r.get("clause") or "").strip() or None
    clause_from = "stored"
    ref, cpage = None, None
    if clause is None and r.get("table_row") is not None:
        cap, body, cap_page = stds.table_clause(doc, r)
        if cap:
            clause, clause_from, cpage = cap, "table_caption", cap_page
            if body:
                ref = _put(
                    cache,
                    "T-" + _key(doc, _norm_clause(cap), cap_page),
                    {
                        "standard_document_id": doc,
                        "standard": label,
                        "clause": cap,
                        "page": cap_page,
                        "source": "table_page",
                        "text": body[:MAX_CLAUSE_CHARS],
                        "truncated": len(body) > MAX_CLAUSE_CHARS,
                    },
                )
    if clause is None:
        clause = stds.placed_clause(doc, r)
        clause_from = "placed" if clause else None
    if clause is None:
        clause = stds.page_clause(doc, r.get("page"))
        clause_from = "page_heading" if clause else None
    if ref is None:
        ref, cpage = _clause_entry(stds, cache, doc, label, clause)
    quote_ref = _quote_entry(cache, r, doc, label, clause)
    if (
        ref is None
    ):  # the clause body was not found: the rule's own verbatim quote stands in
        ref, cpage = quote_ref, r.get("page")
    if clause is None and stds.before_first_heading(doc, r.get("page")):
        clause, clause_from = BEFORE_FIRST_HEADING, "before_first_heading"
    roles = [x for x in (r.get("field"),) if x]
    question = _question_of(r, label, clause, cpage)
    return {
        "item_id": f"R-{r['id']}",
        "source": "rule",
        "rule_version_id": r["id"],
        "standard": label,
        "standard_document_id": doc,
        "clause": clause,
        "clause_from": clause_from,
        "clause_page": cpage if cpage is not None else r.get("page"),
        "rule_kind": _rule_kind(r),
        "requirement_type": r.get("requirement_type"),
        "table_row": r.get("table_row"),
        "comparator": r.get("operator"),
        "value": r.get("value"),
        "value_low": r.get("value_low"),
        "value_high": r.get("value_high"),
        "unit": r.get("unit"),
        "field_roles": roles,
        "question": question,
        "page_hint": _page_hint(r.get("field"), pages),
        "clause_quote_ref": ref,
        "rule_quote_ref": quote_ref,
        "old_engine_state": r["state"],
        "old_engine_reason": r.get("reason_code"),
        "also_skill_ids": [],
    }


def skill_item(
    it: dict, kind: str, stds: _Standards, cache: dict, prefer: set[str], pages: list
) -> dict:
    refs = []
    for ref in it.get("clause_refs") or []:
        doc = stds.resolve(ref["standard"], prefer)
        key, page = (None, None)
        if doc is not None:
            key, page = _clause_entry(stds, cache, doc, ref["standard"], ref["clause"])
        refs.append(
            {
                "standard": ref["standard"],
                "clause": ref["clause"],
                "standard_document_id": doc,
                "clause_page": page,
                "clause_quote_ref": key,
            }
        )
    first = refs[0] if refs else {}
    question = " ".join(
        f"{label}: {it[k].strip()}"
        for label, k in (
            ("Topic", "topic"),
            ("Expected", "expected"),
            ("Acceptable", "acceptable_range"),
            ("Ask the engineer when", "escalate_when"),
        )
        if it.get(k)
    )
    return {
        "item_id": f"S-{it['id']}",
        "source": "skill",
        "rule_version_id": None,
        "standard": first.get("standard"),
        "clause": first.get("clause"),
        "clause_page": first.get("clause_page"),
        "rule_kind": None,
        "comparator": None,
        "value": None,
        "unit": None,
        "field_roles": [],
        "question": question,
        "page_hint": _page_hint(it.get("topic"), pages),
        "clause_quote_ref": first.get("clause_quote_ref"),
        "clause_refs": refs,
        "skill_kind": kind,
        "skill_order": it.get("order"),
        "repeat": bool(it.get("repeat")),
    }


def _fold_duplicates(
    skill_items: list[dict], rule_items: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Drop a skill item whose every clause ref is a rule item's clause; fold it into those rules."""
    by_clause: dict[tuple[str, str], list[dict]] = {}
    for r in rule_items:
        # only a clause the rule states or that its sentence sits in; a page-heading guess never merges
        if r["clause"] and r.get("clause_from", "stored") in (
            "stored",
            "placed",
            "table_caption",
        ):
            by_clause.setdefault(
                (r["standard_document_id"], _norm_clause(r["clause"])), []
            ).append(r)
    kept, merged = [], []
    for s in skill_items:
        targets: list[dict] = []
        refs = s.get("clause_refs") or []
        covered = bool(refs)
        for ref in refs:
            hit = by_clause.get(
                (ref.get("standard_document_id"), _norm_clause(ref["clause"]))
            )
            if not hit:
                covered = False
                break
            targets.extend(hit)
        if not covered:
            kept.append(s)
            continue
        for r in targets:
            if s["item_id"] not in r["also_skill_ids"]:
                r["also_skill_ids"].append(s["item_id"])
                r["question"] += f" Skill guidance ({s['item_id']}): {s['question']}"
        merged.append(
            {
                "skill_item": s["item_id"],
                "into": sorted({r["item_id"] for r in targets}),
            }
        )
    return kept, merged


def _candidate_rules(
    ro: _RowConn,
    document_id: str,
    paper_kind: str | None,
    requirement_rows: list[dict] | None,
    run_id: str | None,
) -> tuple[list[dict], dict[str, int], str | None]:
    """(one requirement row per candidate rule, left-out counts, the classic run used). Rows chosen by the caller come with
    no classic run; otherwise the applicable rules of the stored scope decisions of `run_id` (default: the latest)."""
    left: dict[str, int] = {}
    if requirement_rows is None:
        run_id = run_id or old_engine_run(ro, document_id)
        if not run_id:
            return [], left, run_id
        reqs, left = applicable_rules(
            ro, run_id, no_equipment_filter=paper_kind in NO_EQUIPMENT_KINDS
        )
        return reqs, left, run_id
    seen_keys, reqs = set(), []
    for r in sorted(
        requirement_rows,
        key=lambda r: (r["standard_document_id"], r.get("page") or 0, r["id"]),
    ):
        k = requirement_split.requirement_key(r)
        if k in seen_keys:
            left["stored_repeat"] = left.get("stored_repeat", 0) + 1
            continue
        seen_keys.add(k)
        reqs.append({**r, "state": "candidate", "reason_code": None})
    return reqs, left, run_id


def _checklist(
    conn,
    stds,
    cache,
    rules,
    block,
    kind,
    known,
    skills,
    document_id,
    pages,
    eq_ctx=None,
):
    """(checklist items, merged records): only for the kind the code reads, F2-filtered by equipment type, and never folded
    into a rule that is not AI approved (its line would be capped)."""
    prefer = {r["standard_document_id"] for r in rules}
    sk: list[dict] = []
    skill_kind = kind.get("kind") if known else None
    for skill in load_skills(skill_kind, skills) if skill_kind else []:
        for it in sorted(skill["items"], key=lambda i: i["order"]):
            sk.append(skill_item(it, skill["kind"], stds, cache, prefer, pages))
    types = rules_mod.paper_equipment_types(conn, document_id)
    sk, dropped = rules_mod.filter_skill_items(conn, sk, types, None, eq_ctx)
    rules_mod.add_skill_block(block, dropped)
    return _fold_duplicates(
        sk, [r for r in rules if r.get("rule_tier") != RULE_NOT_APPROVED]
    )


#: Where the candidate rules came from (the words the contract and the screen use).
SOURCE_DECISIONS = "per-rule scope decisions"
SOURCE_BOOKS = "the rules of the selected books"


def build_items_for_run(
    conn,
    document_id: str,
    kind: dict,
    scope_run: str,
    allowed,
    *,
    cache: dict,
    equipment_type,
    ask_unapproved,
) -> dict:
    """`build_items` for the AI reviewer's job. With no per-rule scope decision stored for `scope_run` (the inline selection
    stores books only), the candidates are the rules of the selected books; the Rules used block says so, counts only."""
    by_book = not has_scope_decisions(conn, scope_run)
    rows = selected_book_rows(conn, scope_run, allowed) if by_book else None
    doc = build_items(conn, document_id, kind, run_id=scope_run, cache=cache, equipment_type=equipment_type,
                      equipment_filter="type", ask_unapproved=ask_unapproved, requirement_rows=rows)  # fmt: skip
    block = doc.setdefault("rule_labels", {})
    other = books_not_selected(conn, scope_run, doc.get("paper_kind"), allowed)
    block["candidates"] = {
        "source": SOURCE_BOOKS if by_book else SOURCE_DECISIONS,
        "rows": len(rows) if rows is not None else None,
        "repeats": (doc.get("rules_left_out") or {}).get("stored_repeat", 0),
        "books_not_selected": other,
        "books_included": agent_review_text.books_included(conn, scope_run, allowed)
        if by_book
        else None,
    }
    if by_book:
        block.setdefault("summary_lines", []).append(
            f"rules came from the rule books this review selected ({len(rows or [])} stored rules; no per-rule scope decision"
            f" exists); AI-approved rules of this paper kind in {other['books']} other books were not considered:"
            f" {other['ai_approved_of_this_kind']}"
        )
    return doc


def build_items(
    conn: sqlite3.Connection,
    document_id: str,
    kind: dict,
    *,
    skills: list[dict] | None = None,
    run_id: str | None = None,
    cache: dict | None = None,
    requirement_rows: list[dict] | None = None,
    equipment_type: str | None = None,
    ask_unapproved: str = "off",
    equipment_filter: str = "off",
) -> dict:
    """The item list for one paper, from the database (read only; `conn` is the caller's connection).

    `kind` is the paper kind decided FIRST ({'kind', 'known', 'method', 'guess'}, `agent_review_kind`). Rules come from
    `requirement_rows` (chosen by the classic selection) or, without them, from the stored scope decisions of `run_id` (default:
    the latest completed classic run on the paper). A rule is kept only when its label paper kind is the paper's kind and its
    tier is usable (`agent_review_rules.decide_rule`); the rest are counted in the `rule_labels` block, never dropped silently.
    An unknown paper kind asks nothing. Checklist items are asked only for the paper's kind and (F2) equipment type. `cache`
    is filled with clause text (local only). A checklist item is never folded into a rule that is not AI approved."""
    paper_kind = kind.get("kind")
    cache = {} if cache is None else cache
    ro = _RowConn(conn)
    stds = _Standards(ro)
    pages = _paper_pages(ro, document_id)
    known = bool(kind.get("known")) and paper_kind in PAPER_KINDS
    reqs, left, run_id = _candidate_rules(
        ro, document_id, paper_kind, requirement_rows, run_id
    )
    eq_ctx = rules_mod.load_equipment(conn, document_id, equipment_filter)
    names = dict(stds.held())
    reqs = [{**r, "standard": names.get(r["standard_document_id"])} for r in reqs]
    reqs, lab_left, why_kept = rules_mod.filter_rows(
        conn,
        reqs,
        paper_kind,
        known,
        equipment_type=equipment_type,
        ask_unapproved=ask_unapproved,
        equipment=eq_ctx,
    )
    block = rules_mod.label_block(
        rules_mod.count_left_out(lab_left),
        lab_left,
        {**kind, "known": known},
        rules_mod.missing_rule_books(conn, document_id, equipment_type),
        sum(
            1 for w in why_kept.values() if w.get("tier") == rules_mod.TIER_NOT_APPROVED
        ),
        None if eq_ctx is None else rules_mod.equipment_block(eq_ctx, why_kept),
    )
    rules = [
        rule_item(r, stds, cache, names.get(r["standard_document_id"]), pages)
        for r in reqs
    ]
    for rule in rules:
        why = why_kept[str(rule["rule_version_id"])]
        rule["rule_label"] = rules_mod.rule_label_of(why)
        rule.update(rules_mod.tier_fields(why))
    sk, merged = _checklist(
        conn, stds, cache, rules, block, kind, known, skills, document_id, pages, eq_ctx
    )
    items = sk + rules
    return {
        "rule_labels": block,
        "paper": document_id,
        "paper_kind": paper_kind,
        "made_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "counts": {"skill": len(sk), "rule": len(rules)},
        "old_engine_run": run_id,
        "rules_left_out": dict(sorted(left.items())),
        "skill_merged_into_rules": merged,
        "items": items,
    }


# ---- batching ----------------------------------------------------------------------------------


def batch_by_page(items: list[dict], max_items: int = MAX_BATCH) -> list[list[dict]]:
    """One call per page group: items with the same page_hint set go together, at most `max_items`
    per call, items sharing a clause next to each other (one clause read serves the batch). Items
    with no page hint form their own groups, last (the lead finds the page itself)."""
    groups: dict[tuple[int, ...], list[dict]] = {}
    for it in items:
        groups.setdefault(tuple(sorted(set(it.get("page_hint") or []))), []).append(it)
    out: list[list[dict]] = []
    for pages in sorted(groups, key=lambda p: (not p, p)):
        members = sorted(
            groups[pages],
            key=lambda i: (str(i.get("clause_quote_ref") or ""), str(i["item_id"])),
        )
        for start in range(0, len(members), max_items):
            out.append(members[start : start + max_items])
    return out


# ---- schema check ------------------------------------------------------------------------------


def validate(doc: dict, cache: dict | None = None) -> list[str]:
    """Problems with an item file (empty list = valid). With `cache`, every clause_quote_ref resolves."""
    bad: list[str] = []
    for k in ("paper", "paper_kind", "made_at", "counts", "items"):
        if k not in doc:
            bad.append(f"missing top key {k}")
    if bad:
        return bad
    if doc["paper_kind"] not in PAPER_KINDS:
        bad.append("paper_kind not allowed")
    ids = set()
    n = {"skill": 0, "rule": 0}
    for it in doc["items"]:
        for k in ITEM_KEYS:
            if k not in it:
                bad.append(f"{it.get('item_id')}: missing {k}")
        iid = it.get("item_id")
        if iid in ids:
            bad.append(f"duplicate item_id {iid}")
        ids.add(iid)
        src = it.get("source")
        if src not in n:
            bad.append(f"{iid}: bad source")
            continue
        n[src] += 1
        if not str(iid).startswith("S-" if src == "skill" else "R-"):
            bad.append(f"{iid}: id prefix does not match source")
        if not isinstance(it.get("field_roles"), list) or not isinstance(
            it.get("page_hint"), list
        ):
            bad.append(f"{iid}: field_roles/page_hint must be lists")
        if any(not isinstance(p, int) for p in it.get("page_hint") or []):
            bad.append(f"{iid}: page_hint not ints")
        if it.get("rule_kind") not in RULE_KINDS:
            bad.append(f"{iid}: bad rule_kind")
        if not str(it.get("question") or "").strip():
            bad.append(f"{iid}: empty question")
        ref = it.get("clause_quote_ref")
        if (
            cache is not None
            and ref is not None
            and not (cache.get(ref) or {}).get("text")
        ):
            bad.append(f"{iid}: clause_quote_ref has no text in the cache")
    if n != doc["counts"]:
        bad.append(f"counts {doc['counts']} do not match items {n}")
    return bad
