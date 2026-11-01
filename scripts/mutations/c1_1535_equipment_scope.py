"""PR 1535 rules by equipment scope: each entry breaks one decision line;
backend/tests/test_rules_by_equipment_scope.py must notice."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_rules_by_equipment_scope.py"
_TAG = ("c1_1535", "equipment_scope")
_E = APP / "equipment_scope.py"
_C = APP / "comparison.py"


def _m(n, desc, path, anchor, repl, kw):
    return Mutation(
        id=f"M1535-{n:02d}",
        phase=1535,
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
        "a sheet whose equipment is unknown or unsure loses rules on a guess",
        _E,
        "        out_equipment = bool(types and equipment and not (types & equipment))\n",
        "        out_equipment = bool(types and not (types & equipment))\n",
        "unknown_or_unsure_submittal",
    ),
    _m(
        2,
        "a rule for the sheet's own equipment type is left out",
        _E,
        "        out_equipment = bool(types and equipment and not (types & equipment))\n",
        "        out_equipment = bool(types and equipment and (types & equipment))\n",
        "exchanger_keeps",
    ),
    _m(
        3,
        "a document kind that is not decided drops rules on a guess",
        _E,
        "        out_kind = bool(kinds and kind and kind not in kinds)\n",
        "        out_kind = bool(kinds and kind not in kinds)\n",
        "document_kind_scope",
    ),
    _m(
        4,
        "the switch off no longer returns the rules unchanged",
        _E,
        "    if not enabled():\n",
        "    if False:\n",
        "switch_off",
    ),
    _m(
        5,
        "a guessed document kind counts as decided",
        _E,
        '    if not kind or kind == "unknown" or (guess and row["state"] != "confirmed"):\n',
        '    if not kind or kind == "unknown":\n',
        "submittal_kind_only_when_decided",
    ),
    _m(
        6,
        "the review counts the left-out rules but still checks them",
        _C,
        "    requirements, es = eqs.gate_for_run(\n",
        "    _unused, es = eqs.gate_for_run(\n",
        "review_leaves_out",
    ),
    _m(
        7,
        "every standard is treated as written for one equipment family, so a vessel code is dropped",
        _E,
        "            if any(standard_ids.same_standard(label, c) for c in codes)\n",
        "            if True\n",
        "exchanger_keeps",
    ),
    _m(
        8,
        "the left-out count no longer reaches the run summary the engineer reads",
        APP / "absence.py",
        "    parts.extend(kind_rules.lines(outcome) + equipment_scope.lines(outcome))\n",
        "    parts.extend(kind_rules.lines(outcome))\n",
        "run_summary_lines",
    ),
)
