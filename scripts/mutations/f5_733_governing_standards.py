"""#725 F5 (#733): standards by equipment type; materials standards only for material fields. Ids M6901-M6912."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_f5_733_governing_standards.py"
_A = APP / "applicability.py"
_S = APP / "subject_scope.py"
_TAG = ("f5", "applicability")


def _m(i, desc, path, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=path, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(6901, "the governing standards are never offered to selection", _A,
       "        governing,\n", "", "without_citing_it or title"),
    _m(6902, "a governing standard is not included", _A,
       '    "governing_standard",  # #725 F5: reference/governing_standards.json\n', "",
       "without_citing_it or including_reason"),
    _m(6903, "a governing standard not held is dropped", _A,
       '                not_held.append({"identifier": identifier,', '                (lambda *_: None)({"identifier": identifier,',
       "never_met"),
    _m(6904, "the reason does not say where the type was read", _A,
       '            where = f"{kind} (read from the submittal\'s {source})"', '            where = kind',
       "title or without_citing_it"),
    _m(6905, "a governing standard also cited is reported twice", _A,
       "            if standard_ids.key(g[\"identifier\"]) not in {standard_ids.key(m[\"identifier\"]) for m in missing}],",
       "            ],", "reported_once"),
    _m(6906, "the old order: discipline outranks service again", _A,
       "    METHOD_SERVICE: 3,\n", "    METHOD_SERVICE: 5.5,\n", "service_match or including_reason"),
    _m(6907, "a possible citation outranks an equipment match again", _A,
       "    METHOD_POSSIBLE: 4,\n", "    METHOD_POSSIBLE: 1.5,\n", "including_reason"),
    _m(6908, "a broken table is used anyway", _A,
       "        raise ValueError(f\"{(path or GOVERNING_PATH).name}: not a governing-standards/1 table\")",
       "        pass", "broken_table"),
    _m(6909, "a materials standard applies to everything", _S,
       "        if not label or not is_materials_standard(label):\n", "        if True:\n",
       "no_material_is_stated or stated_material"),
    _m(6910, "every table row of a materials standard is kept while any material is stated", _S,
       "        elif requirement.get(\"requirement_type\") == \"table_value\" and not (",
       "        elif False and not (", "stated_material"),
    _m(6911, "a placeholder material counts as stated", _S,
       "                 if not conditions._is_empty(f.get(\"field_value\"))]", "                 ]",
       "placeholder_material"),
    _m(6912, "materials standards are not recognised", _A,
       "    return any(standard_ids.same_standard(entry_or_label, m) for m in table[\"materials_standards\"])",
       "    return False", "recognised_by_label or no_material_is_stated"),
)
