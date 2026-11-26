"""THE ATTACK ON THE LOCAL MODEL: EVERY CHECKLIST ITEM, AND NO ANSWER IS CUT (lead-4, 26 Nov 2026, after F's 9B valve run on update
10: the attack answered the whole checklist against each rule batch, wrote whole corrected and added items, ran 15 of the run's
36 minutes, and two answers were cut at 8,192 tokens and set aside). Its own home so the checklist module stays under its size
limit.

The items are attacked in groups of `ATTACK_ITEMS`, each against the rules its items cite, and the answer is ONE short fixed
verdict per item (`answer_schema`: keep, remove or fix, a one-sentence reason, a corrected line for a fix): a group's answer is
bounded far below the answer limit. A group whose answer is still cut is asked again in two halves, down to one item; one item
still cut, or an item the answer gave no verdict for, keeps the first engineer's item and is counted under "Steps that did not
run". The local attack adds no items (the knowledge step covers the standards not held). On Claude: not used.
"""

from __future__ import annotations

from . import faults
from . import prompts as P
from .budget import cap
from .engine import StepFailed
from .material import BATCH_CHARS

#: Checklist items per local attack call: with the answer shape's bounds (about 500 characters per verdict at most) a call's
#: answer stays under 6,500 tokens even at one token per character, below the 8,192-token answer limit.
ATTACK_ITEMS = 12
_SPLIT_DEPTH = 4


def _own_rows(it: dict, rows: list[dict]) -> list[dict]:
    """The material rows that are the item's OWN rule: the stored rule(s) of its book and exact clause (else of its cited clause,
    one under it or its parent), or, for a book read by its pages, its page and the pages beside it."""
    from .retry import _in_cited, _same

    rules = [r for r in rows if "rule" in r and r["book"] == it.get("book")]
    # cited by page (`citing.cited`): the no-clause rules of its book holding its quote; a book read by its pages: its page
    # (recheck of update 11, R2-1: with no rules the page branch below was never reached)
    if rules and not str(it.get("clause") or "").strip():
        from .verify import quote_in

        q = str(it.get("rule_quote") or "")
        return [r for r in rules if not str(r["clause"] or "").strip() and quote_in(q, r["text"].removesuffix(" [CUT: rule text longer than shown]"))]  # fmt: skip
    exact = [r for r in rules if _same(r["clause"], it.get("clause"))]
    if exact or rules:
        return exact or [r for r in rules if _in_cited(r["clause"], it.get("clause"))]
    try:
        page = int(it.get("page") or 0)
    except (TypeError, ValueError):
        return []
    return [
        r
        for r in rows
        if "rule" not in r
        and r.get("page_of") == it.get("book")
        and abs(int(r["page"] or 0) - page) <= 1
    ]


def _groups(
    held: list[dict], rows: list[dict]
) -> tuple[list[tuple[list[dict], list[dict]]], list[dict]]:
    """([(items, their material)], items not attackable). Items join a group while it has fewer than ATTACK_ITEMS and the
    group's material, every item's own rule rows, stays within the batch size (review of update 11, B1: a fixed group of 12 under
    a 9,000-character cut showed 11 of 12 rules). An item whose own rule rows are none, or alone over the size, is not attacked."""
    from .checklist import _material_line

    most = cap(BATCH_CHARS, "batch_chars")
    out, off, cur, mat, size = [], [], [], [], 0
    for it in held:
        own = _own_rows(it, rows)
        if not own or sum(len(_material_line(r)) for r in own) > most:
            off.append(it)
            continue
        need = [r for r in own if not any(r is m for m in mat)]
        add = sum(len(_material_line(r)) for r in need)
        if cur and (len(cur) >= ATTACK_ITEMS or size + add > most):
            out.append((cur, mat))
            cur, mat, size = [], [], 0
            need, add = own, sum(len(_material_line(r)) for r in own)
        cur.append(it)
        mat += need
        size += add
    if cur:
        out.append((cur, mat))
    return out, off


def _ask(model, strong, ident, sel, group, mat, depth: int = 0) -> dict:
    from .checklist import _books_line, _dumps, _for_type, _identity, _material_line

    try:
        got = model.ask(step="aim_attack_items", model=strong, system="", cached=None,
                        prompt=_for_type(P.ATTACK_LOCAL) % {
                            "identity": _identity(ident), "items": "\n".join(_dumps(s) for s in group),
                            "books": _books_line(sel),
                            "material": "\n".join(_material_line(r) for r in mat)},
                        carries={b["book"] for b in sel["books"]}, max_tokens=8_192)  # fmt: skip
    except StepFailed as exc:
        if "max_tokens" not in str(exc):
            raise
        if len(group) < 2 or depth >= _SPLIT_DEPTH:
            for _ in group:
                faults.record("aim_attack_item_cut", "an attack item", "answer cut")
            return {}
        h = len(group) // 2
        return _ask(
            model, strong, ident, sel, group[:h], _mat(group[:h], mat), depth + 1
        ) | _ask(model, strong, ident, sel, group[h:], _mat(group[h:], mat), depth + 1)
    ids = {it["id"] for it in group}
    verdicts = (got or {}).get("verdicts") if isinstance(got, dict) else None
    out = {
        v["id"]: v for v in verdicts or [] if isinstance(v, dict) and v.get("id") in ids
    }
    for _ in ids - set(out):
        faults.record(
            "aim_attack_no_verdict",
            "an attack item",
            "no verdict in the answer",
        )
    return out


def _mat(group: list[dict], mat: list[dict]) -> list[dict]:
    """The part of a group's material that is its items' own rules (a half asked again reads only its own)."""
    own = [r for it in group for r in _own_rows(it, mat)]
    return [r for r in mat if any(r is o for o in own)]


def attack(
    model,
    ident: dict,
    sel: dict,
    made: dict,
    rows: list[dict],
    shown: list[dict],
    strong: str,
) -> dict:
    """The checklist after the local attack, with its log (the same shape as the Claude attack's)."""
    from .checklist import HELD

    by_id = {it["id"]: it for it in made["items"]}
    groups, off = _groups(
        [s for s in shown if s.get("source") == HELD], rows
    )  # knowledge items: not attacked here
    for _ in [
        s for s in shown if s.get("source") != HELD
    ]:  # said on the page (review of update 11, recheck)
        faults.record("aim_attack_knowledge", "a knowledge item", "no held rule")
    for _ in off:  # kept as written, counted
        faults.record(
            "aim_attack_not_shown", "an attack item", "its rule could not be shown"
        )
    verdicts: dict = {}
    for group, mat in groups:
        verdicts |= _ask(model, strong, ident, sel, group, mat)
    log = {"removed": [], "fixed": [], "added": [], "rejected": []}
    for i, v in verdicts.items():
        why = str(v.get("why") or "")[:120]
        if v.get("verdict") == "remove" and i in by_id:
            by_id.pop(i)
            log["removed"].append({"id": i, "why": why})
        elif (
            v.get("verdict") == "fix"
            and i in by_id
            and str(v.get("what_to_check") or "").strip()
        ):
            by_id[i] = by_id[i] | {
                "what_to_check": str(v["what_to_check"]).strip()[:300]
            }
            log["fixed"].append({"id": i, "why": why})
    return {**made, "items": list(by_id.values()), "attack": log}
