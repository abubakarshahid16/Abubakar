"""Mutations for review conditions (2026-09-30): the datasheet's own facts
decide whether a conditional requirement applies (`conditions.read_condition`
and the reader under it, the CONDITION_NOT_MET code in `comparison`, and the
CRS Review note in `crs_mapping`). Ids M1560-M1579."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_review_conditions.py"
_C = APP / "conditions.py"


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1560", phase=90,
        description="drop the condition reader: 'pipes larger than 2 inch' "
                    "is never decided from the datasheet's nominal size",
        path=_C,
        anchor="    reading = read_condition(condition)\n",
        replacement="    reading = None  # MUTANT: reader removed\n",
        target=_T, keyword="size_outside or class_inside or temperature_inside",
        tags=("honesty",)),
    Mutation(
        id="M1561", phase=90,
        description="let a wall thickness establish a nominal size",
        path=_C,
        anchor="            if _SIZE_ROLE.search(name) and not condition_choice._MEASURE_WORD.search(name):",
        replacement="            if _SIZE_ROLE.search(name):",
        target=_T, keyword="wall_thickness_is_never",
        tags=("honesty", "critical")),
    Mutation(
        id="M1562", phase=90,
        description="decide a condition read only in part ('... in "
                    "hydrocarbon service', '... unless galvanised')",
        path=_C,
        anchor="    elif unread:\n",
        replacement="    elif False:  # MUTANT: unread words ignored\n",
        target=_T, keyword="read_only_in_part",
        tags=("honesty", "critical")),
    Mutation(
        id="M1563", phase=90,
        description="read 'size OR service' as if both had to hold",
        path=_C,
        anchor="        elif len(kinds) > 1 and _contains_term(folded, \"or\"):",
        replacement="        elif False:",
        target=_T, keyword="read_only_in_part",
        tags=("honesty",)),
    Mutation(
        id="M1564", phase=90,
        description="decide two bounds of one kind without knowing how they combine",
        path=_C,
        anchor="        if len(numeric) != len({n.kind for n in numeric}):",
        replacement="        if False:",
        target=_T, keyword="read_only_in_part",
        tags=("honesty",)),
    Mutation(
        id="M1565", phase=90,
        description="count a low-trust value as evidence for the condition",
        path=_C,
        anchor="    trusted = [(f, v) for f, v, why in judged if why is None]",
        replacement="    trusted = [(f, v) for f, v, why in judged]",
        target=_T, keyword="low_trust_value_cannot_excuse",
        tags=("honesty", "critical")),
    Mutation(
        id="M1566", phase=90,
        description="ignore an untrusted reading that would change the answer",
        path=_C,
        anchor="    if untrusted and _aggregate(rule, [v for _f, v, _w in judged]) != decided:",
        replacement="    if False:",
        target=_T, keyword="untrusted_reading_that_would_change",
        tags=("honesty",)),
    Mutation(
        id="M1567", phase=90,
        description="treat a strict bound as inclusive: NPS 2 would not be "
                    "outside 'larger than 2 inch'",
        path=_C,
        anchor="                and (left.high_open or right.low_open))",
        replacement="                and False)",
        target=_T, keyword="size_outside",
        tags=()),
    Mutation(
        id="M1568", phase=90,
        description="read an unrecognised material grade as 'not carbon steel'",
        path=_C,
        anchor="    if not said:\n        return None\n    wanted = {n.value for n in needs}",
        replacement="    if not said:\n        return False\n    wanted = {n.value for n in needs}",
        target=_T, keyword="unrecognised_material_grade",
        tags=("honesty", "critical")),
    Mutation(
        id="M1569", phase=90,
        description="invert the class bound: 'Class 600 and above' read as "
                    "'and below'",
        path=_C,
        anchor="            if after.group(\"dir\") in _UP:\n                high = None\n"
               "            else:\n                low = None",
        replacement="            if after.group(\"dir\") in _UP:\n                low = None\n"
                    "            else:\n                high = None",
        target=_T, keyword="class_inside_and_outside",
        tags=()),
    Mutation(
        id="M1570", phase=90,
        description="excuse a clause while same-kind alternatives were left unread",
        path=_C,
        anchor="        if got[\"verdict\"] is False and not reading.alternatives_unread:",
        replacement="        if got[\"verdict\"] is False:",
        target=_T, keyword="unread_alternatives",
        tags=("honesty", "critical")),
    Mutation(
        id="M1571", phase=90,
        description="read any stated service that is not 'sour' as not sour",
        path=_C,
        anchor="    if wanted and wanted <= absent:",
        replacement="    if wanted:",
        target=_T, keyword="outside_the_vocabulary",
        tags=("honesty", "critical")),
    Mutation(
        id="M1572", phase=90,
        description="read 'non-sour' as sour",
        path=_C,
        anchor="        value = _NOT_SOUR.sub(\" \", value)\n",
        replacement="",
        target=_T, keyword="service_inside_outside",
        tags=()),
    Mutation(
        id="M1573", phase=90,
        description="establish a design-temperature condition from the "
                    "operating temperature",
        path=_C,
        anchor="            if f\"{which} {kind}\" in name:",
        replacement="            if kind in name:",
        target=_T, keyword="design_field_by_role",
        tags=("honesty",)),
    Mutation(
        id="M1574", phase=90,
        description="accept a value reading that leaves a stated number "
                    "unaccounted for ('-29 / 95 °C' read as 95 °C)",
        path=_C,
        anchor="        if numbers <= condition_choice.stated_values(got[0].text):",
        replacement="        if True:",
        target=_T, keyword="inside_outside_and_straddling",
        tags=("honesty",)),
    Mutation(
        id="M1575", phase=90,
        description="let another nozzle's or tag's size decide the condition",
        path=_C,
        anchor="    if not about:\n        return list(facts)\n",
        replacement="    return list(facts)\n",
        target=_T, keyword="another_nozzle or compared_items_tag",
        tags=()),
    Mutation(
        id="M1576", phase=90,
        description="drop the CRS Review note for a requirement excused by its condition",
        path=APP / "crs_mapping.py",
        anchor="        if (f.get(\"compliance_status\") == _NOT_APPLICABLE\n",
        replacement="        if (False\n",
        target=_T, keyword="crs_lists_not_applicable",
        tags=("honesty",)),
    Mutation(
        id="M1577", phase=90,
        description="drop the CONDITION_NOT_MET code, so the CRS cannot find "
                    "the excused requirement",
        path=APP / "comparison.py",
        anchor="                    f\"{CONDITION_NOT_MET}: this requirement is conditional on \"",
        replacement="                    f\"this requirement is conditional on \"",
        target=_T, keyword="crs_lists_not_applicable or size_outside",
        tags=()),
    Mutation(
        id="M1578", phase=90,
        description="let a low-trust material decide the v1 term gate",
        path=_C,
        anchor="    untrusted = [f for f in stated if _low_trust(f)]\n    if untrusted:\n",
        replacement="    untrusted = [f for f in stated if _low_trust(f)]\n    if False:\n",
        target=_T, keyword="low_trust_material_does_not_decide_the_v1",
        tags=("honesty",)),
    Mutation(
        id="M1579", phase=90,
        description="stop passing the compared fact to the gate, so a review "
                    "judges P-101A on P-101B's size",
        path=APP / "comparison.py",
        anchor="    condition = conditions.evaluate(requirement, submittal_facts, about=fact)",
        replacement="    condition = conditions.evaluate(requirement, submittal_facts)",
        target=_T, keyword="compared_items_tag",
        tags=()),
)
