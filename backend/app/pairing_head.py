"""A field is a clause's field only when the clause is ABOUT it (audit C5).

A clause's subject is a sentence fragment and a sheet's field is a bare label.
They used to pair when the label stood ANYWHERE inside the subject, so a field
called "Fittings", "Manufacturer" or "Rated power" was claimed by any clause that
merely mentions the word in a list, a reference or a complement ("cut water
clearance FOR rated power"): a real value answering an unrelated clause.

The rule, true for any document: the label must stand in the subject's HEAD,
that is, no word that introduces a complement may come BEFORE it. "rated power of
the motor" names "rated power"; "cut water clearance for rated power" does not.
The label may itself hold such a word ("degree of protection"): only what comes
before the label counts. A clause no field names this way is "no field found"
for the engineer, never a quote of an unrelated clause.

"and" and "or" are not in the list: "maximum and minimum design temperature" is
about both of its labels.

A subject that opens with a kind noun and "of" ("type of enclosure", "number of
stages", "class of the flange") is read both as written and without that opening, so
the field "enclosure" still pairs with "type of enclosure". A measured quantity
("capacity of", "power of", "size of", "level of") is never skipped.
A subject that opens with a condition ("at normal flow the valve ...") is not
helped: its first words are the condition, and a label there is the condition,
not what the clause is about.
"""

from __future__ import annotations

#: Words that open a complement, a relative clause or a list item.
COMPLEMENT_WORDS = frozenset(
    {
        "of",
        "for",
        "in",
        "at",
        "on",
        "with",
        "within",
        "without",
        "by",
        "from",
        "to",
        "into",
        "onto",
        "per",
        "via",
        "including",
        "include",
        "includes",
        "between",
        "among",
        "during",
        "under",
        "over",
        "when",
        "where",
        "while",
        "which",
        "that",
        "whose",
        "about",
        "against",
        "across",
        "after",
        "before",
        "through",
        "upon",
        "unless",
        "if",
    }
)


#: A noun that names a KIND, not a measured quantity, and may open a subject before "of":
#: "type of enclosure". Measured quantities ("capacity of", "power of", "size of") are not here:
#: "capacity of the relief valve" is about the capacity, never about the valve.
QUANTITY_NOUNS = frozenset({"type", "kind", "number", "class", "grade", "material"})


def _head_run(words: list[str], label: list[str]) -> bool:
    for start in range(len(words) - len(label) + 1):
        if words[start : start + len(label)] == label:
            return not any(word in COMPLEMENT_WORDS for word in words[:start])
    return False


def names_head(subject: str, name: str) -> bool:
    """Is `name` a whole-word sequence in `subject` with no complement word
    before it? Both are already lowercased words (`_normalise_for_match`)."""
    words, label = subject.split(), name.split()
    if not label:
        return False
    if _head_run(words, label):
        return True
    opens = len(words) > 2 and words[0] in QUANTITY_NOUNS and words[1] == "of"
    return opens and _head_run(words[2:], label)
