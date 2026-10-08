"""#598 "a table cell is a review check only when the submittal has a matching
field": each entry deletes one part and backend/tests/test_w2b_598_review_table_filter.py
must notice. Files: backend/app/table_gate.py, backend/app/comparison.py."""
from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

_T = "tests/test_w2b_598_review_table_filter.py"
_TAG = ("w2b_598", "honesty")


def _m(i, desc, path, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=APP / path,
                    anchor=anchor, replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(2701, "a row is checked whatever its key (every table cell is a check again)",
       "table_gate.py", "        hit = bool(key) and _matches_row(key, values, labels)\n",
       "        hit = True\n"),
    _m(2702, "a matching row no longer stops the column from pulling in every other row",
       "table_gate.py", "        if not checked and not table_selectable[table]:\n",
       "        if not checked:\n"),
    _m(2703, "the column field is no longer a handle for a table the sheet cannot select by row",
       "table_gate.py", "            checked = bool(column) and _matches_column(column, labels)\n",
       "            checked = False\n"),
    _m(2704, "a definition becomes a check again",
       "table_gate.py", "    if requirement.get(\"requirement_type\") == DEFINITION:\n        return DEFINITION\n",
       "    if False:\n        return DEFINITION\n"),
    _m(2705, "unconfirmed garbled text becomes a check again",
       "table_gate.py", "    if held and not requirement.get(\"confirmed_by\"):\n",
       "    if False:\n"),
    _m(2706, "a human-confirmed row stays excluded as garbled text",
       "table_gate.py", "    if held and not requirement.get(\"confirmed_by\"):\n",
       "    if held:\n"),
    _m(2707, "unmatched table cells are dropped silently (no grouped line)",
       "comparison.py", "    table_values_not_compared = gated[\"not_compared\"]\n",
       "    table_values_not_compared = []\n"),
    _m(2708, "the review checks every requirement again (the gate is not applied)",
       "comparison.py", "    requirements = gated[\"kept\"]\n",
       "    requirements = requirements\n"),
    _m(2709, "a table or formula rule is filtered out like the flood",
       "table_gate.py", "        if _has_rule(requirement):\n",
       "        if False:\n"),
    _m(2710, "identifier matching becomes case-sensitive",
       "table_gate.py", "    return tuple(_TOKEN.findall(numparse.fold(text or \"\")))\n",
       "    return tuple(re.findall(r\"[A-Za-z0-9]+\", str(text or \"\")))\n"),
    Mutation(id="M2711", phase=2711, runner="vitest",
             description="the run screen no longer shows the grouped not-compared table values",
             path=FRONTEND_SRC / "views" / "ReviewRunsView.tsx",
             anchor="{run && (run.table_values_not_compared?.length ?? 0) > 0 && (",
             replacement="{false && (",
             target="src/views/ReviewRunsView.test.tsx", keyword="table values that were not compared",
             tags=_TAG),
)
