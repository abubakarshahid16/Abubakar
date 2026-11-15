"""Role 4, step "match": which STORED rule row, if any, a chapter finding is about (nine-role reviewer, builder B4).

A finding read from a rule book's chapter has no rule row of its own. Code gives it one only when it is sure:

  * the same book (`standard_document_id`);
  * the finding's clause quote, already verified in the book's own pages, lies INSIDE the rule's stored `source_text`, or holds
    it WHOLE (compared as folded text, `reader_api._fold`, the paper quote's own fold);
  * exactly ONE rule row passes. Two candidates are no match: code never picks one.

A match is the line `R-<rule id>` and takes that rule's CURRENT tier, asked of the one function every other line uses
(`agent_review_verdict.item_tier` with the run's `tier_lookup`): a match never gives a better tier than the rule has, and a rule the
label table does not approve stays "not approved" (an opinion at most). No match: the caller makes an `F-<hash>` item with no tier.
Pure on its inputs (the rule rows and the tier function are given); no model, no network, no text written. General: no book, layout
or word list (CLAUDE.md rule 13).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from . import agent_review_verdict as verdict
from .reader_api import _fold

#: a rule text shorter than this is never "held whole" by a longer quote: it would match by chance
MIN_SOURCE_CHARS = 20
#: a quote shorter than this proves nothing about which rule it is
MIN_QUOTE_CHARS = 20

WHY_MATCHED = "matched one stored rule of this book"
WHY_NONE = "no stored rule of this book holds this quote"
WHY_MANY = "more than one stored rule of this book holds this quote"
WHY_NO_QUOTE = "no verified clause quote to match on"


@dataclass(frozen=True)
class Match:
    """`rule_id`: the stored rule's id (no "R-" prefix), None when there is no match. `tier`: its CURRENT tier (one of
    `USABLE_TIERS`) or `RULE_NOT_APPROVED`; None when there is no match."""

    rule_id: str | None
    item_id: str | None
    tier: str | None
    why: str
    candidates: int

    @property
    def matched(self) -> bool:
        return self.rule_id is not None


def _holds(quote: str, rule_text: str) -> bool:
    """The folded quote lies inside the folded rule text, or holds it whole."""
    q, r = _fold(quote), _fold(rule_text)
    if not q or not r:
        return False
    if len(q) >= MIN_QUOTE_CHARS and q in r:
        return True
    return len(r) >= MIN_SOURCE_CHARS and r in q


def candidates(book_id: str | None, clause_quote: str | None, rules: Iterable[Mapping]) -> list[Mapping]:
    """The rule rows of the SAME book whose stored `source_text` the quote lies inside or holds whole."""
    if not book_id or not str(clause_quote or "").strip():
        return []
    return [
        r
        for r in rules
        if str(r.get("standard_document_id") or "") == str(book_id) and _holds(str(clause_quote), str(r.get("source_text") or ""))
    ]


def match(
    book_id: str | None,
    clause_quote: str | None,
    rules: Iterable[Mapping],
    tier_lookup: Callable[[Mapping], str | None] | None,
) -> Match:
    """THE match. `rules`: rows with `id`, `standard_document_id`, `source_text`. `tier_lookup`: the run's (`rules.tier_lookup`), the one
    that decides a rule's tier everywhere; with none, nothing is approved. Two candidates are NO match."""
    if not book_id or not str(clause_quote or "").strip():
        return Match(None, None, None, WHY_NO_QUOTE, 0)
    found = candidates(book_id, clause_quote, rules)
    if not found:
        return Match(None, None, None, WHY_NONE, 0)
    if len(found) > 1:
        return Match(None, None, None, WHY_MANY, len(found))
    rule_id = str(found[0].get("id"))
    item_id = f"R-{rule_id}"
    stub = {"item_id": item_id, "source": "rule", "rule_version_id": rule_id, "standard_document_id": str(book_id)}
    tier = verdict.item_tier(stub, tier_lookup)  # the CURRENT tier by the one function; never promoted here
    return Match(rule_id, item_id, tier, WHY_MATCHED, 1)
