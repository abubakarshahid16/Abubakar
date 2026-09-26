"""Mutations for master order B5 on the live review path (2026-09-25).

Every entry targets `backend/tests/test_b5_live.py`. Each deletes one piece of
the wiring - the inclusion policy, the evidence, the scope decision, the
MISSING_LOCALLY and empty-evaluation gates, or the reasons reaching the run and
the CRS - and the named tests must then fail.
"""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_b5_live.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M730", phase=66, description="B5 live: a discipline or similarity match is applied again",
        path=APP / "applicability.py",
        anchor='    "manual", "referenced", "equipment_type", "scope", "service", "project"})\n',
        replacement='    "manual", "referenced", "equipment_type", "scope", "service", "project",\n'
                    '    "discipline", "semantic"})\n',
        target=_T, keyword="discipline_alone or similar_wording_alone or not_compared or as_unknown",
        tags=("honesty",),
    ),
    Mutation(
        id="M731", phase=66, description="B5 live: a confirmed scope exclusion is still applied",
        path=APP / "applicability.py",
        anchor='    return row["method"] in INCLUDING_METHODS and not row.get("excluded_by_scope")\n',
        replacement='    return row["method"] in INCLUDING_METHODS\n',
        target=_T, keyword="confirmed_scope_exclusion", tags=("honesty",),
    ),
    Mutation(
        id="M732", phase=66, description="B5 live: a citation's page and line are not recorded",
        path=APP / "applicability.py",
        anchor='            row["evidence_page"], row["evidence_quote"] = page, quote\n',
        replacement='            row["evidence_page"], row["evidence_quote"] = None, None\n',
        target=_T, keyword="carries_its_page_and_line or reach_the_run_and_the_crs",
    ),
    Mutation(
        id="M733", phase=66, description="B5 live: an unconfirmed NOT_APPLICABLE excludes a standard",
        path=APP / "applicability.py",
        anchor='        if decision.get("decision") == applicability_v2.NOT_APPLICABLE and not confirmed:\n',
        replacement='        if False:\n',
        target=_T, keyword="unconfirmed_scope_exclusion", tags=("honesty",),
    ),
    Mutation(
        id="M734", phase=66, description="B5 live: a scope clause naming the equipment does not apply the standard",
        path=APP / "applicability.py",
        anchor='        if verdict == v2.APPLICABLE and (row is None or row["method"] not in INCLUDING_METHODS):\n',
        replacement='        if False:\n',
        target=_T, keyword="scope_clause_naming_the_equipment",
    ),
    Mutation(
        id="M735", phase=66, description="B5 live: a cited standard is excluded by its scope reading",
        path=APP / "applicability.py",
        anchor='            if row["method"] == METHOD_REFERENCED:\n                # CITED STANDARDS ARE NEVER EXCLUDED',
        replacement='            if False:\n                # CITED STANDARDS ARE NEVER EXCLUDED',
        target=_T, keyword="never_excluded_by_its_scope_reading", tags=("honesty",),
    ),
    Mutation(
        id="M736", phase=66, description="B5 live: the scope step runs without an approved taxonomy",
        path=APP / "applicability.py",
        anchor='    if taxonomy is None:\n        return {}, "scope clauses not checked: no equipment taxonomy is approved"\n',
        replacement='    if taxonomy is None:\n        return {}, None\n',
        target=_T, keyword="without_an_approved_taxonomy",
    ),
    Mutation(
        id="M737", phase=66, description="B5 live: an empty evaluation reaches Approved",
        path=APP / "comparison.py",
        anchor="    if not evaluated:\n        why = (",
        replacement="    if False:\n        why = (",
        target=_T, keyword="nothing_evaluated or only_not_applicable", tags=("honesty", "critical"),
    ),
    Mutation(
        id="M738", phase=66, description="B5 live: not-applicable findings count as an evaluation",
        path=APP / "comparison.py",
        anchor="    evaluated = [s for s in statuses if s != NOT_APPLICABLE]\n",
        replacement="    evaluated = statuses\n",
        target=_T, keyword="only_not_applicable", tags=("honesty",),
    ),
    Mutation(
        id="M739", phase=66, description="B5 live: a cited standard not held no longer blocks approval",
        path=APP / "comparison.py",
        anchor="    if missing_locally:\n        # B5: A CITED STANDARD THAT IS NOT HELD WAS NEVER CHECKED.",
        replacement="    if False:\n        # B5: A CITED STANDARD THAT IS NOT HELD WAS NEVER CHECKED.",
        target=_T, keyword="not_held_blocks_approval or never_approves_with_a_cited",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M740", phase=66, description="B5 live: the review route drops the selection's missing standards",
        path=APP / "main.py",
        anchor='            missing_references=[m["identifier"] for m in selection["missing_references"]])\n',
        replacement="            missing_references=[])\n",
        target=_T, keyword="never_approves_with_a_cited or reach_the_run_and_the_crs",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M741", phase=66, description="B5 live: the CRS workbook has no applicable-standards rows",
        path=APP / "crs_export.py",
        anchor='    for r, entry in enumerate(view["applicable_standards"], start=2):\n',
        replacement="    for r, entry in enumerate([], start=2):\n",
        target=_T, keyword="reach_the_run_and_the_crs",
    ),
    Mutation(
        id="M742", phase=66, description="B5 live: the CRS standards list leaves out cited standards not held",
        path=APP / "main.py",
        anchor="    for ref in _missing_references(submittal_id, allowed):\n        out.append({\"standard\": ref,",
        replacement="    for ref in ():\n        out.append({\"standard\": ref,",
        target=_T, keyword="reach_the_run_and_the_crs", tags=("honesty",),
    ),
    Mutation(
        id="M743", phase=66, description="B5 live: the run's standards list hides the missing standards",
        path=APP / "main.py",
        anchor='            "missing_references": outcome.get("missing_references") or []}\n',
        replacement='            "missing_references": []}\n',
        target=_T, keyword="reach_the_run_and_the_crs",
    ),
    Mutation(
        id="M744", phase=66, description="B5 live: the applicability list calls a considered standard applicable",
        path=APP / "applicability.py",
        anchor='                      for row in result["selected"] if row["included"]}\n',
        replacement='                      for row in result["selected"]}\n',
        target=_T, keyword="as_unknown_not_applicable", tags=("honesty",),
    ),
    Mutation(
        id="M745", phase=66, description="B5 live: a low-completeness reason does not name the missing standards",
        path=APP / "comparison.py",
        anchor="        if missing_locally:\n            # A missing cited standard is one CAUSE",
        replacement="        if False:\n            # A missing cited standard is one CAUSE",
        target=_T, keyword="named_when_it_is_why_completeness_is_low",
    ),
)
