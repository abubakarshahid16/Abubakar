"""S2 select, S3 checklist, the attack: the review checklist of one TYPE of paper, written from the standards ONLY (the measured
experiment's `--fair` path: "standards only, no paper").

No paper is read here: no prompt carries a paper block, no prompt is declared to carry the paper or any contractor submittal
(`NoPaper` refuses such a call before it is asked), and the identity given is type facts only (kind, equipment type or subject
key; no service words, no citations). The catalog holds ONLY the books on the list shown before the start (`allowed_books`):
a held book the type wants that is not on it is never offered and is counted as unlisted.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict

#: The only `built_from` a saved checklist may have (one home: the store, piece D).
from app.aim_review_store import (  # BUILT_FROMS is read by the engine through this module
    BUILT_FROM,
    BUILT_FROM_KNOWLEDGE,
    BUILT_FROMS,  # noqa: F401
)

from . import library as L
from . import prompts as P
from .engine import StepFailed

log = logging.getLogger(__name__)
HELD = "held standard"
KNOWLEDGE = "not from a held standard"
#: An item from the model's knowledge of a public standard the library does NOT hold (or of engineering practice): no clause
#: quote, no clause number; judged like any knowledge item (never Met / Not met).
KNOWLEDGE_NOT_HELD = "engineering knowledge (book not held)"
#: The coverage floor of a checklist for a kind with no main equipment (a procedure, a contract: long papers of many topics).
FLOOR_ITEMS = 30
MAX_KNOWLEDGE = 40
ITEM_KINDS = ("limit", "presence", "consistency", "material", "procedure")
SELECT_MAX_BOOKS = 10  # S2 chooses at most this many books (besides the required ones)
MATERIAL_BUDGET = 150_000
BOOK_BUDGET = 45_000
TEXT_BOOK_BUDGET = 25_000
BATCH_CHARS = 50_000
RULE_CHARS = 700


def _dumps(o) -> str:
    return json.dumps(o, ensure_ascii=False)


def type_identity(ident: dict) -> dict:
    """The type facts the checklist is written for: no word read from the paper (no service, no citation, no subject sentence)."""
    etype = ident.get("equipment_type")
    names = {t["id"]: t["name"] for t in L.taxonomy()}
    key_words = str(ident.get("subject_key") or "").replace("_", " ")
    return {
        "kind": ident.get("kind"),
        "equipment_type": etype,
        "subject": names.get(etype, "") if etype else key_words,
        "subject_key": ident.get("subject_key"),
        "service": "",
        "cited": [],
        "evidence": [],
    }


def _identity(ident: dict) -> str:
    return _dumps(
        {k: ident.get(k) for k in ("kind", "equipment_type", "subject", "service")}
    )


def _for_type(task: str) -> str:
    """A task written for a paper, reworded for the build where no paper is shown (the experiment's `_for(None, ...)`)."""
    return (
        task.replace(
            "The paper above was identified as:",
            "NO PAPER IS SHOWN. The TYPE of paper is:",
        )
        .replace("THIS paper", "a paper of this type")
        .replace("this paper", "a paper of this type")
        .replace("the paper cites them", "a paper of this type is governed by them")
    )


class NoPaper:
    """Wraps the model in the build: a call that carries a cached paper block, or declares the paper or any contractor
    submittal, is refused before it is asked (so no page text of a paper can reach S2, S3 or the attack)."""

    def __init__(self, model, conn, paper_id: str) -> None:
        self.model, self.conn, self.paper_id = model, conn, str(paper_id)

    def ask(self, **kw):
        if kw.get("cached"):
            raise StepFailed(
                f"{kw.get('step')}: build_saw_paper (a paper block reached a checklist prompt)"
            )
        carries = {str(c) for c in kw.get("carries") or ()}
        if self.paper_id in carries:
            raise StepFailed(
                f"{kw.get('step')}: build_saw_paper (the paper was declared in a checklist prompt)"
            )
        if carries:
            marks = ",".join("?" for _ in carries)
            roles = {
                r[0]
                for r in self.conn.execute(
                    f"SELECT COALESCE(document_role, '') FROM document_classification WHERE document_id IN ({marks})",
                    sorted(carries),
                )
            }
            if L.SUBMITTAL_ROLE in roles:
                raise StepFailed(
                    f"{kw.get('step')}: build_saw_paper (a submittal was declared in a checklist prompt)"
                )
        return self.model.ask(**kw)


# ------------------------------------------------------------------ the books the type wants


def wanted(conn, paper_id: str, ident: dict, allowed_books: frozenset[str]) -> dict:
    """The books the type requires (governing the equipment type, method books of the kind), split by the shown list.

    {"listed": {id: why}, "unlisted": [ids held but not on the list], "not_held": [{name, why}]}. Held is decided on the WHOLE
    library, so a held book that is merely not on the list is never called "not held"."""
    lib = L.library(conn, exclude=frozenset({str(paper_id)}))
    kind, etype = ident.get("kind"), ident.get("equipment_type")
    listed: dict[str, str] = {}
    unlisted: list[str] = []
    not_held: list[dict] = []
    for e, name in L.governing_books(lib, etype):
        if not e:
            not_held.append({"name": name, "why": f"{L.WHY_GOVERNS}; not held"})
        elif not L.role_applies(e, kind):
            continue
        elif e["id"] in allowed_books:
            listed.setdefault(e["id"], L.WHY_GOVERNS)
        elif e["id"] not in unlisted:
            unlisted.append(e["id"])
    for e, name in L.method_books(lib, kind):
        if not e:
            not_held.append({"name": name, "why": f"{L.WHY_METHOD}; not held"})
        elif e["id"] in allowed_books:
            listed.setdefault(e["id"], L.WHY_METHOD)
        elif e["id"] not in unlisted:
            unlisted.append(e["id"])
    return {"listed": listed, "unlisted": unlisted, "not_held": not_held}


# ------------------------------------------------------------------ S2 select


def s2_select(
    model,
    conn,
    paper_id: str,
    ident: dict,
    allowed_books: frozenset[str],
    gate_ok,
    lead: str,
) -> dict:
    want = wanted(conn, paper_id, ident, allowed_books)
    cat, pool, required, refused = _catalog(
        conn, paper_id, ident, allowed_books, want, gate_ok
    )
    result = {
        "books": [],
        "catalog_size": len(cat),
        "pool_rules": len(pool),
        "not_held": want["not_held"],
        "unlisted": want["unlisted"],
        "refused_by_gate": refused,
        "_pool": pool,
    }
    if not cat:  # nothing to choose among: no call is paid for; S3 writes the knowledge items alone (labelled as such)
        return result
    lines = "\n".join(
        _dumps(
            {
                "alias": c["alias"],
                "identifier": c["identifier"],
                "committee": c["committee"],
                "rules": c["rules"],
                "tagged": c["tagged"],
                "subjects": c["subjects"],
                **({"required": required[c["book"]]} if c["required"] else {}),
                **({"text_only": True} if c.get("text_only") else {}),
            }
        )
        for c in cat
    )
    out = model.ask(
        step="aim_select",
        model=lead,
        system="",
        cached=None,
        prompt=_for_type(P.S2_TASK)
        % {
            "identity": _identity(ident),
            "catalog": lines,
            "max_books": SELECT_MAX_BOOKS,
        },
        carries={c["book"] for c in cat},
        max_tokens=6000,
        effort="low",
    )
    out = out if isinstance(out, dict) else {}
    result["books"] = _chosen(out, cat, required)
    result["not_held"] = want["not_held"] + [
        {
            "name": str(r.get("name") or "")[:80],
            "why": str(r.get("why") or "")[:80],
            "source": "AI: needed, not in the catalog",
        }
        for r in out.get("not_held_needed") or []
        if isinstance(r, dict) and str(r.get("name") or "").strip()
    ]
    return result


def _catalog(
    conn, paper_id: str, ident: dict, allowed_books: frozenset[str], want: dict, gate_ok
):
    """(catalog lines with aliases, the rule pool, required books {id: why}, refused {id: code}): ONLY listed books."""
    lib = L.library(
        conn, exclude=frozenset({str(paper_id)}), within=frozenset(allowed_books)
    )
    by_id = {e["id"]: e for e in lib}
    kind, etype = ident.get("kind"), ident.get("equipment_type")
    required = {b: w for b, w in want["listed"].items() if b in by_id}
    refused = {}
    for b in list(required):
        why = gate_ok(b)
        if why:
            refused[b] = why
            required.pop(b)
    pool = L.rule_pool(conn, kind, etype, books=set(required), within=frozenset(by_id))
    cat = L.catalog(by_id, pool)
    in_cat = {c["book"] for c in cat}
    for b in required:
        if b not in in_cat:
            cat.append(
                {
                    "book": b,
                    "identifier": L.identifier_of(by_id[b]),
                    "committee": by_id[b].get("committee") or "",
                    "rules": 0,
                    "tagged": 0,
                    "subjects": [],
                    "text_only": True,
                }
            )
    cat = [c for c in cat if L.role_applies(by_id[c["book"]], kind)]
    cat = [c for c in cat if c["book"] in required or not gate_ok(c["book"])]
    for i, c in enumerate(cat):
        c["alias"] = f"B{i + 1:02d}"
        c["required"] = c["book"] in required
    return cat, pool, required, refused


def _chosen(out: dict, cat: list[dict], required: dict[str, str]) -> list[dict]:
    """The books S2 chose (by alias; unknown aliases dropped), the required ones always kept, at most SELECT_MAX_BOOKS + required."""
    alias = {c["alias"]: c for c in cat}
    chosen: dict[str, dict] = {}
    for row in out.get("books") or []:
        if not isinstance(row, dict):
            continue
        c = alias.get(str(row.get("alias") or ""))
        if not c or c["book"] in chosen:
            continue
        subj = row.get("subjects")
        subj = (
            "all"
            if subj == "all" or not isinstance(subj, list)
            else [s for s in subj if s in c["subjects"]] or "all"
        )
        chosen[c["book"]] = {
            **c,
            "why": str(row.get("why") or "")[:120],
            "chosen_subjects": subj,
        }
    for c in cat:  # required books stay, whatever the model said
        if c["required"] and c["book"] not in chosen:
            chosen[c["book"]] = {
                **c,
                "why": required[c["book"]],
                "chosen_subjects": "all",
            }
    return list(chosen.values())[: SELECT_MAX_BOOKS + len(required)]


# ------------------------------------------------------------------ S3 checklist


def material(sel: dict, text: L.BookText) -> tuple[list[dict], list[dict]]:
    """The clause text S3 reads: each chosen book's rules (tagged for the equipment first, then by page), or the pages of a book
    that holds no stored rules. Budgeted, and every cut is counted (rows offered N of M)."""
    pool_by_book = defaultdict(list)
    for r in sel["_pool"]:
        pool_by_book[r["book"]].append(r)
    rows, stats, used, n = [], [], 0, 0
    for b in sel["books"]:
        mine = pool_by_book.get(b["book"], [])
        if b["chosen_subjects"] != "all":
            mine = [r for r in mine if r["subject"] in b["chosen_subjects"]]
        mine.sort(key=lambda r: (not r["tagged"], r["page"] or 0, r["clause"] or ""))
        offered, chars = 0, 0
        if mine:
            for r in mine:
                t = str(r["source_text"] or r["requirement_text"] or "")
                cut = len(t) > RULE_CHARS
                t = t[:RULE_CHARS] + (
                    " [CUT: rule text longer than shown]" if cut else ""
                )
                if chars + len(t) > BOOK_BUDGET or used + len(t) > MATERIAL_BUDGET:
                    break
                n += 1
                rows.append(
                    {
                        "rule": f"R{n:04d}",
                        "book": b["alias"],
                        "book_id": b["book"],
                        "clause": str(r["clause"] or ""),
                        "page": int(r["page"] or 0),
                        "text": t,
                        "req_id": r["id"],
                    }
                )
                offered, chars, used = offered + 1, chars + len(t), used + len(t)
            stats.append(
                {
                    "alias": b["alias"],
                    "identifier": b["identifier"],
                    "rules_offered": offered,
                    "rules_total": len(mine),
                    "cut": offered < len(mine),
                }
            )
        else:
            pages = text.pages(b["book"])
            shown = 0
            for p, t in sorted(pages.items()):
                if chars + len(t) > TEXT_BOOK_BUDGET or used + len(t) > MATERIAL_BUDGET:
                    break
                rows.append(
                    {
                        "page_of": b["alias"],
                        "book_id": b["book"],
                        "page": p,
                        "page_text": t,
                    }
                )
                shown, chars, used = shown + 1, chars + len(t), used + len(t)
            stats.append(
                {
                    "alias": b["alias"],
                    "identifier": b["identifier"],
                    "pages_offered": shown,
                    "pages_total": len(pages),
                    "cut": shown < len(pages),
                }
            )
    return rows, stats


def _material_line(r: dict) -> str:
    if "rule" in r:
        return _dumps(
            {
                "rule": r["rule"],
                "book": r["book"],
                "clause": r["clause"],
                "page": r["page"],
                "text": r["text"],
            }
        )
    return _dumps(
        {"book": r["page_of"], "page": r["page"], "page_text": r["page_text"]}
    )


def _books_line(sel: dict) -> str:
    return "; ".join(f"{b['alias']} = {b['identifier']}" for b in sel["books"])


def _batches(rows: list[dict]) -> list[list[dict]]:
    out, cur, size = [], [], 0
    for r in rows:
        ln = len(_material_line(r))
        if cur and size + ln > BATCH_CHARS:
            out.append(cur)
            cur, size = [], 0
        cur.append(r)
        size += ln
    if cur:
        out.append(cur)
    return out or [[]]


def check_rule_quote(
    text: L.BookText, item: dict, alias_to_book: dict[str, str]
) -> bool:
    """A held-standard item keeps its quote only if code finds it on the book's stored page (that page or the next/previous,
    since a rule may run over a page break). The item's page is corrected to where the quote is."""
    from .verify import find_page

    book = alias_to_book.get(str(item.get("book") or ""))
    q = str(item.get("rule_quote") or "")
    if not book or not q:
        return False
    try:
        page = int(item.get("page") or 0)
    except (TypeError, ValueError):
        page = 0
    pages = {p: text.page(book, p) for p in (page, page - 1, page + 1) if p > 0}
    pages = {p: t for p, t in pages.items() if t}
    found = find_page(q, pages, page)
    if found is None:
        return False
    item["page"] = found
    item["book_id"] = book
    return True


def _source(raw) -> str:
    said = str(raw or "").strip().lower()
    if said.startswith("engineering knowledge"):
        return KNOWLEDGE_NOT_HELD
    return KNOWLEDGE if said.startswith("not") else HELD


def _clean_item(it: dict) -> dict:
    src = _source(it.get("source"))
    kind = str(it.get("kind") or "presence").lower()
    return {
        "topic": str(it.get("topic") or "")[:80],
        "what_to_check": str(it.get("what_to_check") or "")[:300],
        "book": str(it.get("book") or "") if src == HELD else "",
        "clause": ""
        if src == KNOWLEDGE_NOT_HELD
        else str(it.get("clause") or "")[:40],  # no invented clause number
        "page": it.get("page"),
        "rule_quote": str(it.get("rule_quote") or "")[:600] if src == HELD else "",
        "applies_when": str(it.get("applies_when") or "")[:200],
        "paper_fields": [str(f)[:80] for f in (it.get("paper_fields") or [])][:6],
        "paper_pages": [p for p in (it.get("paper_pages") or []) if isinstance(p, int)][
            :6
        ],
        "kind": kind if kind in ITEM_KINDS else "presence",
        "source": src,
        "stands_in_for": str(it.get("stands_in_for") or "")[:80] if src != HELD else "",
    }


def _items_of(out) -> list[dict]:
    rows = (out or {}).get("items") if isinstance(out, dict) else None
    return [_clean_item(it) for it in rows or [] if isinstance(it, dict)]


def s3_checklist(model, ident: dict, sel: dict, text: L.BookText, lead: str) -> dict:
    rows, stats = material(sel, text)
    alias_to_book = {b["alias"]: b["book"] for b in sel["books"]}
    carries = set(alias_to_book.values())
    items, dropped, retried = [], [], 0
    for i, batch in enumerate(_batches(rows)):
        prompt = _for_type(P.S3_TASK) % {
            "identity": _identity(ident),
            "books": _books_line(sel),
            "kinds": _dumps(list(ITEM_KINDS)),
            "knowledge": P.KNOWLEDGE_ASK if i == 0 else "",
            "material": "\n".join(_material_line(r) for r in batch),
        }
        out = model.ask(
            step="aim_checklist",
            model=lead,
            system="",
            cached=None,
            prompt=prompt,
            carries=carries,
            max_tokens=16000,
        )
        got = _items_of(out)
        bad = [
            it
            for it in got
            if it["source"] == HELD and not check_rule_quote(text, it, alias_to_book)
        ]
        if bad:  # one retry: ask for the exact words of those items only
            retried += len(bad)
            fix = model.ask(
                step="aim_checklist_retry",
                model=lead,
                system="",
                cached=None,
                prompt=P.S3_RETRY
                % {
                    "items": _dumps(bad),
                    "material": "\n".join(_material_line(r) for r in batch),
                },
                carries=carries,
                max_tokens=8000,
            )
            fixed = _items_of(fix)
            ok_fixed = [
                it
                for it in fixed
                if it["source"] == HELD and check_rule_quote(text, it, alias_to_book)
            ]
            dropped += [
                {"topic": it["topic"], "why": "rule quote not found on the book page"}
                for it in bad
            ][len(ok_fixed) :]
            got = [it for it in got if it not in bad] + ok_fixed
        items += got
    for n, it in enumerate(items):
        it["id"] = f"C{n + 1:03d}"
    return {
        "items": items,
        "dropped": dropped,
        "quotes_retried": retried,
        "material": stats,
        "books": [
            {
                k: b[k]
                for k in (
                    "alias",
                    "book",
                    "identifier",
                    "committee",
                    "why",
                    "chosen_subjects",
                    "required",
                )
            }
            for b in sel["books"]
        ],
    }


def floor_for(kind: str | None) -> int:
    """The coverage floor of a type's checklist: FLOOR_ITEMS for a kind with no main equipment (`kind_review_table`), else 0. The
    table holds no expected size per kind; this is the method's own floor (the lead, 18 Nov 2026)."""
    from app import kind_review_table

    table_kind = str(kind or "").strip().lower().replace(" ", "_")
    try:
        long_kinds = kind_review_table.no_main_equipment_kinds()
    except Exception as exc:  # noqa: BLE001 - an unreadable table gives no floor, never a stop
        log.info(
            "general review: kind table not read for the floor (%s)", type(exc).__name__
        )
        return 0
    return FLOOR_ITEMS if table_kind in long_kinds else 0


def _not_held_line(sel: dict) -> str:
    return "; ".join(
        sorted(
            {
                str(n.get("name") or "").strip()
                for n in sel.get("not_held") or []
                if str(n.get("name") or "").strip()
            }
        )
    )


def s3_knowledge(model, ident: dict, sel: dict, made: dict, lead: str) -> dict:
    """ENGINEERING KNOWLEDGE where a book is not held (the method's rule: where no standard is held, use engineering knowledge,
    labelled as such). One call, still with NO paper, when a governing or needed standard is not held or the checklist is below
    the kind's floor: items from the model's knowledge of each not-held public standard's requirements (and of engineering
    practice up to the floor), source KNOWLEDGE_NOT_HELD, the standard's public name in `stands_in_for`, no clause quote, no
    clause number. The items so far are named by topic only (the listed books are declared). A failed call adds nothing."""
    names = _not_held_line(sel)
    floor = floor_for(ident.get("kind"))
    have = len(made["items"])
    if not names and have >= floor:
        return made
    most = min(
        MAX_KNOWLEDGE,
        max(floor - have, 0) + 6 * len(names.split("; ") if names else []),
    )
    if most <= 0:
        return made
    prompt = _for_type(P.KNOWLEDGE_TASK) % {
        "identity": _identity(ident),
        "not_held": names
        or "none (write from general engineering practice for this kind of paper)",
        "have": have,
        "topics": _dumps(
            sorted({it["topic"] for it in made["items"] if it.get("topic")})
        ),
        "floor": floor,
        "most": most,
        "kinds": _dumps(list(ITEM_KINDS)),
    }
    try:
        out = model.ask(
            step="aim_checklist_knowledge",
            model=lead,
            system="",
            cached=None,
            prompt=prompt,
            carries={b["book"] for b in sel["books"]},
            max_tokens=12000,
        )
    except StepFailed as exc:
        if exc.stops_run:
            raise
        log.info(
            "general review: knowledge items not written (%s)",
            str(exc).split(" ", 2)[:2],
        )
        return made
    rows = (out or {}).get("items") if isinstance(out, dict) else None
    added = []
    for r in [r for r in rows or [] if isinstance(r, dict)][:most]:
        it = _clean_item(
            {**r, "source": KNOWLEDGE_NOT_HELD}
        )  # labelled first: no book, no quote, no clause number
        it["stands_in_for"] = it["stands_in_for"] or "engineering practice"
        added.append(it)
    for n, it in enumerate(added, have + 1):
        it["id"] = f"C{n:03d}"
    return {
        **made,
        "items": made["items"] + added,
        "knowledge_items": len(added),
        "floor": floor,
    }


def s3_attack(
    model, ident: dict, sel: dict, made: dict, text: L.BookText, strong: str
) -> dict:
    rows, _stats = material(sel, text)
    alias_to_book = {b["alias"]: b["book"] for b in sel["books"]}
    shown = [
        {
            k: it[k]
            for k in (
                "id",
                "topic",
                "what_to_check",
                "book",
                "clause",
                "page",
                "rule_quote",
                "applies_when",
                "paper_fields",
                "kind",
                "source",
            )
        }
        for it in made["items"]
    ]
    out = model.ask(
        step="aim_attack",
        model=strong,
        system="",
        cached=None,
        prompt=_for_type(P.ATTACK_TASK)
        % {
            "identity": _identity(ident),
            "kinds": _dumps(list(ITEM_KINDS)),
            "items": "\n".join(_dumps(s) for s in shown),
            "not_held": _not_held_line(sel) or "none",
            "books": _books_line(sel),
            "material": "\n".join(_material_line(r) for r in rows),
        },
        carries=set(alias_to_book.values()),
        max_tokens=16000,
    )
    out = out if isinstance(out, dict) else {}
    by_id = {it["id"]: it for it in made["items"]}
    log = {"removed": [], "fixed": [], "added": [], "rejected": []}
    for r in out.get("remove") or []:
        if isinstance(r, dict) and r.get("id") in by_id:
            by_id.pop(r["id"])
            log["removed"].append({"id": r["id"], "why": str(r.get("why") or "")[:120]})
    for r in out.get("fix") or []:
        if not (
            isinstance(r, dict)
            and r.get("id") in by_id
            and isinstance(r.get("item"), dict)
        ):
            continue
        it = _clean_item(r["item"])
        if it["source"] == HELD and not check_rule_quote(text, it, alias_to_book):
            log["rejected"].append({"id": r["id"], "why": "fix: rule quote not found"})
            continue
        it["id"] = r["id"]
        by_id[r["id"]] = it
        log["fixed"].append({"id": r["id"], "why": str(r.get("why") or "")[:120]})
    n = len(made["items"])
    for r in out.get("add") or []:
        if not isinstance(r, dict):
            continue
        it = _clean_item(r)
        if it["source"] == HELD and not check_rule_quote(text, it, alias_to_book):
            log["rejected"].append(
                {"topic": it["topic"], "why": "add: rule quote not found"}
            )
            continue
        n += 1
        it["id"] = f"C{n:03d}"
        it["added_by_attack"] = True
        by_id[it["id"]] = it
        log["added"].append({"id": it["id"], "why": str(r.get("why") or "")[:120]})
    return {**made, "items": list(by_id.values()), "attack": log}


def build(
    model,
    conn,
    *,
    paper_id: str,
    ident: dict,
    allowed_books: frozenset[str],
    gate_ok,
    lead: str,
    strong: str,
    text: L.BookText,
    key: str,
    made_at: str,
) -> tuple[dict, dict]:
    """The checklist of the paper's TYPE from the listed books' clauses only. (checklist, selection summary). Raises StepFailed."""
    guarded = NoPaper(model, conn, paper_id)
    typed = type_identity(ident)
    sel = s2_select(guarded, conn, paper_id, typed, allowed_books, gate_ok, lead)
    made = s3_checklist(guarded, typed, sel, text, lead)
    made = s3_knowledge(guarded, typed, sel, made, lead)
    cl = s3_attack(guarded, typed, sel, made, text, strong)
    knows = any(it.get("source") == KNOWLEDGE_NOT_HELD for it in cl["items"])
    cl.update(
        {
            "key": key,
            "built_from": BUILT_FROM_KNOWLEDGE if knows else BUILT_FROM,
            "made_at": made_at,
            "identity": {
                k: typed.get(k)
                for k in ("kind", "equipment_type", "subject", "subject_key")
            },
            "not_held": sel["not_held"],
            "refused_by_gate": sel["refused_by_gate"],
            "pool_rules": sel["pool_rules"],
            "catalog_size": sel["catalog_size"],
        }
    )
    return cl, {"unlisted": sel["unlisted"], "not_held": sel["not_held"]}
