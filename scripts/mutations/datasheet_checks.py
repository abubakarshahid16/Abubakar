"""Owner order 2c: datasheet self-checks (kind B)."""
from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

_T = "tests/test_datasheet_checks.py"
_M = APP / "datasheet_checks.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1056", phase=89, description="a failed consistency check is reported as met",
             path=_M, anchor="            ok = _hold(rule[\"op\"], a[0], b[0], _OPS)\n",
             replacement="            ok = True\n",
             target=_T, keyword="below_operating_is_a_comment_with_the_calculation", tags=("honesty", "critical")),
    Mutation(id="M1057", phase=89, description="gauge and absolute pressures are compared as one scale",
             path=_M, anchor="            if a is None or b is None or a[1] != b[1] or a[2] != b[2]:\n",
             replacement="            if a is None or b is None or a[1] != b[1]:\n",
             target=_T, keyword="gauge_against_absolute", tags=("honesty", "critical")),
    Mutation(id="M1058", phase=89, description="one of two different values under one name is picked",
             path=_M,
             anchor="            if len({_key(f) for f in left}) != 1 or len({_key(f) for f in right}) != 1:\n",
             replacement="            if not left or not right:\n",
             target=_T, keyword="two_different_values_under_one_name", tags=("honesty",)),
    Mutation(id="M1059", phase=89, description="an absent mandatory field is not reported",
             path=_M, anchor="            if not found:\n                out.append(_result(\"DS-M1\"",
             replacement="            if False:\n                out.append(_result(\"DS-M1\"",
             target=_T, keyword="absent_or_tba", tags=("honesty",)),
    Mutation(id="M1060", phase=89, description="a 'TBA' mandatory field passes as a value",
             path=_M,
             # Re-anchored 2026-09-27 (CRS quick wins): the one marker list,
             # `blank_markers`, decides. Re-anchored again in PR 1402: through
             # `fact_is_placeholder`.
             anchor="                if blank_markers.fact_is_placeholder(fact):\n",
             replacement="                if False:\n",
             target=_T, keyword="absent_or_tba", tags=("honesty",)),
    Mutation(id="M1061", phase=89, description="a value without its unit passes",
             path=_M, anchor="                if not unit:\n",
             replacement="                if False:\n",
             target=_T, keyword="without_its_unit", tags=("honesty",)),
    Mutation(id="M1062", phase=89, description="a pressure stated in a temperature unit passes",
             path=_M, anchor="                elif (found := _unit_kind(unit, rules)) and found != kind:\n",
             replacement="                elif False:\n",
             target=_T, keyword="wrong_kind_of_unit", tags=("honesty",)),
    Mutation(id="M1063", phase=89, description="a missing revision block is reported as present",
             path=_M, anchor="    has_block = any(_block(text) for text in page_texts.values())\n",
             replacement="    has_block = True\n",
             target=_T, keyword="revision_block_is_looked_for", tags=("honesty",)),
    Mutation(id="M1064", phase=89, description="the review writes no datasheet check (a zero-standard run says nothing)",
             path=APP / "comparison.py",
             # re-anchored 2026-10-10 (PR #764): the results are kept for the coverage line
             # re-anchored 2026-10-17 (PR #985): the call gained the rule_trust label
             anchor="    findings.extend(datasheet_checks.store(\n",
             replacement="    [] and findings.extend(datasheet_checks.store(\n",
             target=_T, keyword="no_standard_held", tags=("critical",)),
    Mutation(id="M1065", phase=89, runner="vitest",
             description="a datasheet check is not labelled as one on screen",
             path=FRONTEND_SRC / "components/review/reviewFormat.ts",
             anchor='  if (finding.origin === "datasheet_check") return "Datasheet check";\n',
             replacement="",
             target="src/components/review/reviewFormat.test.ts", keyword="datasheet check says what kind",
             tags=("ui",)),

    # -------------------------------------------------------- 2026-09-27 fix
    # Fix 3: `equipment_type` is NULL on almost every submittal (nothing
    # wrote it before B9's classifier, and the classifier itself only
    # matches evidence it can find). `mandatory.get(equipment_type or "", [])`
    # silently checked NOTHING for every one of them - not one of these
    # checks has ever fired on an unclassified datasheet.
    Mutation(id="M1127", phase=94,
             description="the generic mandatory-fields fallback is skipped for an unknown equipment_type",
             path=_M,
             anchor="    mandatory = rules[\"mandatory\"].get(mandatory_list_key(equipment_type, rules), [])\n",
             replacement="    mandatory = rules[\"mandatory\"].get(equipment_type or \"\", [])\n",
             target=_T, keyword="generic_mandatory_list", tags=("honesty", "critical")),

    # A classifier label the mandatory table names only by FAMILY
    # ("Centrifugal Compressor" -> "Compressor") silently fell to the 2-field
    # generic list, because the lookup was verbatim.
    Mutation(id="M1138", phase=94,
             description="a compressor label is not resolved to its family's mandatory list",
             path=_M, anchor="    family = sheet_kind_from_equipment_type(equipment_type)\n",
             replacement="    family = None\n",
             target=_T, keyword="every_label_the_classifier_can_emit or compressor_sheet",
             tags=("honesty", "critical")),
    Mutation(id="M1139", phase=94,
             description="evaluate looks the equipment_type up verbatim again, bypassing the resolver",
             path=_M,
             anchor="    mandatory = rules[\"mandatory\"].get(mandatory_list_key(equipment_type, rules), [])\n",
             replacement="    mandatory = (rules[\"mandatory\"].get(equipment_type or \"\")\n"
                         "                 or rules[\"mandatory\"][\"_generic\"])\n",
             target=_T, keyword="every_label_the_classifier_can_emit or compressor_sheet",
             tags=("honesty", "critical")),

    # PR 1849 (order 14 lane D, review of the three AI-draft limits): a card whose limit no engineer confirmed
    # (`limit_draft`) is QUESTION ONLY; a condition value that rules nothing out never says "does not apply".
    Mutation(id="M1849-01", phase=1849,
             description="a QUESTION ONLY card's stated value is a Pass again (a draft pass that leaves the CRS)",
             path=_M, anchor="    if question_only(item):\n        return _asked(item, fact, where, noted, get, held)\n",
             replacement="",
             target="tests/test_routing_draft_pass.py", keyword="question_only", tags=("honesty", "critical")),
    Mutation(id="M1849-02", phase=1849,
             description="the question-only mark is read from another key: no card is question only",
             path=_M, anchor='QUESTION_ONLY_KEY = "limit_draft"\n',
             replacement='QUESTION_ONLY_KEY = "limit_confirmed"\n',
             target="tests/test_routing_draft_pass.py", keyword="question_only", tags=("honesty", "critical")),
    Mutation(id="M1849-03", phase=1849,
             description="a placeholder condition value ('TBA', '*', 'HOLD') says 'does not apply' again",
             path=_M, anchor='    if blank_markers.fact_is_placeholder(fact):\n        return "marked"\n',
             replacement="",
             target="tests/test_1478_pump_kit_prep.py", keyword="placeholder_fluid", tags=("honesty", "critical")),
    Mutation(id="M1849-04", phase=1849,
             description="a stated 'water' (no service named) says 'does not apply' to the firewater card again",
             path=_M, anchor='    return "open" if _names(fact, condition.get("may_be_any")) else None\n',
             replacement="    return None\n",
             target="tests/test_1478_pump_kit_prep.py", keyword="stated_water", tags=("honesty", "critical")),
    Mutation(id="M1849-05", phase=1849,
             description="a QUESTION ONLY card with two sides no longer asks for the second (a missing MOP is not said)",
             path=_M, anchor='    if rule.get("right"):\n        other, why = _one(get(rule["right"]))\n',
             replacement='    if False:\n        other, why = _one(get(rule["right"]))\n',
             target="tests/test_1480_vessel_kit_prep.py", keyword="asks_for_the_mop", tags=("honesty",)),
    Mutation(id="M1849-06", phase=1849,
             description="a QUESTION ONLY card's calculation keeps its Pass or Fail",
             path=_M, anchor="    if not question_only(item) or result.get(\"status\") not in (COMPLIANT, NON_COMPLIANT):\n",
             replacement="    if True:\n",
             target="tests/test_routing_draft_pass.py", keyword="question_only_calculation", tags=("honesty", "critical")),
)
