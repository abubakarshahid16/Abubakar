"""Mutations of the part-name roles (test B, part of #805; PR 1684)."""

from __future__ import annotations

from ._base import REPO, Mutation

_P = REPO / "backend" / "app" / "part_name_roles.py"
_T = "tests/test_part_name_roles.py"


def _m(
    n: int, description: str, path, anchor: str, replacement: str, keyword: str
) -> Mutation:
    return Mutation(
        id=f"M1684-{n:02d}",
        phase=1684,
        description=description,
        path=path,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=("datasheet", "label_gate"),
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        2,
        "a part word anywhere in the quote is enough: a longer phrase fills the field",
        _P,
        "            if opening and _words(opening.group(1)) == value_words:\n",
        "            if opening or part in quote_words:\n",
        "longer_phrase",
    ),
    _m(
        3,
        "a value that is not a material fills a material field",
        _P,
        "        if not material_value(value, rules):\n            return False\n",
        "        if False:\n            return False\n",
        "not_a_material",
    ),
    _m(
        4,
        "two different values for one part still fill the role",
        _P,
        '        if len({" ".join(_words(f.get("field_value"))) for f in found}) != 1:\n            continue  # two values for one part: no fill\n',
        "        if False:\n            continue\n",
        "two_different_values",
    ),
    _m(
        5,
        "a fact already under the role's own name is overwritten",
        _P,
        '        if " ".join(role.split("_")) in own:\n            continue  # a fact under the role\'s own name already speaks for it\n',
        "        if False:\n            continue\n",
        "already_named",
    ),
    _m(
        6,
        "the switch is ignored for stored facts",
        _P,
        "    if not enabled():\n        return facts\n",
        "    if False:\n        return facts\n",
        "switch_off_changes_nothing",
    ),
    _m(
        7,
        "the stored-facts check never asks for the part-name roles",
        REPO / "backend" / "app" / "datasheet_checks.py",
        "    for fact in datasheet_roles.with_roles(facts, rules, wanted):\n",
        "    for fact in facts:\n",
        "finds_the_material",
    ),
    _m(
        8,
        "the form reader's label gate never takes the relaxed rule",
        REPO / "backend" / "app" / "form_reader.py",
        "    if not label_in_quote(f, printed, rules) and not part_name_roles.accepts(\n        f.key, value, printed, rules\n    ):\n",
        "    if not label_in_quote(f, printed, rules):\n",
        "bare_part_row",
    ),
    _m(
        9,
        "a grade code alone is accepted as a material",
        _P,
        '        _CACHE[key] = re.compile(rf"^(?:{name}|{coded}\\s+{name}|{name}\\s+{coded})\\.?$")\n',
        '        _CACHE[key] = re.compile(rf"^(?:{name}|{coded}\\s+{name}|{name}\\s+{coded}|{coded})\\.?$")\n',
        "never_fills_gate_or_stored",
    ),
    _m(
        10,
        "a seal quote may have words before the label (a sentence fills seal type)",
        _P,
        "    found = re.match(pattern,",
        '    found = re.search(pattern.lstrip("^"),',
        "never_fills",
    ),
    _m(
        11,
        "a name that is also a grade code may follow another name (two entries in one value)",
        _P,
        '        code = rf"(?!{name}(?:\\s|\\.|$)){_GRADE}"',
        '        code = rf"{_GRADE}"',
        "property_two_entries",
    ),
    _m(
        12,
        "a seal quote may have words after the phrase",
        _P,
        '})\\.?$"\n    found = re.match(',
        '})"\n    found = re.match(',
        "never_fills",
    ),
)
