"""The item list for one paper (ported from the experiment's exp11/items.py; no sys.path hack, read only).

items = the checklist items for the paper kind and equipment type + every held rule that fits this paper (its label paper kind
is the paper's kind and its tier is usable), one item per rule (each applicable rule asked once). General code: no equipment
name, tag, field label or sheet layout here (rule 13).

Where the rules come from: the rows the classic selection chose (`requirement_rows`), or the stored scope decisions of the
classic engine's latest completed run on the paper. A rule is in when the run placed it "checked" or "applies, not checked" (a
raised advice query is not a requirement); rows with the same standard and the same normalised text are one rule.

A checklist item whose every clause reference is already a rule item's (same standard, same clause) is a duplicate: the RULE item
wins and the checklist guidance is folded into it (`also_skill_ids`) - except into a rule that is not AI approved.

Clause text (standard text) goes ONLY to the caller's cache dict, keyed by `clause_quote_ref`; the item holds the key.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import agent_review_rules as rules_mod
from . import requirement_split, rule_labels, standard_ids, subject_scope, table_gate
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


def _label(filename: str | None) -> str | None:
    """A standard's name from its file name: the stem (no extension)."""
    if not filename:
        return None
    return Path(filename).stem.strip() or None


#: A table caption line: "Table <id>" (letters, digits, dashes, dots) at the start of a line.
_TABLE_CAPTION = re.compile(
    r"^(?P<cap>Table\s+[A-Z0-9][A-Z0-9.\-]*[A-Z0-9])\b", re.IGNORECASE
)


def _fold_words(text: object) -> str:
    return re.sub(r"[^0-9a-z]", "", str(text or "").lower())


def _norm_clause(clause: object) -> str:
    return re.sub(r"\s+", "", str(clause or "")).upper().rstrip(".")


def _clause_keys(clause: str) -> list[tuple[str, str]]:
    ident = _norm_clause(clause)
    return [(k, ident) for k in ("number", "lettered", "appendix")] if ident else []


def _paper_pages(conn: sqlite3.Connection, doc: str) -> list[tuple[int, str]]:
    return [
        (r["page_no"], r["text"] or "")
        for r in conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
            (doc,),
        )
    ]


class _Standards:
    """Held standards' text, read once per document (StandardText: the same reader get_clause uses)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._text: dict[str, subject_scope.StandardText] = {}
        self._held: list[tuple[str, str]] | None = None

    def text(self, doc: str) -> subject_scope.StandardText:
        if doc not in self._text:
            self._text[doc] = subject_scope.StandardText(_paper_pages(self.conn, doc))
        return self._text[doc]

    def held(self) -> list[tuple[str, str]]:
        """(document id, name) of every document that holds standard rules."""
        if self._held is None:
            self._held = [
                (r["id"], _label(r["filename"]) or r["id"])
                for r in self.conn.execute(
                    "SELECT d.id, d.filename FROM documents d WHERE d.id IN"
                    " (SELECT DISTINCT standard_document_id FROM standard_requirements)"
                    " ORDER BY d.filename"
                )
            ]
        return self._held

    def resolve(self, name: str, prefer: set[str]) -> str | None:
        """The held document for a standard name; one the paper's rules already use wins."""
        hits = [
            d for d, label in self.held() if standard_ids.same_standard(name, label)
        ]
        for d in hits:
            if d in prefer:
                return d
        return hits[0] if hits else None

    def _page_at(self, text: subject_scope.StandardText, offset: int) -> int | None:
        for page, (start, end) in text.page_bounds.items():
            if start <= offset < end or (start == end == offset):
                return page
        return None

    def clause(self, doc: str, clause: str) -> tuple[str | None, int | None]:
        """(clause body, page where it starts), as get_clause reads it; (None, None) when not found."""
        text = self.text(doc)
        for key in _clause_keys(clause):
            spans = text.spans(key)
            if spans:
                start, _soft, end = spans[0]
                lines = [
                    ln
                    for ln, off in zip(text.lines, text.offsets, strict=False)
                    if start <= off < end
                ]
                body = "\n".join(lines).strip()
                if body:
                    return body, self._page_at(text, start)
        return None, None

    def page_lines(self, doc: str, page: int | None) -> list[str]:
        if page is None:
            return []
        row = self.conn.execute(
            "SELECT text FROM pages WHERE document_id = ? AND page_no = ?", (doc, page)
        ).fetchone()
        return (
            [" ".join(x.split()) for x in (row["text"] or "").splitlines() if x.strip()]
            if row
            else []
        )

    def table_clause(
        self, doc: str, requirement: dict
    ) -> tuple[str | None, str | None, int | None]:
        """For a rule read from a table row: (table caption, caption-to-page-end text, page).
        The caption is the last "Table <id>" line before the row on its page, else the first one on
        the page, else the last one on the page before (a table carried over). (None,)*3 if none."""
        page = requirement.get("page")
        lines = self.page_lines(doc, page)
        caps = [i for i, ln in enumerate(lines) if _TABLE_CAPTION.match(ln)]
        row_key = _fold_words(requirement.get("source_text"))[:40]
        at = None
        if row_key:
            for i, ln in enumerate(lines):
                if row_key[:20] and row_key[:20] in _fold_words(ln):
                    at = i
                    break
        pick = None
        if caps:
            before = [i for i in caps if at is not None and i <= at]
            pick = before[-1] if before else caps[0]
            body = lines[pick:]
        else:
            prev = self.page_lines(doc, (page or 0) - 1)
            pcaps = [i for i, ln in enumerate(prev) if _TABLE_CAPTION.match(ln)]
            if not pcaps:
                return None, None, None
            pick, page = pcaps[-1], page - 1
            body = prev[pick:] + lines
            lines = prev
        caption = _TABLE_CAPTION.match(lines[pick]).group("cap")
        return caption, "\n".join(body).strip() or None, page

    def page_clause(self, doc: str, page: int | None) -> str | None:
        """The clause in force at the top of `page`: the last heading opened before the page starts,
        else the first heading on the page. A weaker link than a stored or placed clause."""
        text = self.text(doc)
        bounds = text.page_bounds.get(page)
        if bounds is None:
            return None
        before = on_page = None
        for index, head in enumerate(text.heads):
            if head is None or index in text.bare:
                continue
            off = text.offsets[index]
            if off < bounds[0]:
                before = head
            elif off < bounds[1] and on_page is None:
                on_page = head
        found = before or on_page
        return found[1] if found else None

    def before_first_heading(self, doc: str, page: int | None) -> bool:
        """Does `page` end before the standard's first heading (a cover, foreword or contents page)?"""
        text = self.text(doc)
        bounds = text.page_bounds.get(page)
        if bounds is None:
            return False
        first = next(
            (
                text.offsets[i]
                for i, h in enumerate(text.heads)
                if h is not None and i not in text.bare
            ),
            None,
        )
        return first is None or bounds[1] <= first

    def placed_clause(self, doc: str, requirement: dict) -> str | None:
        """The numbered/lettered heading above where the rule's sentence sits, or None."""
        text = self.text(doc)
        at = text.place(requirement)
        if at is None:
            return None
        found = None
        for index, head in enumerate(text.heads):
            if text.offsets[index] > at:
                break
            if head is not None and index not in text.bare:
                found = head
        return found[1] if found else None


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
    names = dict(stds.held())
    reqs = [{**r, "standard": names.get(r["standard_document_id"])} for r in reqs]
    reqs, lab_left, why_kept = rules_mod.filter_rows(
        conn,
        reqs,
        paper_kind,
        known,
        equipment_type=equipment_type,
        ask_unapproved=ask_unapproved,
    )
    block = rules_mod.label_block(
        rules_mod.count_left_out(lab_left),
        lab_left,
        {**kind, "known": known},
        rules_mod.missing_rule_books(conn, document_id, equipment_type),
        sum(
            1 for w in why_kept.values() if w.get("tier") == rules_mod.TIER_NOT_APPROVED
        ),
    )
    rules = [
        rule_item(r, stds, cache, names.get(r["standard_document_id"]), pages)
        for r in reqs
    ]
    for rule in rules:
        why = why_kept[str(rule["rule_version_id"])]
        rule["rule_label"] = rules_mod.rule_label_of(why)
        rule.update(rules_mod.tier_fields(why))
    prefer = {r["standard_document_id"] for r in rules}
    sk: list[dict] = []
    skill_kind = (
        paper_kind if known else None
    )  # checklist items only for the kind the code reads
    for skill in load_skills(skill_kind, skills) if skill_kind else []:
        for it in sorted(skill["items"], key=lambda i: i["order"]):
            sk.append(skill_item(it, skill["kind"], stds, cache, prefer, pages))
    sk, skill_dropped = rules_mod.filter_skill_items(
        conn, sk, rules_mod.paper_equipment_types(conn, document_id)
    )
    rules_mod.add_skill_block(block, skill_dropped)
    # a checklist item is never folded into a rule that is not AI approved (its line would be capped)
    sk, merged = _fold_duplicates(
        sk, [r for r in rules if r.get("rule_tier") != RULE_NOT_APPROVED]
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
