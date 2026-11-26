"""ON THE LOCAL MODEL A KEPT ITEM'S CLAUSE RESOLVES (lead-4, 26 Nov 2026, after F's 9B run on update 10: eleven items in a row
were cited to one clause for unrelated subjects, as the quote check reads the book PAGE, never the clause). Its own home so the
checklist module stays under its size limit. No document text is logged or recorded: only the cause's own words.

`cited`: a held item whose quote code found on its book page keeps its clause only when a stored rule of that clause holds the
quote; when exactly one other clause of the same book holds it, the item is cited to that clause (the citation that resolves);
otherwise it is treated as a quote not found (retried, or left out and counted). A book read by its pages (no stored rules in
the batch) is cited by page, as before. `cause`: why an item's quote was not found, in plain words, for the count on the page
and the sheet. On Claude both leave everything as before.
"""

from __future__ import annotations

from .budget import is_local
from .verify import find_page, quote_in

_CUT = " [CUT: rule text longer than shown]"


def _clause(c) -> str:
    return str(c or "").strip().rstrip(".")


def cited(
    it: dict, batch: list[dict]
) -> bool:  # `batch`: every rule row of the run (review of update 11, N1)
    """True when the item's clause resolves (see the module); may re-cite the item to the one clause whose rule holds it."""
    if not is_local():
        return True
    rules = [r for r in batch if "rule" in r and r["book"] == it.get("book")]
    if not rules:
        return True  # a book read by its pages: the page and quote are the citation
    q = str(it.get("rule_quote") or "")
    holding = [r for r in rules if quote_in(q, r["text"].removesuffix(_CUT))]
    holds = {
        _clause(r["clause"]) for r in holding if _clause(r["clause"])
    }  # NUMBERED rules holding the quote
    if _clause(it.get("clause")) in holds:
        return True
    if len(holds) == 1:
        it["clause"] = next(iter(holds))
        return True
    if not holds and any(not _clause(r["clause"]) for r in holding):
        # only a rule with no clause number holds it (review of update 11, B2: most stored rules have none): cited by PAGE, like
        # a book read by pages; never re-cited to a numbered clause, and a clause number it gave that holds nothing is dropped
        it["clause"] = ""
        return True
    return False


#: The causes of a quote not found, as the page and the sheet say them.
NO_BOOK = "it named no rule book of this review"
NO_QUOTE = "it gave no rule quote"
OTHER_PAGE = "the quote is on another page of the book than the one it gave"
NOT_IN_CLAUSE = "the quote is on the page but in no stored rule of its clause"
NOT_IN_BOOK = "the quote is not in the book's words (paraphrased)"


def cause(it: dict, text, alias_to_book: dict[str, str]) -> str:
    """Why the item's rule quote was not found (checked in this order)."""
    book = alias_to_book.get(str(it.get("book") or ""))
    q = str(it.get("rule_quote") or "")
    if not book:
        return NO_BOOK
    if not q.strip():
        return NO_QUOTE
    try:
        page = int(it.get("page") or 0)
    except (TypeError, ValueError):
        page = 0
    near = {
        p: t for p in (page, page - 1, page + 1) if p > 0 and (t := text.page(book, p))
    }
    if find_page(q, near, page) is not None:
        return NOT_IN_CLAUSE
    return (
        OTHER_PAGE if find_page(q, dict(text.pages(book))) is not None else NOT_IN_BOOK
    )
