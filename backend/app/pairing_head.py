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
"""

from __future__ import annotations

#: Words that open a complement, a relative clause or a list item.
COMPLEMENT_WORDS = frozenset(
    "of for in at on with within without by from to into onto per via including "
    "include includes between among during under over when where while which that "
    "whose about against across after before through upon unless if".split()
)


def names_head(subject: str, name: str) -> bool:
    """Is `name` a whole-word sequence in `subject` with no complement word
    before it? Both are already lowercased words (`_normalise_for_match`)."""
    words, label = subject.split(), name.split()
    if not label:
        return False
    for start in range(len(words) - len(label) + 1):
        if words[start : start + len(label)] == label:
            return not any(word in COMPLEMENT_WORDS for word in words[:start])
    return False
