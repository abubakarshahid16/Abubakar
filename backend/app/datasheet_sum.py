"""A SUM of two datasheet fields compared with a percent of a third (order 14, lane A).

SAES-J-600 5.1.1: a conventional valve when the superimposed back pressure PLUS the
built-up back pressure is below 10% of the set pressure. One part alone below the limit
proves nothing: the sum is compared, never a part.

Rule (checklist data): {"kind": "sum_percent_of", "field": <role>, "plus": <role>,
"op": "<", "percent": 10, "right": <role>}. Each part is a gauge pressure converted to kPa,
or a percentage of `right` when the sheet states it so. A part that is not given, stated
twice, marked by the contractor or on no gauge basis stops the check with its reason: it
is never taken as 0 and never gives a Pass. Pure: no model, no database, no network.
"""

from __future__ import annotations

KIND = "sum_percent_of"


def _part(dc, get, role: str, res, held):
    """(the fact, None) for one part of the sum, or (None, the result that stops it)."""
    fact, why = dc._one(get(role))
    if fact is None:
        state = (
            "has two different values"
            if why == "two different values"
            else "is not given"
        )
        sentence = (
            f"the {dc._pretty(role).lower()} {state}, so the sum is not worked out"
        )
        return None, held(
            dc.why_held.checked_against(None, why), dc._sentence(sentence)
        )
    if dc.blank_markers.fact_is_placeholder(fact, figure_wins=True):
        marker = dc._said(fact) or fact.get("blank_marker")
        words = (
            f"{dc._label(fact, role)} is marked '{marker}' on page {fact.get('page')}; "
            "the contractor is to provide the value."
        )
        return None, res(dc.MISSING_INFORMATION, words, fact, role)
    return fact, None


def _kpa(dc, fact: dict, role: str, ref_kpa: float, rules: dict) -> float:
    if dc._is_percent(fact):
        return dc._number_of(fact, role) / 100.0 * ref_kpa
    return dc._gauge_kpa(fact, role, rules)


def sum_percent_of(item: dict, _field, get, res, rules: dict) -> dict:
    """One checklist item of kind `sum_percent_of`, as `datasheet_checks.evaluate_item` calls a calculation."""
    from . import datasheet_checks as dc

    rule = item["rule"]

    def held(code, detail, fact=None, role=None):
        return {
            **res(dc.NEEDS_ENGINEER_REVIEW, detail, fact, role),
            dc.why_held.KEY: code,
        }

    reference, parts = rule["right"], []
    for role in (rule["field"], rule["plus"]):
        fact, stop = _part(dc, get, role, res, held)
        if stop is not None:
            return stop
        parts.append((role, fact))
    first = parts[0][1]
    try:
        ref_fact = dc._input(get, reference)
        ref_kpa = dc._gauge_kpa(ref_fact, reference, rules)
        if ref_kpa <= 0:
            raise dc._NotCalculated(
                f"the {dc._pretty(reference).lower()} is not above 0"
            )
        total = sum(_kpa(dc, fact, role, ref_kpa, rules) for role, fact in parts)
    except dc._NotCalculated as exc:
        why = dc._sentence(f"{exc.reason}, so the sum was not worked out")
        return res(dc.NEEDS_ENGINEER_REVIEW, why, first)
    percent = total / ref_kpa * 100.0
    ok = dc._hold(rule["op"], percent, float(rule["percent"]), dc._OPS)
    said = " plus ".join(
        f"{dc._label(f, r)} {dc._said(f)} (page {f.get('page')})" for r, f in parts
    )
    words = (
        f"{said} is {percent:.1f}% of {dc._quoted(ref_fact, reference)}, which is "
        f"{'' if ok else 'not '}{dc._OP_WORDS[rule['op']]} {rule['percent']}%."
    )
    return res(dc.COMPLIANT if ok else dc.NON_COMPLIANT, words, first)
