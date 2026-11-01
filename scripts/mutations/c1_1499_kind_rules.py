"""#1474 / PR 1499 the document kind chooses the rule set: each entry breaks one
decision line; backend/tests/test_1474_kind_chooses_rules.py must notice."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_1474_kind_chooses_rules.py"
_TAG = ("c1_1499", "kind_rules")
_K = APP / "kind_rules.py"
_A = APP / "applicability.py"


def _m(n, desc, path, anchor, repl, kw):
    return Mutation(
        id=f"M1499-{n:02d}",
        phase=1499,
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
        '    if not _known(kind) or (guess and state != "confirmed"):\n',
        '    if not kind or (guess and state != "confirmed"):\n',
        "datasheet_keeps",
    ),
    _m(
        5,
        "the run note lists standards it did apply as unused",
        _K,
        '        if row["standard_document_id"] not in applied\n',
        "        if True\n",
        "unused_standards",
    ),
    _m(
        6,
        "an unknown kind is no longer marked",
        _K,
        "    if kind == DATASHEET:\n",
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
    _m(
        8,
        "a guessed kind blocks the datasheet rules",
        _K,
        '    if not _known(kind) or (guess and state != "confirmed"):\n',
        "    if not _known(kind):\n",
        "guessed_kind",
    ),
    _m(
        9,
        "a guessed kind is not marked as a guess",
        _K,
        "    if _known(kind) and guess:\n",
        "    if False:\n",
        "guessed_kind",
    ),
    _m(
        10,
        "the kind lines no longer reach the run summary and the CRS notes",
        _K,
        "        if t\n",
        "        if False\n",
        "crs_review_notes",
    ),
)
