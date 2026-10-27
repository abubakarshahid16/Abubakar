"""Order 262.1 (PR 1397): which form field a numeric rule limits. `rule_roles.py` feeds a pairing
that rides the comparison path, so it gets entries. Ids M1397-01 onwards, phase 1397."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_262_rule_roles.py"
_TAGS = ("honesty", "o262")


def _m(n, description, path, anchor, replacement, keyword):
    return Mutation(
        id=f"M1397-{n}",
        phase=1397,
        description=description,
        path=path,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=_TAGS,
    )


_R = APP / "rule_roles.py"

MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "a field whose unit cannot be checked (a text field) is in the type's dictionary",
        _R,
        "        if not wanted:\n            continue\n",
        "        wanted = wanted or ('text',)\n",
        "numeric_fields_with_a_checkable_unit",
    ),
    _m(
        "02",
        "a reviewed mapping is used although the rule's unit no longer fits the field",
        _R,
        "        if have & set(families[name]):\n",
        "        if True:\n",
        "text_and_unit_still_fit",
    ),
    _m(
        "03",
        "the kept file claims to be approved, not a draft",
        _R,
        'STATUS = "draft"\n',
        'STATUS = "approved"\n',
        "no_document_text",
    ),
    _m(
        "04",
        "a review ignores the reviewed file",
        APP / "field_vocabulary.py",
        "    named = {**named, **reviewed}\n",
        "",
        "reads_the_reviewed_file",
    ),
    _m(
        "05",
        "a rated speed is checked against no unit family any more",
        _R,
        '    "rated_speed": ("rotation",),\n',
        "",
        "unit_check_comes_from",
    ),
    _m(
        "06",
        "a mapping is kept whatever the hash of the rule text (an edited rule keeps its old field)",
        _R,
        '        hit = by_hash.get(text_hash(r.get("requirement_text")))\n',
        "        hit = next(iter(by_hash.values()), None)\n",
        "text_and_unit_still_fit",
    ),
    _m(
        "07",
        "a mapping of one equipment type is applied to a review of any type",
        _R,
        "        if same_type(file_type, equipment_type):\n",
        "        if True:\n",
        "never_applies_on_another_type",
    ),
    _m(
        "08",
        "an unknown equipment type is treated as a match",
        _R,
        "    if not a or not b:\n        return False\n",
        "    if not a or not b:\n        return True\n",
        "never_applies_on_another_type",
    ),
)
