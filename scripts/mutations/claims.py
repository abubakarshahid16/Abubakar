"""Mutations of `backend/app/claims.py`."""

from __future__ import annotations

from ._base import APP, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from PHASE_4 -----------------------------------------------------
    #: Phase 4: datasheet intelligence. `phase=5` because --phase 4 already
    #: selects 3B; the ids are the stable handle.
    Mutation(
        id="M53", phase=5,
        description="refuse same-unit comparison again, re-blocking the dB(A) case",
        path=APP / "claims.py",
        anchor="    if (a.normalized_value is None or b.normalized_value is None) and same_unit(a, b):",
        replacement="    if False:",
        target="tests/test_datasheets.py",
        keyword="same_unit_dba_values_compare",
        tags=("comparison", "unit"),
    ),
    Mutation(
        id="M54", phase=5,
        description="compare across different units, breaking ScaleMismatch",
        path=APP / "claims.py",
        anchor='    ua, ub = _fold_unit(a.raw_unit or ""), _fold_unit(b.raw_unit or "")\n    return bool(ua) and ua == ub',
        replacement='    ua, ub = _fold_unit(a.raw_unit or ""), _fold_unit(b.raw_unit or "")\n    return True',
        target="tests/test_datasheets.py",
        keyword="different_units_still_refuse",
        tags=("comparison", "honesty"),
    ),
    # ---- from DATASHEET ---------------------------------------------------
    #: The datasheet side: which strings are citations, where a unit lives, and
    #: what is not a fact at all.
    Mutation(
        id="M107", phase=8,
        description="STRIP THE PARENTHETICAL OFF ANY UNIT, turning dB(A) into "
                    "decibels-absolute and reopening the phase 5B defect",
        path=APP / "claims.py",
        anchor="    if folded in _RECOGNISED_UNITS:\n        return text, None",
        replacement="    if False:\n        return text, None",
        target="tests/test_fact_gates.py",
        keyword="db_a_is_never_split",
        tags=("honesty", "critical"),
    ),
    # ---- from CONDITION_AND_QUOTES ----------------------------------------
    #: B24 (the condition safety gate) and B23 (evidence quote validation), plus a
    #: re-anchoring of B20's dimension guard, so all three safety gates that came out
    #: of the Phase 0.5 slice are proven by this harness rather than by an ad-hoc
    #: script in one session's scratchpad.
    Mutation(
        id="M273", phase=29,
        description="remove B20's dimension guard, so a length is compared "
                    "against a temperature and yields NON_COMPLIANT",
        path=APP / "claims.py",
        anchor="    dim_a, dim_b = a.dimension, b.dimension\n"
               "    if dim_a is not None and dim_b is not None and dim_a != dim_b:\n"
               "        return None",
        replacement="    # MUTANT: B20 dimension guard removed",
        target="tests/test_dimension_guard.py",
        tags=("honesty", "critical"),
    ),
)
