"""#1584: does a compiled rule's field name belong to its quote? Pure: no database, no model.

A rule with a figure keeps a strict test: its property is printed. A rule with no figure has a label, often a paraphrase;
one word of it in the quote shows it is about this sentence, and `field_printed` says which kind it is.
"""

from __future__ import annotations

import re

from . import field_vocabulary
from . import standards_converter as sc

#: Field words that name a kind of property, not a thing: the quote need not print them.
_GENERIC_FIELD_WORDS = frozenset(
    {
        "size",
        "type",
        "location",
        "use",
        "value",
        "kind",
        "amount",
        "percent",
        "service",
        "material",
        "requirement",
    }
)
#: Small words a field name may add without saying anything the quote must print.
_FIELD_SMALL_WORDS = frozenset(
    [
        "a",
        "an",
        "the",
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
        "that",
        "which",
        "between",
        "above",
        "below",
        "than",
        "per",
        "its",
    ]
)


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ed"):
        return word[:-1]
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def _field_words(words: str) -> set[str]:
    return {
        _stem(w) for w in field_vocabulary._tokens(words) if len(w) > 1
    } - _FIELD_SMALL_WORDS


def _field_printed(quote: str, name: str, numeric: bool) -> bool:
    """Every word of the field that says WHICH thing is printed in the quote, plurals aside. A generic word (size, type)
    and a qualifier (maximum) need not be, unless the rule states a figure: then the figure's property must be printed."""
    words = _field_words(name)
    qualifiers = sc.field_naming._QUALIFIERS
    skip = qualifiers if numeric else (_GENERIC_FIELD_WORDS | qualifiers)
    named = {w for w in words if w not in skip}
    return (named or words) <= _field_words(quote) and bool(words)


def _names_field(quote: str, name: str, numeric: bool = False) -> bool:
    """A rule with a figure: its field is printed, or a limit could be compared with the wrong property. A rule with no
    figure can give no numeric verdict and its field is only a label, often a paraphrase: one word of it in the quote
    is enough to show it is about this sentence. `field_printed` on the rule says which kind it is."""
    if numeric:
        return _field_printed(quote, name, True)
    return bool(_field_words(name) & _field_words(quote))


def _without_gloss(name: str) -> str:
    """A field's bracketed gloss is the model's own note, not words to store. "valve(s)" has no space and stays."""
    return " ".join(re.sub(r"\s\([^)]*\)", " ", name).split()) or name
