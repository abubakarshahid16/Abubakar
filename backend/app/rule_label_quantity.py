"""Does a rule's quote state a quantity? (lifted from the lab labeller's reviewed rule, exp12 c48daa34)

Used by `rule_labels`: two readings that hold no number cannot approve a rule whose quote states a quantity. STRICT: a
number counts as a quantity unless it is a leading clause number, joined to a name by a hyphen, or directly after a
reference word AND followed by nothing but the end of the text, punctuation, a closing bracket or a common word.
"""

from __future__ import annotations

import itertools
import re

from . import claims, numparse

#: Words after which a number is a REFERENCE (a label), not a quantity: "Table 5", "Note 2", "Class 300", "Type 1".
REFERENCE_WORDS = frozenset(
    {
        "table",
        "figure",
        "fig",
        "note",
        "notes",
        "clause",
        "paragraph",
        "para",
        "section",
        "appendix",
        "annex",
        "part",
        "type",
        "class",
        "grade",
        "plan",
        "category",
        "arrangement",
        "item",
        "no",
        "number",
        "nos",
        "sheet",
        "page",
        "form",
        "step",
        "option",
        "case",
    }
)
_WORD_BEFORE = re.compile(r"([A-Za-z.]+)[\s:(\[]*$")
_LEADING_CLAUSE = re.compile(
    r"^\s*[(\[]*(?:\d+(?:\.\d+)+[.)\]]?\s|\d+[.)\]]?\s+(?=[A-Z(]))"
)


#: Common words (the lab labeller's list, words of 3+ letters): after a reference-word number only these, or end of text,
#: punctuation or a closing bracket, let the number stay a reference.
COMMON_WORDS = frozenset(
    [
        "the",
        "and",
        "for",
        "are",
        "but",
        "not",
        "you",
        "all",
        "any",
        "can",
        "had",
        "her",
        "was",
        "one",
        "our",
        "out",
        "day",
        "get",
        "has",
        "him",
        "his",
        "how",
        "its",
        "may",
        "new",
        "now",
        "old",
        "see",
        "two",
        "way",
        "who",
        "boy",
        "did",
        "let",
        "put",
        "say",
        "she",
        "too",
        "use",
        "that",
        "with",
        "have",
        "this",
        "will",
        "your",
        "from",
        "they",
        "know",
        "want",
        "been",
        "good",
        "much",
        "some",
        "time",
        "very",
        "when",
        "come",
        "here",
        "just",
        "like",
        "long",
        "make",
        "many",
        "more",
        "only",
        "over",
        "such",
        "take",
        "than",
        "them",
        "well",
        "were",
        "what",
        "where",
        "which",
        "while",
        "would",
        "about",
        "after",
        "again",
        "also",
        "back",
        "because",
        "before",
        "being",
        "between",
        "both",
        "could",
        "down",
        "each",
        "even",
        "every",
        "first",
        "give",
        "most",
        "never",
        "other",
        "other",
        "should",
        "still",
        "their",
        "then",
        "there",
        "these",
        "thing",
        "those",
        "through",
        "under",
        "until",
        "upon",
        "used",
        "using",
        "within",
        "without",
        "shall",
        "must",
        "than",
        "into",
        "each",
        "same",
        "also",
        "both",
        "either",
        "neither",
        "where",
        "whether",
        "whose",
        "who",
        "whom",
        "shall",
        "will",
        "unless",
        "provided",
        "applies",
        "apply",
        "applied",
        "required",
        "require",
        "requires",
        "requirement",
        "requirements",
        "specified",
        "specification",
        "standard",
        "standards",
        "shown",
        "shows",
        "table",
        "figure",
        "note",
        "notes",
        "section",
        "clause",
        "paragraph",
        "item",
        "items",
        "type",
        "class",
        "grade",
        "size",
        "design",
        "designed",
        "minimum",
        "maximum",
        "less",
        "greater",
        "equal",
        "least",
        "above",
        "below",
        "inch",
        "inches",
        "mm",
        "bar",
        "psi",
        "use",
        "used",
        "per",
        "total",
        "value",
        "values",
        "test",
        "tested",
        "testing",
        "material",
        "materials",
        "surface",
        "pressure",
        "temperature",
        "flow",
        "rate",
        "length",
        "width",
        "thickness",
        "diameter",
        "height",
        "weight",
        "load",
        "stress",
        "limit",
        "limits",
        "range",
        "ranges",
        "other",
        "another",
        "following",
        "include",
        "included",
        "including",
        "excluding",
        "except",
        "unless",
        "otherwise",
        "general",
        "special",
        "normal",
        "service",
        "condition",
        "conditions",
        "case",
        "cases",
        "point",
        "points",
        "part",
        "parts",
        "number",
        "numbers",
        "set",
        "sets",
        "system",
        "systems",
        "unit",
        "units",
        "area",
        "areas",
    ]
)
#: Unit words the project's unit table does not know but that make a number a quantity (checked after `claims`).
EXTRA_UNIT_WORDS = frozenset(
    {
        "ksi",
        "inch",
        "inches",
        "ft",
        "feet",
        "foot",
        "lb",
        "lbs",
        "lbf",
        "pound",
        "pounds",
        "year",
        "years",
        "month",
        "months",
        "week",
        "weeks",
        "day",
        "days",
        "hour",
        "hours",
        "hr",
        "hrs",
        "minute",
        "minutes",
        "min",
        "second",
        "seconds",
        "sec",
        "percent",
        "degree",
        "degrees",
        "deg",
        "ppm",
        "ppb",
        "kg",
        "g",
        "mg",
        "gram",
        "grams",
        "metre",
        "metres",
        "meter",
        "meters",
        "millimetre",
        "millimetres",
        "millimeter",
        "millimeters",
        "psi",
        "psig",
        "psia",
    }
)
#: Two-letter function words (the common-word list holds words of 3+ letters only).
SHORT_WORDS = frozenset(
    {
        "of",
        "to",
        "on",
        "at",
        "by",
        "is",
        "or",
        "as",
        "be",
        "if",
        "it",
        "so",
        "do",
        "an",
        "we",
        "he",
        "me",
        "my",
        "up",
        "us",
        "no",
        "in",
        "a",
        "i",
    }
)
_PUNCT_ONLY = re.compile(r"^[.,;:!?)\]}]+$")


def _unit_follows(text: str, end: int) -> bool:
    """STRICT. True means 'treat the number as a quantity'. A number after a reference word is skipped ONLY when the
    token after it is end of text, sentence punctuation or a closing bracket, or a common word that is not a unit
    ("Note 5 shall", "Table 2 and"). ANYTHING else makes it a quantity: a unit the project knows, "per", a short letter
    group (kW, Hz, rpm), a slash, a degree, a percent, an inch mark, digits glued to letters, an uncommon plain word
    ("Type 316 stainless", litres, pascals)."""
    parts = text[end:].split()
    if not parts:
        return False
    if _PUNCT_ONLY.match(parts[0]):
        return False
    word = parts[0].rstrip(".,;:!?)]}").lower()
    if (
        word == "per"
        or word in EXTRA_UNIT_WORDS
        or claims.unit_dimension(word) is not None
    ):
        return True
    return not (word in COMMON_WORDS or word in SHORT_WORDS)


#: Numbers written in words; one of them followed by a unit is a quantity ("ten bar", "half an inch" is not caught: a word
#: between them breaks the pair, the safe side being the numeric forms).
NUMBER_WORDS = frozenset(
    [
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "twenty",
        "thirty",
        "fifty",
        "hundred",
        "thousand",
        "half",
        "double",
        "twice",
    ]
)


def _word_quantity(text: str) -> bool:
    toks = [t.strip(".,;:!?()[]{}\"'").lower() for t in text.split()]
    for cur, nxt in itertools.pairwise(toks):
        if cur in NUMBER_WORDS and (
            nxt in EXTRA_UNIT_WORDS or claims.unit_dimension(nxt) is not None
        ):
            return True
    return False


def quote_states_a_quantity(quote: str | None) -> bool:
    """True when the quote states a quantity, by the project's own number code (`numparse.find_numbers`). A number
    counts unless it is (1) a leading clause or paragraph number ("4.2.1 ...", "(1) The ..."; "5 mm minimum" is not one),
    (2) joined to a name by a hyphen ("T-29"), or (3) directly after a reference word (table, figure, note, clause,
    section, type, class, grade, item, no. ...) AND not followed by anything but the end, punctuation or a common word
    (`_unit_follows`). Every other number counts. (Lifted from the lab labeller's reviewed rule, exp12 c48daa34.)"""
    original = str(quote or "")
    lead = _LEADING_CLAUSE.match(original)
    text = numparse.fold_numbers(original[lead.end() :] if lead else original)
    references = {w.rstrip(".") for w in REFERENCE_WORDS}
    for n in numparse.find_numbers(text):
        if n.value is None or n.joined:
            continue
        found = _WORD_BEFORE.search(text[: n.start].rstrip())
        if (
            found
            and found.group(1).lower().rstrip(".") in references
            and not _unit_follows(text, n.end)
        ):
            continue
        return True
    return _word_quantity(text)
