"""PR #965 (#893): a clause that compares two fields is judged in code against
the sheet's two fields. `comparison.py` and the `rule_eval` verdict path are in
the danger zone (rule 6)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_cross_field_limits.py"
_C = APP / "comparison.py"
_R = APP / "requirements_3b.py"
_E = APP / "rule_eval.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M965-01", phase=965,
             description="a field comparison is not judged by the rule path (left with the engineer)",
             path=_C,
             anchor="                                                    requirements_3b.RELATIVE_LIMIT,\n                                                    requirements_3b.CROSS_FIELD_LIMIT):",
             replacement="                                                    requirements_3b.RELATIVE_LIMIT):",
             target=_T, keyword="outlet_at_least_as_large or smaller_than_the_inlet", tags=("honesty", "critical")),
    Mutation(id="M965-02", phase=965,
             description="a ceiling (shall not exceed) is read as a floor",
             path=_R,
             anchor='    operator = _OPERATOR.get(_canonical_comparator(match.group("cmp")))\n    subject = _SUBJECT_LEAD',
             replacement='    operator = ">="\n    subject = _SUBJECT_LEAD',
             target=_T, keyword="a_comparison_of_two_fields_is_read or a_ceiling_is_a_ceiling", tags=("honesty", "critical")),
    Mutation(id="M965-03", phase=965,
             description="a reference that reads like a table or a clause is taken for a field",
             path=_R,
             anchor="or not reference or _NOT_A_FIELD.search(reference)\n",
             replacement="or not reference\n",
             target=_T, keyword="not_a_field_comparison", tags=("honesty", "critical")),
    Mutation(id="M965-04", phase=965,
             description="a conditional comparison is judged unconditionally",
             path=_R,
             anchor="    if match is None or _CONDITION_WORD.search(text):\n",
             replacement="    if match is None:\n",
             target=_T, keyword="not_a_field_comparison", tags=("honesty", "critical")),
    Mutation(id="M965-05", phase=965,
             description="a comparison with no offset has no scale: the reference's unit is not used",
             path=_E,
             anchor='    if not rule.get("unit"):\n',
             replacement='    if False:\n',
             target=_T, keyword="outlet_at_least_as_large or another_unit_of_the_same_quantity", tags=("honesty", "critical")),
    Mutation(id="M965-06", phase=965,
             description='"minus" is added instead of subtracted',
             path=_R,
             anchor='        offset = -offset if match.group("sign").lower() == "minus" else offset\n',
             replacement="        offset = offset\n",
             target=_T, keyword="not_a_field_comparison or a_comparison_of_two_fields_is_read", tags=("honesty",)),
    Mutation(id="M965-07", phase=965,
             description="a stated factor (1.1 times) is ignored",
             path=_R,
             anchor='        factor = claims.parse_value(re.sub(r"\\s*(?:x|times)$", "", mult))\n',
             replacement='        factor = 1.0\n',
             target=_T, keyword="a_comparison_of_two_fields_is_read or factor_scales", tags=("honesty", "critical")),
)
