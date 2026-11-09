"""The subject check behind compare_number (#1690): a figure is compared only with a figure of the SAME subject. No document text."""

from __future__ import annotations

import re

from . import ai_review_proposals

#: Words that carry no subject: articles, modals, comparators, requirement words. A CLOSED set: a word not listed here is
#: part of the subject, so a doubtful case ends as "subject not matched" (cannot decide), never as a pass.
NEUTRAL_WORDS = frozenset(
    {
        "a", "an", "the", "of", "is", "are", "be", "been", "shall", "must", "should", "will", "may", "can", "value", "values",
        "comparator", "requirement", "at", "least", "most", "more", "less", "than", "not", "no", "exceed", "exceeding",
        "maximum", "minimum", "max", "min", "required", "limited", "limit", "between", "and", "to", "from", "up", "equal",
        "greater", "lower", "higher", "above", "below", "under", "over", "have", "has", "with", "for", "in", "by",
    }
)  # fmt: skip
_FIRST_NUMBER = re.compile(r"[-+\u2212]?\d")


def _stem(word: str) -> str:
    """Plural endings only (-ies, -es, -s); never -ing or -ed ("bearing" is not "bear"). Same on both sides."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("sses", "xes", "ches", "shes", "zes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


_FIGURE_TOKEN = re.compile(
    r"\d+(?:[.,]\d+)*|[\u00bc-\u00be\u2150-\u215e]|\b(?:"
    + "|".join(sorted(ai_review_proposals.NUMBER_WORDS))
    + r")\b",
    re.IGNORECASE,
)
#: A number that names a kind, not a quantity: "Class 150", "Type 2", "No. 3".
_LABEL_NUMBER = re.compile(
    r"\b(?:class|type|no|number|grade|series|schedule|sch|pn|dn|group|category|part|table|item|clause|section|zone|size)\.?\s*#?\d",
    re.IGNORECASE,
)


#: Short words that are words, not labels. Any other token of two letters or fewer in a subject region ("Grade A",
#: "Zone H", "Pump K") is a label we cannot compare, so the quote is ambiguous. A lowercase "a" is the article.
SHORT_WORDS_ALLOWED = frozenset(
    {"of", "is", "to", "be", "no", "or", "at", "in", "by", "an", "as", "on"}
)


def _label_before_number(quote: str) -> str:
    found = _FIRST_NUMBER.search(quote)
    return quote[: found.start()] if found else quote


def _has_short_label(quote: str) -> bool:
    for at, token in enumerate(re.findall(r"[A-Za-z]+", _label_before_number(quote))):
        if len(token) > 2 or token.lower() in SHORT_WORDS_ALLOWED:
            continue
        if token.lower() == "a" and (at == 0 or token == "a"):
            continue  # the article: a lowercase "a", or "A" opening the quote; never "Grade A"
        return True
    return False


def subject_ambiguous(quote: str) -> bool:
    """More than one number in the quote (so the figure's own number cannot be told from a number inside its label), or a
    number that names a kind ("Class 150"). Such a quote is never compared."""
    return (
        len(_FIGURE_TOKEN.findall(quote)) > 1
        or bool(_LABEL_NUMBER.search(quote))
        or _has_short_label(quote)
    )


def subject_words(quote: str) -> frozenset[str]:
    """The subject of a quoted figure: the content words BEFORE its first number (its label), lowercased, punctuation
    stripped, inflections folded, neutral words removed (units are never in a label). A bare value has an empty subject."""
    label = _label_before_number(quote)
    out = set()
    for raw in re.findall(r"[a-z]+", label.lower()):
        word = _stem(raw)
        if raw in NEUTRAL_WORDS or word in NEUTRAL_WORDS:
            continue
        out.add(word)
    return frozenset(out)
