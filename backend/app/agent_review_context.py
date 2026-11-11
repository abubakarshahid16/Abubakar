"""F4: the CONTEXT CHECK before a Fail is proven (ported from the experiment's exp12/context_check.py and the Runner's
`context_check_fail`). Pure functions: the request, the neighbour-page rule and the code's verdict on the model's answer. The
model call is an INJECTED callable (`ask`): this module has no network code and buys nothing itself.

Why: a stored rule sentence can lose the context that limits it (a table heading, a scope sentence, a note on the same page).
A Fail is proven only when the rule-book page states no such limit (the model says `limits` is the boolean false), or states
one that the paper evidence is shown to meet, with BOTH quotes verified word for word by code. EVERY other exit holds the
Fail as "AI thinks: not met": no page, rule quote not on its own page, a failed or unreadable call, a model of the lead's
family, a stored line without a matching fingerprint. It can only make a verdict less confident. No equipment word, no
layout (rule 13).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from . import agent_claude, agent_run_second
from .reader_api import _fold

MIN_QUOTE_CHARS = 12
EDGE = 0.15  # a quote in the first or last 15% of its page text pulls in the neighbour page
WHY_LIMITS = (
    "a condition on the rule-book page limits this rule; code cannot prove it holds"
)
WHY_NOT_DONE = "context check not completed"
PROVEN, HELD, NOT_COMPLETED = "proven", "held", "not_completed"

CONTEXT_SYSTEM = (
    "CONTEXT CHECK. A reviewer is about to state that a supplier paper FAILS a held requirement. The requirement is one "
    "sentence cut out of a standard; it may have lost the context that limits it. You get the sentence, its clause number, "
    "the FULL stored text of the standard's page that holds it (and a neighbour page when the sentence sits near the page "
    "edge), then the paper words the Fail rests on and the paper pages. Answer from these texts only. limits: true when the "
    "standard page states a condition, scope, service, type, exception, table heading or note that limits WHEN this "
    "sentence applies, else false. condition_quote: when limits is true, the words of that condition copied word for word "
    'from the standard page. condition_met: "yes" when the paper pages show the condition holds for this item, "no" '
    'when they show it does not, "not_shown" when they do not show it. paper_quote_for_condition: when "yes", the '
    "paper words that show it, copied word for word from the paper pages. reason: at most 20 words."
)
ANSWER_SHAPE = (
    'Reply with ONE JSON object: {"limits": true or false, "condition_quote": "...", "condition_met": '
    '"yes or no or not_shown", "paper_quote_for_condition": "...", "reason": "..."}'
)


def fingerprint(rule_text: Any, paper_quotes: Any) -> str:
    """A hash of the rule quote and the paper quote(s) a check was made on: an old outcome carries over only when both are the
    same (folded) words."""
    parts = [
        _fold(str(rule_text or "")),
        *sorted(_fold(str(q)) for q in (paper_quotes or []) if q),
    ]
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()[:16]


def quote_on_page(quote: Any, page_text: Any) -> bool:
    """The rule quote stands (folded) on its own rule-book page."""
    q = _fold(str(quote or ""))
    return bool(q) and q in _fold(str(page_text or ""))


def neighbour_pages(page: int, text: str, rule_text: str | None) -> list[int]:
    """The pages to send: the quote's page, plus the previous one when the quote starts in the first EDGE of the page text,
    the next one when it ends in the last EDGE (both when the quote is not found on the page)."""
    out = [page]
    folded, quote = _fold(text), _fold(rule_text or "")
    at = folded.find(quote) if quote else -1
    if at < 0:
        return [page - 1, page, page + 1] if page > 1 else [page, page + 1]
    n = max(1, len(folded))
    if at / n < EDGE and page > 1:
        out.insert(0, page - 1)
    if (at + len(quote)) / n > 1 - EDGE:
        out.append(page + 1)
    return out


def build_parts(
    rule_text: str,
    clause: Any,
    rule_pages: Mapping[int, str],
    paper_quotes: list[str],
    paper_pages: Mapping[int, str],
) -> dict:
    claim = {
        "rule_quote": rule_text,
        "clause": clause,
        "standard_pages": {str(n): t for n, t in sorted(rule_pages.items())},
        "paper_quotes_the_fail_rests_on": [q for q in paper_quotes if q],
        "paper_pages": {str(n): t for n, t in sorted(paper_pages.items())},
        "question": ANSWER_SHAPE,
    }
    return {
        "system": [
            {
                "type": "text",
                "text": CONTEXT_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": json.dumps(claim, ensure_ascii=False)}
                ],
            }
        ],
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
    }


def _found(quote: Any, texts: list[str]) -> bool:
    q = _fold(str(quote or ""))
    return len(q) >= MIN_QUOTE_CHARS and any(q in _fold(t) for t in texts)


def evaluate(obj: Any, rule_page_texts: list[str], paper_page_texts: list[str]) -> dict:
    """The code's decision on the model's answer: outcome proven | held | not_completed, plus limits and condition_met."""
    if not isinstance(obj, dict) or not isinstance(obj.get("limits"), bool):
        return {
            "outcome": NOT_COMPLETED,
            "limits": None,
            "condition_met": None,
            "why": WHY_NOT_DONE,
        }
    limits = obj["limits"]
    met = str(obj.get("condition_met") or "").strip().lower() or None
    if not limits:
        return {"outcome": PROVEN, "limits": False, "condition_met": met, "why": None}
    if (
        met == "yes"
        and _found(obj.get("condition_quote"), rule_page_texts)
        and _found(obj.get("paper_quote_for_condition"), paper_page_texts)
    ):
        return {"outcome": PROVEN, "limits": True, "condition_met": "yes", "why": None}
    return {"outcome": HELD, "limits": True, "condition_met": met, "why": WHY_LIMITS}


def held_decision(decision: Mapping, why: str) -> dict:
    return {
        **decision,
        "verdict": "Query",
        "decided_by": "engineer",
        "why": why,
        "context_hold": True,
    }


# ---------------------------------------------------------------- the whole code decision


@dataclass
class ContextResult:
    """`decision`: the decision after the check (a Fail stays only when proven). `info`: the line keys. `exchange`: what
    was asked and answered (the trace; paper text, local only). `fatal`: a fatal exception (budget stop) the caller must
    halt on; the Fail is held."""

    decision: dict
    info: dict = field(default_factory=dict)
    exchange: dict | None = None
    fatal: BaseException | None = None


def _done(
    decision: Mapping,
    fp: str,
    outcome: Mapping,
    exchange: dict | None = None,
    fatal_exc: BaseException | None = None,
) -> ContextResult:
    """The result for an outcome: a Fail stays only when the outcome is `proven`; every other outcome holds it."""
    info = {
        "context_check": outcome["outcome"],
        "context_limits": outcome.get("limits"),
        "context_condition_met": outcome.get("condition_met"),
        "context_hash": fp,
    }
    if outcome["outcome"] == PROVEN:
        return ContextResult(dict(decision), info, exchange, fatal_exc)
    held = held_decision(decision, outcome.get("why") or WHY_NOT_DONE)
    return ContextResult(held, info, exchange, fatal_exc)


def _not_done(decision, fp, exchange=None, fatal_exc=None) -> ContextResult:
    outcome = {
        "outcome": NOT_COMPLETED,
        "limits": None,
        "condition_met": None,
        "why": WHY_NOT_DONE,
    }
    return _done(decision, fp, outcome, exchange, fatal_exc)


def _stored_outcome(stored: Mapping | None, fp: str) -> dict | None:
    """The outcome of an earlier check of the SAME rule quote and paper quote(s) (fingerprint equal), or None."""
    if not stored or stored.get("context_hash") != fp:
        return None
    base = {
        "limits": stored.get("context_limits"),
        "condition_met": stored.get("context_condition_met"),
    }
    if stored.get("context_check") == PROVEN:
        return {**base, "outcome": PROVEN, "why": None}
    if (
        stored.get("context_check") == HELD
    ):  # a line held before stays held, no new call
        return {**base, "outcome": HELD, "why": WHY_LIMITS}
    return None


def _rule_pages(rule_text, rule_doc, rule_page, std_pages) -> dict[int, str] | None:
    """The rule-book page(s) to send, or None when there is no page or the quote is not on its own page."""
    first = (
        std_pages(rule_doc, rule_page)
        if (std_pages and rule_doc and isinstance(rule_page, int))
        else None
    )
    if not first or not rule_text or not quote_on_page(rule_text, first):
        return None
    pages = {}
    for n in neighbour_pages(rule_page, first, rule_text):
        text = first if n == rule_page else std_pages(rule_doc, n)
        if text:
            pages[n] = text
    return pages


def check_fail(
    decision: Mapping,
    *,
    rule_text: str | None,
    paper_quotes: list,
    paper_pages: Mapping[int, str],
    rule_doc: Any,
    rule_page: Any,
    clause: Any,
    std_pages: Callable[[Any, int], str | None] | None,
    ask: Callable[[dict], Mapping] | None,
    lead_model: str | None,
    stored: Mapping | None = None,
    in_scope: bool = True,
    fatal: tuple[type[BaseException], ...] = (),
) -> ContextResult:
    """F4. Only a Fail is checked and the result can only HOLD it. A Fail is proven only if (a) THIS call said proven, or (b)
    the STORED line carries `context_check` proven for the same rule quote and paper quote(s) (fingerprint). Every other path
    holds it ("context check not completed"): no call possible (`ask` None or `in_scope` False), no rule-book page, the rule
    quote not on its own page, an exception from the call, an answer that is not a JSON object with a boolean `limits`, a
    model of the lead's family (or unnamed). A stored `held` line for the same quotes stays held without a new call.

    `ask(parts)` returns {"obj": parsed JSON | None, "text": raw reply text, "model": answering model id, "usd": number};
    when `obj` is absent `text` is parsed. It may raise; it never decides anything."""
    if decision.get("verdict") != "Fail":
        return ContextResult(dict(decision))
    fp = fingerprint(rule_text, paper_quotes)
    carried = _stored_outcome(stored, fp)
    if carried is not None:
        return _done(decision, fp, carried)
    if (
        not in_scope or ask is None
    ):  # no call is made: a Fail is never proven without the check
        return _not_done(decision, fp)
    rule_pages = _rule_pages(rule_text, rule_doc, rule_page, std_pages)
    if not rule_pages:  # no page, or the quote is not on its own page
        return _not_done(decision, fp)
    parts = build_parts(
        rule_text, clause, rule_pages, [str(q) for q in paper_quotes if q], paper_pages
    )
    exchange: dict = {
        "request": parts["messages"][0]["content"][0]["text"],
        "rule_pages": sorted(rule_pages),
        "paper_pages": sorted(paper_pages),
    }
    try:
        reply = ask(parts)
    except fatal as exc:  # a budget stop: the caller halts; the Fail is held
        exchange["error"] = "run stopped"
        return _not_done(decision, fp, exchange, exc)
    except Exception as exc:  # noqa: BLE001
        recorded = (
            type(exc).__name__
        )  # any other failure of the call holds the Fail; only the class is recorded
        exchange["error"] = recorded
        return _not_done(decision, fp, exchange)
    reply = reply if isinstance(reply, Mapping) else {}
    obj = reply.get("obj")
    if obj is None and reply.get("text"):
        obj = agent_claude.parse_json_object(str(reply.get("text")))
    model = reply.get("model")
    exchange.update(answer=obj, model=model, usd=reply.get("usd"))
    if not agent_run_second.models_differ(
        [lead_model or ""], model
    ):  # a model of the lead's family cannot check it
        exchange["error"] = "same model family as the lead, or unknown"
        return _not_done(decision, fp, exchange)
    outcome = evaluate(
        obj, list(rule_pages.values()), [t for t in paper_pages.values() if t]
    )
    exchange["code_decision"] = outcome
    return _done(decision, fp, outcome, exchange)
