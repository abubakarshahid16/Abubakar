"""PR #902 (#893, PF2): a clause that names the values a thing shall be is
paired with the sheet's row of that name; code calls it met only when the
sheet's value is one of them, or the clause only asks for a statement.
`comparison.py` is in the danger zone (rule 6)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_893_named_values.py"
_C = APP / "comparison.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M902-01", phase=902,
             description="a one-word label (\"service\", \"type\") may claim any clause that says the word",
             path=_C,
             anchor='            if len(hit["name"].split()) >= 2 and _contains_words(_singular(subject), _singular(hit["name"]))]\n',
             replacement='            if _contains_words(_singular(subject), _singular(hit["name"]))]\n',
             target=_T, keyword="one_word_label", tags=("honesty",)),
    Mutation(id="M902-02", phase=902,
             description="two readers that read DIFFERENT words for one row are taken as one answer",
             path=_C,
             anchor='                (hit["name"], _normalise_for_match(fact.get("field_value")), fact.get("page"),\n',
             replacement='                (hit["name"], fact.get("page"),\n',
             target=_T, keyword="two_readers", tags=("honesty", "critical")),
    Mutation(id="M902-03", phase=902,
             description="a stated value the clause does NOT name is called met",
             path=_C,
             anchor="            if field_links.is_named_value(stated, names):\n",
             replacement="            if True:\n",
             target=_T, keyword="does_not_name", tags=("honesty", "critical")),
    Mutation(id="M902-04", phase=902,
             description="any clause with a stated value is called met, as if it only asked for a statement",
             path=_C,
             anchor="        if stated and field_links.asks_only_to_be_stated(clause):\n",
             replacement="        if stated:\n",
             target=_T, keyword="does_not_name or conditional_clause", tags=("honesty", "critical")),
    Mutation(id="M902-05", phase=902,
             description="a stated value that is not a named one is called a breach by code",
             path=_C,
             anchor='''            return {"status": NEEDS_ENGINEER_REVIEW,
                    "rationale": (f"{NAMED_VALUE}: the sheet states {stated_value.stated(stated)!r}; the clause names "''',
             replacement='''            return {"status": NON_COMPLIANT,
                    "rationale": (f"{NAMED_VALUE}: the sheet states {stated_value.stated(stated)!r}; the clause names "''',
             target=_T, keyword="does_not_name", tags=("honesty",)),
)
