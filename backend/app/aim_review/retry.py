"""The checklist retry on the local model: a cut answer is never used (lead-4, 26 Nov 2026). Its own home so the checklist
module stays under its size limit."""

from __future__ import annotations

import logging
import re

from . import prompts as P
from .budget import is_local
from .engine import StepFailed

log = logging.getLogger(__name__)


def retried(model, bad: list[dict], batch, carries, lead, depth: int = 0) -> list[dict]:
    """The retry's items for `bad` (one call). On the local model a cut answer is never used: the items are asked again in two
    halves, and one item whose answer is still cut is dropped (its quote stays not found; counted under "Steps that did not run"); on Claude a cut is raised, as before."""
    from .checklist import SPLIT_DEPTH, _dumps, _items_of, _material_line

    prompt = P.S3_RETRY % {
        "items": _dumps(bad),
        "material": "\n".join(_material_line(r) for r in batch),
    }
    try:
        fix = model.ask(step="aim_checklist_retry", model=lead, system="", cached=None, prompt=prompt, carries=carries,
                        max_tokens=8000)  # fmt: skip
    except StepFailed as exc:
        if not is_local() or "max_tokens" not in str(exc):
            raise
        if (
            len(bad) < 2 or depth >= SPLIT_DEPTH
        ):  # still cut: never stops the run; each item is counted as left out
            from . import faults

            for _ in bad:
                faults.record(
                    "aim_retry_dropped", "a checklist retry item", "answer cut"
                )
            return []
        h = len(bad) // 2
        return retried(model, bad[:h], batch, carries, lead, depth + 1) + retried(
            model, bad[h:], batch, carries, lead, depth + 1
        )
    return _items_of(fix)


_CUT = " [CUT: rule text longer than shown]"


#: The share of a quote's words a stored rule must hold to be taken as the rule the quote means (F's 14B run e19e3d8a: a clause
#: often holds several stored rules, and the model's page or clause was off, so "one rule per clause" fixed almost none).
COVER = 0.6


def _words(s) -> set[str]:
    return {
        w
        for w in re.findall(r"[a-z0-9]+", str(s or "").lower())
        if len(w) > 2 or w.isdigit()
    }


def _rule_for(it: dict, rules: list[dict]) -> dict | None:
    """The batch's rule the item's quote means: the one holding the largest share (at least COVER) of the quote's words, the
    item's own book and clause first on a tie; with a quote too short to tell (under 4 words), the one rule of its book and
    clause, if there is exactly one."""
    q = _words(it.get("rule_quote"))
    if len(q) >= 4:
        score = lambda i, r: (len(q & _words(r["text"])) / len(q), r["book"] == it.get("book"),  # noqa: E731
                              _same(r["clause"], it.get("clause")), -i)  # fmt: skip
        i, r = max(enumerate(rules), key=lambda x: score(*x), default=(0, None))
        return r if r is not None and score(i, r)[0] >= COVER else None
    same = [
        r
        for r in rules
        if r["book"] == it.get("book") and _same(r["clause"], it.get("clause"))
    ]
    return same[0] if len(same) == 1 else None


def by_code(bad: list[dict], batch, found) -> tuple[list[dict], list[dict]]:
    """(fixed, still to ask). On the local model, an item whose quote was not found takes the stored words (as shown, without
    the cut mark), book, clause and page of the batch's rule its quote means (`_rule_for`), and is kept only if `found` then
    finds those words on the book page. No call is made for it (F's 14B runs 09105c4b and e19e3d8a, 26 Nov 2026: the retry
    calls ran the review past the swap rule). The others are asked again as before. On Claude: nothing fixed by code."""
    if not is_local():
        return [], bad
    rules = [r for r in batch if "rule" in r]
    fixed, ask = [], []
    for it in bad:
        r = _rule_for(it, rules)
        if r is not None:
            got = it | {"rule_quote": r["text"].removesuffix(_CUT).strip(), "book": r["book"], "clause": r["clause"],
                        "page": r["page"]}  # fmt: skip
            if found(got):
                fixed.append(got)
                continue
        ask.append(it)
    log.info(
        "general review: %d of %d rule quotes taken from the stored rule by code",
        len(fixed),
        len(bad),
    )
    return fixed, ask


def capped(ask: list[dict], size: int) -> list[dict]:
    """On the local model at most ONE retry call per batch (its first `size` items; lead-4, 26 Nov 2026, after F's run
    09105c4b): the other items keep their quote not found, are left out like any such item, and are counted under "Steps that
    did not run". On Claude: every item, as before."""
    if not is_local() or len(ask) <= size:
        return ask
    from . import faults

    for _ in ask[size:]:
        faults.record(
            "aim_retry_capped",
            "a checklist retry item",
            "the local model makes one retry call per batch",
        )
    return ask[:size]


def _same(a, b) -> bool:
    return str(a or "").strip().rstrip(".") == str(b or "").strip().rstrip(".") != ""


#: Items one local checklist call may give per rule part of its batch, and the answer tokens allowed per item (plus a base).
ITEMS_PER_RULE, TOKENS_PER_ITEM, BASE_TOKENS = 2, 320, 500


def room(batch: list[dict], claude_tokens: int) -> tuple[int | None, int]:
    """(at most this many items, at most this many answer tokens) for one checklist call. On the local model both follow the
    batch's size (lead-4, 26 Nov 2026: a fixed 8,192 let the 14B loop on its smallest batches); on Claude (None, as before)."""
    if not is_local():
        return None, claude_tokens
    n = max(4, ITEMS_PER_RULE * len(batch))
    return n, min(claude_tokens, BASE_TOKENS + TOKENS_PER_ITEM * n)


def _key(it: dict) -> tuple:
    return tuple(
        " ".join(str(it.get(k) or "").lower().split())
        for k in ("topic", "what_to_check", "rule_quote")
    )


def unique(items: list[dict]) -> list[dict]:
    """On the local model, an answer that repeats an item is cut at the first repeat (counted under "Steps that did not run"): only the
    items before it are used (a looping answer's tail is the loop). On Claude, unchanged."""
    if not is_local():
        return items
    seen: set = set()
    for i, it in enumerate(items):
        if _key(it) in seen:
            from . import faults

            faults.record(
                "aim_repeat_cut",
                "a repeating checklist answer",
                "the items before the repeat were used",
            )
            return items[:i]
        seen.add(_key(it))
    return items
