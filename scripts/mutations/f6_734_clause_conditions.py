"""#725 F6 (#734): a clause with an application condition applies only when the datasheet matches. Ids M7001-M7008."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_f6_734_clause_conditions.py"
_S = APP / "service_scope.py"
_TAG = ("f6", "scope")


def _m(i, desc, anchor, repl, kw=None, path=_S):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=path, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(7001, "value conditions are read like yes/no fields", 
       '    if condition.get("mode") == "value":\n        return _value_declaration(condition, facts)\n', "",
       "states_otherwise or matching_application"),
    _m(7002, "a matching application does not keep its clause",
       '        if any(f" {m} " in _words(raw) for m in condition["satisfied_by"]):\n', "        if False:\n",
       "matching_application or any_stated_field"),
    _m(7003, "only the first stated field is looked at",
       "    for fact, raw in stated:\n        if any(", "    for fact, raw in stated[:1]:\n        if any(",
       "any_stated_field"),
    _m(7004, "a placeholder counts as a stated application",
       "        if conditions_mod._is_empty(raw) or not str(raw or \"\").strip():\n",
       "        if not str(raw or \"\").strip():\n", "unstated_application"),
    _m(7005, "an unstated application sets the clauses aside",
       "    if not stated:\n        return None\n", "    if not stated:\n        return {\"present\": False, \"label\": \"\", \"value\": \"\", \"page\": None, \"fact_id\": None}\n",
       "unstated_application"),
    _m(7006, "the clause heading is not read",
       '        "requirement_text", "source_text", "condition")) + " " + (heading or ""))',
       '        "requirement_text", "source_text", "condition")))', "parent_heading or states_otherwise"),
    _m(7007, "a parent clause's heading is not read",
       "    return \" \".join(h for h in (headings.get(c) for c in [clause, *_ancestors(clause)] if c) if h)",
       "    return headings.get(clause) or \"\"", "parent_heading or states_otherwise"),
    _m(7008, "the review run does not read the headings itself",
       "    if headings_by_standard is None and any(d is not None and d[\"present\"] is False\n",
       "    if False and any(d is not None and d[\"present\"] is False\n", "review_run_records"),
)
