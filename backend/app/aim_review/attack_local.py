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


def _material_for(group: list[dict], rows: list[dict]) -> list[dict]:
    """The rule rows (and book pages) the group's items cite, within the batch size."""
    from .checklist import _material_line
    from .retry import _in_cited

    cites = [
        (it.get("book"), it.get("clause"), it.get("page"))
        for it in group
        if it.get("book")
    ]
    out, size, most = [], 0, cap(BATCH_CHARS, "batch_chars")
    for r in rows:
        if "rule" in r:
            wanted = any(
                r["book"] == b and _in_cited(r["clause"], c) for b, c, _ in cites
            )
        else:
            wanted = any(
                r.get("page_of") == b and abs(int(r["page"] or 0) - int(p or 0)) <= 1
                for b, _, p in cites
            )
        ln = len(_material_line(r))
        if wanted and size + ln <= most:
            out.append(r)
            size += ln
    return out


def _ask(model, strong, ident, sel, group, rows, depth: int = 0) -> dict:
    from .checklist import _books_line, _dumps, _for_type, _identity, _material_line

    try:
        got = model.ask(step="aim_attack_items", model=strong, system="", cached=None,
                        prompt=_for_type(P.ATTACK_LOCAL) % {
                            "identity": _identity(ident), "items": "\n".join(_dumps(s) for s in group),
                            "books": _books_line(sel),
                            "material": "\n".join(_material_line(r) for r in _material_for(group, rows)) or "none"},
                        carries={b["book"] for b in sel["books"]}, max_tokens=8_192)  # fmt: skip
    except StepFailed as exc:
        if "max_tokens" not in str(exc):
            raise
        if len(group) < 2 or depth >= _SPLIT_DEPTH:
            for _ in group:
                faults.record("aim_attack_item_cut", "an attack item", "answer cut")
            return {}
        h = len(group) // 2
        return _ask(model, strong, ident, sel, group[:h], rows, depth + 1) | _ask(
            model, strong, ident, sel, group[h:], rows, depth + 1
        )
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
    by_id = {it["id"]: it for it in made["items"]}
    verdicts: dict = {}
    for k in range(0, len(shown), ATTACK_ITEMS):
        verdicts |= _ask(model, strong, ident, sel, shown[k : k + ATTACK_ITEMS], rows)
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
