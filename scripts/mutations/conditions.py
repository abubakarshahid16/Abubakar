"""Mutations of `backend/app/conditions.py`."""

from __future__ import annotations

from ._base import APP, _B49_TEST, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from CONDITION_AND_QUOTES ----------------------------------------
    #: B24 (the condition safety gate) and B23 (evidence quote validation), plus a
    #: re-anchoring of B20's dimension guard, so all three safety gates that came out
    #: of the Phase 0.5 slice are proven by this harness rather than by an ad-hoc
    #: script in one session's scratchpad.
    Mutation(
        id="M268", phase=29,
        description="never read the facts that DO state a material, so no "
                    "condition is ever SATISFIED - a gate that always refuses "
                    "is as useless as one that never does",
        path=APP / "conditions.py",
        anchor="    for fact in stated:",
        replacement="    for fact in []:  # MUTANT: stated facts never examined",
        target="tests/test_condition_gate.py",
        tags=("honesty",),
    ),
    Mutation(
        id="M269", phase=29,
        description="treat 'N/A' as a stated value, collapsing UNKNOWN into "
                    "NOT_APPLICABLE - excusing a requirement on absent evidence",
        path=APP / "conditions.py",
        anchor='    stated = [f for f in candidates if not _is_empty(f.get("field_value"))]',
        replacement="    stated = list(candidates)  # MUTANT: N/A treated as a value",
        target="tests/test_condition_gate.py",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M270", phase=29,
        description="remove the requirement_type scoping, so the gate fires on "
                    "the 4,246 table_value rows whose condition column holds a "
                    "table ROW LABEL like 'Arsenic' or '100'",
        path=APP / "conditions.py",
        anchor='    if (requirement or {}).get("requirement_type") != GATED_TYPE:\n'
               "        return None",
        replacement="    if False:  # MUTANT: type scoping removed\n"
                    "        return None",
        target="tests/test_condition_gate.py",
        tags=("critical",),
    ),
    # ---- from B49_EVIDENCE_BY_ROLE ----------------------------------------
    #: B49: the condition gate excused a clause using the fields under test,
    #: because "is this material evidence" was a question about the field's NAME.
    Mutation(
        id="M342", phase=41,
        description="PUT B49 BACK: restore the name-substring rule, so a "
                    "corrosion allowance proves what material a vessel is",
        path=APP / "conditions.py",
        anchor="        if shape == SHAPE_MATERIAL and _states_a_measurement(fact):\n"
               "            continue",
        replacement="        if False:\n            continue",
        target=_B49_TEST,
        keyword="b49_a_length_cannot_establish_a_material",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M343", phase=41,
        description="read the unit only from the unit columns, so a value "
                    "carrying its own unit is a material again",
        path=APP / "conditions.py",
        anchor="    return (claims.parse_value(head) is not None\n"
               "            and claims.unit_dimension(tail.strip()) is not None)",
        replacement="    return False",
        target=_B49_TEST,
        keyword="b49_the_role_test_reads_the_unit",
        tags=("honesty",),
    ),
)
