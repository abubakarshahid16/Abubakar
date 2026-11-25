"""Code reads the numbers a judge did not hand over (26 Nov 2026, the local model's first valve run: 58 of 61 points were
"Question", numbers were given on 5 and none was compared, so no stated value that breaks a rule was found).

ONLY WHEN IT IS UNAMBIGUOUS: the item's rule quote states exactly ONE limit with a comparator ("not less than 3 mm" -> >= 3 mm),
and the judge's own quote (verified on its page by code) holds exactly ONE value of the same quantity. Then code builds the
numbers and the method's one comparison (`steps._numbers`) decides, as it does for numbers a judge gives; a quote with two
values of that quantity, or a rule with two limits, is left to the judge (code never chooses a pairing). Read with the app's
one reader (`claims`); no number parser here. Used on the local model only (`steps._compare`), until it is scored on Claude."""

from __future__ import annotations

NOTE = "numbers read by code from the paper quote and the rule (one value each, the same quantity)"
_OPS = {
    "min": ">=",
    "max": "<=",
    ">=": ">=",
    "<=": "<=",
    "<": "<",
    ">": ">",
    "==": "==",
    "!=": "!=",
}


def numbers(rule_quote: str, quote: str) -> dict | None:
    """The judge's "numbers" object built by code, or None when the rule's limit or the paper's value is not single."""
    from app import claims

    limits = [
        m
        for m in claims.extract_measurements(rule_quote or "")
        if _OPS.get(m.comparator or "")
    ]
    if len(limits) != 1 or not limits[0].raw_unit:
        return None
    limit = limits[0]
    values = [
        m
        for m in claims.extract_measurements(quote or "")
        if m.raw_unit and claims.same_quantity(m.raw_unit, limit.raw_unit)
    ]
    if len(values) != 1:
        return None
    v = values[0]
    return {
        "paper_value": v.raw_value,
        "paper_unit": v.raw_unit,
        "operator": _OPS[limit.comparator],
        "rule_value": limit.raw_value,
        "rule_unit": limit.raw_unit,
    }


def decided(
    it: dict,
    label: str,
    quote: str,
    notes: list[str],
    paper,
    deferred: bool,
    compare,
    nums=None,
) -> tuple | None:
    """(label, code's comparison) when code read the numbers itself and the method's comparison (`compare`, `steps._compare`)
    reached Pass or Fail on them; None otherwise (the AI's label stands, as before). Local model only, a held rule, a quote."""
    from .budget import is_local

    if (
        nums
        or not is_local()
        or it.get("source") != "held standard"
        or not quote
        or deferred
    ):
        return None
    found = numbers(str(it.get("rule_quote") or ""), quote)
    if not found:
        return None
    tried: list[str] = []
    new, cmp_ = compare(it, label, found, quote, tried, paper, deferred)
    if not (isinstance(cmp_, dict) and cmp_.get("result") in ("pass", "fail")):
        return None
    notes.extend([*tried, NOTE])
    return new, cmp_


def met_unproven(said, label: str, nums, deferred: bool, code_cmp) -> list[str]:
    """[AI_MET_UNPROVEN] when the judge itself said Met, with numbers, and code could not prove them (the line fell back to a
    Question): an AI verdict of a pass is internal only, kept on All points, never sent. The same rule as the Claude line
    (o14/u7b-A `verify.met_unproven`), here for the local model."""
    from . import AI_MET_UNPROVEN
    from .budget import is_local

    if (
        not is_local()
        or said != "Met"
        or label != "Question"
        or deferred
        or not isinstance(nums, dict)
    ):
        return []
    if isinstance(code_cmp, dict) and code_cmp.get("result") in ("pass", "fail"):
        return []
    return [AI_MET_UNPROVEN]
