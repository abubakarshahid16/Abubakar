"""The checklist retry on the local model: a cut answer is never used (lead-4, 26 Nov 2026). Its own home so the checklist
module stays under its size limit."""

from __future__ import annotations

from . import prompts as P
from .budget import is_local
from .engine import StepFailed


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
