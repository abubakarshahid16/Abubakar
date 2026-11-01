"""#1474 / PR 1498 the document kind chooses the rule set: each entry breaks one
decision line; backend/tests/test_1474_kind_chooses_rules.py must notice."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_1474_kind_chooses_rules.py"
_TAG = ("c1_1498", "kind_rules")
_K = APP / "kind_rules.py"
_A = APP / "applicability.py"


def _m(n, desc, path, anchor, repl, kw):
    return Mutation(
        id=f"M1498-{n:02d}",
        phase=1498,
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
        "a procedure gets the datasheet checklist again",
        _K,
        '    return [] if note and note["blocked"] else scope.evaluate(*args)\n',
        "    return scope.evaluate(*args)\n",
        "no_checklist_and_says_so",
    ),
    _m(
        2,
        "a procedure reads an equipment type again, so governing standards return",
        _K,
        "    if blocked(document_id):\n        return set(), None, None, facts\n",
        "    if False:\n        return set(), None, None, facts\n",
        "governing_standard",
    ),
    _m(
        3,
        "a procedure's equipment type still matches classified standards",
        _K,
        '    return {**profile, "equipment_type": None}, (rows, None)\n',
        "    return profile, (rows, None)\n",
        "classified_for_the_equipment_type",
    ),
    _m(
        4,
        "a datasheet is treated as a non-datasheet",
        _K,
        '    if not kind or kind in (DATASHEET, "unknown"):\n',
        "    if not kind:\n",
        "datasheet_keeps",
    ),
    _m(
        5,
        "the run no longer says the equipment type was not used",
        _K,
        "            if used\n",
        "            if False\n",
        "records_the_equipment_type_as_not_used",
    ),
    _m(
        6,
        "an unknown kind is no longer marked",
        _K,
        '    if kind == DATASHEET or (kind and kind != "unknown"):\n',
        "    if True:\n",
        "unknown_kind",
    ),
    _m(
        7,
        "the switch is ignored",
        _K,
        "    return bool(settings.kind_chooses_rules_enabled)\n",
        "    return True\n",
        "switch_off",
    ),
)
