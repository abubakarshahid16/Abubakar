"""Owner order 2a + 2b: table/formula rules in code, judged on the output field."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_rule_eval.py"
_R = APP / "rule_eval.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1073", phase=91, description="a 'whichever is greater' row takes the first term",
             path=_R, anchor='            if op == "max":\n                return max(values), row\n',
             replacement='            if op == "max":\n                return values[0], row\n',
             target=_T, keyword="each_row_shape or max_rule_takes_the_greater", tags=("honesty", "critical")),
    Mutation(id="M1074", phase=91, description="a design pressure below the required value passes",
             path=_R, anchor='    ok = _CMP[comparator](x_out, required)\n',
             replacement="    ok = True\n",
             target=_T, keyword="each_row_shape or too_low", tags=("honesty", "critical")),
    Mutation(id="M1075", phase=91, description="gauge and absolute are compared as one scale",
             path=_R, anchor='    if b_in != b_out or (b_rule and b_rule != b_in) or (not b_rule and b_in == "a"):\n',
             replacement="    if False:\n",
             target=_T, keyword="gauge_against_absolute", tags=("honesty", "critical")),
    Mutation(id="M1076", phase=91, description="a half-parsed table is used as a rule",
             path=_R, anchor="        expr = _parse_expr(rest, symbols)\n        if expr is None:\n            return None\n",
             replacement="        expr = _parse_expr(rest, symbols)\n        if expr is None:\n            continue\n",
             target=_T, keyword="unparseable_table", tags=("honesty", "critical")),
    Mutation(id="M1077", phase=91, description="a rule number that is not on the page is accepted",
             path=_R, anchor="    return rule_numbers(rule) <= present\n",
             replacement="    return True\n",
             target=_T, keyword="number_not_on_the_page or model_parse", tags=("honesty", "critical")),
    Mutation(id="M1078", phase=91, description="the comparison ignores the parsed rule (back to engineer review on the input)",
             path=APP / "comparison.py",
             anchor="            if rule is not None:\n                rule_verdict, fact = rule_eval.judge(rule, facts)\n",
             replacement="            if False:\n                rule_verdict, fact = rule_eval.judge(rule, facts)\n",
             target=_T, keyword="meets_the_calculated", tags=("critical",)),
    Mutation(id="M1079", phase=91, description="the input field is judged when the output is missing",
             path=_R,
             anchor='    output = out_hits[0] if out_state == SINGLE else None\n',
             replacement='    output = out_hits[0] if out_state == SINGLE else (in_hits[0] if in_state == SINGLE else None)\n',
             target=_T, keyword="missing_is_missing_information", tags=("honesty", "critical")),
    Mutation(id="M1080", phase=91, description="the parsed rule is not stored on the requirement",
             path=_R,
             anchor='            conn.execute("UPDATE standard_requirements SET rule_json = ?, rule_source = ?"\n',
             replacement='            conn.execute("SELECT ?, ?"\n',
             target=_T, keyword="stored_once", tags=("audit",)),
    Mutation(id="M1081", phase=91, description="a model's parse is kept without the number check",
             path=_R, anchor='    return rule if rule["rows"] and verify_numbers(rule, text) else None\n',
             replacement='    return rule if rule["rows"] else None\n',
             target=_T, keyword="model_parse_is_kept_only", tags=("honesty", "critical")),
)
