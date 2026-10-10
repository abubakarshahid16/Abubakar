"""#617: range cells such as 5-10 are recorded as a range requirement. Ids M6301-M6308."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w2b_617_range_cells.py"
_R = APP / "requirements_3b.py"
_S = APP / "standards.py"
_TAG = ("w2b", "tables")


def _m(i, desc, path, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=path, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(6301, "a range cell is skipped as not a number", _S,
       "                span = requirements_3b.cell_range(raw_value) if reading is None else None\n",
       "                span = None\n", "recorded_as_one_range or ambiguous_range or no_unit or re_extracting"),
    _m(6302, "an ambiguous dash is read as a range", _R,
       "    ambiguous = ((sep.strip().lower() != \"to\" and sep[:1].isspace() and not sep[-1:].isspace())\n",
       "    ambiguous = (False\n", "ambiguous"),
    _m(6303, "a reversed range keeps its bounds", _R,
       "    if ambiguous or low is None or high is None or low > high:",
       "    if ambiguous or low is None or high is None:", "ambiguous_dash"),
    _m(6304, "a range is stored as its low number", _S,
       "                    value = None\n                elif unit:", "                    value = low\n                elif unit:",
       "recorded_as_one_range"),
    _m(6305, "the bounds are not stored", _S,
       "                            \"value_low\": low if span is not None else None,\n", "",
       "recorded_as_one_range or no_unit"),
    _m(6306, "a range is typed as a single table value", _S,
       "                            \"requirement_type\": (\"table_value\" if span is None\n"
       "                                                 else requirements_3b.TABLE_RANGE),",
       "                            \"requirement_type\": \"table_value\",", "recorded_as_one_range or ambiguous_range"),
    _m(6307, "an ambiguous range is given the between operator", _S,
       "                            (requirements_3b.RANGE_OPERATOR if span.low is not None else None))",
       "                            requirements_3b.RANGE_OPERATOR)", "ambiguous_range"),
    _m(6308, "the bounds are left in the cell's unit when the unit is known", _S,
       "                        low, high = lo.normalized_value, hi.normalized_value\n", "",
       "recorded_as_one_range"),
)
