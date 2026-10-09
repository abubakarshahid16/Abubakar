"""#531: table-consistency check. Ids M5201-M5212 (session 1 holds M5001-M5014
and M5101-M5105)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w5b_531_table_consistency.py"
_P = APP / "table_consistency.py"
_TAG = ("w5b", "tables")


def _m(i, desc, anchor, repl, kw=None, path=_P):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=path, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(5201, "overlapping bands are not reported", "            if lo2.value < hi1.value:", "            if False:", "overlap"),
    _m(5202, "a gap counts even between contiguous whole-number bands",
       "            elif lo2.value - hi1.value > _step(hi1, lo2) * 1.0000001:",
       "            elif lo2.value - hi1.value > 0:", "meet_without_overlap"),
    _m(5203, "a shared boundary is not reported", "            elif lo2.value == hi1.value:", "            elif False:",
       "belongs_to_two_bands"),
    _m(5204, "bands are compared in table order, not by value",
       "        ordered = sorted((b for b in bands if b[1].value <= b[2].value), key=lambda b: b[1].value)",
       "        ordered = [b for b in bands if b[1].value <= b[2].value]", "out_of_order"),
    _m(5205, "an inverted band is not reported", "            if lo.value > hi.value:", "            if False:", "low_end"),
    _m(5206, "rounding is an error: no allowance for the printed precision (total column)",
       "            allowed = sum(t.half_unit for t in terms) + total.half_unit\n            if abs(sum(t.value for t in terms) - total.value) > allowed + 1e-12:\n                findings.append(_finding(\n                    \"total_column_mismatch\",",
       "            allowed = 0\n            if abs(sum(t.value for t in terms) - total.value) > allowed + 1e-12:\n                findings.append(_finding(\n                    \"total_column_mismatch\",",
       "within_rounding"),
    _m(5207, "a total column mismatch is not reported",
       "            if abs(sum(t.value for t in terms) - total.value) > allowed + 1e-12:\n                findings.append(_finding(\n                    \"total_column_mismatch\",",
       "            if False:\n                findings.append(_finding(\n                    \"total_column_mismatch\",", "total_column"),
    _m(5208, "a total row mismatch is not reported",
       "            if abs(sum(t.value for t in terms) - total.value) > allowed + 1e-12:\n                findings.append(_finding(\n                    \"total_row_mismatch\",",
       "            if False:\n                findings.append(_finding(\n                    \"total_row_mismatch\",", "total_row"),
    _m(5209, "a total is checked over cells that are not all numbers",
       "            if total is None or len(terms) < 2 or any(t is None for t in terms):",
       "            terms = [t for t in terms if t is not None]\n            if total is None or len(terms) < 2:", "not_all_numbers"),
    _m(5210, "a stated formula is not checked", "        ran += 1\n        for r, row in enumerate(data, start=1):\n            cells =",
       "        ran += 1\n        continue\n        for r, row in enumerate(data, start=1):\n            cells =", "formula"),
    _m(5211, "a table with nothing to check is called ok",
       "    elif checked == 0:\n        state = \"nothing_checked\"", "    elif checked == 0:\n        state = \"ok\"", "nothing_to_check or unparsed"),
    _m(5212, "an unparsed table is counted as checked",
       "        if not parse.parsed:\n            unparsed += 1\n            continue",
       "        if not parse.parsed:\n            unparsed += 1\n            checked += 1\n            continue", "unparsed"),
)
