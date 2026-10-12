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
        anchor="    if match:\n        result = _inclusion(",
        replacement="    if covered and not match and not generic:\n"
                    "        return _result(NOT_APPLICABLE, 'other equipment', covered[0])\n"
                    "    if match:\n        result = _inclusion(",
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
        anchor="if restricts and nodes and not _names_submittal(nodes, profile) and profile.type:",
        replacement="if restricts and nodes and not _names_submittal(nodes, profile):",
        target="tests/test_applicability_v2.py",
        keyword="unknown_equipment_type_never_yields_not_applicable",
        tags=("honesty", "applicability"),
    ),
    # ---- M-03 run 2026-09-25: the two measured wrong exclusions ------------
    Mutation(
        id="M600", phase=61,
        description="an exclusion of a SUB-KIND ('submersible pumps') excludes "
                    "the whole family, so a centrifugal pump is wrongly excluded",
        path=APP / "applicability_v2.py",
        anchor="    if _names_submittal(nodes, profile) and _unqualified(item.get(\"term\"), lexicon):\n",
        replacement="    if _names_submittal(nodes, profile):\n",
        target="tests/test_applicability_v2.py",
        keyword="sub_kind_does_not_exclude",
        tags=("honesty", "applicability"),
    ),
    Mutation(
        id="M601", phase=61,
        description="an 'exclusion' whose quote carries no exclusion cue still "
                    "excludes (a procurement sentence read as a scope exclusion)",
        path=APP / "applicability_v2.py",
        anchor="    if not _EXCLUSION_CUE.search(_cue_text(item)):\n        return False\n",
        replacement="",
        target="tests/test_applicability_v2.py",
        keyword="not_an_exclusion_does_not_exclude",
        tags=("honesty", "applicability"),
    ),
    Mutation(
        id="M602", phase=61,
        description="NOT_APPLICABLE is confirmed by two agreeing re-reads instead of three",
        path=APP / "applicability_v2.py",
        anchor="    return len(rereads) >= needed and len(agreeing) == len(rereads)\n",
        replacement="    return len(agreeing) >= 2\n",
        target="tests/test_applicability_v2.py",
        keyword="three_agreeing_rereads",
        tags=("honesty", "applicability"),
    ),
    Mutation(
        id="M606", phase=61,
        description="a qualified sub-kind inclusion ('subsurface valves') is asserted "
                    "APPLICABLE instead of a candidate",
        path=APP / "applicability_v2.py",
        anchor="    if not type_match and not _unqualified(match.get(\"term\"), lexicon):\n",
        replacement="    if False:\n",
        target="tests/test_applicability_v2.py",
        keyword="qualified_sub_kind_inclusion",
        tags=("honesty", "applicability"),
    ),
    Mutation(
        id="M607", phase=61,
        description="a repair/maintenance-only scope is asserted APPLICABLE to a new item",
        path=APP / "applicability_v2.py",
        anchor="            (activities and activities <= _EXISTING_ONLY) or existing_cue):\n",
        replacement="            existing_cue):\n",
        target="tests/test_applicability_v2.py",
        keyword="repair_only_scope",
        tags=("honesty", "applicability"),
    ),
    Mutation(
        id="M608", phase=61,
        description="the verified-quote existing-equipment cue is ignored",
        path=APP / "applicability_v2.py",
        anchor="    existing_cue = _EXISTING_CUE.search(quotes) and not _NEW_CUE.search(quotes)\n",
        replacement="    existing_cue = False\n",
        target="tests/test_applicability_v2.py",
        keyword="existing_equipment_quote",
        tags=("honesty", "applicability"),
    ),
    # ---- b5-quality 2026-09-25: cue context, quotes name terms, stage, lists -
    Mutation(
        id="M665", phase=62,
        description="the code-cut cue context is ignored - a list item under 'excluded from the scope are:' "
                    "no longer excludes",
        path=APP / "applicability_v2.py",
        anchor="    return f\"{item.get('cue_context') or ''} {item.get('quote') or ''}\"\n",
        replacement="    return item.get('quote') or ''\n",
        target="tests/test_applicability_v2.py",
        keyword="list_item_under_an_exclusion_intro_excludes",
        tags=("applicability",),
    ),
    Mutation(
        id="M666", phase=62,
        description="a term its own verified quote does not contain may decide",
        path=APP / "applicability_v2.py",
        anchor="            and all(w in words for w in re.findall(r\"[a-z0-9]+\", phrase))}\n",
        replacement="}\n",
        target="tests/test_applicability_v2.py",
        keyword="its_own_quote_does_not_contain",
        tags=("honesty", "applicability"),
    ),
    Mutation(
        id="M667", phase=62,
        description="an equipment limit that only LISTS other equipment excludes (the owner's rule: UNKNOWN)",
        path=APP / "applicability_v2.py",
        anchor="            restricts = bool(_LIMIT_CUE.search(_cue_text(item)))\n",
        replacement="            restricts = True\n",
        target="tests/test_applicability_v2.py",
        keyword="equipment_limit_must_say_it_restricts",
        tags=("honesty", "applicability"),
    ),
    Mutation(
        id="M668", phase=62,
        description="any stage limit ('as a repair') holds a new item as a candidate, not only an 'in-service / existing' one",
        path=APP / "applicability_v2.py",
        anchor="                        and _EXISTING_ONLY_CUE.search(item.get(\"quote\") or \"\")\n",
        replacement="",
        target="tests/test_applicability_v2.py",
        keyword="only_an_in_service_or_existing_quote",
        tags=("honesty", "applicability"),
    ),
    Mutation(
        id="M669", phase=62,
        description="a verified new-construction quote no longer keeps an inclusion",
        path=APP / "applicability_v2.py",
        anchor="    if profile.stage == \"new\" and not _new_construction(record) and (\n",
        replacement="    if profile.stage == \"new\" and (\n",
        target="tests/test_applicability_v2.py",
        keyword="new_construction_quote_keeps",
        tags=("applicability",),
    ),
    Mutation(
        id="M674", phase=62,
        description="a NEGATED existing-equipment sentence ('not applied retroactively to existing') is a "
                    "stage limit (the measured wrong exclusion of a new-vessel welding standard)",
        path=APP / "applicability_v2.py",
        anchor="                        and not _NEGATED.search(_cue_text(item))\n",
        replacement="",
        target="tests/test_applicability_v2.py",
        keyword="negated_existing_equipment",
        tags=("honesty", "applicability"),
    ),
    Mutation(
        id="M675", phase=62,
        description="a coordinated list under an exclusion intro is not read by code",
        path=APP / "applicability_v2.py",
        anchor="    return _EXCLUSION_CUE.search(item.get(\"cue_context\") or \"\") is not None and _names_submittal(\n",
        replacement="    return False and _names_submittal(\n",
        target="tests/test_applicability_v2.py",
        keyword="listed_kind_under_an_exclusion_intro",
        tags=("applicability",),
    ),
    # ---- owner decision 4c 2026-09-25: activity / stage is never an exclusion ground
    Mutation(
        id="M680", phase=62,
        description="an in-service / existing stage limit is an exclusion ground again (NOT_APPLICABLE for a "
                    "new submittal) - retracted by owner decision 4c",
        path=APP / "applicability_v2.py",
        anchor="                    stage_limit = item\n",
        replacement="                    return _result(NOT_APPLICABLE, 'stage limit', item)\n",
        target="tests/test_applicability_v2.py",
        keyword="stage_limit",
        tags=("honesty", "applicability"),
    ),
    Mutation(
        id="M681", phase=62,
        description="the stage-limit candidate hold is dropped - an in-service repair scope is asserted "
                    "APPLICABLE to a new submittal",
        path=APP / "applicability_v2.py",
        anchor="    if stage_limit is not None:\n",
        replacement="    if False:\n",
        target="tests/test_applicability_v2.py",
        keyword="keeps_a_new_item_a_candidate",
        tags=("honesty", "applicability"),
    ),
)
