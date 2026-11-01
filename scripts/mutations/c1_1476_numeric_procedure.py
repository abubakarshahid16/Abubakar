"""#1476 numeric limits on a procedure: each entry changes one decision line;
backend/tests/test_1476_numeric_procedure.py must notice."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_1476_numeric_procedure.py"
_TAG = ("c1_1476", "numeric_procedure")
_P = APP / "procedure_text.py"


def _m(n, desc, anchor, repl, kw):
    return Mutation(
        id=f"M1476-{n:02d}",
        phase=1476,
        description=desc,
        path=_P,
        anchor=anchor,
        replacement=repl,
        target=_T,
        keyword=kw,
        tags=_TAG,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        1,
        "a numeric limit of a procedure is no longer looked up in the page text (MISSING_INFORMATION again)",
        '        and requirement.get("requirement_type") == "numeric_limit"\n    )\n',
        '        and requirement.get("requirement_type") == "numeric_limit"\n        and False\n    )\n',
        "found_states_both_numbers or not_found_is_the_unfound_row",
    ),
    _m(
        2,
        "a numeric limit that has a submitted fact is taken from the datasheet path to the page text",
        "    numeric = (\n        fact is None\n",
        "    numeric = (\n        True\n",
        "with_a_fact_is_not_routed",
    ),
    _m(
        3,
        "a numeric limit that demands a certificate or drawing is checked against the procedure text",
        "    numeric = (\n        fact is None\n        and evidence in {None, requirements_3b.DATA_SHEET_EVIDENCE}\n",
        "    numeric = (\n        fact is None\n        and True\n",
        "names_another_document",
    ),
    _m(
        4,
        "two same-quantity numbers in the quote are compared (the first is picked)",
        "    if len(same) != 1:\n",
        "    if not same:\n",
        "two_same_quantity",
    ),
    _m(
        5,
        "a number of another quantity in the quote is compared with the limit",
        "        if claims.same_quantity(raw_unit, m.raw_unit)\n",
        "        if True\n",
        "different_quantity",
    ),
    _m(
        6,
        "the unit code is not used: minutes are no longer read as the same quantity as hours",
        "        if claims.same_quantity(raw_unit, m.raw_unit)\n",
        "        if m.raw_unit.strip().lower() == str(raw_unit).strip().lower()\n",
        "unit_code_is_used",
    ),
)
