"""Mutations of `backend/app/match_rules.py`."""

from __future__ import annotations

from ._base import APP, _MATCH_RULES_TEST, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from B193_PAIRING ------------------------------------------------
    #: Master order B4, issue #193: pairing measured against gold and made
    #: precise. Phase 58.
    Mutation(
        id="M477", phase=58,
        description="PUT THE FALSE PAIRING BACK: a table row with no lead-in "
                    "sentence pairs its lookup INPUT (#193, SAES-E-014 7.2.4)",
        path=APP / "match_rules.py",
        anchor='    return header.startswith(name + " ")',
        replacement="    return False",
        target=_MATCH_RULES_TEST, keyword="header_only_table_row_refuses or measured_false_pairing",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M478", phase=58,
        description="apply the header-column rule to ordinary limits too, so "
                    "'maximum operating pressure of the vessel' refuses its own "
                    "field (#193)",
        path=APP / "match_rules.py",
        anchor='    if requirement.get("requirement_type") != "table_row":\n        return False\n',
        replacement="",
        target=_MATCH_RULES_TEST, keyword="only_for_table_rows",
        tags=("honesty",),
    ),
    Mutation(
        id="M479", phase=58,
        description="refuse a field that IS the whole header, a table naming "
                    "one quantity with no input column (#193)",
        path=APP / "match_rules.py",
        anchor='.startswith(name + " ")',
        replacement=".startswith(name)",
        target=_MATCH_RULES_TEST, keyword="names_only_one_quantity",
    ),
    Mutation(
        id="M482", phase=58,
        description="treat a sentence subject as a table header, so 'X shall "
                    "be according to the table' refuses X, the constrained "
                    "quantity - a correct pairing silenced (#193, found by the "
                    "full suite)",
        path=APP / "match_rules.py",
        anchor="    if _HEADER_VERB.search(header):\n        return False\n",
        replacement="",
        target=_MATCH_RULES_TEST, keyword="sentence_subject_is_not_a_header",
        tags=("honesty",),
    ),
)
