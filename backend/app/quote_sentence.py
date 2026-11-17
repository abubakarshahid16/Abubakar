"""THE test of a quote shown as evidence on a general review's CRS (order 14 LPC, C4, 17 Nov 2026).

A quote code verified on its page proves only that the words are there. Shown as what the paper says, it must also be words a
reader can judge: "(herein referred", "4.", a run of underscores or the tail of a sentence are on the page, but they say nothing.
So an AI quote is shown as evidence only when it passes this one fixed, general test (`is_evidence`); otherwise the row says it
holds no quote and keeps the paper's words beside that mark (`refused_words`: completeness, nothing is dropped silently). Used by
every writer of a general AI line's quote: the paper's one CRS and page (`review_points_service.sentence_quotes`) and the general
review's own files (`agent_general_crs`). A value code compared (a datasheet cell, a rule check's Pass or Fail) is never read by it.

The test (general, English text; nothing of one paper's words or layout). Evidence is EITHER
  * a full sentence: it starts as a sentence starts (a capital, a digit or a quote mark; never an open bracket, a closing mark or a
    lower-case word, which is the middle of a sentence), it does not end inside an open bracket or on a word that needs more
    ("the", "of", "shall"), it holds at least `MIN_WORDS` words (a number counts as one) and a verb-like word: a modal or
    auxiliary verb ("shall", "is", "has"), a word with a verb ending ("-ed", "-es"), or, in a quote that ends as a sentence
    does, a lower-case word ending in "-s" after its first word ("The team meets ...");
  * or a one-line clause that states a value: it starts as a sentence starts, holds a number and at least two words
    ("Retention 10% of the price"), and does not end inside an open bracket.
"""

from __future__ import annotations

import re

MIN_WORDS = 6
VALUE_WORDS = 2
LABEL_MAX = 6  # words of a label before a value
_TOKEN = re.compile(r"[^\W_]+(?:[.,'’-][^\W_]+)*")  # a word or a number  # noqa: RUF001
_WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")  # noqa: RUF001
#: Modal and auxiliary verbs: closed-class words of English, true for any paper.
_AUX = frozenset(
    [
        "shall",
        "should",
        "will",
        "would",
        "must",
        "may",
        "might",
        "can",
        "could",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "am",
        "has",
        "have",
        "had",
        "having",
        "do",
        "does",
        "did",
    ]
)
#: Closed-class words a sentence never ends on: the words after them are missing.
_NEEDS_MORE = frozenset(
    [
        "the",
        "a",
        "an",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "for",
        "from",
        "with",
        "and",
        "or",
        "nor",
        "but",
        "as",
        "than",
        "that",
        "which",
        "who",
        "whose",
        "this",
        "these",
        "those",
        "its",
        "their",
        "shall",
        "should",
        "will",
        "would",
        "must",
        "may",
        "can",
        "could",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "has",
        "have",
        "had",
    ]
)
_VERB_ENDING = re.compile(r"^[a-z]{2,}(?:ed|es)$")
_S_ENDING = re.compile(r"^[a-z]{2,}[^s]s$")
_DIGIT = re.compile(r"\d")


def _flat(text: object) -> str:
    return " ".join(str(text or "").split())


def _starts_and_ends_whole(flat: str) -> bool:
    """It starts as a sentence starts and does not stop inside a bracket or on a word that needs more."""
    first = flat.lstrip("\"'“‘ ")[:1]  # noqa: RUF001
    if not first or first in "([{)]}" or first.islower():
        return False
    if flat.count("(") > flat.count(")") or flat.count("[") > flat.count("]"):
        return False
    words = _WORD.findall(flat)
    return not words or words[-1].lower() not in _NEEDS_MORE


def is_full_sentence(text: object) -> bool:
    """Is the quote a full sentence by the fixed test above?"""
    flat = _flat(text)
    if not _starts_and_ends_whole(flat) or len(_TOKEN.findall(flat)) < MIN_WORDS:
        return False
    words = _WORD.findall(flat)
    low = [w.lower() for w in words]
    if any(w in _AUX for w in low) or any(_VERB_ENDING.match(w) for w in low):
        return True
    ends = flat.rstrip("\"'”’ )")[-1:] in ".!?;:"  # noqa: RUF001
    return ends and any(_S_ENDING.match(w) for w in words[1:])


def is_value_clause(text: object) -> bool:
    """Is the quote a one-line clause that states a value: it starts and ends whole, has two or more words, and holds a real value
    (`_values`: a figure with a unit, a comparator or a range; never a clause, page or article number)?"""
    flat = _flat(text)
    return (
        _starts_and_ends_whole(flat)
        and len(_WORD.findall(flat)) >= VALUE_WORDS
        and bool(_values(flat))
    )


def is_evidence(text: object) -> bool:
    """THE test: a full sentence, or a one-line clause that states a value."""
    return is_full_sentence(text) or is_value_clause(text)


def refused_words(text: object) -> str:
    """The mark a refused quote carries, with the paper's words beside it (never dropped)."""
    flat = _flat(text)
    if not flat:
        return "No quote: the passage found on the page is empty."
    return f'No quote: the paper\'s words "{flat}" are not a full sentence.'


#: The units a value may carry: a closed list of measurement and money units (general vocabulary of any engineering paper). A word
#: that is not one ("Site", "of", "after") is never a unit.
UNITS = frozenset(
    [
        "%",
        "°c",
        "°f",
        "degc",
        "degf",
        "mm",
        "cm",
        "m",
        "km",
        "in",
        "ft",
        "yd",
        "mil",
        "kg",
        "g",
        "t",
        "lb",
        "lbs",
        "n",
        "kn",
        "mn",
        "nm",
        "w",
        "kw",
        "mw",
        "kwh",
        "mwh",
        "v",
        "kv",
        "a",
        "ma",
        "hz",
        "khz",
        "rpm",
        "bar",
        "barg",
        "bara",
        "mbar",
        "psi",
        "psig",
        "psia",
        "pa",
        "kpa",
        "mpa",
        "gpa",
        "l",
        "ml",
        "m3",
        "m³",
        "m3/h",
        "m3/hr",
        "nm3/h",
        "l/s",
        "l/min",
        "gpm",
        "gph",
        "s",
        "sec",
        "secs",
        "min",
        "mins",
        "h",
        "hr",
        "hrs",
        "hour",
        "hours",
        "day",
        "days",
        "week",
        "weeks",
        "month",
        "months",
        "year",
        "years",
        "db",
        "dba",
        "usd",
        "sar",
        "kwd",
        "eur",
        "gbp",
        "ppm",
        "ppb",
        "cp",
        "cst",
        "mph",
        "kph",
        "m/s",
    ]
)
#: Words that make the number after them a reference, never a value ("Page 3", "Section 12", "Article 4").
REFERENCE_WORDS = frozenset(
    [
        "page",
        "pages",
        "section",
        "sections",
        "clause",
        "clauses",
        "article",
        "articles",
        "sub-article",
        "part",
        "item",
        "note",
        "table",
        "figure",
        "fig",
        "appendix",
        "schedule",
        "annex",
        "paragraph",
        "para",
        "rev",
        "revision",
        "no",
        "number",
        "of",
        "chapter",
        "step",
    ]
)
_FIGURE = r"\d+(?:[.,]\d+)*"
_VALUE = re.compile(
    rf"(?P<cmp>[<>\u2264\u2265=]\s*{_FIGURE})"
    rf"|(?P<range>{_FIGURE}\s*(?:-|\u2013|to)\s*{_FIGURE})"
    rf"|(?P<cur>(?:[$\u20ac\u00a3]|\b(?:USD|SAR|EUR|GBP|KWD))\s*{_FIGURE})"
    rf"|(?P<unit>{_FIGURE})\s*(?P<u>%|[\u00b0A-Za-z\u00b3/0-9]+)",
)
_BARE_FIGURE = re.compile(rf"^[+-]?{_FIGURE}$")
_CODE = re.compile(
    r"^(?=[A-Za-z0-9-]*\d)(?=[A-Za-z0-9-]*[A-Za-z])[A-Za-z0-9-]{2,20}$|^[A-Z]{2,12}$"
)


def _after_reference(flat: str, start: int) -> bool:
    words = _WORD.findall(flat[:start])
    return bool(words) and words[-1].lower() in REFERENCE_WORDS


def _values(flat: str) -> list[re.Match]:
    """Every real value in the text: a comparator, a range, a money figure, or a figure with a unit of `UNITS`, never after a
    reference word."""
    out = []
    for m in _VALUE.finditer(flat):
        if m.group("unit") and m.group("u").lower().rstrip(".") not in UNITS:
            continue
        if not _after_reference(flat, m.start()):
            out.append(m)
    return out


def _label_ok(prefix: str) -> bool:
    """A label before a value: empty, or words that start with a capital and name no reference ("Set pressure", "Material")."""
    prefix = prefix.strip(" :=-")
    if not prefix:
        return True
    words = _WORD.findall(prefix)
    return (
        prefix[:1].isupper()
        and not _DIGIT.search(prefix)
        and len(words) <= LABEL_MAX
        and not any(w.lower() in REFERENCE_WORDS for w in words)
    )


def holds_value(text: object) -> bool:
    """Does the quote hold a value a check can compare? The whole quote is a figure ("80"), a code value ("316L", "WCB"), or a
    value at its end after at most a label: a figure with a unit, a comparator, a range or a money figure ("Set pressure 10 barg",
    "< 15", "Material A105"). A clause, page or article number ("4.", "2.1 Site Conditions", "Page 3 of 8") and a value inside a
    fragment ("and 10 days after") are not."""
    flat = _flat(text)
    if not flat:
        return False
    if _BARE_FIGURE.match(flat) or (len(flat.split()) == 1 and _CODE.match(flat)):
        return True
    found = _values(flat)
    if found and not flat[found[-1].end() :].strip(" ."):
        return _label_ok(flat[: found[-1].start()])
    head, _, last = flat.rpartition(" ")
    return bool(head) and bool(_CODE.match(last)) and _label_ok(head)


def refused_many(found: list[tuple[object, object]]) -> str:
    """The mark for one or more refused passages [(words, page)], every different passage with its page beside it (never dropped)."""
    seen: dict[str, object] = {}
    for text, page in found:
        flat = _flat(text)
        if flat and flat not in seen:
            seen[flat] = page
    if not seen:
        return refused_words("")
    parts = [
        f'"{t}"' + (f" (page {pg})" if pg not in (None, "") else "")
        for t, pg in seen.items()
    ]
    words = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    if len(parts) == 1:
        ((text, page),) = seen.items()
        where = f" (page {page})" if page not in (None, "") else ""
        return f'No quote: the paper\'s words "{text}" are not a full sentence{where}.'
    return f"No quote: the paper's words {words} are not full sentences."
