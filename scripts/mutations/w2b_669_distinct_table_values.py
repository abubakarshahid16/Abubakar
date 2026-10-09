"""#669 leftover: table values not compared are counted as distinct values. Ids M6501-M6505."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w2b_669_distinct_table_values.py"
_TAG = ("w2b", "honesty")


def _m(i, desc, path, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=path, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(6501, "the grouped line counts stored rows again", APP / "table_gate.py",
       '            "line": (f"{distinct} table values in {len(tables)} "',
       '            "line": (f"{entry[\'count\']} table values in {len(tables)} "', "grouped_line"),
    _m(6502, "the grouped line hides that repeats were stored", APP / "table_gate.py",
       '                   if distinct != entry["count"] else "")', '                   if False else "")',
       "grouped_line"),
    _m(6503, "distinct is case and spacing sensitive", APP / "table_gate.py",
       '        entry["distinct"].add(" ".join(str(requirement.get("requirement_text") or "").lower().split()))',
       '        entry["distinct"].add(str(requirement.get("requirement_text") or ""))', "case_and_spacing"),
    _m(6504, "the CRS sentence counts stored rows again", APP / "absence.py",
       '            f"{distinct} standards-table value(s) were not compared{note}: "',
       '            f"{cells} standards-table value(s) were not compared{note}: "', "counts_distinct"),
    _m(6505, "an older run's number is not called stored rows", APP / "absence.py",
       '            distinct, note = cells, " (stored rows; repeats of the same value not removed)"',
       '            distinct, note = cells, ""', "older_run"),
)
