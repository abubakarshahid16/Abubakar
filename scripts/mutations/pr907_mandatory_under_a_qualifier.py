"""PR #907 (#898, PF2): a mandatory field stated under a leading qualifier is
an engineer's question that names the row, not "not found".
`datasheet_checks.py` is in the danger zone (rule 6)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_898_mandatory_under_a_qualifier.py"
_M = APP / "datasheet_checks.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M907-01", phase=907,
             description="a field stated under a qualifier is reported as not found again",
             path=_M,
             anchor="            named = [] if found else (qualified.get(tag, {}).get(role) or qualified.get(None, {}).get(role) or [])\n",
             replacement="            named = []\n",
             target=_T, keyword="engineers_question or both_named or common_sections", tags=("honesty",)),
    Mutation(id="M907-02", phase=907,
             description="a blank qualified field ('TBA') counts as the field being stated",
             path=_M,
             anchor='        elif (under := qualified_role_of(fact.get("field_name") or "", rules)) and not fact.get("is_blank"):\n',
             replacement='        elif (under := qualified_role_of(fact.get("field_name") or "", rules)):\n',
             target=_T, keyword="blank_qualified", tags=("honesty", "critical")),
    Mutation(id="M907-03", phase=907,
             description="any number of leading words is a qualifier ('lube oil system design pressure')",
             path=_M,
             anchor="QUALIFIER_WORDS = 2\n",
             replacement="QUALIFIER_WORDS = 9\n",
             target=_T, keyword="what_is_not_a_qualified_role", tags=("honesty",)),
    Mutation(id="M907-04", phase=907,
             description="a qualified field is said to be the field: the question becomes silence",
             path=_M,
             anchor="                out.append(_result(QUALIFIED_RULE, NEEDS_ENGINEER_REVIEW,\n",
             replacement="                out.append(_result(QUALIFIED_RULE, COMPLIANT,\n",
             target=_T, keyword="engineers_question or common_sections", tags=("honesty", "critical")),
)
