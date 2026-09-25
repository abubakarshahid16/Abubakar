"""Mutations of `backend/app/applicability_v2.py`."""

from __future__ import annotations

from ._base import APP, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from B5_STANDARDS_INVENTORY --------------------------------------
    #: B5 part 2: standard family, licence status, cover-page backfill, and the
    #: "cited by a submittal" flag on the inventory.
    Mutation(
        id="M560", phase=61,
        description="a scope that lists OTHER equipment becomes NOT_APPLICABLE "
                    "(the v1 wrong-NA shape) instead of UNKNOWN",
        path=APP / "applicability_v2.py",
        anchor="    if match:\n        return _result(APPLICABLE,",
        replacement="    if covered and not match and not generic:\n"
                    "        return _result(NOT_APPLICABLE, 'other equipment', covered[0])\n"
                    "    if match:\n        return _result(APPLICABLE,",
        target="tests/test_applicability_v2.py",
        keyword="vessel_only_scope_does_not_make_a_pump",
        tags=("honesty", "applicability"),
    ),
    Mutation(
        id="M561", phase=61,
        description="an item with no quote may decide",
        path=APP / "applicability_v2.py",
        anchor='    return bool((item.get("quote") or "").strip())',
        replacement="    return True",
        target="tests/test_applicability_v2.py",
        keyword="item_without_a_quote_never_decides",
        tags=("honesty", "applicability"),
    ),
    Mutation(
        id="M562", phase=61,
        description="let a generic scope return NOT_APPLICABLE from a limit",
        path=APP / "applicability_v2.py",
        anchor="    if not generic:\n        for item in limits:",
        replacement="    if True:\n        for item in limits:",
        target="tests/test_applicability_v2.py",
        keyword="generic_scope_never_yields_not_applicable",
        tags=("honesty", "applicability"),
    ),
    Mutation(
        id="M563", phase=61,
        description="psig read as MPa - the number comparison stops converting units",
        path=APP / "applicability_v2.py",
        anchor='"psi": 0.00689476, "psig": 0.00689476}',
        replacement='"psi": 0.00689476, "psig": 1.0}',
        target="tests/test_applicability_v2.py",
        keyword="pressure_limits_are_compared_by_code",
        tags=("honesty", "applicability"),
    ),
    Mutation(
        id="M564", phase=61,
        description="an equipment limit excludes a submittal whose type is UNKNOWN",
        path=APP / "applicability_v2.py",
        anchor="if nodes and not _names_submittal(nodes, profile) and profile.type:",
        replacement="if nodes and not _names_submittal(nodes, profile):",
        target="tests/test_applicability_v2.py",
        keyword="unknown_equipment_type_never_yields_not_applicable",
        tags=("honesty", "applicability"),
    ),
)
