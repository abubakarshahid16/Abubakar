"""A checklist result that rests on a value nobody can trust yet is a QUESTION, never a Pass or Fail (lead, 15 Nov 2026; R48n; the rule of `comparison.low_trust_reason`,
which the standards comparison already applies, made true for the datasheet checks too, whichever path calls them and whether or not any trust switch is on).

`hold_results` is called first by `deferred_value.hold_results`, the one exit of `datasheet_checks.evaluate` (the evaluator itself is untouched). A COMPLIANT or NON_COMPLIANT result is turned into
NEEDS_ENGINEER_REVIEW (hold code `hold_reason.OTHER`, the check's own reading kept in the words) when it RESTS on an untrusted fact: the fact it is about, the fact of
the role it is checked against, or, for a calculation, a fact of its input roles. "Untrusted": the value carries two readings (`reading_conflict`, made by the calculator
step), or `comparison.low_trust_reason` names a reason (a state of conflict or needing an engineer, a model reading whose quote is not proved), unless an engineer has
confirmed the value. It is the same for a presence check ("stated" on a value with two readings), a compared check and a consistency pair. The question names the field
and the reason. Pure: no database, no model, no network.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from . import hold_reason

_DECIDED = ("COMPLIANT", "NON_COMPLIANT")
_QUERY = "NEEDS_ENGINEER_REVIEW"


def reason(fact: Mapping | None) -> str | None:
    """Why this value may not rest a verdict, in words, or None."""
    if not fact:
        return None
    from . import comparison

    return fact.get("reading_conflict") or comparison.low_trust_reason(dict(fact))


def hold_results(
    results: list[dict], facts: Sequence[Mapping], rules: dict, wanted
) -> list[dict]:
    """`results` with every decided result that rests on an untrusted fact turned into a question."""
    from . import deferred_value
    from .datasheet_checks import role_of

    if not results or not any(reason(f) for f in facts):
        return results
    right_of = deferred_value._right_roles(rules)
    bad: dict[tuple, tuple[str, str]] = {}
    for f in facts:
        why = reason(f)
        role = (
            role_of(
                str(f.get("field_name") or f.get("field_label") or ""), rules, wanted
            )
            if why
            else None
        )
        if role:
            bad[(f.get("equipment_tag"), role)] = (
                str(f.get("field_label") or role),
                why,
            )
    by_id = {f.get("id"): f for f in facts}
    out = []
    for r in results:
        if r.get("status") not in _DECIDED:
            out.append(r)
            continue
        roles = {r.get("role"), right_of.get(r.get("rule_id"))} | (
            set(deferred_value.CALC_INPUT_ROLES) if r.get("calc") else set()
        )
        own = by_id.get(r.get("fact_id"))
        hit = (
            own and reason(own) and (str(own.get("field_label") or ""), reason(own))
        ) or next(
            (
                bad[(tag, role)]
                for role in roles
                if role
                for tag in (r.get("equipment_tag"), None)
                if (tag, role) in bad
            ),
            None,
        )
        if not hit:
            out.append(r)
            continue
        out.append(
            {
                **r,
                "status": _QUERY,
                hold_reason.KEY: hold_reason.OTHER,
                "detail": f"Could not be judged: {hit[0]}: {hit[1]}. The check read {r['status']}; engineer to confirm. {r.get('detail') or ''}".strip(),
            }
        )
    return out
