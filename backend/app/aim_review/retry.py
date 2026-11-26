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

            for it in bad:
                it["_cut"] = True  # counted here, not again as "not found" (`unfound`)
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


#: The share of a quote's content words a stored rule must hold to be taken as the rule the quote means (F's 14B run e19e3d8a: a
#: clause often holds several stored rules, and the model's page was off, so "one rule per clause" fixed almost none).
COVER = 0.6
#: Words that say nothing about what a rule is about: they never count towards COVER (review of update 10, M1: "the", "shall"
#: and "for" made a coating quote match a gasket rule). Plain English grammar words only.
_GRAMMAR = (
    "the and for are was were shall should must may can will with without from into onto upon this that these those such "
    "than then any all each every other its their his her our your not nor but per via has have had been being where when "
    "which who whom what how also only both either neither more most less least same very"
)
_STOP = frozenset(re.findall(r"[a-z]+", _GRAMMAR))


def _words(s) -> set[str]:
    """The content words of `s`: words of 3 letters or more that are not grammar words, and numbers."""
    found = re.findall(r"[a-z0-9]+", str(s or "").lower())
    return {w for w in found if w.isdigit() or (len(w) >= 3 and w not in _STOP)}


def _clause_parts(c) -> tuple[str, ...]:
    return tuple(p for p in str(c or "").strip().rstrip(".").split(".") if p.strip())


def _in_cited(rule_clause, cited) -> bool:
    """The rule's clause is the cited clause, one under it ("4.1" -> "4.1.2"), or the cited clause's parent ("4.1.2" -> "4.1")."""
    r, c = _clause_parts(rule_clause), _clause_parts(cited)
    return bool(r and c) and (r[: len(c)] == c or r == c[:-1])


def _rule_for(it: dict, rules: list[dict]) -> dict | None:
    """The rule the item's quote means, looked for ONLY in the item's own book and within its cited clause (`_in_cited`):
    the one holding the largest share (at least COVER) of the quote's content words, its exact clause first on a tie. With a
    quote of under 4 content words, the one rule of its book and exact clause, if there is exactly one. A rule of another
    book or clause is never taken (review of update 10, M1: code compared the paper against the wrong rule's limit)."""
    mine = [
        r
        for r in rules
        if r["book"] == it.get("book") and _in_cited(r["clause"], it.get("clause"))
    ]
    q = _words(it.get("rule_quote"))
    if len(q) >= 4:

        def score(i: int, r: dict) -> tuple:
            return (
                len(q & _words(r["text"])) / len(q),
                _same(r["clause"], it.get("clause")),
                -i,
            )

        i, r = max(enumerate(mine), key=lambda x: score(*x), default=(0, None))
        return r if r is not None and score(i, r)[0] >= COVER else None
    same = [r for r in mine if _same(r["clause"], it.get("clause"))]
    return same[0] if len(same) == 1 else None


def by_code(bad: list[dict], batch, found) -> tuple[list[dict], list[dict]]:
    """(fixed, still to ask). On the local model, an item whose quote was not found takes the stored words (as shown, without
    the cut mark), clause and page of the rule of its own book and cited clause its quote means (`_rule_for`), and is kept only if `found` then
    finds those words on the book page. No call is made for it (F's 14B runs 09105c4b and e19e3d8a, 26 Nov 2026: the retry
    calls ran the review past the swap rule). The others are asked again as before. On Claude: nothing fixed by code."""
    if not is_local():
        return [], bad
    rules = [r for r in batch if "rule" in r]
    fixed, ask = [], []
    for it in bad:
        r = _rule_for(it, rules)
        if r is not None:
            got = it | {
                "rule_quote": r["text"].removesuffix(_CUT).strip(),
                "clause": r["clause"],
                "page": r["page"],
            }
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


def unfound(asked: list[dict], ok: list[dict], why) -> None:
    """On the local model: the items asked again whose answer came back (not cut) and still did not give a quote found, each
    counted by its cause (review of update 11, N4: they were only in the checklist's 'dropped')."""
    if not is_local():
        return
    from . import faults

    answered = [it for it in asked if not it.pop("_cut", False)]
    n, topics = max(0, len(answered) - len(ok)), {o.get("topic") for o in ok}
    missing = [it for it in answered if it.get("topic") not in topics]
    for it in (missing + [it for it in answered if it not in missing])[:n]:
        faults.record("aim_retry_not_found", "a checklist retry item", why(it))


def capped(ask: list[dict], size: int, why=None) -> list[dict]:
    """On the local model at most ONE retry call per batch (its first `size` items; lead-4, 26 Nov 2026, after F's run
    09105c4b): the other items keep their quote not found, are left out like any such item, and are counted under "Steps that
    did not run". On Claude: every item, as before."""
    if not is_local() or len(ask) <= size:
        return ask
    from . import faults

    for it in ask[
        size:
    ]:  # counted by cause (`citing.cause`): the page and the sheet say why
        faults.record(
            "aim_retry_capped",
            "a checklist retry item",
            why(it) if why else "not asked again",
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
