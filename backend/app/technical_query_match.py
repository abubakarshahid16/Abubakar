"""What an evidence passage of a technical query is worth, decided by CODE (follow-up to #1920; the 12-question test of 26 Nov 2026).

Two things an engineer needs beside a passage that the search alone did not give:

LOCATOR. "clause 6.1, page 4", not just a page. Read from the passage's own heading when the search gave one, else from the stored page text:
the nearest clause heading ABOVE the passage on its page (else the last heading of the page before). A heading is only a line that looks like
one ("6.1 Painting", "Article 6 ...", "6 GENERAL"); a table row ("12 Set pressure bar") is not. Nothing found = no locator (never a guess).

KEY-TERM COUNT, INFORMATION ONLY. How many of the question's KEY TERMS the passage holds (its distinctive words, no filler), shown as "4 of 6 key
terms". It is never used to say that a question is "not covered": measured on the 12-question test (26 Nov 2026) the overlap missed 7 of 10 answered
questions, because contractors word questions their own way. Passages are ranked by the reranker's own score (`rank_score`).
"""

from __future__ import annotations

import math
import re

STOP = frozenset(
    "a an and are as at be been being but by can could did do does for from had has have how if in into is it its may might must no not of on or our "
    "shall should so such than that the their them then there these they this those to under up upon was we were what when where which who whom why "
    "will with within without would you your please confirm state advise provide clarify specify kindly regarding concerning applicable apply applies "
    "required requirement requirements require contract contractor company project work works document documents clause section article query "
    "question questions answer".split()
)
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9/-]*")
MIN_TERM_LEN = 3


def stem(word: str) -> str:
    """A light stem: lower case, a plural or an -ing/-ed ending removed from a word of 5 letters or more (never from an identifier with a digit)."""
    w = word.casefold().strip("-/")
    if any(c.isdigit() for c in w) or len(w) < 5:
        return w
    for ending in ("ies", "ing", "ed", "es", "s"):
        if ending == "s" and w.endswith("ss"):
            continue
        if w.endswith(ending) and len(w) - len(ending) >= 4:
            return (w[: -len(ending)] + "y") if ending == "ies" else w[: -len(ending)]
    return w


def key_terms(question: str) -> list[str]:
    """The question's distinctive terms, stemmed, each once, in order: no filler words, nothing shorter than 3 letters unless it carries a digit."""
    seen: dict[str, None] = {}
    for raw in WORD.findall(question or ""):
        word = raw.casefold()
        if word in STOP or (
            len(word) < MIN_TERM_LEN and not any(c.isdigit() for c in word)
        ):
            continue
        seen.setdefault(stem(raw), None)
    return list(seen)


def required(n_terms: int) -> int:
    """How many key terms a passage must hold to MATCH: every one when there are one or two, else at least half (rounded up)."""
    return n_terms if n_terms <= 2 else math.ceil(n_terms / 2)


def score(terms: list[str], text: str) -> dict:
    """`{"matched": [terms the passage holds], "terms": N, "count": n, "matches": bool}` for one passage."""
    held = {stem(w) for w in WORD.findall(text or "")}
    matched = [t for t in terms if t in held]
    return {
        "matched": matched,
        "terms": len(terms),
        "count": len(matched),
        "matches": bool(terms) and len(matched) >= required(len(terms)),
    }


def coverage_of(terms: list[str], scores: list[dict]) -> dict:
    """Counts only, as INFORMATION: how many key terms the question has, how many passages there are, how many hold at least half of them.
    No verdict is drawn from them (a contractor words a question their own way, so a low overlap does not mean "not covered": measured on the
    12-question test, 26 Nov 2026, it was wrong on 7 of 10 answered questions)."""
    return {
        "key_terms": len(terms),
        "passages": len(scores),
        "matching_passages": sum(1 for s in scores if s["matches"]),
    }


# ------------------------------------------------------------------ the locator

KEYWORD = r"(?P<kw>clause|article|section|paragraph|schedule|appendix|annex|part)"
HEADING = re.compile(
    rf"^\s*(?:{KEYWORD}\s+)?(?P<num>(?:\d+\.)+\d+|\d+|[A-Z])(?P<sep>[\s.):–—-]+)(?P<title>[A-Z][^\n]{{2,80}})\s*$",
    re.IGNORECASE,
)
CLAUSE_NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)+)(?![\w.])")


def _heading_of(line: str) -> str | None:
    """A heading line as "6.1 Painting" / "Article 6 General", or None when the line is not a clause heading."""
    m = HEADING.match(line)
    if not m:
        return None
    kw, num, title = m.group("kw"), m.group("num"), " ".join(m.group("title").split())
    dotted = "." in num
    if not (
        kw or dotted or (num.isdigit() and title.isupper() and len(title.split()) <= 8)
    ):
        return None  # a bare number before words is a table row or a list, not a heading (a lone letter needs its keyword: "Annex A")
    if not kw and not dotted and not title[:1].isupper():
        return None
    if len(num) == 1 and num.isalpha() and not kw:
        return None
    label = f"{kw.capitalize()} " if kw else ""
    return f"{label}{num} {title}"[:100].strip()


def _squash(text: str) -> str:
    return " ".join((text or "").split())


#: A clause number standing ALONE on its line ("4.2.1", "4.", "Clause 7") whose title is the next line (a form found in the contract
#: parts: the number in one column, the title in the next). A dotted number of two levels or more, or a number with its dot.
_NUMBER_ALONE = re.compile(
    rf"^\s*(?:{KEYWORD}\s+)?(?P<num>(?:\d+\.)+\d+\.?|\d+\.)\s*$", re.IGNORECASE
)
_TITLE_LINE = re.compile(
    r"^\s*[A-Z(][^\n]{2,}$"
)  # a title, or a list item's text (any length: `_item_or_title` tells them apart)


#: A list item's text (not a title): a sentence, a long line, or a line holding a reference in brackets.
_ITEM_TEXT = re.compile(r"[.;:)]\s*$|\(|\S+(\s+\S+){7,}")


def _item_or_title(number: str, nxt: str, after: str) -> str | None:
    """A number standing alone ("4.2.1", "7.") with the next line: a clause heading "4.2.1 Title", or for a single number before a sentence
    a numbered LIST ITEM "Item 7", with the clause it refers to beside it when its text names one ("Item 7 (refers to 3.2.1)")."""
    if "." in number.rstrip("."):
        # a clause heading's title is heading-length: a dotted number before a long sentence is a wrapped reference, not a heading
        return (
            f"{number.rstrip('.')} {_squash(nxt)}"[:100].strip()
            if len(nxt.strip()) <= 80
            else None
        )
    if not _ITEM_TEXT.search(nxt.strip()):
        return f"{number.rstrip('.')} {_squash(nxt)}"[:100].strip()
    ref = CLAUSE_NUMBER.search(f"{nxt} {after}")
    return f"Item {number.rstrip('.')}" + (
        f" (refers to {ref.group(1)})" if ref else ""
    )


def _headings(lines: list[str]) -> list[tuple[int, str]]:
    """(line index, heading) of every clause heading of a page: one line ("6.1 Painting"), a number alone with its title on the next line,
    or a numbered list item of a schedule ("Item 7", review of evidence run 5: Q7)."""
    out = []
    for i, line in enumerate(lines):
        heading = _heading_of(line)
        if (
            heading is None
            and (m := _NUMBER_ALONE.match(line))
            and i + 1 < len(lines)
            and _TITLE_LINE.match(lines[i + 1])
        ):
            kw = m.group("kw")
            after = lines[i + 2] if i + 2 < len(lines) else ""
            found = _item_or_title(m.group("num"), lines[i + 1], after)
            heading = (
                f"{kw.capitalize()} {found}"
                if found and kw and not found.startswith("Item")
                else found
            )
        if heading:
            out.append((i, heading))
    return out


#: How far into a passage a heading may stand and still be its locator, when no heading stands above it on the page.
HEADING_IN_PASSAGE = 300


def heading_above(page_text: str, quote: str) -> str | None:
    """The nearest clause heading above the quote on this page (the line the quote starts on counts); when there is none above, the first
    heading in the quote's own first lines. None when there is none, or the quote cannot be placed on the page."""
    lines = (page_text or "").splitlines()
    squashed, offsets = "", []
    for line in lines:
        offsets.append(len(squashed))
        squashed += _squash(line) + " "
    anchor = _squash(quote)[:80]
    at = squashed.find(anchor) if anchor else -1
    if at < 0:
        return None
    above = [h for i, h in _headings(lines) if offsets[i] <= at]
    if above:
        return above[-1]
    inside = [
        h for i, h in _headings(lines) if at < offsets[i] < at + HEADING_IN_PASSAGE
    ]
    return inside[0] if inside else None


def last_heading(page_text: str) -> str | None:
    found = _headings((page_text or "").splitlines())
    return found[-1][1] if found else None


_SENTENCE = re.compile(r"(?<=[.;:!?])\s+|\n+")


def best_sentence(terms: list[str], text: str) -> str | None:
    """The sentence of a passage holding the most of the question's key terms (the first of equals), or None when none holds one: where the
    matched words sit, so a passage spanning several clauses is located at the clause that answers (review of evidence run 2: Q1, Q4)."""
    best, most = None, 0
    for sentence in (x.strip() for x in _SENTENCE.split(text or "")):
        held = score(terms, sentence)["count"] if sentence else 0
        if held > most:
            best, most = sentence, held
    return best


def locator_for(
    page_text: str,
    earlier_page_text: str | None,
    quote: str,
    passage_heading: str | None = None,
) -> str | None:
    """The locator of a passage: the search's own heading when it names a clause number, else the nearest heading above the quote on its page,
    else the last heading of the page before. None when none is found."""
    head = " ".join(str(passage_heading or "").split())
    if head and CLAUSE_NUMBER.search(head):
        return head[:100]
    return heading_above(page_text, quote) or (
        last_heading(earlier_page_text) if earlier_page_text else None
    )
