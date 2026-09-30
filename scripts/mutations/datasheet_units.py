"""Mutations for the three generic defects the datasheet benchmark found
(2026-09-30): the unit vocabulary, a unit in its own cell, and units in the
rules/AI merge.

1. The vocabulary (`claims`): the compound-rate grammar (M1740, M1741),
   the time units (M1742), a bracketed reference (M1743), superscripts
   (M1744), and the two other homes that read it - `match_rules` (M1745)
   and `geometry_reader` (M1746).
2. The unit cell (`datasheet_inputs.pairs_from_rows`): detection (M1747),
   the header's Units column (M1748), a lone value cell (M1749), a blank
   beside a unit (M1750), the gauge reference (M1751).
3. The merge (`datasheet_ai`, `datasheets._write_ai_reading`): a proven AI
   unit (M1752), the quote as the proof (M1753), different units conflict
   (M1754), the reference must match (M1755), one AI reading confirms two
   code readings (M1756), the table-shape "<row> - <column>" label
   (M1757), the unit written on the fact (M1758), an unconfirmed rules fact
   is flagged (M1759).
Targets: backend/tests/test_datasheet_unit_columns.py and
backend/tests/test_datasheet_ai.py.
"""

from __future__ import annotations

from ._base import APP, Mutation

_U = "tests/test_datasheet_unit_columns.py"
_T = "tests/test_datasheet_ai.py"
_CL = APP / "claims.py"
_MR = APP / "match_rules.py"
_GR = APP / "geometry_reader.py"
_IN = APP / "datasheet_inputs.py"
_AI = APP / "datasheet_ai.py"
_DS = APP / "datasheets.py"

MUTATIONS: tuple[Mutation, ...] = (
    # ------------------------------------------------------- 1. vocabulary
    Mutation(id="M1740", phase=1740,
             description="the compound-rate grammar accepts nothing",
             path=_CL,
             anchor="    return any((a, b) in _RATE_QUANTITIES\n",
             replacement="    return False and any((a, b) in _RATE_QUANTITIES\n",
             target=_U, keyword="compound_rate or ai_gate or rate_value or match_rule",
             tags=("datasheet_units",)),
    Mutation(id="M1741", phase=1741,
             description="the grammar accepts any pair of unit families (N/S, kg per kg)",
             path=_CL,
             anchor="    return any((a, b) in _RATE_QUANTITIES\n",
             replacement="    return any(True\n",
             target=_U, keyword="still_not_a_unit", tags=("datasheet_units",)),
    Mutation(id="M1742", phase=1742,
             description="ms, weeks and months are not units",
             path=_CL,
             anchor='    "ms": "time", "msec": "time",\n'
                    '    "week": None, "weeks": None, "wk": None, "wks": None,\n'
                    '    "month": None, "months": None, "yr": None, "yrs": None,\n',
             replacement="",
             target=_U, keyword="time_and_calendar or calendar_durations or ai_gate",
             tags=("datasheet_units",)),
    Mutation(id="M1743", phase=1743,
             description="a unit with its reference in brackets (kPa(g)) is not a unit",
             path=_CL,
             anchor="    return bracket is not None and _recognised_folded(_fold_unit(bracket.group(\"base\")))\n",
             replacement="    return False\n",
             target=_U, keyword="reference", tags=("datasheet_units",)),
    Mutation(id="M1744", phase=1744,
             description="a superscript m3 is not the unit m3",
             path=_CL,
             anchor='    u = u.replace("²", "2").replace("³", "3")\n',
             replacement="",
             target=_U, keyword="superscript", tags=("datasheet_units",)),
    Mutation(id="M1745", phase=1745,
             description="match_rules reads the raw spelling set, not the shared vocabulary",
             path=_MR,
             anchor="    return not claims.is_unit(unknown)\n",
             replacement="    return claims._fold_unit(unknown) not in claims._RECOGNISED_UNITS\n",
             target=_U, keyword="match_rule", tags=("datasheet_units",)),
    Mutation(id="M1746", phase=1746,
             description="the geometry reader ignores the shared vocabulary",
             path=_GR,
             anchor="    if not stripped or not claims.is_unit(stripped):\n",
             replacement="    if True:\n",
             target=_U, keyword="geometry_reader", tags=("datasheet_units",)),
    # ------------------------------------------------------- 2. the unit cell
    Mutation(id="M1747", phase=1747,
             description="a unit in its own cell is read as part of the value",
             path=_IN,
             anchor="        at = found[0] if len(found) == 1 else None\n",
             replacement="        at = None\n",
             target=_U, keyword="unit_cell_before or workbook_with_a_unit_column or gauge",
             tags=("datasheet_units", "datasheet_inputs")),
    Mutation(id="M1748", phase=1748,
             description="a header row's Units column is ignored",
             path=_IN,
             anchor='            unit_col = next((i for i, c in rest if is_unit_header(c.rstrip(":"))), None)\n',
             replacement="            unit_col = None\n",
             target=_U, keyword="header_units_column", tags=("datasheet_units", "datasheet_inputs")),
    Mutation(id="M1749", phase=1749,
             description="a lone value cell under a Unit header is taken as the unit",
             path=_IN,
             anchor="    if len(rest) < 2:\n",
             replacement="    if False:\n",
             target=_U, keyword="one_value_cell", tags=("datasheet_units", "datasheet_inputs")),
    Mutation(id="M1750", phase=1750,
             description="a unit is glued onto a blank marker ('By Vendor mm')",
             path=_IN,
             anchor="    if _QUANTITY_START.match(value) and measure_value(value)[1] is None:\n",
             replacement="    if True:\n",
             target=_U, keyword="blank_beside", tags=("datasheet_units", "datasheet_inputs")),
    Mutation(id="M1751", phase=1751,
             description="a unit cell's gauge reference is dropped (kPa(g) -> kPa)",
             path=_IN,
             anchor="    unit = unit_text if claims.is_unit(unit_text) else (primary_unit(unit_text) or unit_text)\n",
             replacement="    unit = primary_unit(unit_text) or unit_text\n",
             target=_U, keyword="gauge", tags=("datasheet_units", "datasheet_inputs")),
    # ------------------------------------------------------- 3. the merge
    Mutation(id="M1752", phase=1752,
             description="an AI unit the quote proves is not kept on the agreed fact",
             path=_AI,
             anchor="    if ours and unit_in_quote(ours, ai_fact.get(\"quote\")):\n        return AI_UNIT\n",
             replacement="    if False:\n        return AI_UNIT\n",
             target=_T, keyword="proven_unit or quote_proves or confirms_two",
             tags=("datasheet_units", "datasheet_ai")),
    Mutation(id="M1753", phase=1753,
             description="an AI unit is taken as proven without its quote printing it",
             path=_AI,
             anchor="    return bool(folded) and re.search(\n",
             replacement="    return True or re.search(\n",
             target=_T, keyword="does_not_print", tags=("datasheet_units", "datasheet_ai")),
    Mutation(id="M1754", phase=1754,
             description="the same number in two different units counts as agreement",
             path=_AI,
             anchor="        return SAME if same_unit(theirs, ours) else UNIT_DIFFERS\n",
             replacement="        return SAME\n",
             target=_T, keyword="different_units or gauge_and_absolute",
             tags=("datasheet_units", "datasheet_ai", "critical")),
    Mutation(id="M1755", phase=1755,
             description="a gauge and an absolute pressure are one unit",
             path=_AI,
             anchor="    if ref_a != ref_b:\n        return False\n",
             replacement="    if False:\n        return False\n",
             target=_T, keyword="gauge_and_absolute", tags=("datasheet_units", "datasheet_ai")),
    Mutation(id="M1756", phase=1756,
             description="one AI reading confirms only one of two code readings of a cell",
             path=_AI,
             anchor="            if fresh or fits:\n                partner[ri] = (fresh or fits)[0]\n",
             replacement="            if fresh:\n                partner[ri] = fresh[0]\n",
             target=_T, keyword="confirms_two", tags=("datasheet_units", "datasheet_ai")),
    Mutation(id="M1757", phase=1757,
             description="a table-shape '<row> - <column>' label is not matched to its row",
             path=_AI,
             anchor="    if sep and head.strip() and tail.strip():\n",
             replacement="    if False:\n",
             target=_T, keyword="confirms_two", tags=("datasheet_units", "datasheet_ai")),
    Mutation(id="M1758", phase=1758,
             description="the proven unit is not written on the agreed rule fact",
             path=_DS,
             anchor="            proven = _proven_unit_columns(rule, d.get(\"unit\"))\n",
             replacement="            proven = None\n",
             target=_T, keyword="writes_the_unit", tags=("datasheet_units", "datasheet_ai")),
    Mutation(id="M1759", phase=1759,
             description="a rules fact the AI read and did not confirm is not flagged",
             path=_DS,
             anchor="            conn.execute(\"UPDATE submittal_facts SET bbox = ? WHERE id = ?\",\n"
                    "                         (_unconfirmed_box(rule.get(\"bbox\"), engine), rule[\"id\"]))\n",
             replacement="            pass\n",
             target=_T, keyword="not_confirm or empty_reading",
             tags=("datasheet_units", "datasheet_ai")),
)
