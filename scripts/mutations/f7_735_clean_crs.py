"""#725 F7 (#735) part 1: one row per problem, no contractor blame for a system miss, severity, order. Ids M7101-M7108."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_f7_735_clean_crs.py"
_M = APP / "crs_mapping.py"
_E = APP / "crs_export.py"
_TAG = ("f7", "crs")


def _m(i, desc, path, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=path, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(7101, "one row per tag value again", _M,
       "            f.get(\"origin\") == _DATASHEET_ORIGIN)\n\n\ndef _grouped",
       "            f.get(\"origin\") == _DATASHEET_ORIGIN, _fold(f.get(\"contractor_evidence_text\")),\n"
       "            f.get(\"contractor_page\"))\n\n\ndef _grouped", "three_tags or worst_severity"),
    _m(7102, "the first tag's value is printed for every tag", _M,
       "    elif len({(_provided(g), g.get(\"contractor_page\")) for g in group}) > 1:\n",
       "    elif False:\n", "three_tags"),
    _m(7103, "a system miss is put on the contractor again", _M,
       "        return (f\"Engineer to check whether the datasheet states {what}: no field this \"\n"
       "                \"system read was paired with it.\")",
       "        return f\"Contractor to state {what} on the datasheet.\"", "engineers_question"),
    _m(7104, "the row severity is the first finding's, not the worst", _M,
       "    return next((s for s in SEVERITY_ORDER if s in found), \"\")",
       "    return str(group[0].get(\"severity\") or \"\")", "worst_severity"),
    _m(7105, "rows are not ordered by page and clause", _M,
       "        for group in sorted(_grouped(bucket), key=_row_order):\n",
       "        for group in _grouped(bucket):\n", "ordered_by_page"),
    _m(7106, "clauses sort as text (8.10 before 8.2)", _M,
       "    return tuple(int(p) if p.isdigit() else 10 ** 6 for p in re.findall(r\"\\w+\", str(clause or \"\"))) or (10 ** 6,)",
       "    return (str(clause or \"\"),)", "ordered_by_page"),
    _m(7107, "the group leader depends on input order", _M,
       "    return [sorted(groups[k], key=_leader_order) for k in order]",
       "    return [sorted(groups[k], key=lambda f: not f.get(\"confirmed_by\")) for k in order]",
       "number_key"),
    _m(7108, "the workbook leaves the severity out", _E,
       "                  entry[\"standard_reference\"], entry.get(\"severity\", \"\")]",
       "                  entry[\"standard_reference\"], \"\"]", "severity_column"),
)
