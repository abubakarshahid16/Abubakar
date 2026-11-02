"""#805 plan change 6: a run's version 2 rows as `coverage_pair` states them: apart, with their own denominator."""

from __future__ import annotations

PASS, FAIL = "COMPLIANT", "NON_COMPLIANT"
DECIDED = (PASS, FAIL)
NOT_MEASURED = "not measured"
ORIGIN = "rulebook_v2"


def rulebook_part(part: dict, findings: list[dict], wrong_ids: set[int] | None) -> dict:
    """The version 2 rows of a run that read them: decided of the approved rules for this
    equipment type. Never in `decided`; a run with no rule says why, not 0 of 0."""
    rows = [f for f in findings if f.get("origin") == ORIGIN]
    # a row per tag; a rule is one rule: a fail if any tag fails, a pass only if every tag passes
    by_rule: dict[str, list[dict]] = {}
    for f in rows:
        by_rule.setdefault(f.get("requirement_source_text") or "", []).append(f)
    passed = failed = 0
    for held in by_rule.values():
        said = [f.get("compliance_status") for f in held]
        failed += FAIL in said
        # a safety Pass an engineer has not ticked is not yet decided, as on the rules' lane
        passed += all(
            f.get("compliance_status") == PASS and not f.get("show_for_engineer_tick")
            for f in held
        )
    decided = passed + failed
    wrong = (
        None
        if wrong_ids is None
        else sum(
            any(
                id(f) in wrong_ids and f.get("compliance_status") in DECIDED
                for f in held
            )
            for held in by_rule.values()
        )
    )
    rules = part.get("rules") or 0
    said = f"{wrong} wrong of {decided} decided" if wrong is not None else NOT_MEASURED
    reference = part.get("material_reference")
    told = (
        f" Material families come from an owner-signed reference, version {reference}, not engineer-confirmed."
        if reference
        else ""
    )
    held_back = part.get("withheld") or {}
    no_grant = held_back.get("not_readable_by_this_reader") or 0
    by_book = held_back.get("withheld_by_the_book") or 0
    if no_grant or by_book:
        told += (
            f" Approved rules left out, not counted above: {no_grant} this reader may not read, {by_book} withheld"
            " by the rulebook."
        )
    outside = held_back.get("outside_equipment_scope") or 0
    if outside:
        told += (
            f" Rules not paired, not counted above: {outside} outside this equipment type's scope, by the scope clause"
            " of their own Part or Appendix."
        )
    return {
        "state": part.get("state"),
        "equipment_type": part.get("equipment_type"),
        "snapshot_id": part.get("snapshot_id"),
        "rules": rules,
        "decided": decided,
        "pass": passed,
        "fail": failed,
        "query": rules - decided,
        "wrong": wrong,
        "reasons": part.get("reasons") or {},
        "line": (
            f"Rulebook version 2, stated apart, not added to the rules: {decided} of {rules} approved rules"
            f" for this equipment type decided (pass {passed}, fail {failed}, query {rules - decided})."
            f" Risk: {said}.{told}"
            if rules
            else f"Rulebook version 2 read no rule: {part.get('state')}.{told}"
        ),
    }
