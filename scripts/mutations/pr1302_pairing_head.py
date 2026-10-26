"""PR 1302 (audit C5): a field pairs with a clause only when its label stands in the
clause subject's head, not in a complement, a list or a condition."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_c5_pairing_head.py"
_C = APP / "comparison.py"
_P = APP / "pairing_head.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1302-01",
        phase=1302,
        description="the literal-containment route pairs a field mentioned anywhere in the clause again",
        path=_C,
        anchor="        if field_links.names_head(subject, name):\n",
        replacement="        if _contains_words(subject, name):\n",
        target=_T,
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1302-02",
        phase=1302,
        description="the synonym route pairs a field mentioned anywhere in the clause again",
        path=_C,
        anchor="        elif field_links.names_head(canonical_subject, canonical_name):\n",
        replacement="        elif _contains_words(canonical_subject, canonical_name):\n",
        target=_T,
        tags=("honesty",),
    ),
    Mutation(
        id="M1302-03",
        phase=1302,
        description="any label inside the subject is in its head: the complement words are not looked at",
        path=_P,
        anchor="            return not any(word in COMPLEMENT_WORDS for word in words[:start])\n",
        replacement="            return True\n",
        target=_T,
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1302-04",
        phase=1302,
        description='"for" no longer opens a complement: "cut water clearance for rated power" claims the field',
        path=_P,
        anchor='        "for",\n',
        replacement="",
        target=_T,
        tags=("honesty",),
    ),
    Mutation(
        id="M1302-05",
        phase=1302,
        description='"and" counts as a complement word: "maximum and minimum design temperature" no longer pairs',
        path=_P,
        anchor='        "if",\n',
        replacement='        "if",\n        "and",\n',
        target=_T,
        tags=("honesty",),
    ),
    Mutation(
        id="M1302-06",
        phase=1302,
        description="the abbreviation route pairs a field mentioned anywhere in the clause again",
        path=_C,
        anchor="        elif (field_links.names_head(subject_form, _match_form(name))\n",
        replacement="        elif (_contains_words(subject_form, _match_form(name))\n",
        target=_T,
        tags=("honesty",),
    ),
    Mutation(
        id="M1302-07",
        phase=1302,
        description='the opening "type of / number of ..." is no longer skipped: "type of enclosure" loses its field',
        path=_P,
        anchor="    return opens and _head_run(words[2:], label)\n",
        replacement="    return False\n",
        target=_T,
        tags=("honesty",),
    ),
)
