"""#531 (PR 1369): table-consistency check. Ids M1369-01 onwards, phase 1369."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_531_table_consistency.py"
_P = APP / "table_consistency.py"
_TAG = ("w5b", "tables")


def _m(i, desc, anchor, repl, kw=None, path=_P):
    return Mutation(
        id=f"M1369-{i:02d}",
        phase=1369,
        description=desc,
        path=path,
        anchor=anchor,
        replacement=repl,
        target=_T,
        keyword=kw,
        tags=_TAG,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        1,
        "overlapping bands are not reported",
        "            if lo2.value < hi1.value:",
        "            if False:",
        "overlap",
    ),
    _m(
        2,
        "a gap counts even between contiguous whole-number bands",
        "            elif lo2.value - hi1.value > _step(hi1, lo2) * 1.0000001:",
        "            elif lo2.value - hi1.value > 0:",
        "meet_without_overlap",
    ),
    _m(
        3,
        "a shared boundary is not reported",
        "            elif lo2.value == hi1.value:",
        "            elif False:",
        "belongs_to_two_bands",
    ),
    _m(
        4,
        "bands are compared in table order, not by value",
        "        ordered = sorted(\n            (b for b in bands if b[1].value <= b[2].value), key=lambda b: b[1].value\n        )",
        "        ordered = [b for b in bands if b[1].value <= b[2].value]",
        "out_of_order",
    ),
    _m(
        5,
        "an inverted band is not reported",
        "            if lo.value > hi.value:",
        "            if False:",
        "low_end",
    ),
    _m(
        6,
        "rounding is an error: no allowance for the printed precision (total column)",
        "            allowed = sum(t.half_unit for t in terms) + total.half_unit\n            bad = abs(",
        "            bad = abs(sum(t.value for t in terms) - total.value) > allowed + 1e-12\n",
        "within_rounding",
    ),
    _m(
        7,
        "a total column mismatch is not reported",
        "            bad = abs(sum(t.value for t in terms) - total.value) > allowed + 1e-12\n",
        "            bad = False\n",
        "total_column",
    ),
    _m(
        8,
        "a total row mismatch is not reported",
        "            if any(_sums_to(c, total) for c in tested):\n                continue\n",
        "            if True:\n                continue\n",
        "total_row",
    ),
    _m(
        9,
        "a total is checked over cells that are not all numbers",
        "            if total is None or len(terms) < 2 or any(t is None for t in terms):",
        "            terms = [t for t in terms if t is not None]\n            if total is None or len(terms) < 2:",
        "not_all_numbers",
    ),
    _m(
        10,
        "a stated formula is not checked",
        "        ran += 1\n        for r, row in enumerate(data, start=1):\n            cells =",
        "        ran += 1\n        continue\n        for r, row in enumerate(data, start=1):\n            cells =",
        "formula",
    ),
    _m(
        11,
        "a table with nothing to check is called ok",
        '    elif checked == 0:\n        state = "nothing_checked"',
        '    elif checked == 0:\n        state = "ok"',
        "nothing_to_check or unparsed",
    ),
    _m(
        12,
        "an unparsed table is counted as checked",
        "        if not parse.parsed:\n            unparsed += 1\n            continue",
        "        if not parse.parsed:\n            unparsed += 1\n            checked += 1\n            continue",
        "unparsed",
    ),
    _m(
        13,
        "a Total column that is a product (quantity x price) is reported as a wrong sum",
        "        if agree < MIN_SUMMING_ROWS or agree * 2 < len(checked):\n            continue\n",
        "        if not checked:\n            continue\n",
        "product",
    ),
    _m(
        14,
        "one row that adds up by chance makes a column a sum",
        "MIN_SUMMING_ROWS = 2\n",
        "MIN_SUMMING_ROWS = 1\n",
        "happens_to_add_up",
    ),
    _m(
        15,
        "a Total / Grand total is compared only with the rows since the last subtotal",
        "                candidates = [every, subtotals + since, since]\n",
        "                candidates = [since]\n",
        "grand_total_after_a_subtotal",
    ),
    _m(
        16,
        "a Total must equal ALL the ways of adding the rows, not any one of them",
        "            if any(_sums_to(c, total) for c in tested):\n",
        "            if all(_sums_to(c, total) for c in tested):\n",
        "grand_total_after_a_subtotal",
    ),
)
